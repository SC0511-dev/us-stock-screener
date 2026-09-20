#!/usr/bin/env python3
"""采集日线行情并写入数据库。

默认只补采数据不新鲜的股票，因此可以每天重复运行，不会重复下载。

用法：
    python scripts/fetch_prices.py                 # 采集股票池全部股票
    python scripts/fetch_prices.py --years 5       # 拉取更长历史
    python scripts/fetch_prices.py --force         # 忽略新鲜度，强制重采
    python scripts/fetch_prices.py --symbols AAPL,MSFT
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import store  # noqa: E402
from ustock.sources import prices as px  # noqa: E402

BENCH = ["SPY", "QQQ", "IWM"]  # 基准指数 ETF，用于计算相对强弱


def main():
    ap = argparse.ArgumentParser(description="采集日线行情")
    ap.add_argument("--years", type=int, default=3, help="回溯年数，默认 3 年")
    ap.add_argument("--symbols", help="指定代码，逗号分隔；默认取股票池全部")
    ap.add_argument("--force", action="store_true", help="忽略已有数据强制重采")
    ap.add_argument("--limit", type=int, help="只采前 N 只，便于快速试跑")
    ap.add_argument("--workers", type=int, default=6,
                    help="并发线程数，默认 6。调高可提速，但过高可能被数据源限流")
    args = ap.parse_args()

    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        u = store.query("SELECT symbol FROM universe ORDER BY symbol")
        if u.empty:
            print("股票池为空，请先运行 scripts/fetch_universe.py")
            return
        syms = u["symbol"].tolist()

    syms = list(dict.fromkeys(syms + BENCH))   # 基准始终采集
    if args.limit:
        syms = syms[:args.limit] + BENCH

    if not args.force:
        have = store.query(
            "SELECT symbol, MAX(date) d, COUNT(*) n FROM prices GROUP BY symbol")
        fresh = set(have[(have["n"] > 200)]["symbol"]) if not have.empty else set()
        # 最近一次数据在 3 天内即视为新鲜（跨周末）
        if not have.empty:
            latest = have["d"].max()
            fresh = set(have[(have["d"] >= latest) & (have["n"] > 200)]["symbol"])
        skip = [s for s in syms if s in fresh]
        syms = [s for s in syms if s not in fresh]
        if skip:
            print(f"跳过 {len(skip)} 只已是最新的股票（--force 可强制重采）")

    if not syms:
        print("没有需要采集的股票，全部已是最新。")
        return

    print(f"开始采集 {len(syms)} 只股票 × {args.years} 年日线"
          f"（并发 {args.workers} 线程）…")
    t0 = time.time()
    ok = fail = rows = 0
    failed = []
    done = 0

    # 网络请求并发执行，数据库写入仍在主线程串行完成（SQLite 单写者更稳妥）
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(px.fetch, s, args.years): s for s in syms}
        for fu in as_completed(futs):
            s = futs[fu]
            done += 1
            try:
                d = fu.result()
                if d.empty:
                    fail += 1
                    failed.append(s)
                else:
                    rows += store.upsert(d, "prices")
                    ok += 1
            except Exception:
                fail += 1
                failed.append(s)
            if done % 50 == 0 or done == len(syms):
                el = time.time() - t0
                print(f"  进度 {done}/{len(syms)}  成功 {ok}  失败 {fail}  "
                      f"用时 {el:.0f}s  预计剩余 {el / done * (len(syms) - done):.0f}s",
                      flush=True)

    store.set_meta("prices_last_fetch", time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"\n✅ 完成：成功 {ok} 只，失败 {fail} 只，写入 {rows:,} 行，"
          f"用时 {time.time() - t0:.0f}s")
    if failed:
        print(f"   失败代码（多为退市或代码变更）：{failed[:20]}"
              f"{' …' if len(failed) > 20 else ''}")


if __name__ == "__main__":
    main()
