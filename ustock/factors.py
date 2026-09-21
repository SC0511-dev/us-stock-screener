"""
因子加工：把原始数据转换成可直接用于筛选的比率与派生指标。

分三块：
    fundamental_snapshot  财报事实 → TTM、同比增速、利润率、估值、偿债能力
    short_snapshot        FINRA 做空量 → 做空占比及其异常度
    merge_all             把行情因子、基本面因子、做空因子拼成一张宽表

关于 TTM 的说明：
    美股公司财年起止各不相同，直接用“最近四个自然季度”会对非日历财年公司产生偏差。
    这里按报告期末日期排序后取最近四期求和，只要这四期连续即可得到正确的滚动十二个月值；
    若可用期数不足四期，则返回空值而不是用不完整数据凑数——
    宁可显示“无数据”，也不要给出一个看起来合理但错误的估值倍数。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import store

# 区间类指标需要求 TTM，时点类指标直接取最新值
DURATION = ["revenue", "net_income", "gross_profit", "operating_income",
            "ocf", "capex", "eps_diluted", "cost_of_revenue"]
INSTANT = ["assets", "liabilities", "equity", "cash", "debt_lt", "shares",
           "assets_current", "liabilities_current", "retained_earnings"]


def fundamental_snapshot(symbols: list[str] | None = None) -> pd.DataFrame:
    """由财报事实表计算每只股票的基本面因子。

    实现上做了两件事来保证速度：
    1. 只读取需要的股票（默认取股票池），而不是把整张表载入内存——
       数据库里往往残留着其他批次采集的股票，全量读取会白白多处理几十万行；
    2. 用「按报告期倒序编号」的方式做向量化聚合，而不是逐只股票循环过滤。
       编号 0~3 即最近四个季度，4~7 即去年同期四个季度，
       于是滚动十二个月值与同比变化都能一次性算出。
    """
    sql = "SELECT symbol, tag, end_date, value, form FROM fundamentals"
    params: tuple = ()
    if symbols is None:
        u = store.query("SELECT symbol FROM universe")
        symbols = u["symbol"].tolist() if not u.empty else None
    if symbols:
        sql += f" WHERE symbol IN ({','.join('?' * len(symbols))})"
        params = tuple(symbols)
    f = store.query(sql, params)
    if f.empty:
        return pd.DataFrame()

    f["end_dt"] = pd.to_datetime(f["end_date"], errors="coerce")
    q_all = f[f["form"] == "FRAME_Q"].copy()
    a_all = f[f["form"] == "FRAME_A"].copy()

    # ── 用年报倒推缺失的第四季度 ──
    # 公司在 10-K 里披露全年，不单独披露第四季度，因此 SEC 的季度数据天然缺 Q4。
    # 若直接取「最近四行」求和，加到的会是不连续的四个季度
    # （中间漏掉一个季度、还跨了财年），滚动十二个月因此严重失真。
    # 这里用「全年 − 已有的三个季度」把缺失的那一季补出来。
    if not a_all.empty and not q_all.empty:
        m = a_all.merge(q_all, on=["symbol", "tag"], suffixes=("_a", "_q"))
        gap = (m["end_dt_a"] - m["end_dt_q"]).dt.days
        m = m[gap.between(0, 370)]          # 只保留落在该财年内的季度
        g = m.groupby(["symbol", "tag", "end_dt_a"], as_index=False).agg(
            n=("value_q", "size"), s=("value_q", "sum"),
            ann=("value_a", "first"))
        g = g[g["n"] == 3]                  # 恰好缺一个季度时才推导
        if not g.empty:
            derived = pd.DataFrame({
                "symbol": g["symbol"], "tag": g["tag"],
                "end_dt": g["end_dt_a"],
                "end_date": g["end_dt_a"].dt.strftime("%Y-%m-%d"),
                "value": g["ann"] - g["s"], "form": "FRAME_Q_DERIVED",
            })
            q_all = pd.concat([q_all, derived], ignore_index=True)

    q_all = q_all.drop_duplicates(["symbol", "tag", "end_date"], keep="first")
    q_all = q_all.sort_values(["symbol", "tag", "end_dt"], ascending=[True, True, False])
    q_all["rk"] = q_all.groupby(["symbol", "tag"]).cumcount()

    a_all = a_all.sort_values(["symbol", "tag", "end_dt"], ascending=[True, True, False])
    a_all["rk"] = a_all.groupby(["symbol", "tag"]).cumcount()

    q, a = q_all, a_all

    def _pivot(df, agg="sum"):
        if df.empty:
            return pd.DataFrame()
        return df.pivot_table(index="symbol", columns="tag",
                              values="value", aggfunc=agg)

    def _ttm_window(lo: int, hi: int) -> pd.DataFrame:
        """取排名 [lo, hi) 的四个季度求和，并校验它们确实连续覆盖十二个月。

        校验很有必要：即便补齐了第四季度，仍可能因个别季度缺报而出现空档。
        跨度明显偏离一年时宁可返回空，也不要给出一个错误的滚动十二个月值。
        """
        w = q[(q["rk"] >= lo) & (q["rk"] < hi)]
        if w.empty:
            return pd.DataFrame()
        stat = w.groupby(["symbol", "tag"]).agg(
            n=("value", "size"), s=("value", "sum"),
            lo_dt=("end_dt", "min"), hi_dt=("end_dt", "max"))
        span = (stat["hi_dt"] - stat["lo_dt"]).dt.days
        # 四个连续季度的首尾间隔约 270 天（三个季度的跨度），放宽到 240~300
        good = stat[(stat["n"] == 4) & span.between(240, 300)]
        if good.empty:
            return pd.DataFrame()
        return good.reset_index().pivot(index="symbol", columns="tag", values="s")

    ttm = _ttm_window(0, 4)
    ttm_py = _ttm_window(4, 8)

    ann = _pivot(a[a["rk"] == 0], "first")
    ann_py = _pivot(a[a["rk"] == 1], "first")

    inst = _pivot(q[(q["rk"] == 0) & (q["form"] == "FRAME_Q")], "first")
    inst_py = _pivot(q[(q["rk"] == 4) & (q["form"] == "FRAME_Q")], "first")

    idx = f["symbol"].drop_duplicates().sort_values()
    d = pd.DataFrame({"symbol": idx}).set_index("symbol")

    def col(df, tag):
        return df[tag].reindex(d.index) if (not df.empty and tag in df) \
            else pd.Series(np.nan, index=d.index)

    for m in DURATION:
        v = col(ttm, m)
        d[f"{m}_ttm"] = v.fillna(col(ann, m))          # 季度不足时用年度回退
        d[f"{m}_ttm_py"] = col(ttm_py, m).fillna(col(ann_py, m))
    for m in INSTANT:
        d[m] = col(inst, m)
        d[f"{m}_py"] = col(inst_py, m)

    # 同比增速用滚动十二个月对比，比单季对比更稳定，也避开季节性影响
    for m in ("revenue", "net_income"):
        cur, prev = d[f"{m}_ttm"], d[f"{m}_ttm_py"]
        prev = prev.where(prev > 0)
        d[f"{m}_yoy"] = cur / prev - 1

    d = d.reset_index()

    rev, ni = d["revenue_ttm"], d["net_income_ttm"]
    # 公司未直接披露毛利时，用「营收 − 营业成本」补算
    if "cost_of_revenue_ttm" in d.columns:
        d["gross_profit_ttm"] = d["gross_profit_ttm"].fillna(
            rev - d["cost_of_revenue_ttm"])
    # ── 盈利能力 ──
    d["gross_margin"] = d["gross_profit_ttm"] / rev.replace(0, np.nan)
    d["net_margin"] = ni / rev.replace(0, np.nan)
    d["op_margin"] = d["operating_income_ttm"] / rev.replace(0, np.nan)
    d["roe"] = ni / d["equity"].replace(0, np.nan)
    d["roa"] = ni / d["assets"].replace(0, np.nan)
    # ── 现金流 ──
    d["fcf_ttm"] = d["ocf_ttm"] - d["capex_ttm"].fillna(0)
    d["fcf_margin"] = d["fcf_ttm"] / rev.replace(0, np.nan)
    # ── 偿债与结构 ──
    d["debt_to_equity"] = d["debt_lt"] / d["equity"].replace(0, np.nan)
    d["equity_ratio"] = d["equity"] / d["assets"].replace(0, np.nan)
    d["cash_ratio"] = d["cash"] / d["assets"].replace(0, np.nan)
    return d


def add_scores(d: pd.DataFrame) -> pd.DataFrame:
    """计算三个美股常用的综合评分。

    这些评分的价值不在于“分高就能涨”，而在于用一个数字快速刻画公司的
    财务质量、破产风险与资本回报水平，便于横向比较和初筛。
    """
    d = d.copy()

    # ── Piotroski F-Score（9 分制财务质量）──
    # 由 Joseph Piotroski 于 2000 年提出，用九项逐年变化判断基本面是否在改善。
    # 得分 8~9 视为财务稳健，0~2 通常意味着基本面持续恶化。
    roa = d["net_income_ttm"] / d["assets"].replace(0, np.nan)
    roa_py = d["net_income_ttm_py"] / d["assets_py"].replace(0, np.nan)
    turn = d["revenue_ttm"] / d["assets"].replace(0, np.nan)
    turn_py = d["revenue_ttm_py"] / d["assets_py"].replace(0, np.nan)
    lev = d["debt_lt"] / d["assets"].replace(0, np.nan)
    lev_py = d["debt_lt_py"] / d["assets_py"].replace(0, np.nan)
    cr = d["assets_current"] / d["liabilities_current"].replace(0, np.nan)
    cr_py = d["assets_current_py"] / d["liabilities_current_py"].replace(0, np.nan)
    gm = d["gross_profit_ttm"] / d["revenue_ttm"].replace(0, np.nan)
    gm_py = d["gross_profit_ttm_py"] / d["revenue_ttm_py"].replace(0, np.nan)

    # 每个信号同时登记「判断结果」与「所需输入是否齐备」。
    # 必须显式检查输入，因为 pandas 里 NaN > 0 会得到 False 而不是 NaN——
    # 若只看比较结果，缺数据的公司会被当成「九项全不满足」而拿到 0 分。
    signals = {
        "f_roa_pos": (roa > 0, roa.notna()),                       # 盈利
        "f_cfo_pos": (d["ocf_ttm"] > 0, d["ocf_ttm"].notna()),     # 经营现金流为正
        "f_roa_up": (roa > roa_py, roa.notna() & roa_py.notna()),  # 盈利能力改善
        "f_accrual": (d["ocf_ttm"] > d["net_income_ttm"],          # 利润有现金支撑
                      d["ocf_ttm"].notna() & d["net_income_ttm"].notna()),
        "f_lev_down": (lev < lev_py, lev.notna() & lev_py.notna()),        # 杠杆下降
        "f_cr_up": (cr > cr_py, cr.notna() & cr_py.notna()),               # 流动性改善
        "f_no_dilution": (d["shares"] <= d["shares_py"] * 1.02,            # 未明显增发
                          d["shares"].notna() & d["shares_py"].notna()),
        "f_gm_up": (gm > gm_py, gm.notna() & gm_py.notna()),               # 毛利率改善
        "f_turn_up": (turn > turn_py, turn.notna() & turn_py.notna()),     # 资产周转改善
    }
    raw = sum((cond & ok).astype(int) for cond, ok in signals.values())
    d["f_score_valid"] = sum(ok.astype(int) for _, ok in signals.values())
    # 有效项太少时分数没有意义，必须置空而不是给 0 分。
    # 否则外国发行人（提交 20-F 而非 10-K，SEC XBRL 覆盖不同）这类
    # 纯粹缺数据的公司，会被显示成「F 分 0」即财务最差，严重误导。
    d["f_score"] = raw.where(d["f_score_valid"] >= 6)

    # ── Altman Z-Score（破产风险）──
    # Z > 2.99 财务安全，1.81~2.99 灰色地带，< 1.81 存在财务困境信号。
    # 该模型基于制造业样本推导，用于金融股与轻资产科技股时会失真。
    ta = d["assets"].replace(0, np.nan)
    wc = d["assets_current"] - d["liabilities_current"]
    d["altman_z"] = (1.2 * wc / ta
                     + 1.4 * d["retained_earnings"] / ta
                     + 3.3 * d["operating_income_ttm"] / ta
                     + 0.6 * d["market_cap"] / d["liabilities"].replace(0, np.nan)
                     + 1.0 * d["revenue_ttm"] / ta)

    # ── Magic Formula（格林布拉特神奇公式）──
    # 原版用 EBIT/(净营运资本+净固定资产) 衡量资本回报，
    # 免费数据拿不到净固定资产，这里用「总资产 − 流动负债」即已动用资本近似（ROCE）。
    capital = ta - d["liabilities_current"]
    d["roce"] = d["operating_income_ttm"] / capital.where(capital > 0)
    d["earnings_yield"] = d["operating_income_ttm"] / d["ev"].where(d["ev"] > 0)
    # 两项各自排名后相加，名次越小越好
    r1 = d["roce"].rank(ascending=False)
    r2 = d["earnings_yield"].rank(ascending=False)
    d["magic_rank"] = (r1 + r2).rank()
    return d


def add_valuation(fund: pd.DataFrame, px_snap: pd.DataFrame) -> pd.DataFrame:
    """结合最新股价计算市值与估值倍数。

    市值 = 最新收盘价 × 流通在外股数（来自 SEC dei 标签）。
    注意该股数为报告期末数字，回购或增发频繁的公司会有偏差。
    """
    d = fund.merge(px_snap[["symbol", "close"]], on="symbol", how="left")
    d["market_cap"] = d["close"] * d["shares"]
    mc = d["market_cap"]
    d["ps"] = mc / d["revenue_ttm"].replace(0, np.nan)
    # 亏损公司的市盈率没有意义，置空而不是给出负数
    pe = mc / d["net_income_ttm"].replace(0, np.nan)
    d["pe"] = pe.where(d["net_income_ttm"] > 0)
    d["pb"] = mc / d["equity"].replace(0, np.nan)
    d["fcf_yield"] = d["fcf_ttm"] / mc.replace(0, np.nan)
    d["ev"] = mc + d["debt_lt"].fillna(0) - d["cash"].fillna(0)
    ebitda_proxy = d["operating_income_ttm"]
    d["ev_to_ebit"] = d["ev"] / ebitda_proxy.where(ebitda_proxy > 0)
    return d


def short_snapshot(days: int = 20) -> pd.DataFrame:
    """由做空量表计算做空占比因子。"""
    sv = store.query(
        "SELECT symbol, date, short_vol, total_vol FROM short_volume "
        "WHERE date >= date('now', ?)", (f"-{days * 2} days",))
    if sv.empty:
        return pd.DataFrame()
    from .sources import shortvol
    return shortvol.summarize(sv)


def events_snapshot(as_of: str | None = None) -> pd.DataFrame:
    """由财报日历计算距财报天数因子。"""
    ev = store.query("SELECT symbol, date, kind, detail FROM events")
    if ev.empty:
        return pd.DataFrame()
    from .sources import events as ev_src
    return ev_src.days_to_earnings(ev, as_of)


def inst_snapshot() -> pd.DataFrame:
    """机构持仓因子：持有家数与机构持股市值。"""
    d = store.query("SELECT symbol, value, shares, holders FROM holdings13f "
                    "WHERE period=(SELECT MAX(period) FROM holdings13f)")
    if d.empty:
        return pd.DataFrame()
    return d.rename(columns={"value": "inst_value", "shares": "inst_shares",
                             "holders": "inst_holders"})


def options_snapshot(days: int = 7) -> pd.DataFrame:
    """期权情绪因子：逐字段取最近一次的有效值。

    不能简单地「只取最新日期那一批」。期权数据有两个来源：
    CBOE 提供隐含波动率与希腊字母但限流严格，Nasdaq 稳定可批量但没有波动率。
    若某天用 Nasdaq 补采了一遍，最新日期这批的隐含波动率全是空值，
    会让前一天从 CBOE 取到的有效数据凭空消失。

    因此这里在最近若干天的窗口内，对每个字段分别取最后一个非空值。
    """
    d = store.query(
        "SELECT * FROM options_agg WHERE date >= date('now', ?) ORDER BY date",
        (f"-{days} days",))
    if d.empty:
        return pd.DataFrame()
    # groupby().last() 默认跳过空值，正好实现「逐字段取最近有效值」
    out = d.drop(columns=[c for c in ("date", "source") if c in d.columns]) \
           .groupby("symbol", as_index=False).last()
    return out


def politician_snapshot(days: int = 90) -> pd.DataFrame:
    """政要持仓因子（可选数据源）：统计近期买入与卖出笔数。"""
    d = store.query("SELECT symbol, txn_type, date FROM politician_trades "
                    "WHERE date >= date('now', ?)", (f"-{days} days",))
    if d.empty:
        return pd.DataFrame()
    d["buy"] = d["txn_type"].str.lower().str.contains("purchase|buy", na=False)
    g = d.groupby("symbol")
    return pd.DataFrame({
        "pol_buys": g["buy"].sum(),
        "pol_sells": g["buy"].apply(lambda x: (~x).sum()),
        "pol_trades": g.size(),
    }).reset_index()


def merge_all(px_snap: pd.DataFrame, fund: pd.DataFrame | None = None,
              short: pd.DataFrame | None = None,
              universe: pd.DataFrame | None = None,
              events: pd.DataFrame | None = None,
              inst: pd.DataFrame | None = None,
              options: pd.DataFrame | None = None,
              politician: pd.DataFrame | None = None) -> pd.DataFrame:
    """把各类因子合并成一张宽表，缺失的部分保持为空值。"""
    out = px_snap.copy()
    for extra in (fund, short, events, inst, options, politician):
        if extra is not None and not extra.empty:
            dup = [c for c in extra.columns if c in out.columns and c != "symbol"]
            out = out.merge(extra.drop(columns=dup), on="symbol", how="left")
    if universe is not None and not universe.empty:
        cols = [c for c in ("symbol", "name", "sector", "theme",
                            "in_sp500", "in_ndx", "in_dow",
                            "market_cap_nq", "analyst_target",
                            "sector_nq", "industry_nq")
                if c in universe.columns]
        out = out.merge(universe[cols].drop_duplicates("symbol"), on="symbol", how="left")

    # 市值优先采用交易所口径：SEC 的流通股数标签只覆盖约八成公司，
    # 交易所直接给出的市值覆盖更完整，也更贴近市场实际口径。
    if "market_cap_nq" in out.columns:
        if "market_cap" in out.columns:
            out["market_cap"] = out["market_cap_nq"].fillna(out["market_cap"])
        else:
            out["market_cap"] = out["market_cap_nq"]
        # 市值口径变了，依赖它的估值倍数需要同步重算
        for col, base in (("ps", "revenue_ttm"), ("pb", "equity")):
            if base in out.columns:
                out[col] = out["market_cap"] / out[base].replace(0, np.nan)
        if "net_income_ttm" in out.columns:
            pe = out["market_cap"] / out["net_income_ttm"].replace(0, np.nan)
            out["pe"] = pe.where(out["net_income_ttm"] > 0)
        if "fcf_ttm" in out.columns:
            out["fcf_yield"] = out["fcf_ttm"] / out["market_cap"].replace(0, np.nan)

    # 距分析师一年期目标价的空间
    if "analyst_target" in out.columns and "close" in out.columns:
        out["upside_to_target"] = out["analyst_target"] / out["close"] - 1

    # 机构持股占比依赖市值，必须等市值口径最终确定后再算，
    # 否则会用到覆盖率较低的旧口径，导致部分股票结果为空。
    if "inst_value" in out.columns and "market_cap" in out.columns:
        out["inst_own_pct"] = out["inst_value"] / out["market_cap"].replace(0, np.nan)
    return out
