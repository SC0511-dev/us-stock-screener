"""
选股引擎：把“条件”组合成“策略”。

核心概念只有两个：
    快照（snapshot） 每只股票在某个交易日的全部因子值，一行一只票
    条件（condition） 一个具名的布尔判断，例如“价格站上 50 日均线”

条件库里的条件大部分是程序化批量生成的（例如对 8 条均线分别生成“站上/跌破/金叉”），
这样既能覆盖到 200 条以上，又不会产生大量重复代码、改口径时也只需改一处。

所有条件都是纯函数：输入快照表，输出与之等长的布尔序列。
因此可以任意用与/或组合，也方便在回测里对历史某一天重放。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from . import indicators, patterns

MA_PERIODS = (5, 10, 20, 30, 50, 60, 120, 150, 200)


@dataclass(frozen=True)
class Condition:
    """一个可复用的筛选条件。"""
    key: str                    # 唯一标识，用于在策略里引用
    label: str                  # 中文说明
    category: str               # 所属分类，便于浏览
    fn: Callable[[pd.DataFrame], pd.Series]

    def __call__(self, df: pd.DataFrame) -> pd.Series:
        try:
            s = self.fn(df)
        except Exception:
            return pd.Series(False, index=df.index)
        return pd.Series(s, index=df.index).fillna(False).astype(bool)


CONDITIONS: dict[str, Condition] = {}


def register(key: str, label: str, category: str):
    """用装饰器注册条件。"""
    def deco(fn):
        CONDITIONS[key] = Condition(key, label, category, fn)
        return fn
    return deco


def add(key: str, label: str, category: str, fn) -> None:
    """直接注册条件，供程序化批量生成使用。"""
    CONDITIONS[key] = Condition(key, label, category, fn)


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """安全取列：列不存在时返回全 NaN，避免条件因缺列而报错。"""
    return df[name] if name in df.columns else pd.Series(np.nan, index=df.index)


# ════════════════════════ 一、趋势与均线 ════════════════════════

for p in MA_PERIODS:
    add(f"above_ma{p}", f"价格站上 {p} 日均线", "趋势均线",
        lambda d, p=p: _col(d, "close") > _col(d, f"ma{p}"))
    add(f"below_ma{p}", f"价格跌破 {p} 日均线", "趋势均线",
        lambda d, p=p: _col(d, "close") < _col(d, f"ma{p}"))
    add(f"near_ma{p}", f"价格贴近 {p} 日均线（±3%）", "趋势均线",
        lambda d, p=p: (_col(d, "close") / _col(d, f"ma{p}") - 1).abs() < 0.03)

add("ma_bull_stack", "均线多头排列（20>50>200）", "趋势均线",
    lambda d: (_col(d, "ma20") > _col(d, "ma50")) & (_col(d, "ma50") > _col(d, "ma200")))
add("ma_bear_stack", "均线空头排列（20<50<200）", "趋势均线",
    lambda d: (_col(d, "ma20") < _col(d, "ma50")) & (_col(d, "ma50") < _col(d, "ma200")))
add("golden_cross_50_200", "金叉：50 日上穿 200 日", "趋势均线",
    lambda d: (_col(d, "ma50") > _col(d, "ma200")) &
              (_col(d, "ma50_prev") <= _col(d, "ma200_prev")))
add("death_cross_50_200", "死叉：50 日下穿 200 日", "趋势均线",
    lambda d: (_col(d, "ma50") < _col(d, "ma200")) &
              (_col(d, "ma50_prev") >= _col(d, "ma200_prev")))
add("ma200_rising", "200 日均线向上", "趋势均线",
    lambda d: _col(d, "ma200") > _col(d, "ma200_prev"))
add("adx_trending", "ADX>25，趋势明确", "趋势均线", lambda d: _col(d, "adx") > 25)
add("adx_strong", "ADX>40，趋势强劲", "趋势均线", lambda d: _col(d, "adx") > 40)
add("adx_range", "ADX<20，震荡无趋势", "趋势均线", lambda d: _col(d, "adx") < 20)
add("dmi_bull", "DMI 多头（+DI>-DI）", "趋势均线",
    lambda d: _col(d, "plus_di") > _col(d, "minus_di"))
add("above_sar", "价格在 SAR 之上", "趋势均线", lambda d: _col(d, "close") > _col(d, "sar"))
add("aroon_bull", "Aroon 上行主导", "趋势均线",
    lambda d: _col(d, "aroon_up") > _col(d, "aroon_down"))

# ════════════════════════ 二、动量与摆荡 ════════════════════════

add("rsi_oversold", "RSI(14)<30 超卖", "动量摆荡", lambda d: _col(d, "rsi14") < 30)
add("rsi_overbought", "RSI(14)>70 超买", "动量摆荡", lambda d: _col(d, "rsi14") > 70)
add("rsi_healthy", "RSI(14) 在 40~70 强势区", "动量摆荡",
    lambda d: _col(d, "rsi14").between(40, 70))
add("rsi_rising", "RSI 较前日上升", "动量摆荡",
    lambda d: _col(d, "rsi14") > _col(d, "rsi14_prev"))
add("macd_above_zero", "MACD 在零轴之上", "动量摆荡", lambda d: _col(d, "macd") > 0)
add("macd_golden", "MACD 金叉", "动量摆荡",
    lambda d: (_col(d, "macd_hist") > 0) & (_col(d, "macd_hist_prev") <= 0))
add("macd_dead", "MACD 死叉", "动量摆荡",
    lambda d: (_col(d, "macd_hist") < 0) & (_col(d, "macd_hist_prev") >= 0))
add("macd_hist_growing", "MACD 柱状体放大", "动量摆荡",
    lambda d: _col(d, "macd_hist") > _col(d, "macd_hist_prev"))
add("kdj_golden", "KDJ 金叉", "动量摆荡",
    lambda d: (_col(d, "kdj_k") > _col(d, "kdj_d")) &
              (_col(d, "kdj_k_prev") <= _col(d, "kdj_d_prev")))
add("kdj_oversold", "KDJ 超卖（K<20）", "动量摆荡", lambda d: _col(d, "kdj_k") < 20)
add("cci_oversold", "CCI<-100", "动量摆荡", lambda d: _col(d, "cci") < -100)
add("cci_overbought", "CCI>100", "动量摆荡", lambda d: _col(d, "cci") > 100)
add("willr_oversold", "威廉指标超卖（<-80）", "动量摆荡", lambda d: _col(d, "willr") < -80)
add("mfi_oversold", "资金流量指标超卖（MFI<20）", "动量摆荡", lambda d: _col(d, "mfi") < 20)
add("mfi_strong", "资金流入强（MFI>50）", "动量摆荡", lambda d: _col(d, "mfi") > 50)
add("stochrsi_oversold", "StochRSI 超卖", "动量摆荡", lambda d: _col(d, "stochrsi_k") < 20)

for label, col in (("1 个月", "mom_1m"), ("3 个月", "mom_3m"),
                   ("6 个月", "mom_6m"), ("12 个月", "mom_12m")):
    add(f"{col}_pos", f"{label}动量为正", "动量摆荡", lambda d, c=col: _col(d, c) > 0)
    add(f"{col}_strong", f"{label}动量 >20%", "动量摆荡", lambda d, c=col: _col(d, c) > 0.20)
    add(f"{col}_weak", f"{label}动量 <-20%", "动量摆荡", lambda d, c=col: _col(d, c) < -0.20)

add("mom_12_1_top", "12-1 动量为正（学术口径）", "动量摆荡",
    lambda d: _col(d, "mom_12_1") > 0)
add("rs_leader", "相对强弱评级 ≥80（跑赢大盘）", "相对强弱",
    lambda d: _col(d, "rs_rating") >= 80)
add("rs_strong", "相对强弱评级 ≥70", "相对强弱", lambda d: _col(d, "rs_rating") >= 70)
add("rs_laggard", "相对强弱评级 ≤20（跑输大盘）", "相对强弱",
    lambda d: _col(d, "rs_rating") <= 20)

# ════════════════════════ 三、波动与通道 ════════════════════════

add("boll_upper_break", "突破布林上轨", "波动通道",
    lambda d: _col(d, "close") > _col(d, "boll_up"))
add("boll_lower_break", "跌破布林下轨", "波动通道",
    lambda d: _col(d, "close") < _col(d, "boll_low"))
add("boll_squeeze", "布林带收窄（带宽处于低位）", "波动通道",
    lambda d: _col(d, "boll_width") < 0.10)
add("boll_upper_half", "价格位于布林带上半区", "波动通道",
    lambda d: _col(d, "boll_pctb") > 0.5)
add("low_volatility", "年化波动率 <25%", "波动通道", lambda d: _col(d, "vol_20d") < 0.25)
add("high_volatility", "年化波动率 >60%", "波动通道", lambda d: _col(d, "vol_20d") > 0.60)
add("atr_tight", "ATR 占比 <3%（波动收敛）", "波动通道", lambda d: _col(d, "natr") < 3)
add("atr_wide", "ATR 占比 >6%（波动放大）", "波动通道", lambda d: _col(d, "natr") > 6)
add("vol_contracting", "波动收缩（20 日 < 60 日）", "波动通道",
    lambda d: _col(d, "vol_20d") < _col(d, "vol_60d"))

# ════════════════════════ 四、量能 ════════════════════════

add("volume_surge", "放量：成交量 >20 日均量 2 倍", "量能",
    lambda d: _col(d, "vol_ratio") > 2.0)
add("volume_up", "温和放量（>1.5 倍）", "量能", lambda d: _col(d, "vol_ratio") > 1.5)
add("volume_dry", "当日缩量（<0.6 倍）", "量能", lambda d: _col(d, "vol_ratio") < 0.6)
add("volume_dry_5d", "量能萎缩（5 日均量 <20 日均量的 0.8 倍）", "量能",
    lambda d: _col(d, "vol_ratio_5d") < 0.8)
add("volume_expanding_5d", "量能放大（5 日均量 >20 日均量的 1.3 倍）", "量能",
    lambda d: _col(d, "vol_ratio_5d") > 1.3)
add("volume_price_up", "放量上涨", "量能",
    lambda d: (_col(d, "vol_ratio") > 1.5) & (_col(d, "ret1") > 0.02))
add("volume_price_down", "放量下跌", "量能",
    lambda d: (_col(d, "vol_ratio") > 1.5) & (_col(d, "ret1") < -0.02))
add("obv_rising", "OBV 上升（资金净流入）", "量能",
    lambda d: _col(d, "obv") > _col(d, "obv_prev"))
add("adosc_positive", "佳庆震荡指标为正", "量能", lambda d: _col(d, "adosc") > 0)

for amt, label in ((1e6, "100 万"), (1e7, "1000 万"), (5e7, "5000 万"), (1e8, "1 亿")):
    add(f"liquid_{int(amt)}", f"日均成交额 >{label}美元", "流动性",
        lambda d, a=amt: _col(d, "dollar_vol_20d") > a)

# ════════════════════════ 五、价格位置 ════════════════════════

add("near_52w_high", "距 52 周高点 <5%", "价格位置",
    lambda d: _col(d, "pct_from_52w_high") > -0.05)
add("at_52w_high", "创 52 周新高", "价格位置",
    lambda d: _col(d, "close") > _col(d, "high_52w_prior"))
add("near_52w_low", "距 52 周低点 <10%", "价格位置",
    lambda d: _col(d, "pct_from_52w_low") < 0.10)
add("off_52w_low_30", "已自 52 周低点反弹 >30%", "价格位置",
    lambda d: _col(d, "pct_from_52w_low") > 0.30)
add("shallow_drawdown", "回撤 <10%", "价格位置", lambda d: _col(d, "drawdown") > -0.10)
add("deep_drawdown", "回撤 >30%", "价格位置", lambda d: _col(d, "drawdown") < -0.30)
add("gap_up", "跳空高开 >2%", "价格位置", lambda d: _col(d, "gap") > 0.02)
add("gap_down", "跳空低开 >2%", "价格位置", lambda d: _col(d, "gap") < -0.02)

# ════════════════════════ 六、K 线形态（61 种自动注册）════════════════════════

for _fn, (_cn, _dir, _hq) in patterns.PATTERNS.items():
    add(f"pat_{_fn.lower()}", f"形态：{_cn}", "K线形态",
        lambda d, f=_fn: _col(d, f) != 0)
    if _dir in ("both", "bull"):
        add(f"pat_{_fn.lower()}_bull", f"形态：{_cn}（看涨）", "K线形态",
            lambda d, f=_fn: _col(d, f) > 0)
    if _dir in ("both", "bear"):
        add(f"pat_{_fn.lower()}_bear", f"形态：{_cn}（看跌）", "K线形态",
            lambda d, f=_fn: _col(d, f) < 0)

add("pat_any_bull_hq", "出现任一高可靠度看涨形态", "K线形态",
    lambda d: pd.concat([_col(d, f) > 0 for f in patterns.HIGH_QUALITY], axis=1).any(axis=1))
add("pat_any_bear_hq", "出现任一高可靠度看跌形态", "K线形态",
    lambda d: pd.concat([_col(d, f) < 0 for f in patterns.HIGH_QUALITY], axis=1).any(axis=1))


# ════════════════════════ 快照与筛选 ════════════════════════

def build_snapshot(prices: pd.DataFrame, bench: pd.DataFrame | None = None,
                   date: str | None = None, with_patterns: bool = True) -> pd.DataFrame:
    """把行情长表加工成“一只票一行”的因子快照。

    除了当日因子，还会附带若干 *_prev 列（前一日取值），
    金叉、死叉这类需要比较相邻两日的条件依赖它们。
    """
    ind = indicators.compute_all(prices)
    if ind.empty:
        return ind
    if with_patterns:
        pat = patterns.scan_all(prices)
        pcols = [c for c in pat.columns if c in patterns.PATTERNS]
        ind = ind.merge(pat[["symbol", "date"] + pcols], on=["symbol", "date"], how="left")
    if bench is not None and not bench.empty:
        ind = indicators.add_relative_strength(ind, bench)

    # 生成前一日列
    need_prev = ["ma50", "ma200", "rsi14", "macd_hist", "kdj_k", "kdj_d", "obv"]
    g = ind.groupby("symbol", sort=False)
    for c in need_prev:
        if c in ind.columns:
            ind[f"{c}_prev"] = g[c].shift(1)

    snap = (ind[ind["date"] == date] if date
            else ind.sort_values("date").groupby("symbol", as_index=False).tail(1))
    return snap.reset_index(drop=True)


def screen(snap: pd.DataFrame, conditions: list[str], mode: str = "and",
           universe: pd.DataFrame | None = None) -> pd.DataFrame:
    """按条件筛选快照。

    参数：
        conditions 条件 key 列表，未注册的 key 会被忽略并提示
        mode       "and" 全部满足 / "or" 满足任一
        universe   可选，提供后会把公司名称与行业合并进结果
    """
    if snap.empty:
        return snap
    unknown = [k for k in conditions if k not in CONDITIONS]
    if unknown:
        print(f"  提示：忽略未知条件 {unknown}")
    conds = [CONDITIONS[k] for k in conditions if k in CONDITIONS]
    if not conds:
        return snap.iloc[0:0]

    masks = pd.concat([c(snap) for c in conds], axis=1)
    keep = masks.all(axis=1) if mode == "and" else masks.any(axis=1)
    out = snap[keep].copy()
    out["命中条件数"] = masks[keep].sum(axis=1)

    if universe is not None and not out.empty:
        u = universe.drop_duplicates("symbol")
        cols = [c for c in ("symbol", "name", "sector") if c in u.columns]
        out = out.merge(u[cols], on="symbol", how="left")
    return out


def list_conditions(category: str | None = None, keyword: str | None = None) -> pd.DataFrame:
    """浏览条件库。可按分类或关键词过滤。"""
    rows = [{"条件key": c.key, "说明": c.label, "分类": c.category}
            for c in CONDITIONS.values()
            if (category is None or c.category == category)
            and (keyword is None or keyword in c.label or keyword in c.key)]
    return pd.DataFrame(rows)


def categories() -> pd.Series:
    """各分类下的条件数量。"""
    return pd.Series([c.category for c in CONDITIONS.values()]).value_counts()


# ════════════════════════ 七、基本面（SEC 财报）════════════════════════
# 这些条件依赖 fundamentals 表；若未采集财报数据，条件恒为假，不会误判为通过。

add("profitable", "盈利（TTM 净利润为正）", "基本面",
    lambda d: _col(d, "net_income_ttm") > 0)
add("fcf_positive", "自由现金流为正", "基本面", lambda d: _col(d, "fcf_ttm") > 0)

for pct, lab in ((0.10, "10%"), (0.20, "20%"), (0.30, "30%"), (0.50, "50%")):
    add(f"rev_growth_{int(pct*100)}", f"营收同比增速 >{lab}", "基本面",
        lambda d, p=pct: _col(d, "revenue_yoy") > p)
add("rev_growth_neg", "营收同比下滑", "基本面", lambda d: _col(d, "revenue_yoy") < 0)
add("ni_growth_20", "净利润同比增速 >20%", "基本面",
    lambda d: _col(d, "net_income_yoy") > 0.20)

for pct, lab in ((0.30, "30%"), (0.50, "50%"), (0.70, "70%")):
    add(f"gross_margin_{int(pct*100)}", f"毛利率 >{lab}", "基本面",
        lambda d, p=pct: _col(d, "gross_margin") > p)
for pct, lab in ((0.10, "10%"), (0.20, "20%")):
    add(f"net_margin_{int(pct*100)}", f"净利率 >{lab}", "基本面",
        lambda d, p=pct: _col(d, "net_margin") > p)
add("op_margin_15", "营业利润率 >15%", "基本面", lambda d: _col(d, "op_margin") > 0.15)
add("fcf_margin_10", "自由现金流利润率 >10%", "基本面",
    lambda d: _col(d, "fcf_margin") > 0.10)

for pct, lab in ((0.15, "15%"), (0.20, "20%"), (0.30, "30%")):
    add(f"roe_{int(pct*100)}", f"净资产收益率 >{lab}", "基本面",
        lambda d, p=pct: _col(d, "roe") > p)
add("roa_5", "总资产收益率 >5%", "基本面", lambda d: _col(d, "roa") > 0.05)

add("low_debt", "长期负债权益比 <0.5", "基本面",
    lambda d: _col(d, "debt_to_equity") < 0.5)
add("moderate_debt", "长期负债权益比 <1", "基本面",
    lambda d: _col(d, "debt_to_equity") < 1.0)
add("high_debt", "长期负债权益比 >2", "基本面",
    lambda d: _col(d, "debt_to_equity") > 2.0)
add("strong_equity", "权益占总资产 >50%", "基本面",
    lambda d: _col(d, "equity_ratio") > 0.5)

# ── 估值 ──
for v, lab in ((15, "15"), (25, "25"), (40, "40")):
    add(f"pe_below_{v}", f"市盈率 <{lab}（且盈利）", "估值",
        lambda d, x=v: (_col(d, "pe") > 0) & (_col(d, "pe") < x))
add("pe_above_50", "市盈率 >50（高估值）", "估值", lambda d: _col(d, "pe") > 50)
for v in (2, 5, 10):
    add(f"ps_below_{v}", f"市销率 <{v}", "估值", lambda d, x=v: _col(d, "ps") < x)
add("pb_below_3", "市净率 <3", "估值", lambda d: _col(d, "pb") < 3)
add("fcf_yield_5", "自由现金流收益率 >5%", "估值", lambda d: _col(d, "fcf_yield") > 0.05)
add("ev_ebit_below_15", "EV/EBIT <15", "估值",
    lambda d: (_col(d, "ev_to_ebit") > 0) & (_col(d, "ev_to_ebit") < 15))

# ── 市值分层（美股口径）──
add("mega_cap", "超大盘股（市值 >2000 亿美元）", "市值",
    lambda d: _col(d, "market_cap") > 2e11)
add("large_cap", "大盘股（市值 >100 亿美元）", "市值",
    lambda d: _col(d, "market_cap") > 1e10)
add("mid_cap", "中盘股（20 亿~100 亿美元）", "市值",
    lambda d: _col(d, "market_cap").between(2e9, 1e10))
add("small_cap", "小盘股（3 亿~20 亿美元）", "市值",
    lambda d: _col(d, "market_cap").between(3e8, 2e9))
add("micro_cap", "微盘股（市值 <3 亿美元）", "市值",
    lambda d: _col(d, "market_cap") < 3e8)

# ════════════════════════ 八、市场结构（做空）════════════════════════

add("short_heavy", "做空成交占比 >60%", "市场结构",
    lambda d: _col(d, "short_ratio") > 0.60)
add("short_light", "做空成交占比 <40%", "市场结构",
    lambda d: _col(d, "short_ratio") < 0.40)
add("short_spike", "做空占比异常放大（Z>2）", "市场结构",
    lambda d: _col(d, "short_ratio_z") > 2)
add("short_easing", "做空占比异常回落（Z<-2）", "市场结构",
    lambda d: _col(d, "short_ratio_z") < -2)
add("squeeze_candidate", "轧空候选：做空占比高且价格站上 20 日线", "市场结构",
    lambda d: (_col(d, "short_ratio") > 0.55) & (_col(d, "close") > _col(d, "ma20")))

# ════════════════════════ 九、指数归属 ════════════════════════

add("in_sp500", "标普 500 成分股", "指数归属", lambda d: _col(d, "in_sp500") == 1)
add("in_ndx", "纳斯达克 100 成分股", "指数归属", lambda d: _col(d, "in_ndx") == 1)
add("in_dow", "道琼斯成分股", "指数归属", lambda d: _col(d, "in_dow") == 1)


# ════════════════════════ 十、事件驱动（财报日）════════════════════════
# 依赖 events 表；未采集财报日历时这些条件恒为假。

add("earnings_soon_5", "5 个自然日内公布财报", "事件驱动",
    lambda d: _col(d, "days_to_earnings").between(0, 5))
add("earnings_soon_14", "14 个自然日内公布财报", "事件驱动",
    lambda d: _col(d, "days_to_earnings").between(0, 14))
add("no_earnings_30", "未来 30 天内无财报（避开财报波动）", "事件驱动",
    lambda d: _col(d, "days_to_earnings").isna() | (_col(d, "days_to_earnings") > 30))
add("just_reported", "刚公布财报（5 日内）", "事件驱动",
    lambda d: _col(d, "days_since_earnings").between(0, 5))
add("pead_window", "财报后漂移窗口（1~45 日）", "事件驱动",
    lambda d: _col(d, "days_since_earnings").between(1, 45))
add("post_earnings_gap_up", "财报后跳空高开", "事件驱动",
    lambda d: (_col(d, "days_since_earnings").between(0, 2)) & (_col(d, "gap") > 0.02))


# ════════════════════════ 十一、财务综合评分 ════════════════════════

add("f_score_8", "Piotroski F-Score ≥8（财务稳健）", "财务评分",
    lambda d: _col(d, "f_score") >= 8)
add("f_score_7", "Piotroski F-Score ≥7", "财务评分", lambda d: _col(d, "f_score") >= 7)
add("f_score_low", "Piotroski F-Score ≤3（基本面恶化）", "财务评分",
    lambda d: _col(d, "f_score") <= 3)
add("altman_safe", "Altman Z >2.99（财务安全区）", "财务评分",
    lambda d: _col(d, "altman_z") > 2.99)
add("altman_distress", "Altman Z <1.81（财务困境信号）", "财务评分",
    lambda d: _col(d, "altman_z") < 1.81)
add("magic_top50", "神奇公式综合排名前 50", "财务评分",
    lambda d: _col(d, "magic_rank") <= 50)
add("magic_top100", "神奇公式综合排名前 100", "财务评分",
    lambda d: _col(d, "magic_rank") <= 100)
add("roce_15", "已动用资本回报率 >15%", "财务评分", lambda d: _col(d, "roce") > 0.15)
add("earnings_yield_8", "息税前收益率 >8%", "财务评分",
    lambda d: _col(d, "earnings_yield") > 0.08)

# ════════════════════════ 十二、机构持仓（13F）════════════════════════

add("inst_many_holders", "机构持有家数 >1000", "机构持仓",
    lambda d: _col(d, "inst_holders") > 1000)
add("inst_own_high", "机构持股占市值 >70%", "机构持仓",
    lambda d: _col(d, "inst_own_pct") > 0.70)
add("inst_own_low", "机构持股占市值 <30%（关注度低）", "机构持仓",
    lambda d: _col(d, "inst_own_pct") < 0.30)
add("inst_covered", "有机构持仓数据", "机构持仓",
    lambda d: _col(d, "inst_holders").notna())

# ════════════════════════ 十三、期权情绪 ════════════════════════

add("iv_elevated", "30 天隐含波动率 >40（预期波动大）", "期权情绪",
    lambda d: _col(d, "iv30") > 40)
add("iv_low", "30 天隐含波动率 <20（预期平静）", "期权情绪",
    lambda d: _col(d, "iv30") < 20)
add("pc_bullish", "认沽认购成交比 <0.7（偏多）", "期权情绪",
    lambda d: _col(d, "put_call_vol") < 0.7)
add("pc_bearish", "认沽认购成交比 >1.2（偏空/避险）", "期权情绪",
    lambda d: _col(d, "put_call_vol") > 1.2)
add("pc_oi_bullish", "认沽认购持仓比 <0.7", "期权情绪",
    lambda d: _col(d, "put_call_oi") < 0.7)
# 阈值依据实测分布标定：期权名义成交/正股成交量的中位数约 0.2、75 分位约 0.4，
# 超过 0.8 已属明显偏高，超过 1.5 相当罕见。
add("option_active", "期权名义成交偏高（>正股成交量 0.8 倍）", "期权情绪",
    lambda d: _col(d, "opt_stock_vol") > 0.8)
add("option_unusual", "期权异动：名义成交超过正股成交量", "期权情绪",
    lambda d: _col(d, "opt_stock_vol") > 1.2)
add("skew_steep", "波动率偏斜陡峭（下跌保护昂贵）", "期权情绪",
    lambda d: _col(d, "iv_skew") > 0.05)

# ════════════════════════ 十四、政要持仓（可选数据源）════════════════════════
# 需用户自行配置第三方数据源，未配置时这些条件恒为假。

add("politician_bought", "近 90 日有政要买入", "政要持仓",
    lambda d: _col(d, "pol_buys") > 0)
add("politician_bought_multi", "近 90 日多位政要买入（≥2 笔）", "政要持仓",
    lambda d: _col(d, "pol_buys") >= 2)
add("politician_net_buy", "近 90 日政要净买入", "政要持仓",
    lambda d: _col(d, "pol_buys") > _col(d, "pol_sells"))


# ════════════════════════ 十五、分析师预期 ════════════════════════
# 数据来自交易所汇总的一年期目标价。卖方预期系统性偏乐观，
# 不宜当作价格预测，更适合观察「预期与现价的偏离程度」。

add("target_upside_20", "距分析师目标价 >20% 空间", "分析师预期",
    lambda d: _col(d, "upside_to_target") > 0.20)
add("target_upside_40", "距分析师目标价 >40% 空间", "分析师预期",
    lambda d: _col(d, "upside_to_target") > 0.40)
add("above_target", "现价已超过分析师目标价", "分析师预期",
    lambda d: _col(d, "upside_to_target") < 0)
