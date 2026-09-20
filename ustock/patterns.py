"""
K 线形态识别（61 种）。

底层调用 TA-Lib 的 CDL 系列函数，与主流看盘软件口径一致。
返回值约定沿用 TA-Lib：正数表示看涨信号，负数表示看跌信号，0 表示当日未形成该形态。
绝对值 100 与 200 的区别在于形态的确认强度（部分形态区分普通型与强化型）。

使用形态时要注意两件事：
1. 形态是“提示”不是“结论”。单一 K 线形态的胜率普遍不高，必须结合趋势位置、
   成交量与所处支撑阻力一起看，本项目因此提供 trend_filter 参数做趋势过滤。
2. 形态在流动性差的小票上极易失真（价格跳动本身就不连续），
   建议配合成交额门槛筛选后再看形态。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import talib
    HAS_TALIB = True
except ImportError:
    HAS_TALIB = False

# 形态英文函数名 → (中文名, 方向倾向, 是否高可靠度)
# 方向倾向：bull=偏多，bear=偏空，both=需看信号正负判断
PATTERNS: dict[str, tuple[str, str, bool]] = {
    "CDL2CROWS": ("两只乌鸦", "bear", False),
    "CDL3BLACKCROWS": ("三只乌鸦", "bear", True),
    "CDL3INSIDE": ("三内部上涨/下跌", "both", False),
    "CDL3LINESTRIKE": ("三线打击", "both", True),
    "CDL3OUTSIDE": ("三外部上涨/下跌", "both", False),
    "CDL3STARSINSOUTH": ("南方三星", "bull", False),
    "CDL3WHITESOLDIERS": ("红三兵", "bull", True),
    "CDLABANDONEDBABY": ("弃婴", "both", True),
    "CDLADVANCEBLOCK": ("大敌当前", "bear", False),
    "CDLBELTHOLD": ("捉腰带线", "both", False),
    "CDLBREAKAWAY": ("脱离", "both", False),
    "CDLCLOSINGMARUBOZU": ("收盘光头光脚", "both", False),
    "CDLCONCEALBABYSWALL": ("藏婴吞没", "bull", False),
    "CDLCOUNTERATTACK": ("反击线", "both", False),
    "CDLDARKCLOUDCOVER": ("乌云压顶", "bear", True),
    "CDLDOJI": ("十字线", "both", False),
    "CDLDOJISTAR": ("十字星", "both", False),
    "CDLDRAGONFLYDOJI": ("蜻蜓十字", "bull", False),
    "CDLENGULFING": ("吞没形态", "both", True),
    "CDLEVENINGDOJISTAR": ("十字暮星", "bear", True),
    "CDLEVENINGSTAR": ("暮星", "bear", True),
    "CDLGAPSIDESIDEWHITE": ("跳空并列阳线", "both", False),
    "CDLGRAVESTONEDOJI": ("墓碑十字", "bear", False),
    "CDLHAMMER": ("锤头线", "bull", True),
    "CDLHANGINGMAN": ("上吊线", "bear", True),
    "CDLHARAMI": ("孕线", "both", False),
    "CDLHARAMICROSS": ("十字孕线", "both", False),
    "CDLHIGHWAVE": ("风高浪大线", "both", False),
    "CDLHIKKAKE": ("陷阱形态", "both", False),
    "CDLHIKKAKEMOD": ("修正陷阱形态", "both", False),
    "CDLHOMINGPIGEON": ("家鸽", "bull", False),
    "CDLIDENTICAL3CROWS": ("三胞胎乌鸦", "bear", False),
    "CDLINNECK": ("颈内线", "bear", False),
    "CDLINVERTEDHAMMER": ("倒锤头", "bull", False),
    "CDLKICKING": ("反冲形态", "both", True),
    "CDLKICKINGBYLENGTH": ("长缺影反冲", "both", False),
    "CDLLADDERBOTTOM": ("梯底", "bull", False),
    "CDLLONGLEGGEDDOJI": ("长腿十字", "both", False),
    "CDLLONGLINE": ("长实体蜡烛", "both", False),
    "CDLMARUBOZU": ("光头光脚", "both", False),
    "CDLMATCHINGLOW": ("相同低价", "bull", False),
    "CDLMATHOLD": ("铺垫形态", "bull", False),
    "CDLMORNINGDOJISTAR": ("十字晨星", "bull", True),
    "CDLMORNINGSTAR": ("晨星", "bull", True),
    "CDLONNECK": ("颈上线", "bear", False),
    "CDLPIERCING": ("刺透形态", "bull", True),
    "CDLRICKSHAWMAN": ("黄包车夫", "both", False),
    "CDLRISEFALL3METHODS": ("上升/下降三法", "both", True),
    "CDLSEPARATINGLINES": ("分离线", "both", False),
    "CDLSHOOTINGSTAR": ("射击之星", "bear", True),
    "CDLSHORTLINE": ("短实体蜡烛", "both", False),
    "CDLSPINNINGTOP": ("纺锤线", "both", False),
    "CDLSTALLEDPATTERN": ("停顿形态", "bear", False),
    "CDLSTICKSANDWICH": ("条形三明治", "bull", False),
    "CDLTAKURI": ("探水竿", "bull", False),
    "CDLTASUKIGAP": ("跳空并列阴阳线", "both", False),
    "CDLTHRUSTING": ("插入线", "bear", False),
    "CDLTRISTAR": ("三星形态", "both", True),
    "CDLUNIQUE3RIVER": ("奇特三河床", "bull", False),
    "CDLUPSIDEGAP2CROWS": ("向上跳空两乌鸦", "bear", False),
    "CDLXSIDEGAP3METHODS": ("跳空三法", "both", False),
}

# 公认信号质量较高、实战中更常用的形态子集
HIGH_QUALITY = [k for k, (_, _, hq) in PATTERNS.items() if hq]


def cn_name(fn: str) -> str:
    """英文形态函数名转中文名。"""
    return PATTERNS.get(fn, (fn, "", False))[0]


def scan(df: pd.DataFrame, only: list[str] | None = None) -> pd.DataFrame:
    """对单只股票识别全部形态，在原表上追加以形态函数名命名的列。"""
    if not HAS_TALIB:
        raise RuntimeError("形态识别需要 TA-Lib，请先安装：pip install TA-Lib")
    d = df.copy().reset_index(drop=True)
    o, h, l, c = (np.ascontiguousarray(d[x].astype("float64").to_numpy())
                  for x in ("open", "high", "low", "close"))
    for fn in (only or PATTERNS):
        try:
            d[fn] = getattr(talib, fn)(o, h, l, c)
        except Exception:
            d[fn] = 0
    return d


def scan_all(prices: pd.DataFrame, only: list[str] | None = None) -> pd.DataFrame:
    """批量识别多只股票的形态。"""
    out = []
    for _, g in prices.groupby("symbol", sort=False):
        g = g.sort_values("date")
        if len(g) < 20:
            continue
        out.append(scan(g, only))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def signals_on(df: pd.DataFrame, date: str | None = None,
               only: list[str] | None = None,
               trend_filter: bool = False) -> pd.DataFrame:
    """列出指定交易日出现的形态信号。

    参数：
        date          目标日期，默认取每只股票的最后一个交易日
        only          只看指定形态，例如 patterns.HIGH_QUALITY
        trend_filter  开启后只保留“顺势”信号：看涨形态要求价格在 20 日均线上方，
                      看跌形态要求在下方。可显著降低逆势形态的噪音。
    返回：
        symbol / date / 形态英文名 / 形态中文名 / 信号值 / 方向
    """
    scanned = scan_all(df, only)
    if scanned.empty:
        return pd.DataFrame()

    cols = [c for c in scanned.columns if c in PATTERNS]
    if date:
        snap = scanned[scanned["date"] == date]
    else:
        snap = scanned.groupby("symbol", as_index=False).tail(1)

    rows = []
    for _, r in snap.iterrows():
        for fn in cols:
            val = r[fn]
            if not val:
                continue
            direction = "看涨" if val > 0 else "看跌"
            if trend_filter and "ma20" in r and pd.notna(r["ma20"]):
                above = r["close"] > r["ma20"]
                if (val > 0) != above:      # 信号方向与趋势不一致则跳过
                    continue
            rows.append({
                "symbol": r["symbol"], "date": r["date"],
                "pattern": fn, "形态": cn_name(fn),
                "signal": int(val), "方向": direction,
                "强度": "强" if abs(val) >= 200 else "普通",
            })
    return pd.DataFrame(rows)
