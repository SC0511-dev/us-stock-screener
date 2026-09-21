#!/usr/bin/env python3
"""采集 SEC 财报数据并写入数据库。

数据来自 SEC EDGAR 的 XBRL frames 接口，官方、免费、无需密钥。
首次运行约需数分钟，之后有缓存，重复运行很快。

用法：
    python scripts/fetch_fundamentals.py
    python scripts/fetch_fundamentals.py --quarters 13   # 拉更长历史便于算同比
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import config, store  # noqa: E402
from ustock.sources import fundamentals as fd  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="采集 SEC 财报数据")
    ap.add_argument("--quarters", type=int, default=9, help="回溯季度数，默认 9")
    ap.add_argument("--years", type=int, default=3, help="回溯年度数，默认 3")
    ap.add_argument("--metrics", help="只采指定指标，逗号分隔")
    args = ap.parse_args()

    u = store.query("SELECT symbol, cik FROM universe WHERE cik IS NOT NULL")
    if u.empty:
        print("股票池为空或缺少 CIK，请先运行 scripts/fetch_universe.py")
        return
    # 一个 CIK 可能对应多个股票代码：同一家公司发行多个类别的股票时
    # （例如 Alphabet 的 GOOGL 与 GOOG、福克斯的 FOXA 与 FOX），
    # 它们共用一份财报。若用「CIK → 单个代码」的字典，后者会覆盖前者，
    # 导致其中一个类别完全取不到财报数据。
    cik2syms: dict[int, list[str]] = {}
    for sym, cik in zip(u["symbol"], u["cik"]):
        cik2syms.setdefault(int(cik), []).append(sym)

    metrics = args.metrics.split(",") if args.metrics else None
    ua = config.sec_ua()
    print(f"开始采集 SEC 财报（股票池 {len(u)} 只）…")
    t0 = time.time()
    df = fd.build(metrics, args.quarters, args.years, ua)
    if df.empty:
        print("未获取到数据")
        return

    df = df[df["cik"].isin(cik2syms)].copy()
    # 同一 CIK 下的每个股票代码都复制一份，保证各类别股票都有财报
    df["symbol"] = df["cik"].map(cik2syms)
    df = df.explode("symbol")
    # 源表里的 tag 是 XBRL 原始标签名，先改名，避免与下面 metric→tag 重名
    df = df.rename(columns={"tag": "xbrl_tag"})
    out = df.rename(columns={"metric": "tag", "end": "end_date",
                             "val": "value", "period": "fy"})[
        ["symbol", "tag", "end_date", "value", "fy"]]
    out["fp"] = out["fy"].str[-2:]
    # 年度与季度可能落在同一 end_date，用 form 区分以免主键冲突
    out["form"] = "FRAME_" + df["freq"].values

    n = store.upsert(out, "fundamentals")
    store.set_meta("fundamentals_last_fetch", time.strftime("%Y-%m-%d %H:%M:%S"))
    cov = out.groupby("tag")["symbol"].nunique().sort_values(ascending=False)
    print(f"\n✅ 写入 {n:,} 条，用时 {time.time() - t0:.0f}s")
    print("各指标覆盖股票数：")
    for k, v in cov.items():
        print(f"   {k:18s} {v:>4} / {len(u)}  ({v / len(u) * 100:.0f}%)")


if __name__ == "__main__":
    main()
