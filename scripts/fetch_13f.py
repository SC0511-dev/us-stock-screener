#!/usr/bin/env python3
"""采集 SEC Form 13F 机构持仓。

首次运行需要把持仓里的 CUSIP 映射成股票代码，受 OpenFIGI 免费层速率限制，
大约需要十分钟；映射结果会永久缓存，之后每季度更新只需几十秒。

用法：
    python scripts/fetch_13f.py
    python scripts/fetch_13f.py --top 4000    # 映射更多标的（更慢但覆盖更广）
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import config, store  # noqa: E402
from ustock.sources import holdings13f as h13  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="采集 13F 机构持仓")
    ap.add_argument("--top", type=int, default=2500,
                    help="按持仓市值映射前 N 个标的，默认 2500")
    args = ap.parse_args()

    ua = config.sec_ua()
    print("采集 SEC Form 13F 机构持仓…")
    t0 = time.time()
    df = h13.build(top_n=args.top, ua=ua)
    if df.empty:
        print("未获取到数据")
        return

    urls = h13.list_datasets(ua)
    period = urls[0].rsplit("/", 1)[-1].replace("_form13f.zip", "")
    df["period"] = period

    u = store.query("SELECT symbol FROM universe")
    if not u.empty:
        before = len(df)
        df = df[df["symbol"].isin(set(u["symbol"]))]
        print(f"  筛选至股票池：{before} → {len(df)} 只")

    n = store.upsert(df, "holdings13f")
    store.set_meta("holdings13f_last_fetch", time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"\n✅ 写入 {n:,} 条（报告期 {period}），用时 {time.time() - t0:.0f}s")
    if not df.empty:
        top = df.nlargest(5, "value")[["symbol", "holders", "value"]]
        print("   机构持仓市值 Top5：")
        for _, r in top.iterrows():
            print(f"     {r['symbol']:6s} {int(r['holders']):>5} 家机构  "
                  f"{r["value"] / 1e8:>9,.0f} 亿美元")


if __name__ == "__main__":
    main()
