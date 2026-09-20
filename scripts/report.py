#!/usr/bin/env python3
"""全因素快照报告。

把股票池里每只股票的所有因子并排输出，用于快速扫描全局、
检查数据覆盖情况，或作为进一步筛选的起点。

用法：
    python scripts/report.py                      # 全部股票，按主题分组
    python scripts/report.py --group AI与算力      # 只看某个主题
    python scripts/report.py --sort rs_rating     # 自定义排序
    python scripts/report.py --csv out.csv        # 导出完整因子表
    python scripts/report.py --coverage           # 只看数据覆盖率体检
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from screen import build_snapshot  # noqa: E402
from ustock import report_html, strategies  # noqa: E402

# 分区展示：每个因子家族一组列
BLOCKS = {
    "技术面": ["close", "rs_rating", "mom_3m", "mom_12m", "pct_from_52w_high",
              "rsi14", "adx", "natr", "vol_ratio"],
    "基本面": ["revenue_yoy", "gross_margin", "net_margin", "roe", "fcf_margin"],
    "估值": ["market_cap", "pe", "ps", "pb", "fcf_yield"],
    "财务评分": ["f_score", "altman_z", "magic_rank", "roce"],
    "市场结构": ["short_ratio", "short_ratio_z"],
    "期权情绪": ["put_call_vol", "put_call_oi", "iv30", "opt_stock_vol"],
    "机构持仓": ["inst_holders", "inst_own_pct"],
    "事件": ["days_to_earnings"],
}

PCT = {"mom_3m", "mom_12m", "pct_from_52w_high", "revenue_yoy", "gross_margin",
       "net_margin", "roe", "fcf_margin", "fcf_yield", "short_ratio",
       "inst_own_pct", "roce"}

CN = {"close": "现价", "rs_rating": "RS", "mom_3m": "3月%", "mom_12m": "12月%",
      "pct_from_52w_high": "距高点%", "rsi14": "RSI", "adx": "ADX", "natr": "ATR%",
      "vol_ratio": "量比", "revenue_yoy": "营收增%", "gross_margin": "毛利%",
      "net_margin": "净利%", "roe": "ROE%", "fcf_margin": "FCF率%",
      "market_cap": "市值亿$", "pe": "PE", "ps": "PS", "pb": "PB",
      "fcf_yield": "FCF收益%", "f_score": "F分", "altman_z": "Z值",
      "magic_rank": "神奇名次", "roce": "ROCE%", "short_ratio": "做空%",
      "short_ratio_z": "做空Z", "put_call_vol": "P/C量", "put_call_oi": "P/C仓",
      "iv30": "IV30", "opt_stock_vol": "期权/正股", "inst_holders": "机构数",
      "inst_own_pct": "机构占比%", "days_to_earnings": "距财报",
      "symbol": "代码", "name": "名称", "theme": "主题"}


def fmt(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    d = df[cols].copy()
    for c in d.columns:
        if c in PCT and pd.api.types.is_numeric_dtype(d[c]):
            d[c] = (d[c] * 100).round(1)
        elif c == "market_cap":
            d[c] = (d[c] / 1e8).round(0)
        elif pd.api.types.is_numeric_dtype(d[c]):
            d[c] = d[c].round(2)
    return d.rename(columns=CN)


def coverage(snap: pd.DataFrame) -> None:
    """按因子家族统计数据覆盖率，缺失多的地方一目了然。"""
    print("\n【数据覆盖率】")
    for block, cols in BLOCKS.items():
        print(f"\n  {block}")
        for c in cols:
            if c not in snap.columns:
                print(f"    {CN.get(c, c):12s} ❌ 无此列")
                continue
            n = snap[c].notna().sum()
            pct = n / len(snap) * 100
            bar = "█" * int(pct / 5)
            flag = "" if pct >= 80 else ("  ⚠️ 覆盖偏低" if pct >= 40 else "  ⚠️ 覆盖很低")
            print(f"    {CN.get(c, c):12s} {n:>3}/{len(snap)} {pct:>5.0f}% {bar}{flag}")


def main():
    ap = argparse.ArgumentParser(description="全因素快照报告")
    ap.add_argument("--group", help="只看某个主题分组")
    ap.add_argument("--sort", default="rs_rating", help="排序字段")
    ap.add_argument("--csv", help="导出完整因子表")
    ap.add_argument("--coverage", action="store_true", help="只输出数据覆盖率体检")
    ap.add_argument("--blocks", help="只显示指定因子家族，逗号分隔")
    ap.add_argument("--html", nargs="?", const="report.html",
                    help="生成交互式 HTML 报告，默认输出到 report.html")
    ap.add_argument("--open", action="store_true", help="生成后直接用浏览器打开")
    args = ap.parse_args()

    snap, u = build_snapshot()
    if snap is None:
        return
    # 因子合并阶段可能已带入 theme，重复合并会产生 theme_x / theme_y
    if "theme" not in snap.columns and "theme" in u.columns:
        snap = snap.merge(u[["symbol", "theme"]].drop_duplicates("symbol"),
                          on="symbol", how="left")

    print(f"股票池 {len(snap)} 只 · 数据日期 {snap['date'].max()}")

    if args.html:
        # 把每个内置策略的命中结果一并写进页面，便于在表格上叠加高亮
        hits = {}
        for k, st in strategies.STRATEGIES.items():
            try:
                _, out = strategies.run(k, snap, u, top=None)
            except Exception:
                continue
            hits[k] = {"name": st.name, "desc": st.desc, "note": st.note,
                       "symbols": out["symbol"].tolist() if not out.empty else []}
        html = report_html.build(snap, hits)
        path = Path(args.html).expanduser().resolve()
        path.write_text(html, encoding="utf-8")
        print(f"\n✅ 交互式报告已生成：{path}")
        print(f"   {len(snap)} 只股票 × {len(report_html.GROUPS)} 个因子家族 × "
              f"{len(hits)} 个策略，文件 {path.stat().st_size / 1024:.0f} KB")
        if args.open:
            import webbrowser
            webbrowser.open(path.as_uri())
        return

    if args.coverage:
        coverage(snap)
        return

    if args.group:
        snap = snap[snap["theme"] == args.group]
        if snap.empty:
            print(f"主题「{args.group}」没有股票")
            return

    if args.sort in snap.columns:
        snap = snap.sort_values(args.sort, ascending=False)

    blocks = (args.blocks.split(",") if args.blocks else list(BLOCKS))
    base = [c for c in ("symbol", "name", "theme") if c in snap.columns]

    for b in blocks:
        cols = [c for c in BLOCKS.get(b, []) if c in snap.columns]
        if not cols:
            continue
        print(f"\n{'═' * 100}\n【{b}】\n{'═' * 100}")
        print(fmt(snap, base + cols).to_string(index=False))

    coverage(snap)

    if args.csv:
        snap.to_csv(args.csv, index=False)
        print(f"\n完整因子表已导出：{args.csv}（{len(snap)} 行 × {len(snap.columns)} 列）")


if __name__ == "__main__":
    main()
