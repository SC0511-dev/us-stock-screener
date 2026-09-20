"""
政要持仓（可选数据源）。

美国《STOCK 法案》要求国会议员在股票交易后 45 天内披露，
这类数据常被用作另类因子——但**它没有可靠的免费公开接口**。

实测情况（2026 年 9 月）：
    众议院披露站 disclosures-clerk.house.gov   Akamai 拦截，真实浏览器访问也是 403
    参议院 efdsearch.senate.gov                同样 403
    第三方服务（Disclosed Capitol、Apify 等）    有免费层但都需要注册并使用 API Key

因此本模块设计成**可选插件**：默认关闭，不写死任何厂商。
若你有可用的数据源，在 config/settings.json 中配置后即可启用：

    {
      "politician_source": {
        "url": "https://例子/api/congress-trades?limit=1000",
        "api_key": "你的密钥",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "field_map": {
          "symbol": "ticker",
          "date": "transaction_date",
          "politician": "representative",
          "chamber": "chamber",
          "txn_type": "type",
          "amount_min": "amount_min",
          "amount_max": "amount_max"
        }
      }
    }

字段映射让你把任意数据源的字段名对应到本项目的表结构，
不必为每个服务商单独写适配代码。
"""
from __future__ import annotations

import json
import urllib.request

import pandas as pd

from .. import config, net

COLUMNS = ["symbol", "date", "politician", "chamber",
           "txn_type", "amount_min", "amount_max"]


def is_configured() -> bool:
    """是否已配置可用的政要持仓数据源。"""
    cfg = config.load().get("politician_source") or {}
    return bool(cfg.get("url"))


def fetch(verbose: bool = True) -> pd.DataFrame:
    """按配置抓取政要交易记录并映射成本项目的表结构。"""
    cfg = config.load().get("politician_source") or {}
    url = cfg.get("url")
    if not url:
        if verbose:
            print("  未配置 politician_source，跳过。"
                  "该因子为可选项，需自备第三方数据源。")
        return pd.DataFrame(columns=COLUMNS)

    headers = {"User-Agent": net.UA, "Accept": "application/json"}
    if cfg.get("api_key"):
        headers[cfg.get("auth_header", "Authorization")] = \
            cfg.get("auth_prefix", "Bearer ") + cfg["api_key"]

    try:
        req = urllib.request.Request(url, headers=headers)
        raw = json.loads(urllib.request.urlopen(
            req, timeout=60, context=net.CTX).read())
    except Exception as e:
        print(f"  数据源请求失败：{type(e).__name__}: {str(e)[:80]}")
        return pd.DataFrame(columns=COLUMNS)

    # 返回值可能是数组，也可能包在某个字段里
    if isinstance(raw, dict):
        for k in ("data", "results", "trades", "items"):
            if isinstance(raw.get(k), list):
                raw = raw[k]
                break
    if not isinstance(raw, list) or not raw:
        print("  数据源返回结果为空或结构无法识别")
        return pd.DataFrame(columns=COLUMNS)

    df = pd.DataFrame(raw)
    fm = cfg.get("field_map") or {}
    out = pd.DataFrame()
    for col in COLUMNS:
        src = fm.get(col, col)
        out[col] = df[src] if src in df.columns else None

    out = out[out["symbol"].notna()].copy()
    out["symbol"] = out["symbol"].astype(str).str.upper().str.replace(
        ".", "-", regex=False)
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for c in ("amount_min", "amount_max"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["date"])
    if verbose:
        print(f"  取得 {len(out)} 条交易记录，涉及 {out['symbol'].nunique()} 只股票")
    return out
