#!/usr/bin/env python3
"""策略历史验证。

用法：
    python scripts/backtest.py --strategy minervini
    python scripts/backtest.py --conditions above_ma200,rs_leader --every 21
    python scripts/backtest.py --strategy momentum_leader --top 20 --csv out.csv

结果解读见输出末尾的局限性说明——这不是交易回测，不能直接当作收益预期。
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import backtest, config, store, strategies  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="策略历史验证")
    ap.add_argument("--strategy", help="内置策略 key")
    ap.add_argument("--conditions", help="自定义条件，逗号分隔")
    ap.add_argument("--every", type=int, default=21, help="检验间隔交易日，默认 21")
    ap.add_argument("--top", type=int, default=20, help="每次取前 N 只")
    ap.add_argument("--csv", help="导出逐次结果")
    args = ap.parse_args()

    if not args.strategy and not args.conditions:
        ap.error("请指定 --strategy 或 --conditions")

    cfg = config.load()
    u = store.query("SELECT symbol FROM universe")
    prices = store.load_prices()
    if prices.empty or u.empty:
        print("数据不足，请先运行采集脚本")
        return
    prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")
    bench = prices[prices["symbol"] == cfg["benchmark"]]
    stocks = prices[prices["symbol"].isin(set(u["symbol"]))]

    print(f"构建因子面板（{stocks['symbol'].nunique()} 只 × "
          f"{stocks['date'].nunique()} 个交易日）…")
    panel = backtest.build_panel(stocks, bench)
    if panel.empty:
        print("面板为空")
        return

    if args.strategy:
        res = backtest.run_strategy(args.strategy, panel, bench, args.every, args.top)
        s = res["strategy"]
        print(f"\n策略：{s.name}（{s.key}）")
        print(f"注意：{s.note}\n")
    else:
        conds = [c.strip() for c in args.conditions.split(",")]
        res = backtest.run(conds, panel, bench, args.every, args.top)
        print(f"\n条件：{', '.join(conds)}\n")

    summ = res["summary"]
    if not summ:
        print("没有产生有效的检验结果（可能是历史数据不足）")
        return
    for k, v in summ.items():
        print(f"  {k:18s} {v}")

    pd_ = res["per_date"]
    if not pd_.empty:
        show = [c for c in ["date", "n", "ret_20", "bench_20", "excess_20", "win_20"]
                if c in pd_.columns]
        t = pd_[show].copy()
        for c in ("ret_20", "bench_20", "excess_20", "win_20"):
            if c in t:
                t[c] = (t[c] * 100).round(1)
        print("\n逐次检验（20 日持有）：")
        print(t.rename(columns={"date": "检验日", "n": "选出", "ret_20": "收益%",
                                "bench_20": "基准%", "excess_20": "超额%",
                                "win_20": "胜率%"}).to_string(index=False))

    print("\n" + "─" * 60)
    print("局限性提醒：")
    print("  1. 股票池取自当前指数成分，存在幸存者偏差，会高估表现")
    print("  2. 财报因子未还原披露时点，含基本面条件的策略存在前视偏差")
    print("  3. 未计滑点与手续费，也未做仓位与止损管理")
    print("  结论仅供研究参考，不构成投资建议。")

    if args.csv:
        res["per_date"].to_csv(args.csv, index=False)
        print(f"\n已导出：{args.csv}")


if __name__ == "__main__":
    main()
