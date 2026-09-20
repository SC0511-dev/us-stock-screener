#!/usr/bin/env python3
"""采集财报日历。

用法：
    python scripts/fetch_events.py                 # 未来 45 天 + 过去 15 天
    python scripts/fetch_events.py --ahead 60 --back 30
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import store  # noqa: E402
from ustock.sources import events  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="采集财报日历")
    ap.add_argument("--ahead", type=int, default=45, help="向后覆盖天数")
    ap.add_argument("--back", type=int, default=15, help="向前覆盖天数")
    args = ap.parse_args()

    print(f"采集财报日历（过去 {args.back} 天 ~ 未来 {args.ahead} 天）…")
    t0 = time.time()
    df = events.fetch_range(args.ahead, args.back)
    if df.empty:
        print("未获取到数据")
        return

    u = store.query("SELECT symbol FROM universe")
    if not u.empty:
        before = df["symbol"].nunique()
        df = df[df["symbol"].isin(set(u["symbol"]))]
        print(f"  筛选至股票池：{before} → {df['symbol'].nunique()} 只")

    n = store.upsert(df, "events")
    store.set_meta("events_last_fetch", time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"\n✅ 写入 {n:,} 条财报日，{df['symbol'].nunique()} 只股票，"
          f"用时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
