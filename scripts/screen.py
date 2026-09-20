#!/usr/bin/env python3
"""选股主程序。

三种用法：

  1) 运行内置策略
     python scripts/screen.py --strategy minervini
     python scripts/screen.py --strategy quality_growth --top 20

  2) 自由组合条件
     python scripts/screen.py --conditions above_ma200,rs_leader,rev_growth_20
     python scripts/screen.py --conditions rsi_oversold,above_ma200 --mode and

  3) 浏览可用的策略与条件
     python scripts/screen.py --list-strategies
     python scripts/screen.py --list-conditions
     python scripts/screen.py --list-conditions --category 基本面
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import config, factors, screen, store, strategies  # noqa: E402

# 结果里优先展示的列，按可读性排序
SHOW = ["symbol", "name", "sector", "close", "rs_rating", "mom_3m",
        "pct_from_52w_high", "rsi14", "vol_ratio", "market_cap",
        "pe", "ps", "revenue_yoy", "net_margin", "roe",
        "short_ratio", "days_to_earnings", "命中条件数"]

PCT_COLS = {"mom_1m", "mom_3m", "mom_6m", "mom_12m", "pct_from_52w_high",
            "pct_from_52w_low", "revenue_yoy", "net_income_yoy", "net_margin",
            "gross_margin", "roe", "roa", "fcf_yield", "short_ratio", "drawdown"}


def fmt(df: pd.DataFrame) -> pd.DataFrame:
    """把结果整理成便于阅读的表格：百分比转百分号、市值转亿美元。"""
    d = df.copy()
    for c in d.columns:
        if c in PCT_COLS and pd.api.types.is_numeric_dtype(d[c]):
            d[c] = (d[c] * 100).round(1)
    if "market_cap" in d:
        d["market_cap"] = (d["market_cap"] / 1e8).round(0)
    for c in ("close", "pe", "ps", "rsi14", "vol_ratio", "rs_rating"):
        if c in d and pd.api.types.is_numeric_dtype(d[c]):
            d[c] = d[c].round(2)
    ren = {"symbol": "代码", "name": "名称", "sector": "行业", "close": "现价",
           "rs_rating": "RS", "mom_3m": "3月涨幅%", "pct_from_52w_high": "距52周高%",
           "rsi14": "RSI", "vol_ratio": "量比", "market_cap": "市值(亿$)",
           "pe": "PE", "ps": "PS", "revenue_yoy": "营收增%",
           "days_to_earnings": "距财报",
           "net_margin": "净利率%", "roe": "ROE%", "short_ratio": "做空占比%"}
    return d.rename(columns=ren)


def build_snapshot(date=None):
    """读取本地数据并构建因子快照。"""
    cfg = config.load()
    u = store.query("SELECT * FROM universe")
    if u.empty:
        print("股票池为空，请先运行：python scripts/fetch_universe.py")
        return None, None

    # 在 SQL 层就按股票池过滤：数据库里可能残留其他批次采集的股票，
    # 全量载入再用 pandas 过滤会白白多读几十万行。
    bench_sym = cfg["benchmark"]
    want = sorted(set(u["symbol"]) | {bench_sym})
    prices = store.load_prices(symbols=want)
    if prices.empty:
        print("行情为空，请先运行：python scripts/fetch_prices.py")
        return None, None
    prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")

    bench = prices[prices["symbol"] == bench_sym]
    stocks = prices[prices["symbol"].isin(set(u["symbol"]))]

    snap = screen.build_snapshot(stocks, bench=bench, date=date)
    if snap.empty:
        print("快照为空：可能是行情数据过少（每只股票至少需要 60 个交易日）")
        return None, None

    fund = factors.fundamental_snapshot()
    if not fund.empty:
        fund = factors.add_valuation(fund, snap[["symbol", "close"]])
        fund = factors.add_scores(fund)          # F-Score / Z-Score / 神奇公式
    short = factors.short_snapshot()
    ev = factors.events_snapshot(date)
    inst = factors.inst_snapshot()
    opt = factors.options_snapshot()
    pol = factors.politician_snapshot()
    snap = factors.merge_all(snap, fund, short, u, ev, inst, opt, pol)
    return snap, u


def main():
    ap = argparse.ArgumentParser(description="美股选股")
    ap.add_argument("--strategy", help="内置策略 key")
    ap.add_argument("--conditions", help="自定义条件，逗号分隔")
    ap.add_argument("--mode", default="and", choices=["and", "or"], help="条件组合方式")
    ap.add_argument("--top", type=int, default=30, help="展示前 N 条")
    ap.add_argument("--date", help="按历史某一交易日选股，格式 YYYY-MM-DD")
    ap.add_argument("--sort", help="自定义排序字段")
    ap.add_argument("--csv", help="导出结果到 CSV")
    ap.add_argument("--list-strategies", action="store_true")
    ap.add_argument("--list-conditions", action="store_true")
    ap.add_argument("--category", help="配合 --list-conditions 按分类过滤")
    args = ap.parse_args()

    if args.list_strategies:
        print("内置策略：\n")
        for s in strategies.STRATEGIES.values():
            print(f"  {s.key:18s} {s.name}")
            print(f"  {'':18s} {s.desc}")
            if s.note:
                print(f"  {'':18s} 注意：{s.note}")
            print()
        return

    if args.list_conditions:
        df = screen.list_conditions(args.category)
        print(f"共 {len(df)} 个条件"
              f"{'（分类：' + args.category + '）' if args.category else ''}\n")
        print(df.to_string(index=False))
        if not args.category:
            print("\n按分类统计：")
            print(screen.categories().to_string())
        return

    if not args.strategy and not args.conditions:
        ap.error("请指定 --strategy 或 --conditions（或用 --list-strategies 查看可选项）")

    snap, u = build_snapshot(args.date)
    if snap is None:
        return
    print(f"快照：{len(snap)} 只股票，日期 {snap['date'].max()}\n")

    if args.strategy:
        s, out = strategies.run(args.strategy, snap, u, args.top)
        print(f"策略：{s.name}（{s.key}）")
        print(f"逻辑：{s.desc}")
        if s.note:
            print(f"注意：{s.note}")
        print(f"条件：{'、'.join(screen.CONDITIONS[c].label for c in s.conditions)}\n")
    else:
        conds = [c.strip() for c in args.conditions.split(",")]
        out = screen.screen(snap, conds, args.mode, u)
        labels = [screen.CONDITIONS[c].label for c in conds if c in screen.CONDITIONS]
        print(f"条件（{args.mode}）：{'、'.join(labels)}\n")
        if args.sort and args.sort in out.columns:
            out = out.sort_values(args.sort, ascending=False)
        out = out.head(args.top)

    if out.empty:
        print("没有股票满足全部条件。")
        print("这通常不是程序出错，而是当前市场环境下确实没有符合条件的标的——"
              "可尝试放宽条件或改用 --mode or。")
        return

    cols = [c for c in SHOW if c in out.columns]
    print(f"选出 {len(out)} 只：\n")
    print(fmt(out[cols]).to_string(index=False))

    if args.csv:
        out.to_csv(args.csv, index=False)
        print(f"\n已导出：{args.csv}")


if __name__ == "__main__":
    main()
