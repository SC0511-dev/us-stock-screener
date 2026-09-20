#!/usr/bin/env python3
"""采集期权聚合指标（CBOE）。

只保存聚合值（隐含波动率、认沽认购比、持仓量等），不存逐合约数据。

用法：
    python scripts/fetch_options.py                # 股票池全部
    python scripts/fetch_options.py --symbols AAPL,NVDA
    python scripts/fetch_options.py --workers 8
"""
import argparse
import datetime as dt
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import store  # noqa: E402
from ustock.sources import options as op  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="采集期权聚合指标")
    ap.add_argument("--symbols", help="指定代码，逗号分隔")
    ap.add_argument("--workers", type=int, default=6, help="并发线程数")
    ap.add_argument("--limit", type=int, help="只采前 N 只")
    ap.add_argument("--source", default="auto", choices=["auto", "nasdaq", "cboe"],
                    help="auto=优先CBOE失败退Nasdaq；nasdaq=只用Nasdaq（快但无隐含波动率）")
    ap.add_argument("--force", action="store_true", help="忽略当日已采记录重新采集")
    args = ap.parse_args()

    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        u = store.query("SELECT symbol FROM universe ORDER BY symbol")
        if u.empty:
            print("股票池为空，请先运行 scripts/fetch_universe.py")
            return
        syms = u["symbol"].tolist()
    if args.limit:
        syms = syms[:args.limit]

    today = dt.date.today().strftime("%Y-%m-%d")
    if not args.force:
        # 断点续采：当日已成功采集的跳过，便于分多次补齐（CBOE 限流时尤其有用）
        have = store.query("SELECT symbol FROM options_agg WHERE date=?", (today,))
        if not have.empty:
            done_set = set(have["symbol"])
            before = len(syms)
            syms = [s for s in syms if s not in done_set]
            print(f"  跳过当日已采集的 {before - len(syms)} 只（--force 可强制重采）")
    if not syms:
        print("当日数据已齐全。")
        return
    print(f"采集 {len(syms)} 只股票的期权聚合指标（并发 {args.workers}）…")
    t0, rows, done, miss = time.time(), [], 0, 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(op.fetch_summary, s, 21600,
                            args.source != 'nasdaq'): s for s in syms}
        for fu in as_completed(futs):
            done += 1
            try:
                d = fu.result()
                if d:
                    d["date"] = today
                    rows.append(d)
                else:
                    miss += 1
            except Exception:
                miss += 1
            if done % 100 == 0 or done == len(syms):
                el = time.time() - t0
                print(f"  进度 {done}/{len(syms)}  无期权 {miss}  "
                      f"用时 {el:.0f}s  预计剩余 {el / done * (len(syms) - done):.0f}s",
                      flush=True)

    if not rows:
        print("未获取到数据")
        return
    df = pd.DataFrame(rows)
    n = store.upsert(df, "options_agg")
    store.set_meta("options_last_fetch", time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"\n✅ 写入 {n:,} 条，用时 {time.time() - t0:.0f}s")
    print(f"   无期权的股票 {miss} 只（小盘股常见，属正常）")
    if "source" in df:
        print(f"   数据源分布：{df['source'].value_counts().to_dict()}")
    iv = pd.to_numeric(df.get("iv30"), errors="coerce").dropna() if "iv30" in df else []
    if len(iv):
        print(f"   有隐含波动率的 {len(iv)} 只，iv30 中位数 {iv.median():.1f}")
    else:
        print("   本次未取到隐含波动率（CBOE 限流时会退回 Nasdaq，该源不提供 IV）")


if __name__ == "__main__":
    main()
