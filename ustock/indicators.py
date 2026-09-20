"""
技术指标与量价因子计算。

所有指标都基于 TA-Lib 计算，保证口径与主流看盘软件一致。
在传统指标之外，这里额外加入了几类美股选股常用、而 A 股体系里较少见的因子：

    相对强弱 RS      对标 IBD 的 Relative Strength，衡量个股跑赢大盘的程度
    动量分层         1/3/6/12 个月动量，动量因子是美股最经得起检验的因子之一
    距 52 周高点     美股突破策略的核心变量（A 股因有涨跌停，形态意义不同）
    美元成交额       美股无换手率口径统一问题，用成交额衡量流动性更直接
    回撤与波动       最大回撤、年化波动率、ATR 占比

输入是单只股票按日期升序排列的 OHLCV，输出在原表上追加指标列。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import talib
    HAS_TALIB = True
except ImportError:  # 没装 TA-Lib 时退化为仅计算纯 pandas 实现的因子
    HAS_TALIB = False

TRADING_DAYS = 252


def _arr(s: pd.Series) -> np.ndarray:
    """TA-Lib 只接受连续的 float64 数组。"""
    return np.ascontiguousarray(s.astype("float64").to_numpy())


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """为单只股票计算全部指标。df 需含 open/high/low/close/volume 且按日期升序。"""
    d = df.copy().reset_index(drop=True)
    o, h, l, c, v = (_arr(d[x]) for x in ("open", "high", "low", "close", "volume"))
    n = len(d)
    if n < 20:                       # 数据太短，指标无意义
        return d

    # ── 均线族 ──
    for p in (5, 10, 20, 30, 50, 60, 120, 150, 200):
        if n > p:
            d[f"ma{p}"] = talib.SMA(c, p) if HAS_TALIB else d["close"].rolling(p).mean()
    for p in (12, 26):
        if n > p:
            d[f"ema{p}"] = talib.EMA(c, p) if HAS_TALIB else d["close"].ewm(span=p).mean()

    if HAS_TALIB:
        # ── 趋势 ──
        d["macd"], d["macd_signal"], d["macd_hist"] = talib.MACD(c, 12, 26, 9)
        d["adx"] = talib.ADX(h, l, c, 14)          # 趋势强度，>25 视为有趋势
        d["adxr"] = talib.ADXR(h, l, c, 14)
        d["plus_di"] = talib.PLUS_DI(h, l, c, 14)
        d["minus_di"] = talib.MINUS_DI(h, l, c, 14)
        d["sar"] = talib.SAR(h, l)
        d["trix"] = talib.TRIX(c, 12)
        d["dpo"] = c - talib.SMA(c, 20)
        d["aroon_down"], d["aroon_up"] = talib.AROON(h, l, 14)

        # ── 摆荡 ──
        d["rsi6"], d["rsi14"] = talib.RSI(c, 6), talib.RSI(c, 14)
        d["kdj_k"], d["kdj_d"] = talib.STOCH(h, l, c, 9, 3, 0, 3, 0)
        d["kdj_j"] = 3 * d["kdj_k"] - 2 * d["kdj_d"]
        d["cci"] = talib.CCI(h, l, c, 14)
        d["willr"] = talib.WILLR(h, l, c, 14)
        d["mfi"] = talib.MFI(h, l, c, v, 14)
        d["roc"] = talib.ROC(c, 12)
        d["ppo"] = talib.PPO(c, 12, 26)
        d["ultosc"] = talib.ULTOSC(h, l, c)
        d["stochrsi_k"], d["stochrsi_d"] = talib.STOCHRSI(c, 14, 5, 3)

        # ── 波动 ──
        d["boll_up"], d["boll_mid"], d["boll_low"] = talib.BBANDS(c, 20, 2, 2)
        d["atr"] = talib.ATR(h, l, c, 14)
        d["natr"] = talib.NATR(h, l, c, 14)        # ATR 占价格百分比，可跨股比较
        d["trange"] = talib.TRANGE(h, l, c)

        # ── 量能 ──
        d["obv"] = talib.OBV(c, v)
        d["ad"] = talib.AD(h, l, c, v)
        d["adosc"] = talib.ADOSC(h, l, c, v, 3, 10)

    # ── 布林带宽度与位置（挤压突破策略的核心）──
    if "boll_up" in d:
        d["boll_width"] = (d["boll_up"] - d["boll_low"]) / d["boll_mid"]
        rng = (d["boll_up"] - d["boll_low"]).replace(0, np.nan)
        d["boll_pctb"] = (d["close"] - d["boll_low"]) / rng

    # ── 收益率与动量（美股动量因子）──
    d["ret1"] = d["close"].pct_change()
    for label, days in (("1m", 21), ("3m", 63), ("6m", 126), ("12m", TRADING_DAYS)):
        d[f"mom_{label}"] = d["close"].pct_change(days)
    # 12-1 动量：剔除最近一个月的反转效应，学术界标准口径
    d["mom_12_1"] = d["close"].shift(21).pct_change(TRADING_DAYS - 21)

    # ── 波动与回撤 ──
    d["vol_20d"] = d["ret1"].rolling(20).std() * np.sqrt(TRADING_DAYS)
    d["vol_60d"] = d["ret1"].rolling(60).std() * np.sqrt(TRADING_DAYS)
    roll_max = d["close"].rolling(TRADING_DAYS, min_periods=20).max()
    d["drawdown"] = d["close"] / roll_max - 1        # 当前距区间高点的回撤

    # ── 52 周高低点（美股突破策略核心变量）──
    d["high_52w"] = d["high"].rolling(TRADING_DAYS, min_periods=20).max()
    # 判断“创新高”要和不含当日的历史高点比，否则等价于要求收盘价正好等于当日最高价
    d["high_52w_prior"] = d["high"].shift(1).rolling(TRADING_DAYS, min_periods=20).max()
    d["low_52w"] = d["low"].rolling(TRADING_DAYS, min_periods=20).min()
    d["pct_from_52w_high"] = d["close"] / d["high_52w"] - 1
    d["pct_from_52w_low"] = d["close"] / d["low_52w"] - 1

    # ── 流动性与量能异动 ──
    d["dollar_vol"] = d["close"] * d["volume"]
    d["dollar_vol_20d"] = d["dollar_vol"].rolling(20).mean()
    d["vol_ma20"] = d["volume"].rolling(20).mean()
    d["vol_ratio"] = d["volume"] / d["vol_ma20"]     # 当日放量倍数
    # 单日量比容易被三巫日、指数调仓、财报日等一次性事件带偏，
    # 判断「量能萎缩」应当看一段时间的均量比，而不是某一天。
    d["vol_ma5"] = d["volume"].rolling(5).mean()
    d["vol_ratio_5d"] = d["vol_ma5"] / d["vol_ma20"]
    d["gap"] = d["open"] / d["close"].shift(1) - 1   # 跳空幅度

    # ── 价格相对均线位置 ──
    for p in (20, 50, 200):
        col = f"ma{p}"
        if col in d:
            d[f"px_vs_{col}"] = d["close"] / d[col] - 1

    return d


def compute_all(prices: pd.DataFrame, min_rows: int = 60) -> pd.DataFrame:
    """对多只股票批量计算指标。prices 为含 symbol 列的长表。"""
    out = []
    for sym, g in prices.groupby("symbol", sort=False):
        g = g.sort_values("date")
        if len(g) < min_rows:
            continue
        out.append(compute(g))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def add_relative_strength(ind: pd.DataFrame, bench: pd.DataFrame,
                          windows=(63, 126, TRADING_DAYS)) -> pd.DataFrame:
    """加入相对强弱因子：个股相对基准（默认 SPY）的超额动量，并给出横截面百分位。

    rs_<n>      个股 n 日涨幅减基准 n 日涨幅，为正表示跑赢大盘
    rs_rating   综合多窗口后的百分位得分（0~99），对标 IBD 的 RS Rating

    注意 date 列在整个项目中统一使用 "YYYY-MM-DD" 字符串，
    基准序列的索引必须与之保持同一类型，否则对齐会静默失败、得分全部退化成中位数。
    """
    ind = ind.copy()
    b = bench.sort_values("date")
    # 与 ind["date"] 保持一致的字符串索引
    b = b.assign(date=b["date"].astype(str)).set_index("date")["close"]

    valid = []
    for w in windows:
        bench_ret = b.pct_change(w)
        br = ind["date"].astype(str).map(bench_ret)
        stock_ret = ind.groupby("symbol")["close"].pct_change(w)
        ind[f"rs_{w}"] = stock_ret - br
        if ind[f"rs_{w}"].notna().any():
            valid.append(w)

    if not valid:
        # 基准数据不足时不要伪造分数，留空比给出误导性的 50 分更诚实
        ind["rs_score"] = np.nan
        ind["rs_rating"] = np.nan
        return ind

    # IBD 的 RS Rating 给近期更高权重，这里用 2:1:1 近似
    weights = {63: 0.5, 126: 0.25, TRADING_DAYS: 0.25}
    tot = sum(weights.get(w, 1 / len(valid)) for w in valid)
    score = sum(ind[f"rs_{w}"] * weights.get(w, 1 / len(valid)) for w in valid) / tot
    ind["rs_score"] = score
    # 百分位需在同一交易日内横向比较；当日样本不足时结果无意义，置空
    grp = ind.groupby("date")["rs_score"]
    ind["rs_rating"] = grp.rank(pct=True).mul(99).round(0)
    ind.loc[grp.transform("count") < 20, "rs_rating"] = np.nan
    return ind
