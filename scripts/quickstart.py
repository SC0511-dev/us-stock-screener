#!/usr/bin/env python3
"""交互式向导：配置 → 采集 → 生成报告，一路走完。

面向第一次使用的人：不需要懂命令行参数，也不需要手改配置文件，
按提示回答两三个问题即可，结束时自动打开可视化报告。

已经配置过的用户再次运行，会变成「一键更新数据 + 重新生成报告」。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PY = str(ROOT / ".venv" / "bin" / "python")
if not Path(PY).exists():
    PY = sys.executable

from ustock import __title__, __version_label__  # noqa: E402


# ──────────────────────────── 终端输出小工具 ────────────────────────────

def c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def title(t: str) -> None:
    print("\n" + c("1;36", "━" * 52))
    print(c("1;36", f"  {t}"))
    print(c("1;36", "━" * 52) + "\n")


def ask(prompt: str, default: str = "", valid=None) -> str:
    """带默认值的输入。直接回车即采用默认值。"""
    hint = f" [{default}]" if default else ""
    while True:
        v = input(c("36", f"  {prompt}{hint}: ")).strip() or default
        if valid is None or valid(v):
            return v
        print(c("31", "    输入无效，请重试"))


def choose(prompt: str, options: list[tuple[str, str]], default: int = 1) -> str:
    """单选。options 为 [(值, 说明)]。"""
    print(f"\n  {prompt}")
    for i, (_, desc) in enumerate(options, 1):
        mark = c("32", "←推荐") if i == default else ""
        print(f"    {i}. {desc} {mark}")
    while True:
        v = input(c("36", f"  请选择 [1-{len(options)}，默认 {default}]: ")).strip()
        if not v:
            return options[default - 1][0]
        if v.isdigit() and 1 <= int(v) <= len(options):
            return options[int(v) - 1][0]
        print(c("31", "    请输入列表中的编号"))


def run(args: list[str], desc: str) -> bool:
    """执行采集脚本并实时显示进度。"""
    print(f"\n  {c('36', '→')} {desc}")
    t0 = time.time()
    p = subprocess.run([PY, str(ROOT / "scripts" / args[0])] + args[1:],
                       cwd=ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        print(c("31", f"    失败：{(p.stderr or p.stdout).strip()[-300:]}"))
        return False
    # 只回显脚本输出的最后一行结果摘要，避免刷屏
    tail = [l for l in (p.stdout or "").splitlines() if l.strip()]
    if tail:
        print(f"    {tail[-1].strip()}")
    print(c("32", f"    完成（{time.time() - t0:.0f} 秒）"))
    return True


# ──────────────────────────── 向导主体 ────────────────────────────

def setup_config() -> bool:
    """首次运行时引导填写配置。"""
    cfg_path = ROOT / "config" / "settings.json"
    example = ROOT / "config" / "settings.example.json"
    cfg = json.loads(example.read_text()) if example.exists() else {}
    if cfg_path.exists():
        try:
            cfg.update(json.loads(cfg_path.read_text()))
        except Exception:
            pass

    ua = cfg.get("sec_user_agent", "")
    if "your-email@example.com" not in ua and ua:
        return True   # 已配置过，跳过

    title("第 1 步 · 填写联系邮箱")
    print("  财报数据来自美国证券交易委员会（SEC）的公开接口。")
    print("  SEC 要求所有自动化访问声明真实联系方式，否则可能限制访问。")
    print(c("90", "  邮箱只会随请求发给 SEC，本程序不会上传到任何其他地方。\n"))

    email = ask("你的邮箱", valid=lambda v: "@" in v and "." in v.split("@")[-1])
    cfg["sec_user_agent"] = f"us-stock-screener/1.0 ({email})"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    print(c("32", f"\n  ✓ 已保存到 config/settings.json"))
    return True


def main() -> None:
    title(f"{__title__} · {__version_label__}")
    print("  这个向导会带你完成配置、数据采集，并生成第一份选股报告。")
    print("  全程约 5~10 分钟，数据都存在本机，不会上传。")

    setup_config()

    # ── 选股票池 ──
    title("第 2 步 · 选择股票范围")
    scope = choose("要分析哪些股票？", [
        ("watchlist", "热门 100 只（AI/半导体/互联网/科技/能源/大盘蓝筹）· 最快，约 3 分钟"),
        ("index", "主要指数成分股 约 520 只（标普500 + 纳指100 + 道指）· 约 8 分钟"),
        ("all", "全美股 约 7000 只 · 约 50 分钟，适合放着跑"),
    ], default=1)

    title("第 3 步 · 采集数据")
    print("  接下来会依次从 SEC、Nasdaq、FINRA、CBOE 获取数据。")
    print(c("90", "  这些都是公开免费接口，不需要任何账号或密钥。"))

    if scope == "watchlist":
        ok = run(["fetch_universe.py", "--watchlist", "config/watchlist_100.json"], "构建股票池")
    else:
        ok = run(["fetch_universe.py", "--scope", scope], "构建股票池")
    if not ok:
        print(c("31", "\n  股票池构建失败，请检查网络后重试。"))
        return

    steps = [
        (["fetch_prices.py", "--years", "3"], "采集日线行情（最慢的一步）"),
        (["fetch_fundamentals.py"], "采集 SEC 财报"),
        (["fetch_profile.py"], "采集市值、行业与分析师目标价"),
        (["fetch_short.py", "--days", "20"], "采集 FINRA 做空数据"),
        (["fetch_events.py"], "采集财报日历"),
        (["fetch_options.py", "--source", "nasdaq"], "采集期权情绪"),
    ]
    failed = []
    for args, desc in steps:
        if not run(args, desc):
            failed.append(desc)

    # 13F 首次需要做代码映射，耗时较长，交给用户决定
    title("第 4 步 · 机构持仓（可选）")
    print("  机构持仓来自 SEC Form 13F，首次采集需要把持仓里的证券编号")
    print("  映射成股票代码，大约需要 10 分钟（之后更新只要几十秒）。")
    if ask("现在就采集吗？(y/N)", "n").lower().startswith("y"):
        run(["fetch_13f.py", "--top", "1200"], "采集 13F 机构持仓")
    else:
        print(c("90", "  已跳过。之后可随时执行：.venv/bin/python scripts/fetch_13f.py"))

    # ── 生成报告 ──
    title("第 5 步 · 生成报告")
    out = ROOT / "report.html"
    if run(["report.py", "--html", str(out)], "生成交互式报告"):
        print(c("1;32", f"\n  ✓ 全部完成"))
        if failed:
            print(c("33", f"  提示：以下步骤未成功，相关因子会显示为空：{'、'.join(failed)}"))
            print(c("33", "       通常是网络波动，重新运行本向导即可补齐。"))
        print(f"\n  报告文件：{out}")
        try:
            webbrowser.open(out.as_uri())
            print(c("90", "  已在浏览器中打开。"))
        except Exception:
            pass

        print("\n  " + c("1;36", "接下来可以试试："))
        print(f"    {c('90', '# 运行内置策略')}")
        print("    .venv/bin/python scripts/screen.py --strategy minervini")
        print(f"    {c('90', '# 查看全部 20 个策略')}")
        print("    .venv/bin/python scripts/screen.py --list-strategies")
        print(f"    {c('90', '# 之后更新数据，重跑本向导即可')}")
        print("    .venv/bin/python scripts/quickstart.py")
        print()
        print(c("33", "  ⚠️  本工具仅用于投资研究，输出不构成投资建议。\n"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(c("33", "\n\n  已取消。重新运行本脚本可继续。\n"))
