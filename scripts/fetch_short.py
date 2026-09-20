#!/usr/bin/env python3
"""采集 FINRA 每日做空量。

数据来自 FINRA 公开的 RegSHO 合并文件，每个交易日一份，覆盖全市场。

用法：
    python scripts/fetch_short.py              # 最近 20 个交易日
    python scripts/fetch_short.py --days 60
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import store  # noqa: E402
from ustock.sources import shortvol  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="采集 FINRA 做空数据")
    ap.add_argument("--days", type=int, default=20, help="回溯交易日数，默认 20")
    ap.add_argument("--all-symbols", action="store_true",
                    help="保留全市场数据；默认只保留股票池内的股票以节省空间")
    args = ap.parse_args()

    print(f"开始采集最近 {args.days} 个交易日的做空数据…")
    t0 = time.time()
    df = shortvol.fetch_recent(args.days)
    if df.empty:
        print("未获取到数据")
        return

    if not args.all_symbols:
        u = store.query("SELECT symbol FROM universe")
        if not u.empty:
            before = df["symbol"].nunique()
            df = df[df["symbol"].isin(set(u["symbol"]))]
            print(f"  已筛选至股票池：{before} → {df['symbol'].nunique()} 只")

    n = store.upsert(df, "short_volume")
    store.set_meta("short_last_fetch", time.strftime("%Y-%m-%d %H:%M:%S"))
    ratio = (df["short_vol"] / df["total_vol"]).median()
    print(f"\n✅ 写入 {n:,} 条，{df['symbol'].nunique()} 只股票，"
          f"用时 {time.time() - t0:.0f}s")
    print(f"   做空占比中位数 {ratio:.1%}"
          f"（偏高属正常：含做市商对冲等技术性做空，应看相对自身历史的变化）")


if __name__ == "__main__":
    main()
