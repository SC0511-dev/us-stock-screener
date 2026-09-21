"""
策略历史验证。

这里做的是「选股有效性检验」，而不是完整的交易回测——
不模拟下单、不考虑滑点与手续费、不做仓位管理，
只回答一个问题：**按这套条件在历史某天选出的股票，之后一段时间表现如何？**

做法是把时间轴切成若干个检验日，在每个检验日用当时可得的数据选股，
然后统计未来 5 / 20 / 60 个交易日的收益，并与同期基准对比。

必须注意的三个局限（结论务必据此打折）：
    幸存者偏差   股票池取自当前指数成分，历史上被剔除的公司不在其中，
                 这会系统性地高估策略表现，是本模块最大的偏差来源。
    前视偏差     财报因子按当前值计算，未还原“当时尚未披露”的状态；
                 因此含基本面条件的策略，其历史表现参考价值低于纯技术策略。
    样本量       检验日较少时，结果很大程度上取决于所处的市场环境。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators, patterns, screen, strategies

HORIZONS = (5, 20, 60)

# 回测面板由行情推导，因此只覆盖价格与量能类因子。
# 其余因子（财报、机构持仓、期权、做空、事件）只有「当前值」，
# 没有「当时可得的值」，把它们接到历史日期上会产生严重的前视偏差。
PANEL_CATEGORIES = {
    "趋势均线", "动量摆荡", "波动通道", "量能", "价格位置",
    "流动性", "K线形态", "相对强弱",
}
EXTERNAL_CATEGORIES = {
    "基本面", "估值", "财务评分", "市值", "市场结构",
    "期权情绪", "机构持仓", "事件驱动", "分析师预期", "政要持仓", "指数归属",
}


def unsupported_conditions(conditions: list[str]) -> list[tuple[str, str]]:
    """找出回测面板无法提供数据的条件，返回 [(条件key, 所属分类)]。

    这些条件在回测里会恒为假，若不提示，使用者会误以为
    「这个策略历史上从未触发」，而真实原因是数据不在面板里。
    """
    out = []
    for k in conditions:
        c = screen.CONDITIONS.get(k)
        if c and c.category in EXTERNAL_CATEGORIES:
            out.append((k, c.category))
    return out


def attach_current_factors(panel: pd.DataFrame) -> pd.DataFrame:
    """把「当前」的财报、做空、期权、机构持仓因子接到面板的每一行上。

    ⚠️ 这会引入严重的前视偏差：用今天才知道的财务数据去判断一年前该不该买。
    仅用于粗略观察因子方向，**得到的收益数字不具备任何预测意义**。
    调用方必须向使用者明确说明这一点。
    """
    from . import factors
    extra = []
    fund = factors.fundamental_snapshot()
    if not fund.empty:
        px = panel.sort_values("date").groupby("symbol", as_index=False).tail(1)
        fund = factors.add_scores(factors.add_valuation(fund, px[["symbol", "close"]]))
        extra.append(fund)
    for f in (factors.short_snapshot(), factors.options_snapshot(),
              factors.inst_snapshot()):
        if f is not None and not f.empty:
            extra.append(f)
    out = panel
    for e in extra:
        dup = [c for c in e.columns if c in out.columns and c != "symbol"]
        out = out.merge(e.drop(columns=dup), on="symbol", how="left")
    return out


def build_panel(prices: pd.DataFrame, bench: pd.DataFrame,
                with_patterns: bool = True) -> pd.DataFrame:
    """一次性计算全历史的因子面板，供各检验日反复取用。

    逐个日期重算指标会非常慢，这里算一次、后续按日期切片。
    """
    ind = indicators.compute_all(prices)
    if ind.empty:
        return ind
    if with_patterns:
        pat = patterns.scan_all(prices)
        if not pat.empty:
            pcols = [c for c in pat.columns if c in patterns.PATTERNS]
            ind = ind.merge(pat[["symbol", "date"] + pcols],
                            on=["symbol", "date"], how="left")
    ind = indicators.add_relative_strength(ind, bench)

    g = ind.groupby("symbol", sort=False)
    for c in ("ma50", "ma200", "rsi14", "macd_hist", "kdj_k", "kdj_d", "obv"):
        if c in ind.columns:
            ind[f"{c}_prev"] = g[c].shift(1)

    # 预先算好各持有期的前瞻收益，回测时直接取用
    for h in HORIZONS:
        ind[f"fwd_{h}"] = g["close"].shift(-h) / ind["close"] - 1
    return ind


def bench_forward(bench: pd.DataFrame) -> pd.DataFrame:
    """基准在各持有期的前瞻收益，用于计算超额收益。"""
    b = bench.sort_values("date").copy()
    for h in HORIZONS:
        b[f"bfwd_{h}"] = b["close"].shift(-h) / b["close"] - 1
    return b[["date"] + [f"bfwd_{h}" for h in HORIZONS]]


def test_dates(panel: pd.DataFrame, every: int = 21, warmup: int = 220) -> list[str]:
    """生成检验日序列。

    warmup 用于跳过指标尚未成形的早期区间（200 日均线至少需要 200 个交易日）。
    every 为间隔交易日数，默认约一个月一次。
    """
    ds = sorted(panel["date"].unique())
    return ds[warmup::every]


def run(conditions: list[str], panel: pd.DataFrame, bench: pd.DataFrame,
        every: int = 21, top: int | None = None,
        sort_by: str | None = None, ascending: bool = False) -> dict:
    """在历史各检验日运行条件组合，汇总选股表现。"""
    bf = bench_forward(bench).set_index("date")
    dates = test_dates(panel, every)
    rows, detail = [], []

    for d in dates:
        snap = panel[panel["date"] == d]
        if snap.empty:
            continue
        picked = screen.screen(snap, conditions, "and")
        if picked.empty:
            rows.append({"date": d, "n": 0})
            continue
        if sort_by and sort_by in picked.columns:
            picked = picked.sort_values(sort_by, ascending=ascending)
        if top:
            picked = picked.head(top)

        rec = {"date": d, "n": len(picked)}
        for h in HORIZONS:
            col, bcol = f"fwd_{h}", f"bfwd_{h}"
            r = picked[col].dropna()
            if r.empty:
                continue
            br = bf.loc[d, bcol] if d in bf.index else np.nan
            rec[f"ret_{h}"] = r.mean()
            rec[f"med_{h}"] = r.median()
            rec[f"win_{h}"] = (r > 0).mean()
            rec[f"bench_{h}"] = br
            rec[f"excess_{h}"] = r.mean() - br if pd.notna(br) else np.nan
            rec[f"beat_{h}"] = (r > br).mean() if pd.notna(br) else np.nan
        rows.append(rec)
        detail.append(picked.assign(test_date=d)[
            ["test_date", "symbol"] + [f"fwd_{h}" for h in HORIZONS]])

    per_date = pd.DataFrame(rows)
    summary = {}
    if not per_date.empty:
        act = per_date[per_date["n"] > 0]
        summary = {
            "检验次数": len(per_date),
            "有选出股票的次数": len(act),
            "平均每次选出": round(act["n"].mean(), 1) if len(act) else 0,
        }
        for h in HORIZONS:
            if f"ret_{h}" in per_date.columns:
                summary[f"{h}日平均收益"] = round(act[f"ret_{h}"].mean() * 100, 2)
                summary[f"{h}日基准收益"] = round(act[f"bench_{h}"].mean() * 100, 2)
                summary[f"{h}日超额收益"] = round(act[f"excess_{h}"].mean() * 100, 2)
                summary[f"{h}日胜率"] = round(act[f"win_{h}"].mean() * 100, 1)
                summary[f"{h}日跑赢基准比例"] = round(act[f"beat_{h}"].mean() * 100, 1)
    return {
        "summary": summary,
        "per_date": per_date,
        "detail": pd.concat(detail, ignore_index=True) if detail else pd.DataFrame(),
    }


def run_strategy(key: str, panel: pd.DataFrame, bench: pd.DataFrame,
                 every: int = 21, top: int | None = 20) -> dict:
    """按内置策略做历史验证。"""
    s = strategies.STRATEGIES[key]
    out = run(s.conditions, panel, bench, every, top, s.sort_by, s.ascending)
    out["strategy"] = s
    return out
