"""
股票池：决定“这次要扫哪些票”。

支持三种范围（scope）：
    index   —— 主要指数成分股，约 600 只（S&P500 + 纳斯达克100 + 道琼斯30），默认
    all     —— 全美股上市普通股，约 6000+ 只（NYSE / Nasdaq / AMEX）
    自定义   —— 直接传入代码列表

同时负责把股票代码映射到 SEC 的 CIK 编号，这是抓取财报数据的前提。
"""
from __future__ import annotations

import io
import json
import re

import pandas as pd

from . import net

# ─────────────────────────────── 数据源地址 ───────────────────────────────

WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# 纳斯达克官方接口直接给出纳指100成分，比维基页面稳定（维基已改版，不再内嵌成分表）
NASDAQ_NDX = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
# slickcharts 提供道指与标普成分及指数权重，用作道指主源、标普备源
SLICK_DOW = "https://www.slickcharts.com/dowjones"
SLICK_SP500 = "https://www.slickcharts.com/sp500"
NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"

# 指数成分股一天最多变一次，缓存久一点；全市场代码表每日更新
_TTL_DAY = 86400


def normalize(sym: str) -> str:
    """统一股票代码写法。

    不同数据源对含点代码的写法不一致（BRK.B / BRK-B / BRKB），
    本项目内部统一用连字符形式（BRK-B），取数时再按各源要求转换。
    """
    return re.sub(r"[.\s]", "-", str(sym).strip().upper())


def _pick_table(html: str, want_cols: tuple[str, ...]) -> pd.DataFrame | None:
    """从维基页面的多个表格里挑出含有目标列的那一个。

    维基页面结构时常调整，写死表格序号很脆弱，所以改成按列名特征匹配。
    """
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return None
    for t in tables:
        cols = {str(c).strip().lower() for c in t.columns}
        if any(w in cols for w in want_cols):
            return t
    return None


# ─────────────────────────────── 指数成分股 ───────────────────────────────

def sp500() -> pd.DataFrame:
    """标普 500 成分股，含 GICS 行业与 CIK。"""
    html = net.fetch_text(WIKI_SP500, cache_ttl=_TTL_DAY)
    t = _pick_table(html, ("symbol",))
    if t is None:
        return pd.DataFrame(columns=["symbol", "name", "sector", "industry"])
    t.columns = [str(c).strip() for c in t.columns]
    out = pd.DataFrame({
        "symbol": t["Symbol"].map(normalize),
        "name": t.get("Security"),
        "sector": t.get("GICS Sector"),
        "industry": t.get("GICS Sub-Industry"),
    })
    return out.dropna(subset=["symbol"]).drop_duplicates("symbol")


def _slickcharts(url: str) -> pd.DataFrame:
    """解析 slickcharts 成分股表，返回代码、名称与指数权重。"""
    html = net.fetch_text(url, cache_ttl=_TTL_DAY)
    for t in pd.read_html(io.StringIO(html)):
        cols = {str(c).strip() for c in t.columns}
        if {"Symbol", "Company"} <= cols:
            w = (t["Weight"].astype(str).str.rstrip("%").astype(float) / 100
                 if "Weight" in cols else None)
            return pd.DataFrame({
                "symbol": t["Symbol"].map(normalize),
                "name": t["Company"],
                "weight": w,
            }).dropna(subset=["symbol"]).drop_duplicates("symbol")
    return pd.DataFrame(columns=["symbol", "name", "weight"])


def nasdaq100() -> pd.DataFrame:
    """纳斯达克 100 成分股（来自纳斯达克官方接口，含市值）。"""
    d = net.try_fetch_json(NASDAQ_NDX, cache_ttl=_TTL_DAY)
    rows = (((d or {}).get("data") or {}).get("data") or {}).get("rows") or []
    if not rows:
        return pd.DataFrame(columns=["symbol", "name", "sector"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "symbol": df["symbol"].map(normalize),
        "name": df.get("companyName"),
        "sector": df.get("sector").replace("", None) if "sector" in df else None,
    }).dropna(subset=["symbol"]).drop_duplicates("symbol")


def dow30() -> pd.DataFrame:
    """道琼斯工业平均指数 30 只成分股（含指数权重）。"""
    return _slickcharts(SLICK_DOW)


def sp500_weights() -> pd.DataFrame:
    """标普 500 成分的指数权重，用于补充 sp500() 的行业信息。"""
    return _slickcharts(SLICK_SP500)


# ─────────────────────────────── 全市场代码表 ───────────────────────────────

def _parse_pipe_table(text: str) -> pd.DataFrame:
    """解析 NasdaqTrader 的竖线分隔文件，并丢掉结尾的文件生成时间行。"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and lines[-1].lower().startswith("file creation time"):
        lines = lines[:-1]
    return pd.read_csv(io.StringIO("\n".join(lines)), sep="|", dtype=str)


def all_us_listed(include_etf: bool = False) -> pd.DataFrame:
    """全部在美上市证券（Nasdaq + NYSE + AMEX 等）。

    默认剔除 ETF 与测试代码。ETF 没有财报，纳入后基本面因子会大面积缺失。
    """
    frames = []

    nd = _parse_pipe_table(net.fetch_text(NASDAQ_LISTED, cache_ttl=_TTL_DAY))
    nd = nd[nd["Test Issue"] == "N"]
    if not include_etf:
        nd = nd[nd["ETF"] != "Y"]
    frames.append(pd.DataFrame({
        "symbol": nd["Symbol"].map(normalize),
        "name": nd["Security Name"],
        "exchange": "NASDAQ",
        "is_etf": nd["ETF"].eq("Y"),
    }))

    ot = _parse_pipe_table(net.fetch_text(OTHER_LISTED, cache_ttl=_TTL_DAY))
    ot = ot[ot["Test Issue"] == "N"]
    if not include_etf:
        ot = ot[ot["ETF"] != "Y"]
    # 交易所代码：N=NYSE, A=NYSE American, P=NYSE Arca, Z=Cboe BZX, V=IEX
    ex_map = {"N": "NYSE", "A": "AMEX", "P": "ARCA", "Z": "CBOE", "V": "IEX"}
    frames.append(pd.DataFrame({
        "symbol": ot["ACT Symbol"].map(normalize),
        "name": ot["Security Name"],
        "exchange": ot["Exchange"].map(ex_map).fillna(ot["Exchange"]),
        "is_etf": ot["ETF"].eq("Y"),
    }))

    df = pd.concat(frames, ignore_index=True)
    # 剔除优先股、权证、单位等非普通股（代码含 $ 或超长后缀）
    df = df[~df["symbol"].str.contains(r"\$", na=False)]
    df = df[df["symbol"].str.len() <= 5]
    return df.dropna(subset=["symbol"]).drop_duplicates("symbol").reset_index(drop=True)


# ─────────────────────────────── SEC CIK 映射 ───────────────────────────────

def cik_map(sec_ua: str = net.DEFAULT_SEC_UA) -> dict[str, str]:
    """股票代码 → SEC CIK（十位补零）。抓取 SEC 财报数据的必需前提。"""
    raw = net.fetch_json(SEC_TICKERS, ua=sec_ua, cache_ttl=_TTL_DAY)
    out = {}
    for item in raw.values():
        out[normalize(item["ticker"])] = str(item["cik_str"]).zfill(10)
    return out


def name_map(sec_ua: str = net.DEFAULT_SEC_UA) -> dict[str, str]:
    """股票代码 → 公司名称。与 CIK 映射同源，不产生额外请求。"""
    raw = net.fetch_json(SEC_TICKERS, ua=sec_ua, cache_ttl=_TTL_DAY)
    return {normalize(v["ticker"]): v.get("title") for v in raw.values()}


# ─────────────────────────────── 对外主入口 ───────────────────────────────

def build(scope: str = "index", symbols: list[str] | None = None,
          sec_ua: str = net.DEFAULT_SEC_UA, with_cik: bool = True) -> pd.DataFrame:
    """构建股票池。

    参数：
        scope    "index" 主要指数成分 / "all" 全市场 / "custom" 使用 symbols
        symbols  scope="custom" 时的代码列表
    返回：
        含 symbol / name / sector / exchange / in_sp500 / in_ndx / in_dow / cik 的表
    """
    if scope == "custom":
        if not symbols:
            raise ValueError("scope='custom' 需要提供 symbols 列表")
        df = pd.DataFrame({"symbol": [normalize(s) for s in symbols]})
        # 公司名称直接取自 SEC 代码表，与 CIK 同源、不额外发请求
        try:
            df["name"] = df["symbol"].map(name_map(sec_ua))
        except Exception:
            df["name"] = None

    elif scope == "all":
        df = all_us_listed()
        sp = set(sp500()["symbol"])
        nx = set(nasdaq100()["symbol"])
        dj = set(dow30()["symbol"])
        df["in_sp500"] = df["symbol"].isin(sp)
        df["in_ndx"] = df["symbol"].isin(nx)
        df["in_dow"] = df["symbol"].isin(dj)

    elif scope == "index":
        sp, nx, dj = sp500(), nasdaq100(), dow30()
        df = (sp[["symbol", "name", "sector"]]
              .merge(nx[["symbol"]].assign(_n=True), on="symbol", how="outer")
              .merge(dj[["symbol"]].assign(_d=True), on="symbol", how="outer"))
        # 指数外的票（如仅在纳指100/道指）补上名称与行业
        extra = pd.concat([nx[["symbol", "name"]], dj[["symbol", "name"]]])
        names = dict(zip(extra["symbol"], extra["name"]))
        df["name"] = df["name"].fillna(df["symbol"].map(names))
        df["in_sp500"] = df["symbol"].isin(set(sp["symbol"]))
        df["in_ndx"] = df["_n"].fillna(False).astype(bool)
        df["in_dow"] = df["_d"].fillna(False).astype(bool)
        df = df.drop(columns=["_n", "_d"])
        # 附上标普指数权重，可用作“大盘权重股”这类筛选条件
        try:
            w = sp500_weights().set_index("symbol")["weight"]
            df["sp_weight"] = df["symbol"].map(w)
        except Exception:
            df["sp_weight"] = None
    else:
        raise ValueError(f"未知的 scope：{scope}（可选 index / all / custom）")

    if with_cik:
        try:
            m = cik_map(sec_ua)
            df["cik"] = df["symbol"].map(m)
        except Exception as e:
            print(f"  提示：CIK 映射获取失败（{e}），基本面因子将不可用")
            df["cik"] = None

    return df.sort_values("symbol").reset_index(drop=True)
