#!/usr/bin/env python3
"""采集股票池并写入数据库。

用法：
    python scripts/fetch_universe.py               # 默认指数成分股（约 520 只）
    python scripts/fetch_universe.py --scope all   # 全美股（约 6000 只）
    python scripts/fetch_universe.py --symbols AAPL,MSFT,NVDA
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import store, universe  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="采集股票池")
    ap.add_argument("--scope", default="index", choices=["index", "all", "custom"],
                    help="index=指数成分股，all=全美股，custom=自定义代码")
    ap.add_argument("--symbols", help="scope=custom 时的代码，逗号分隔")
    ap.add_argument("--watchlist", help="自选股票池 JSON 文件，例如 config/watchlist_100.json")
    ap.add_argument("--sec-ua", default=None,
                    help="SEC 要求的 User-Agent，格式：程序名 (你的邮箱)")
    args = ap.parse_args()

    kw = {"sec_ua": args.sec_ua} if args.sec_ua else {}
    theme_map = {}

    if args.watchlist:
        wl = json.loads(Path(args.watchlist).read_text())
        groups = wl.get("groups") or {}
        syms = []
        for g, lst in groups.items():
            for s in lst:
                s = universe.normalize(s)
                if s not in theme_map:
                    theme_map[s] = g
                    syms.append(s)
        print(f"自选股票池「{wl.get('name', args.watchlist)}」：{len(syms)} 只，"
              f"{len(groups)} 个主题")
        u = universe.build("custom", symbols=syms, **kw)
    else:
        syms = args.symbols.split(",") if args.symbols else None
        print(f"正在构建股票池（scope={args.scope}）…")
        u = universe.build(args.scope, symbols=syms, **kw)

    if theme_map:
        u["theme"] = u["symbol"].map(theme_map)

    for c in ("in_sp500", "in_ndx", "in_dow"):
        if c in u.columns:
            u[c] = u[c].astype(int)
    n = store.upsert(u, "universe")
    store.set_meta("universe_scope", args.watchlist or args.scope)

    print(f"✅ 已写入 {n} 只股票")
    if "theme" in u.columns and u["theme"].notna().any():
        for g, c in u["theme"].value_counts().items():
            print(f"   {g:10s} {c:>3} 只")
    if "in_sp500" in u.columns:
        print(f"   标普500 {int(u.in_sp500.sum())} | 纳指100 {int(u.in_ndx.sum())} "
              f"| 道指 {int(u.in_dow.sum())}")
    print(f"   含 CIK（可取财报）{int(u['cik'].notna().sum())} 只")


if __name__ == "__main__":
    main()
