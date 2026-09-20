"""
公司概况：市值、行业分类与分析师目标价。

数据来自纳斯达克的 summary 接口，免费无需密钥。

为什么需要这个源：
    市值本可以用「股价 × 流通股数」算出，但 SEC 的流通股数标签
    （dei:EntityCommonStockSharesOutstanding）只覆盖约八成公司，
    而纳斯达克直接给出市值，覆盖面更完整、也更贴近市场口径。

    这个接口还顺带提供行业分类与一年期分析师目标价：
    前者让自定义股票池也能按行业筛选，后者可以算出「距目标价空间」，
    是少数能免费拿到的卖方预期类指标。

注意：分析师目标价是卖方机构预期的汇总，系统性偏乐观，
不宜当作价格预测，更适合用来观察预期与现价的偏离程度。
"""
from __future__ import annotations

import re

import pandas as pd

from .. import net

URL = "https://api.nasdaq.com/api/quote/{sym}/summary?assetclass=stocks"


def _num(x) -> float | None:
    """把 "929,487,966,806" / "$370.00" 这类字符串转成数字。"""
    if x is None:
        return None
    s = re.sub(r"[$,\s]", "", str(x))
    if s in ("", "N/A", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch(symbol: str, cache_ttl: int = 86400) -> dict:
    """取单只股票的概况。失败返回空字典。"""
    sym = symbol.replace("-", ".")
    d = net.try_fetch_json(URL.format(sym=sym), cache_ttl=cache_ttl)
    sd = ((d or {}).get("data") or {}).get("summaryData") or {}
    if not sd:
        return {}

    def val(key):
        v = sd.get(key)
        return v.get("value") if isinstance(v, dict) else v

    out = {
        "symbol": symbol,
        "market_cap_nq": _num(val("MarketCap")),
        "sector_nq": val("Sector"),
        "industry_nq": val("Industry"),
        "analyst_target": _num(val("OneYrTarget")),
        "avg_volume": _num(val("AverageVolume")),
    }
    return {k: v for k, v in out.items() if v not in (None, "", "N/A")}
