"""
公司事件：财报日。

数据来自纳斯达克官方财报日历，按日期查询，一次返回当天所有公布财报的公司。

为什么财报日重要：
    美股个股的财报披露时点高度分散，全年各周都有公司发布财报，
    财报前后往往出现波动率骤升与跳空，很多技术形态在这个窗口会失真。
    因此筛选时通常需要主动避开或专门捕捉这个窗口。

关于 PEAD（财报后漂移）：
    学术上被反复验证的现象是「超预期的公司在财报后数周仍倾向于继续上涨」。
    要完整刻画它需要分析师预期数据，而预期数据没有稳定的免费来源，
    因此本项目只提供「距财报日天数」这一维度，不做超预期判断。
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from .. import net

URL = "https://api.nasdaq.com/api/calendar/earnings?date={d}"


def fetch_day(day: dt.date) -> pd.DataFrame:
    """取某一天公布财报的公司列表。"""
    d = net.try_fetch_json(URL.format(d=day.isoformat()), cache_ttl=86400)
    rows = ((d or {}).get("data") or {}).get("rows") or []
    if not rows:
        return pd.DataFrame(columns=["symbol", "date", "kind", "detail"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "symbol": df["symbol"].astype(str).str.upper().str.replace(".", "-", regex=False),
        "date": day.strftime("%Y-%m-%d"),
        "kind": "earnings",
        # time 字段形如 time-pre-market / time-after-hours，指明盘前还是盘后公布
        "detail": df.get("time", pd.Series([""] * len(df))).astype(str),
    })


def fetch_range(days_ahead: int = 45, days_back: int = 15,
                verbose: bool = True) -> pd.DataFrame:
    """取未来与过去一段时间内的财报日。

    往前取一段是为了支持「刚公布财报」这类条件（财报后漂移窗口）。
    """
    today = dt.date.today()
    frames = []
    for i in range(-days_back, days_ahead + 1):
        d = today + dt.timedelta(days=i)
        if d.weekday() >= 5:           # 周末不会公布财报
            continue
        df = fetch_day(d)
        if not df.empty:
            frames.append(df)
    if verbose:
        print(f"  覆盖 {len(frames)} 个交易日")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def days_to_earnings(events: pd.DataFrame, as_of: str | None = None) -> pd.DataFrame:
    """计算每只股票距离最近一次财报的天数。

    days_to_earnings   距下一次财报的天数（未来，正数）
    days_since_earnings 距上一次财报的天数（过去，正数）
    """
    if events.empty:
        return pd.DataFrame(columns=["symbol", "days_to_earnings",
                                     "days_since_earnings"])
    ref = pd.Timestamp(as_of) if as_of else pd.Timestamp.today().normalize()
    e = events[events["kind"] == "earnings"].copy()
    e["d"] = pd.to_datetime(e["date"])

    fut = e[e["d"] >= ref].groupby("symbol")["d"].min()
    past = e[e["d"] < ref].groupby("symbol")["d"].max()
    out = pd.DataFrame({"next_earnings": fut, "last_earnings": past})
    out["days_to_earnings"] = (out["next_earnings"] - ref).dt.days
    out["days_since_earnings"] = (ref - out["last_earnings"]).dt.days
    return out.reset_index()
