"""
日线行情采集。

主源是纳斯达克官方接口：免密钥、字段齐全（OHLCV）、已做拆股前复权。
备源是 Yahoo，仅在主源失败时启用——Yahoo 对密集请求限流很凶，不适合当主力。

注意：两个源都只做拆股复权、不做分红复权。这与 TradingView 默认口径一致，
技术分析用它没问题；但计算长期总收益时会低估分红部分，需另行处理。
"""
from __future__ import annotations

import datetime as dt
import re

import pandas as pd

from .. import net

COLS = ["symbol", "date", "open", "high", "low", "close", "volume"]


def _money(x) -> float | None:
    """把 "$336.13" / "86,588,200" 这类字符串转成数字。"""
    if x is None:
        return None
    s = re.sub(r"[$,\s]", "", str(x))
    if s in ("", "N/A", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def from_nasdaq(symbol: str, years: int = 3, cache_ttl: int = 43200) -> pd.DataFrame:
    """纳斯达克官方历史行情。"""
    end = dt.date.today()
    start = end - dt.timedelta(days=int(365.25 * years) + 15)
    # 代码里的连字符要还原成点（BRK-B → BRK.B），否则查不到
    sym_q = symbol.replace("-", ".")
    for cls in ("stocks", "etf"):
        url = (f"https://api.nasdaq.com/api/quote/{sym_q}/historical"
               f"?assetclass={cls}&fromdate={start}&todate={end}&limit=9999")
        d = net.try_fetch_json(url, cache_ttl=cache_ttl)
        rows = (((d or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
        if not rows:
            continue
        df = pd.DataFrame(rows)
        out = pd.DataFrame({
            "symbol": symbol,
            "date": pd.to_datetime(df["date"], format="%m/%d/%Y").dt.strftime("%Y-%m-%d"),
            "open": df["open"].map(_money),
            "high": df["high"].map(_money),
            "low": df["low"].map(_money),
            "close": df["close"].map(_money),
            "volume": df["volume"].map(_money),
        })
        return out.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    return pd.DataFrame(columns=COLS)


def from_yahoo(symbol: str, years: int = 3, cache_ttl: int = 43200) -> pd.DataFrame:
    """Yahoo 行情（备源）。被限流时返回空表，由调用方决定如何降级。"""
    rng = f"{max(1, years)}y"
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval=1d&range={rng}")
    d = net.try_fetch_json(url, cache_ttl=cache_ttl)
    try:
        r = d["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
        df = pd.DataFrame({
            "symbol": symbol,
            "date": pd.to_datetime(r["timestamp"], unit="s").strftime("%Y-%m-%d"),
            "open": q["open"], "high": q["high"], "low": q["low"],
            "close": q["close"], "volume": q["volume"],
        })
        return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=COLS)


# Yahoo 一旦被限流，同一次运行内不再重试，避免把时间浪费在必然失败的请求上
_yahoo_alive = [True]


def fetch(symbol: str, years: int = 3) -> pd.DataFrame:
    """取单只股票的日线行情，自动在主备源之间切换。"""
    df = from_nasdaq(symbol, years)
    if not df.empty:
        return df
    if _yahoo_alive[0]:
        df = from_yahoo(symbol, years)
        if df.empty:
            _yahoo_alive[0] = False
        return df
    return pd.DataFrame(columns=COLS)
