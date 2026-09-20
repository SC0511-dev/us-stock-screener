"""
做空数据：FINRA RegSHO 每日做空量。

这是一类完全免费公开的市场结构信息。
FINRA 每个交易日发布一份合并文件，包含全市场每只股票当日的做空成交量。

与常被引用的“双周做空比例（Short Interest）”相比，这份日频数据有两个优势：
    时效性高    每日更新，而双周数据滞后约两周
    颗粒度细    可以看出做空占比的逐日变化与突变

需要注意的是：做空成交量占比高 ≠ 看空该股。
做市商对冲、ETF 套利、可转债对冲都会产生大量“技术性做空”，
因此该指标更适合看“相对自身历史的异常变化”，而不是绝对高低。
"""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd

from .. import net

URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{ymd}.txt"


def fetch_day(day: dt.date) -> pd.DataFrame:
    """取某一交易日的全市场做空量。非交易日返回空表。"""
    url = URL.format(ymd=day.strftime("%Y%m%d"))
    try:
        txt = net.fetch_text(url, cache_ttl=86400 * 30)
    except Exception:
        return pd.DataFrame(columns=["symbol", "date", "short_vol",
                                     "short_exempt", "total_vol"])
    df = pd.read_csv(io.StringIO(txt), sep="|")
    df = df[df["Symbol"].notna()]
    out = pd.DataFrame({
        "symbol": df["Symbol"].astype(str).str.upper().str.replace(".", "-", regex=False),
        "date": day.strftime("%Y-%m-%d"),
        "short_vol": pd.to_numeric(df["ShortVolume"], errors="coerce"),
        "short_exempt": pd.to_numeric(df.get("ShortExemptVolume"), errors="coerce"),
        "total_vol": pd.to_numeric(df["TotalVolume"], errors="coerce"),
    })
    return out.dropna(subset=["total_vol"])


def fetch_recent(days: int = 30, end: dt.date | None = None,
                 verbose: bool = True) -> pd.DataFrame:
    """取最近若干个自然日的数据，自动跳过周末与休市日。"""
    end = end or dt.date.today()
    frames, got = [], 0
    for i in range(days * 2):          # 多留余量以覆盖节假日
        if got >= days:
            break
        d = end - dt.timedelta(days=i)
        if d.weekday() >= 5:           # 周六周日直接跳过
            continue
        df = fetch_day(d)
        if not df.empty:
            frames.append(df)
            got += 1
    if verbose:
        print(f"  取得 {len(frames)} 个交易日的做空数据")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def summarize(sv: pd.DataFrame) -> pd.DataFrame:
    """按股票汇总做空占比指标。

    short_ratio        最新交易日做空量占总成交量比例
    short_ratio_avg20  近 20 日均值，作为该股的“常态水平”
    short_ratio_z      最新值相对自身历史的 Z 分数，用来识别异常放大
    """
    if sv.empty:
        return pd.DataFrame()
    d = sv.copy()
    d["ratio"] = d["short_vol"] / d["total_vol"].replace(0, pd.NA)
    d = d.sort_values(["symbol", "date"])
    g = d.groupby("symbol")["ratio"]
    out = pd.DataFrame({
        "short_ratio": g.last(),
        "short_ratio_avg20": g.mean(),
        "short_ratio_std": g.std(),
        "short_days": g.count(),
    }).reset_index()
    out["short_ratio_z"] = ((out["short_ratio"] - out["short_ratio_avg20"]) /
                            out["short_ratio_std"].replace(0, pd.NA))
    return out
