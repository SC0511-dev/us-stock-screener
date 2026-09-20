#!/usr/bin/env python3
"""数据体检：检查本地数据是否齐全、新鲜，以及各因子的覆盖率。

用法：
    python scripts/status.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ustock import config, store  # noqa: E402


def main():
    print("═" * 58)
    print("  UStock 数据体检")
    print("═" * 58)

    cfg = config.load()
    if "your-email@example.com" in cfg["sec_user_agent"]:
        print("\n⚠️  config/settings.json 里的 sec_user_agent 仍是占位邮箱。")
        print("   SEC 要求自动化访问声明真实联系方式，建议尽快修改。")

    print("\n【数据表】")
    print(store.stats().to_string(index=False))

    meta = store.query("SELECT key, value, updated_at FROM meta")
    if not meta.empty:
        print("\n【最近采集时间】")
        print(meta.to_string(index=False))

    # 行情新鲜度
    last = store.query("SELECT MAX(date) d FROM prices")["d"][0]
    if last:
        days = (pd.Timestamp.today().normalize() - pd.Timestamp(last)).days
        tag = "✅ 新鲜" if days <= 4 else f"⚠️ 已滞后 {days} 天，建议重新采集"
        print(f"\n【行情新鲜度】最新交易日 {last}　{tag}")

    # 每只股票的数据量是否够算指标
    cnt = store.query("SELECT symbol, COUNT(*) n FROM prices GROUP BY symbol")
    if not cnt.empty:
        short = cnt[cnt["n"] < 250]
        print(f"\n【行情长度】{len(cnt)} 只股票，"
              f"中位数 {int(cnt['n'].median())} 个交易日")
        if len(short):
            print(f"   其中 {len(short)} 只不足 250 日，200 日均线类条件对其不可用：")
            print(f"   {', '.join(short['symbol'].head(12))}"
                  f"{' …' if len(short) > 12 else ''}")

    # 基本面覆盖率
    f = store.query("SELECT tag, COUNT(DISTINCT symbol) n FROM fundamentals "
                    "GROUP BY tag ORDER BY n DESC")
    total = store.query("SELECT COUNT(*) n FROM universe")["n"][0]
    if not f.empty and total:
        print(f"\n【基本面覆盖率】（股票池 {total} 只）")
        for _, r in f.iterrows():
            bar = "█" * int(r["n"] / total * 20)
            print(f"   {r['tag']:18s} {r['n']:>4}  {r['n']/total*100:>3.0f}%  {bar}")
        print("\n   说明：毛利覆盖率偏低属正常——多数公司不单独披露毛利，")
        print("   系统会用「营收 − 营业成本」补算，金融股等仍可能缺失。")

    print("\n" + "═" * 58)


if __name__ == "__main__":
    main()
