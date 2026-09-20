"""
本地存储：用 SQLite 落地原始数据。

设计原则是“只存原始数据，不存派生指标”。
技术指标和 K 线形态都能从行情表毫秒级算出来，存进库反而带来两个麻烦：
指标口径一改就得整表重算，以及历史数据回补后容易出现新旧口径混用。
所以这里只保存：股票池、日线行情、财报事实、做空量、内部人交易等一手数据。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ustock.db"

SCHEMA = """
-- 股票池
CREATE TABLE IF NOT EXISTS universe(
    symbol     TEXT PRIMARY KEY,
    name       TEXT,
    sector     TEXT,
    industry   TEXT,
    exchange   TEXT,
    cik        TEXT,
    in_sp500   INTEGER DEFAULT 0,
    in_ndx     INTEGER DEFAULT 0,
    in_dow     INTEGER DEFAULT 0,
    sp_weight  REAL,
    theme      TEXT,          -- 自选池的主题分组，例如「AI与算力」
    updated_at TEXT
);

-- 日线行情（已做拆股前复权，未做分红复权）
CREATE TABLE IF NOT EXISTS prices(
    symbol TEXT, date TEXT,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY(symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);

-- SEC 财报事实（一行一个指标一个报告期）
CREATE TABLE IF NOT EXISTS fundamentals(
    symbol TEXT, tag TEXT, end_date TEXT, value REAL,
    fy TEXT, fp TEXT, form TEXT, filed TEXT,
    PRIMARY KEY(symbol, tag, end_date, form)
);
CREATE INDEX IF NOT EXISTS idx_fund_symbol ON fundamentals(symbol);

-- FINRA 每日做空量
CREATE TABLE IF NOT EXISTS short_volume(
    symbol TEXT, date TEXT,
    short_vol REAL, short_exempt REAL, total_vol REAL,
    PRIMARY KEY(symbol, date)
);
CREATE INDEX IF NOT EXISTS idx_short_date ON short_volume(date);

-- 内部人交易（SEC Form 4）
CREATE TABLE IF NOT EXISTS insider(
    symbol TEXT, filed TEXT, accession TEXT,
    owner TEXT, role TEXT, txn_type TEXT, shares REAL, price REAL,
    PRIMARY KEY(symbol, accession, owner, txn_type)
);

-- 公司事件（财报日等）
CREATE TABLE IF NOT EXISTS events(
    symbol TEXT, date TEXT, kind TEXT, detail TEXT,
    PRIMARY KEY(symbol, date, kind)
);

-- 机构持仓（SEC Form 13F 季度汇总）
CREATE TABLE IF NOT EXISTS holdings13f(
    symbol TEXT, period TEXT,
    value REAL, shares REAL, holders INTEGER, cusip TEXT,
    PRIMARY KEY(symbol, period)
);

-- 期权聚合指标（CBOE）
CREATE TABLE IF NOT EXISTS options_agg(
    symbol TEXT, date TEXT,
    iv30 REAL, atm_iv REAL, iv_skew REAL,
    put_call_vol REAL, put_call_oi REAL,
    opt_volume REAL, opt_oi REAL, opt_stock_vol REAL,
    PRIMARY KEY(symbol, date)
);

-- 政要持仓（可选，需用户自备第三方数据源）
CREATE TABLE IF NOT EXISTS politician_trades(
    symbol TEXT, date TEXT, politician TEXT, chamber TEXT,
    txn_type TEXT, amount_min REAL, amount_max REAL,
    PRIMARY KEY(symbol, date, politician, txn_type)
);

-- 采集元信息，记录各任务最近一次成功时间
CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
);
"""


# 表结构升级：CREATE TABLE IF NOT EXISTS 不会给已存在的表补列，
# 因此新增字段必须在这里登记，老数据库才能平滑升级而不用删库重建。
MIGRATIONS = [
    ("universe", "theme", "TEXT"),
    ("universe", "market_cap_nq", "REAL"),
    ("universe", "analyst_target", "REAL"),
    ("universe", "sector_nq", "TEXT"),
    ("universe", "industry_nq", "TEXT"),
    ("universe", "avg_volume", "REAL"),
    ("options_agg", "source", "TEXT"),
]


def _migrate(c) -> None:
    """为已存在的表补上后续版本新增的字段。"""
    cache: dict[str, set] = {}
    for table, col, typ in MIGRATIONS:
        if table not in cache:
            try:
                cache[table] = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            except Exception:
                cache[table] = set()
        if cache[table] and col not in cache[table]:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                cache[table].add(col)
            except Exception:
                pass


@contextmanager
def conn(db: Path | str = DB_PATH):
    """打开数据库连接，自动建表并在退出时提交。"""
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db)
    c.execute("PRAGMA journal_mode=WAL")       # 读写并发更友好
    c.execute("PRAGMA synchronous=NORMAL")     # 批量写入更快
    try:
        c.executescript(SCHEMA)
        _migrate(c)
        yield c
        c.commit()
    finally:
        c.close()


def upsert(df: pd.DataFrame, table: str, db: Path | str = DB_PATH) -> int:
    """按主键写入或更新，返回写入行数。

    这里用 INSERT ... ON CONFLICT DO UPDATE 而不是 INSERT OR REPLACE。
    两者看似等价，但后者是「删除旧行再插入新行」，
    DataFrame 里没带的列会被直接清成 NULL——
    例如只更新股票池的名称时，会把另一个任务写入的市值、目标价一并抹掉。
    """
    if df is None or df.empty:
        return 0
    if df.columns.duplicated().any():
        # 重复列名会让占位符数量与实际值对不上，这里保留第一次出现的那列
        df = df.loc[:, ~df.columns.duplicated()]
    with conn(db) as c:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
        use = list(dict.fromkeys(x for x in df.columns if x in cols))
        d = df[use].where(pd.notna(df[use]), None)
        pk = [r[1] for r in c.execute(f"PRAGMA table_info({table})") if r[5]]
        ph = ",".join("?" * len(use))
        upd = [x for x in use if x not in pk]
        if pk and upd:
            setter = ",".join(f"{x}=excluded.{x}" for x in upd)
            sql = (f"INSERT INTO {table}({','.join(use)}) VALUES({ph}) "
                   f"ON CONFLICT({','.join(pk)}) DO UPDATE SET {setter}")
        else:
            sql = f"INSERT OR REPLACE INTO {table}({','.join(use)}) VALUES({ph})"
        c.executemany(sql, d.itertuples(index=False, name=None))
        return len(d)


def query(sql: str, params: tuple = (), db: Path | str = DB_PATH) -> pd.DataFrame:
    """执行查询并返回 DataFrame。"""
    with conn(db) as c:
        return pd.read_sql_query(sql, c, params=params)


def load_prices(symbols: list[str] | None = None, start: str | None = None,
                db: Path | str = DB_PATH) -> pd.DataFrame:
    """读取日线行情，返回按 symbol、date 排序的长表。"""
    sql = "SELECT * FROM prices"
    where, params = [], []
    if symbols:
        where.append(f"symbol IN ({','.join('?' * len(symbols))})")
        params += list(symbols)
    if start:
        where.append("date >= ?")
        params.append(start)
    if where:
        sql += " WHERE " + " AND ".join(where)
    df = query(sql + " ORDER BY symbol, date", tuple(params), db)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def set_meta(key: str, value: str, db: Path | str = DB_PATH) -> None:
    """记录任务完成时间等元信息。"""
    with conn(db) as c:
        c.execute("INSERT OR REPLACE INTO meta(key,value,updated_at) "
                  "VALUES(?,?,datetime('now'))", (key, value))


def stats(db: Path | str = DB_PATH) -> pd.DataFrame:
    """各数据表的行数与覆盖范围，用于快速体检。"""
    rows = []
    with conn(db) as c:
        for t in ("universe", "prices", "fundamentals", "short_volume",
                  "events", "holdings13f", "options_agg", "politician_trades"):
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            extra = ""
            if n and t in ("prices", "short_volume"):
                lo, hi, k = c.execute(
                    f"SELECT MIN(date),MAX(date),COUNT(DISTINCT symbol) FROM {t}").fetchone()
                extra = f"{k} 只 / {lo} ~ {hi}"
            elif n and t in ("fundamentals", "events", "holdings13f",
                             "options_agg", "politician_trades"):
                k = c.execute(f"SELECT COUNT(DISTINCT symbol) FROM {t}").fetchone()[0]
                extra = f"{k} 只"
            rows.append({"表": t, "行数": n, "覆盖": extra})
    return pd.DataFrame(rows)
