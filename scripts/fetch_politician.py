#!/usr/bin/env python3
"""采集政要持仓（可选功能，需自备第三方数据源）。

美国国会议员的股票交易披露没有可用的免费公开接口
（官方站点有反爬拦截，第三方服务均需注册密钥），
因此本功能默认关闭。配置方法见 ustock/sources/politician.py 顶部说明。

用法：
    python scripts/fetch_politician.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import store  # noqa: E402
from ustock.sources import politician as pol  # noqa: E402


def main():
    if not pol.is_configured():
        print("政要持仓数据源未配置，本功能已跳过。\n")
        print("这是一个可选因子。美国国会议员交易披露没有可靠的免费接口：")
        print("  · 官方披露站（众议院/参议院）有反爬拦截，程序与浏览器均被拒绝")
        print("  · 第三方服务有免费层，但都需要注册并使用 API Key")
        print("\n如需启用，请在 config/settings.json 中加入 politician_source 配置，")
        print("详见 ustock/sources/politician.py 顶部的示例。")
        return

    print("采集政要持仓…")
    t0 = time.time()
    df = pol.fetch()
    if df.empty:
        return
    u = store.query("SELECT symbol FROM universe")
    if not u.empty:
        df = df[df["symbol"].isin(set(u["symbol"]))]
    n = store.upsert(df, "politician_trades")
    store.set_meta("politician_last_fetch", time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"\n✅ 写入 {n:,} 条，用时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
