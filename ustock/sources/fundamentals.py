"""
基本面采集：SEC EDGAR XBRL。

为什么用 frames 接口而不是 companyfacts：
    companyfacts 一次返回一家公司的全部历史事实，单个文件 4~8 MB，
    500 家公司就要下载并缓存超过 1 GB，既慢又没必要。
    frames 接口按“指标 + 报告期”返回全市场横截面，一次请求覆盖上千家公司，
    拉取 12 个指标 × 10 个报告期只需约 120 次请求。

为什么需要标签回退链：
    美国会计准则允许公司在多个近义标签中选择，营收就至少有三种常见写法。
    单用 Revenues 只能覆盖约 380 家，叠加 RevenueFromContractWithCustomer 系列后
    覆盖面显著提升。这里按优先级依次取值，先到先得。
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from .. import net

# 指标定义：(分类账, 单位, 标签回退链, 期间类型)
# duration = 区间指标（利润表、现金流量表），instant = 时点指标（资产负债表）
METRICS: dict[str, tuple[str, str, list[str], str]] = {
    "revenue": ("us-gaap", "USD", [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ], "duration"),
    "net_income": ("us-gaap", "USD", ["NetIncomeLoss"], "duration"),
    "gross_profit": ("us-gaap", "USD", ["GrossProfit"], "duration"),
    "operating_income": ("us-gaap", "USD", [
        "OperatingIncomeLoss"], "duration"),
    # 约六成公司不单独披露毛利，需用「营收 − 营业成本」推导，
    # 因此这里把营业成本也拉下来，由 factors 层负责补算。
    "cost_of_revenue": ("us-gaap", "USD", [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfServices",
        "CostOfGoodsSold",
    ], "duration"),
    "ocf": ("us-gaap", "USD", [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ], "duration"),
    "capex": ("us-gaap", "USD", [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ], "duration"),
    "eps_diluted": ("us-gaap", "USD-per-shares", [
        "EarningsPerShareDiluted"], "duration"),
    "assets": ("us-gaap", "USD", ["Assets"], "instant"),
    "liabilities": ("us-gaap", "USD", ["Liabilities"], "instant"),
    "equity": ("us-gaap", "USD", [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ], "instant"),
    "cash": ("us-gaap", "USD", [
        "CashAndCashEquivalentsAtCarryingValue"], "instant"),
    "debt_lt": ("us-gaap", "USD", [
        "LongTermDebtNoncurrent", "LongTermDebt"], "instant"),
    "shares": ("dei", "shares", [
        "EntityCommonStockSharesOutstanding"], "instant"),
    # 下面三项用于计算 Piotroski F-Score 与 Altman Z-Score
    "assets_current": ("us-gaap", "USD", ["AssetsCurrent"], "instant"),
    "liabilities_current": ("us-gaap", "USD", ["LiabilitiesCurrent"], "instant"),
    "retained_earnings": ("us-gaap", "USD", [
        "RetainedEarningsAccumulatedDeficit"], "instant"),
}

FRAME_URL = "https://data.sec.gov/api/xbrl/frames/{tax}/{tag}/{unit}/{period}.json"


def recent_periods(n_quarters: int = 9, as_of: dt.date | None = None) -> list[str]:
    """生成最近 n 个季度的报告期标签，例如 CY2026Q2。

    从**当前季度**开始往回取，而不是预先回退几个季度。
    公司在季度结束后约四到八周才陆续申报，最新一两个季度确实可能数据稀疏，
    但请求一个空的 frame 成本极低（几十毫秒），而预先回退的代价是
    整整少掉一个季度的财报——所有滚动十二个月指标都会因此偏旧，
    对盈利快速变化的公司误差极大。

    数据是否足够由后续的连续性校验判断，不在这里预判。
    """
    d = as_of or dt.date.today()
    q = (d.month - 1) // 3 + 1
    y = d.year
    out = []
    for _ in range(n_quarters):
        out.append(f"CY{y}Q{q}")
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    return out


def annual_periods(n: int = 3, as_of: dt.date | None = None) -> list[str]:
    """生成最近 n 个年度报告期标签，例如 CY2025。

    现金流量表在 10-Q 中多按年初至今累计披露，季度 frames 因此只能匹配到零星几期，
    凑不满滚动十二个月所需的四期。年度 frames 覆盖面好得多（实测经营现金流可达 5700+ 家），
    因此作为 TTM 的回退口径。
    """
    d = as_of or dt.date.today()
    # 年报披露滞后，最近一个完整年度通常要到次年一季度后才齐全
    y = d.year - 1 if d.month >= 4 else d.year - 2
    return [f"CY{y - i}" for i in range(n)]


def fetch_frame(tag: str, period: str, tax: str = "us-gaap",
                unit: str = "USD", ua: str | None = None) -> pd.DataFrame:
    """拉取单个“指标 + 报告期”的全市场横截面。失败返回空表。"""
    url = FRAME_URL.format(tax=tax, tag=tag, unit=unit, period=period)
    d = net.try_fetch_json(url, ua=ua or net.DEFAULT_SEC_UA, cache_ttl=86400 * 7)
    rows = (d or {}).get("data") or []
    if not rows:
        return pd.DataFrame(columns=["cik", "end", "val"])
    df = pd.DataFrame(rows)[["cik", "end", "val"]]
    df["cik"] = df["cik"].astype(int)
    return df


def fetch_metric(metric: str, periods: list[str], ua: str | None = None,
                 verbose: bool = True) -> pd.DataFrame:
    """按标签回退链拉取某指标的多期数据。

    同一公司同一报告期若在多个标签下都有值，取回退链中排序靠前的那个。
    """
    tax, unit, tags, kind = METRICS[metric]
    frames = []
    for period in periods:
        p = period + ("I" if kind == "instant" else "")
        got: set[int] = set()
        for prio, tag in enumerate(tags):
            df = fetch_frame(tag, p, tax, unit, ua)
            if df.empty:
                continue
            df = df[~df["cik"].isin(got)]
            if df.empty:
                continue
            got |= set(df["cik"])
            df = df.assign(metric=metric, period=period, tag=tag, prio=prio)
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["cik", "end", "val", "metric", "period", "tag"])
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["cik", "period", "prio"]).drop_duplicates(
        ["cik", "period"], keep="first").drop(columns=["prio"])


def build(metrics: list[str] | None = None, n_quarters: int = 9,
          n_years: int = 3, ua: str | None = None,
          verbose: bool = True) -> pd.DataFrame:
    """拉取全部指标，返回长表：cik / metric / period / end / val / freq。

    区间类指标同时拉取季度与年度两种口径：季度用于计算同比与滚动十二个月，
    年度作为季度数据不足时的回退。时点类指标只需季度（取的是时点余额）。
    """
    metrics = metrics or list(METRICS)
    periods = recent_periods(n_quarters)
    years = annual_periods(n_years)
    if verbose:
        print(f"  季度：{periods[0]} 回溯至 {periods[-1]}（{len(periods)} 期）")
        print(f"  年度：{', '.join(years)}")
    out = []
    for i, m in enumerate(metrics, 1):
        df = fetch_metric(m, periods, ua)
        if not df.empty:
            df["freq"] = "Q"
        parts = [df]
        # 只有区间指标才有年度口径；时点指标的年度值与季度末余额重复
        if METRICS[m][3] == "duration":
            da = fetch_metric(m, years, ua)
            if not da.empty:
                da["freq"] = "A"
                parts.append(da)
        got = pd.concat([x for x in parts if not x.empty], ignore_index=True) \
            if any(not x.empty for x in parts) else pd.DataFrame()
        if verbose:
            nq = df["cik"].nunique() if not df.empty else 0
            na = (got[got["freq"] == "A"]["cik"].nunique()
                  if not got.empty and "freq" in got else 0)
            print(f"  [{i}/{len(metrics)}] {m:18s} 季度 {nq:>5} 家 / 年度 {na:>5} 家")
        if not got.empty:
            out.append(got)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()
