#!/usr/bin/env python3
"""采集公司概况：市值、行业分类、分析师目标价。

用法：
    python scripts/fetch_profile.py
    python scripts/fetch_profile.py --symbols AAPL,NVDA
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import store  # noqa: E402
from ustock.sources import profile  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="采集公司概况")
    ap.add_argument("--symbols", help="指定代码，逗号分隔")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        u = store.query("SELECT symbol FROM universe ORDER BY symbol")
        if u.empty:
            print("股票池为空，请先运行 scripts/fetch_universe.py")
            return
        syms = u["symbol"].tolist()

    print(f"采集 {len(syms)} 只股票的公司概况…")
    t0, rows, done = time.time(), [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(profile.fetch, s): s for s in syms}
        for fu in as_completed(futs):
            done += 1
            try:
                d = fu.result()
                if d:
                    rows.append(d)
            except Exception:
                pass
            if done % 50 == 0 or done == len(syms):
                print(f"  进度 {done}/{len(syms)}", flush=True)

    if not rows:
        print("未获取到数据")
        return
    df = pd.DataFrame(rows)

    # 概况写回股票池表：补齐行业分类，并单独存市值与目标价
    with store.conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(universe)")]
        for col, typ in (("market_cap_nq", "REAL"), ("analyst_target", "REAL"),
                         ("sector_nq", "TEXT"), ("industry_nq", "TEXT"),
                         ("avg_volume", "REAL")):
            if col not in cols:
                c.execute(f"ALTER TABLE universe ADD COLUMN {col} {typ}")
        for _, r in df.iterrows():
            sets, vals = [], []
            for col in ("market_cap_nq", "analyst_target", "sector_nq",
                        "industry_nq", "avg_volume"):
                if col in r and pd.notna(r[col]):
                    sets.append(f"{col}=?")
                    vals.append(r[col])
            if sets:
                c.execute(f"UPDATE universe SET {','.join(sets)} WHERE symbol=?",
                          vals + [r["symbol"]])

    store.set_meta("profile_last_fetch", time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"\n✅ 更新 {len(df)} 只，用时 {time.time() - t0:.0f}s")
    print(f"   有市值 {df['market_cap_nq'].notna().sum() if 'market_cap_nq' in df else 0} 只"
          f" | 有目标价 {df['analyst_target'].notna().sum() if 'analyst_target' in df else 0} 只")


if __name__ == "__main__":
    main()
