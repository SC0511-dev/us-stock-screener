"""
内置选股策略。

策略 = 一组条件 + 一个排序口径。

这里收录的都是**美股市场长期使用、且多数有公开研究支撑**的范式。
美股可当日回转交易、无单日涨跌幅限制、允许做空，财报披露时点分散，
机构持仓与做空数据按季或按日公开——这些特征共同决定了下面这些策略的设计方式。

策略分四类：
    趋势动量   顺势交易，牛市有效、熊市失效
    质量价值   基于财报的选股，换手低、周期长
    事件结构   围绕财报、机构持仓、期权与做空的特定情形
    防御反转   低波动与均值回归

> 所有策略的输出都只是研究起点，不构成投资建议。
> 每个策略都标注了「局限」，请务必连同结果一起阅读。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import screen


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    desc: str
    conditions: list[str]
    sort_by: str = "rs_rating"
    ascending: bool = False
    note: str = ""
    family: str = "趋势动量"


STRATEGIES: dict[str, Strategy] = {}


def reg(s: Strategy) -> None:
    STRATEGIES[s.key] = s


# ═══════════════════════════ 一、趋势动量 ═══════════════════════════

reg(Strategy(
    key="minervini",
    name="Minervini 趋势模板",
    desc="美股波段交易最广为人知的筛选框架：价格位于各条中长期均线之上、"
         "均线多头排列、200 日均线向上、已明显脱离 52 周低点且接近 52 周高点，"
         "相对强弱排名进入前 30%。",
    conditions=["above_ma50", "above_ma150", "above_ma200", "ma_bull_stack",
                "ma200_rising", "off_52w_low_30", "rs_strong", "liquid_10000000"],
    note="只在牛市或结构性行情中有效；熊市几乎选不出票，空结果本身就是风险提示。",
))

reg(Strategy(
    key="vcp",
    name="VCP 波动收缩形态",
    desc="Minervini 的招牌形态：强势股在高位横盘整理时，波动区间逐次收窄、"
         "成交量同步萎缩，代表卖压衰竭，随后往往以放量突破结束整理。"
         "这里用「波动率收缩 + ATR 收敛 + 缩量 + 贴近高点 + 趋势向上」量化刻画。",
    conditions=["vol_contracting", "atr_tight", "volume_dry_5d", "near_52w_high",
                "above_ma50", "ma_bull_stack", "rs_strong", "liquid_10000000"],
    sort_by="rs_rating",
    note="量能萎缩用 5 日均量与 20 日均量之比来判断，而非当日量比——"
         "单日成交量会被三巫日、指数调仓、财报日等一次性事件严重干扰。"
         "VCP 的精髓是「收缩次数与幅度逐级递减」，纯用当日快照只能近似。"
         "形态本身不给方向，必须等放量突破确认，否则可能向下破位。",
))

reg(Strategy(
    key="darvas_box",
    name="Darvas 箱体突破",
    desc="达瓦斯箱体法：股价在箱体内震荡后放量突破箱顶。"
         "这里以「创 52 周新高 + 显著放量 + 趋势确认」作为突破信号。"
         "美股没有单日涨跌幅限制，突破后价格可连续运行，这类策略因此更易执行。",
    conditions=["at_52w_high", "volume_surge", "adx_trending",
                "above_ma50", "liquid_10000000"],
    sort_by="vol_ratio",
    note="突破失败（假突破）比例不低。原法依靠箱体下沿止损控制风险，"
         "本项目不提供止损执行，使用时须自行设定离场规则。",
))

reg(Strategy(
    key="dual_momentum",
    name="双动量",
    desc="Antonacci 的双动量框架：同时要求绝对动量为正（12 个月自身上涨）"
         "与相对动量领先（跑赢大盘），再加长期趋势过滤。"
         "绝对动量用于在熊市中自动离场，是它相对纯相对动量的关键改进。",
    conditions=["mom_12m_pos", "mom_12_1_top", "rs_leader",
                "above_ma200", "liquid_10000000"],
    sort_by="rs_rating",
    note="动量因子长期有效但存在「动量崩溃」：市场由跌转涨的拐点处回撤极大。",
))

reg(Strategy(
    key="momentum_leader",
    name="动量龙头",
    desc="中期动量与相对强弱双双领先，且价格站上全部关键均线，聚焦市场最强的一批股票。",
    conditions=["rs_leader", "mom_3m_strong", "above_ma50", "above_ma200",
                "ma_bull_stack", "liquid_50000000"],
    sort_by="mom_6m",
    note="风格切换时回撤剧烈，且龙头股估值通常不便宜。",
))

reg(Strategy(
    key="ma_pullback",
    name="强势股回踩均线",
    desc="长期趋势向上、均线多头排列，短期回调至 50 日均线附近的顺势买点。",
    conditions=["above_ma200", "ma_bull_stack", "near_ma50", "rs_strong",
                "liquid_10000000"],
    note="50 日与 200 日均线是美股机构普遍参考的趋势线，回调至此常有承接。"
         "但均线只是参考位，跌破后继续下行同样常见，须自行设定离场规则。",
))

reg(Strategy(
    key="canslim_lite",
    name="CANSLIM 简化版",
    desc="O'Neil 体系的可量化部分：营收与净利润同比双增、贴近 52 周高点、相对强弱领先。",
    conditions=["rev_growth_20", "ni_growth_20", "near_52w_high",
                "rs_leader", "above_ma50", "liquid_10000000"],
    note="原版还包含机构认可度与行业龙头判断，本项目只实现可量化部分。",
))

# ═══════════════════════════ 二、质量价值 ═══════════════════════════

reg(Strategy(
    key="piotroski",
    name="Piotroski 高分股",
    desc="Piotroski F-Score 用九项财务指标的逐年变化判断基本面是否在改善："
         "盈利性、现金流质量、杠杆与流动性、运营效率。"
         "得分 8 分以上代表财务状况稳健且在持续改善。"
         "原始研究发现该指标在低市净率股票中区分度最强，故叠加估值条件。",
    conditions=["f_score_8", "pb_below_3", "profitable", "liquid_10000000"],
    sort_by="f_score",
    family="质量价值",
    note="F-Score 衡量的是「改善趋势」而非「绝对优秀」，"
         "一家从很差改善到一般的公司也可能拿高分。",
))

reg(Strategy(
    key="magic_formula",
    name="神奇公式",
    desc="Greenblatt 的组合：同时看资本回报率与息税前收益率，两项排名相加取最优。"
         "思路是「用便宜的价格买回报率高的生意」。",
    conditions=["magic_top100", "profitable", "liquid_10000000"],
    sort_by="magic_rank",
    ascending=True,
    family="质量价值",
    note="原版用「净营运资本＋净固定资产」算资本回报，免费数据拿不到净固定资产，"
         "本项目用「总资产 − 流动负债」近似，结果与原版会有差异。"
         "该公式对金融股与强周期股不适用。",
))

reg(Strategy(
    key="quality_growth",
    name="高质量成长股",
    desc="高毛利、高净资产收益率、营收持续增长、自由现金流为正，"
         "并要求 Piotroski 分数不低，排除「增长但财务恶化」的情形。",
    conditions=["rev_growth_20", "gross_margin_50", "roe_15", "fcf_positive",
                "profitable", "f_score_7", "liquid_10000000"],
    sort_by="revenue_yoy",
    family="质量价值",
    note="不含估值约束，选出的公司可能已经很贵，需另行判断买入价位。",
))

reg(Strategy(
    key="value_quality",
    name="低估值优质股",
    desc="盈利稳健、负债可控、自由现金流为正、估值合理，"
         "并要求 Altman Z 处于安全区以规避价值陷阱。",
    conditions=["profitable", "pe_below_25", "moderate_debt", "fcf_positive",
                "roe_15", "altman_safe", "liquid_10000000"],
    sort_by="pe",
    ascending=True,
    family="质量价值",
    note="低市盈率常常是「价值陷阱」——业务衰退导致的便宜并不值得买。",
))

reg(Strategy(
    key="cash_cow",
    name="现金奶牛",
    desc="自由现金流收益率高、利润率稳健、负债低，适合偏防御的配置。",
    conditions=["fcf_yield_5", "fcf_margin_10", "low_debt", "profitable",
                "liquid_10000000"],
    sort_by="fcf_yield",
    family="质量价值",
    note="周期性行业在景气高点也会呈现高现金流收益率，需判断是否可持续。",
))

# ═══════════════════════════ 三、事件结构 ═══════════════════════════

reg(Strategy(
    key="pead",
    name="财报后漂移",
    desc="学术上被反复验证的 PEAD 现象：财报公布后，价格倾向于沿财报当日的方向"
         "继续漂移数周。这里捕捉「刚公布财报 + 跳空高开 + 趋势未破」的组合。",
    conditions=["pead_window", "gap_up", "above_ma50", "rs_strong",
                "liquid_10000000"],
    sort_by="rs_rating",
    family="事件结构",
    note="完整的 PEAD 需要分析师预期数据来判断是否超预期，"
         "而预期数据没有稳定的免费来源，因此这里用「跳空方向」近似替代，效果会打折。",
))

reg(Strategy(
    key="inst_favorite",
    name="机构重仓股",
    desc="13F 显示机构持有家数众多、持股占流通市值比例高，同时技术面处于上升趋势。"
         "机构集中持有意味着流动性好、研究覆盖充分。",
    conditions=["inst_many_holders", "inst_own_high", "above_ma200",
                "rs_strong", "liquid_10000000"],
    sort_by="inst_holders",
    family="事件结构",
    note="13F 每季度披露且滞后 45 天，反映的是上季度末的持仓，不是当前持仓。"
         "机构高度拥挤的股票在风格切换时也更容易被集中抛售。",
))

reg(Strategy(
    key="unusual_options",
    name="期权异动",
    desc="期权名义成交量达到正股成交量两倍以上，同时正股放量上涨——"
         "通常意味着有资金在用期权表达方向性观点。",
    conditions=["option_unusual", "volume_up", "above_ma50", "liquid_10000000"],
    sort_by="opt_stock_vol",
    family="事件结构",
    note="期权异动同样可能来自对冲、备兑开仓或做市商调仓，并不必然是看多。"
         "需结合认沽认购比与价格方向一起判断。",
))

reg(Strategy(
    key="short_squeeze",
    name="轧空候选",
    desc="做空成交占比显著高于自身常态，同时价格站上 20 日均线并开始放量，"
         "空头回补可能推动价格加速上行。",
    conditions=["squeeze_candidate", "short_spike", "volume_up", "liquid_10000000"],
    sort_by="short_ratio",
    family="事件结构",
    note="美股特有玩法，风险极高：轧空来得快去得也快。"
         "且做空成交占比受做市商对冲干扰，绝对值高并不等于市场看空。",
))

# ═══════════════════════════ 四、防御反转 ═══════════════════════════

reg(Strategy(
    key="low_vol_quality",
    name="低波动优质股",
    desc="低波动异象：长期来看低波动股票的风险调整后收益反而优于高波动股票。"
         "这里在低波动基础上叠加盈利质量与财务安全要求。",
    conditions=["low_volatility", "profitable", "f_score_7", "moderate_debt",
                "altman_safe", "liquid_10000000"],
    sort_by="vol_20d",
    ascending=True,
    family="防御反转",
    note="低波动策略在强势牛市中会明显跑输，其价值主要体现在下跌与震荡期。",
))

reg(Strategy(
    key="squeeze_breakout",
    name="布林带挤压突破",
    desc="布林带收窄至低位、波动率同步收缩后向上突破，典型的蓄势启动形态。",
    conditions=["boll_squeeze", "vol_contracting", "above_ma50", "volume_up",
                "liquid_10000000"],
    sort_by="vol_ratio",
    family="防御反转",
    note="挤压只说明「即将变盘」，方向仍需趋势判断，反向突破同样常见。",
))

reg(Strategy(
    key="oversold_bounce",
    name="超跌反弹候选",
    desc="长期趋势仍在（站上 200 日线）但短期严重超卖，博取均值回归。",
    conditions=["above_ma200", "rsi_oversold", "below_ma20", "liquid_10000000"],
    sort_by="rsi14",
    ascending=True,
    family="防御反转",
    note="下跌趋势中的超卖可以更超卖，必须设止损；不适合已破位的个股。",
))

reg(Strategy(
    key="pattern_reversal",
    name="高可靠度看涨形态",
    desc="出现锤头、晨星、吞没等公认信号较强的看涨 K 线形态，且价格位于 200 日均线之上。",
    conditions=["pat_any_bull_hq", "above_ma200", "liquid_10000000"],
    family="防御反转",
    note="单一 K 线形态胜率有限，务必结合支撑位与成交量确认。",
))


def run(key: str, snap: pd.DataFrame, universe: pd.DataFrame | None = None,
        top: int | None = 30) -> tuple[Strategy, pd.DataFrame]:
    """运行指定策略，返回策略对象与选股结果。"""
    if key not in STRATEGIES:
        raise KeyError(f"未知策略：{key}。可用：{', '.join(STRATEGIES)}")
    s = STRATEGIES[key]
    out = screen.screen(snap, s.conditions, "and", universe)
    if not out.empty and s.sort_by in out.columns:
        out = out.sort_values(s.sort_by, ascending=s.ascending)
    return s, (out.head(top) if top else out)


def listing() -> pd.DataFrame:
    """列出全部内置策略。"""
    return pd.DataFrame([{
        "分类": s.family, "策略key": s.key, "名称": s.name,
        "条件数": len(s.conditions), "排序依据": s.sort_by,
    } for s in STRATEGIES.values()])
