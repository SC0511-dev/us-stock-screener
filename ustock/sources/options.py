"""
期权数据：CBOE 延迟报价。

CBOE 公开提供完整期权链且无需密钥，字段比多数免费源丰富：
每个合约都带隐含波动率、未平仓量、成交量与希腊字母，
标的层还直接给出 30 天隐含波动率（iv30）。

本模块**只保留聚合指标**，不落库逐合约数据。
原因是单只股票的完整期权链约 1.4 MB、三千多个合约，
全量存储对选股几乎没有增量价值，却会让数据库膨胀到几百 MB。

聚合出的指标：
    iv30              30 天隐含波动率，衡量市场对未来波动的定价
    put_call_vol      认沽/认购成交量比，>1 通常表示避险或看空情绪升温
    put_call_oi       认沽/认购未平仓量比，反映存量持仓的方向倾斜
    atm_iv            平值期权隐含波动率
    iv_skew           虚值认沽与虚值认购的隐含波动率之差，正值越大表示下跌保护越贵
    opt_stock_vol     期权名义成交量占正股成交量比例，用于识别期权异动

两个数据源的分工（实测所得）：
    CBOE     数据最全（含隐含波动率与希腊字母），但限流很严格，
             密集请求会被 429 拦截，因此只适合慢速、增量地补采。
    Nasdaq   只有成交量与未平仓量、没有隐含波动率，但可以稳定批量获取。

因此本模块优先尝试 CBOE，失败则退回 Nasdaq 取部分指标。
缺失的隐含波动率会保持为空，而不是用其他数值替代——
一个错误的波动率数字比没有数字危害更大。

注意：期权情绪指标的解读高度依赖上下文。
认沽比高既可能是看空，也可能只是持股者在买保险；
必须结合价格位置与该股自身的历史水平判断。
"""
from __future__ import annotations

import re

import pandas as pd

from .. import net

URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"

# 合约代码形如 AAPL260921C00245000：根代码 + 到期日(YYMMDD) + C/P + 行权价×1000
_RE = re.compile(r"^(?P<root>[A-Z]+)(?P<exp>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


def parse_contract(code: str) -> dict | None:
    """解析期权合约代码，取出到期日、方向与行权价。"""
    m = _RE.match(code)
    if not m:
        return None
    return {
        "exp": m.group("exp"),
        "is_put": m.group("cp") == "P",
        "strike": int(m.group("strike")) / 1000.0,
    }


def fetch_chain(symbol: str, cache_ttl: int = 21600) -> tuple[pd.DataFrame, dict]:
    """取单只股票的完整期权链与标的信息。失败返回空表。"""
    # CBOE 对含连字符的代码使用去掉分隔符的写法
    sym = symbol.replace("-", "")
    d = net.try_fetch_json(URL.format(sym=sym), cache_ttl=cache_ttl)
    data = (d or {}).get("data") or {}
    opts = data.get("options") or []
    if not opts:
        return pd.DataFrame(), {}
    df = pd.DataFrame(opts)
    parsed = df["option"].map(parse_contract)
    keep = parsed.notna()
    df = df[keep].copy()
    p = pd.DataFrame(list(parsed[keep]))
    df["is_put"] = p["is_put"].values
    df["strike"] = p["strike"].values
    df["exp"] = p["exp"].values
    meta = {k: v for k, v in data.items() if k != "options"}
    return df, meta


def summarize(symbol: str, chain: pd.DataFrame, meta: dict) -> dict:
    """把期权链压缩成一行聚合指标。"""
    if chain.empty:
        return {}
    spot = meta.get("current_price") or meta.get("close")
    puts, calls = chain[chain["is_put"]], chain[~chain["is_put"]]

    def s(df, col):
        return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())

    pv, cv = s(puts, "volume"), s(calls, "volume")
    po, co = s(puts, "open_interest"), s(calls, "open_interest")

    out = {
        "symbol": symbol,
        "iv30": meta.get("iv30"),
        "opt_volume": pv + cv,
        "opt_oi": po + co,
        "put_call_vol": pv / cv if cv else None,
        "put_call_oi": po / co if co else None,
    }

    if spot:
        # 平值：行权价最接近现价的一档，取认沽认购隐含波动率均值
        near = chain.assign(dist=(chain["strike"] - spot).abs()).nsmallest(8, "dist")
        iv = pd.to_numeric(near["iv"], errors="coerce").dropna()
        out["atm_iv"] = float(iv.mean()) if len(iv) else None

        # 波动率偏斜：虚值认沽（行权价低于现价 5~15%）减虚值认购（高于现价 5~15%）
        otm_p = puts[(puts["strike"] < spot * 0.95) & (puts["strike"] > spot * 0.85)]
        otm_c = calls[(calls["strike"] > spot * 1.05) & (calls["strike"] < spot * 1.15)]
        ivp = pd.to_numeric(otm_p["iv"], errors="coerce").dropna()
        ivc = pd.to_numeric(otm_c["iv"], errors="coerce").dropna()
        out["iv_skew"] = (float(ivp.mean() - ivc.mean())
                          if len(ivp) and len(ivc) else None)

        # 期权名义成交量（1 张合约 = 100 股）占正股成交量比例
        stock_vol = meta.get("volume")
        if stock_vol:
            out["opt_stock_vol"] = (pv + cv) * 100 / float(stock_vol)

    return out


NASDAQ_URL = ("https://api.nasdaq.com/api/quote/{sym}/option-chain?assetclass=stocks"
              "&limit=1000&excode=oprac&callput=callput&money=all&type=all")


def fetch_summary_nasdaq(symbol: str, cache_ttl: int = 21600) -> dict:
    """备用源：纳斯达克期权链。只能得到认沽认购比与持仓量，没有隐含波动率。"""
    sym = symbol.replace("-", ".")
    d = net.try_fetch_json(NASDAQ_URL.format(sym=sym), cache_ttl=cache_ttl)
    rows = (((d or {}).get("data") or {}).get("table") or {}).get("rows") or []
    if not rows:
        return {}
    df = pd.DataFrame(rows)

    def num(col):
        return pd.to_numeric(
            df.get(col, pd.Series(dtype=str)).astype(str).str.replace(",", ""),
            errors="coerce").fillna(0)

    cv, pv = num("c_Volume").sum(), num("p_Volume").sum()
    co, po = num("c_Openinterest").sum(), num("p_Openinterest").sum()
    if cv + pv + co + po == 0:
        return {}
    return {
        "symbol": symbol,
        "opt_volume": float(cv + pv),
        "opt_oi": float(co + po),
        "put_call_vol": float(pv / cv) if cv else None,
        "put_call_oi": float(po / co) if co else None,
        # 隐含波动率相关字段该源不提供，保持缺失
        "iv30": None, "atm_iv": None, "iv_skew": None,
    }


def fetch_summary(symbol: str, cache_ttl: int = 21600,
                  prefer_cboe: bool = True) -> dict:
    """取单只股票的期权聚合指标，自动在两个源之间切换。"""
    if prefer_cboe:
        try:
            chain, meta = fetch_chain(symbol, cache_ttl)
            out = summarize(symbol, chain, meta)
            if out:
                out["source"] = "cboe"
                return out
        except Exception:
            pass
    out = fetch_summary_nasdaq(symbol, cache_ttl)
    if out:
        out["source"] = "nasdaq"
    return out
