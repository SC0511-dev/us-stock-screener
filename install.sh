#!/usr/bin/env bash
# 美股选股器 · 一键安装
#
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/SC0511-dev/us-stock-screener/main/install.sh | bash
#
# 脚本只做四件事，全部在你本机完成，不上传任何数据：
#   1. 检查 Python 版本
#   2. 下载项目到 ~/us-stock-screener
#   3. 建立独立的 Python 环境并安装依赖（不污染系统环境）
#   4. 启动交互式向导，引导你完成配置与首次采集

set -euo pipefail

DIR="${USTOCK_DIR:-$HOME/us-stock-screener}"
REPO="https://github.com/SC0511-dev/us-stock-screener.git"

c() { printf "\033[%sm%s\033[0m\n" "$1" "$2"; }
ok() { c "32" "  ✓ $1"; }
info() { c "36" "  → $1"; }
die() { c "31" "  ✗ $1"; exit 1; }

echo
c "1;36" "════════════════════════════════════════"
c "1;36" "   美股选股器 · 安装程序"
c "1;36" "════════════════════════════════════════"
echo

# ── 1. Python ──
info "检查 Python…"
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    v=$("$cand" -c 'import sys;print(f"{sys.version_info[0]}{sys.version_info[1]:02d}")' 2>/dev/null || echo 0)
    if [ "$v" -ge 310 ] 2>/dev/null; then PY="$cand"; break; fi
  fi
done
if [ -z "$PY" ]; then
  echo
  die "未找到 Python 3.10 或更高版本。

  macOS  在终端执行：xcode-select --install
         或到 https://www.python.org/downloads/ 下载安装
  Windows 到 https://www.python.org/downloads/ 下载，安装时务必勾选
          「Add Python to PATH」
  Linux  sudo apt install python3 python3-venv

  装好后重新运行本脚本即可。"
fi
ok "Python $($PY -V 2>&1 | cut -d' ' -f2)（$PY）"

# ── 2. 下载项目 ──
if [ -d "$DIR/.git" ]; then
  info "项目已存在，更新到最新版…"
  git -C "$DIR" pull --quiet --ff-only 2>/dev/null || info "更新跳过（本地有改动）"
  ok "已是最新：$DIR"
else
  command -v git >/dev/null 2>&1 || die "未找到 git。macOS 请执行：xcode-select --install"
  info "下载项目到 $DIR …"
  git clone --quiet --depth 1 "$REPO" "$DIR"
  ok "下载完成"
fi
cd "$DIR"

# ── 3. 独立环境与依赖 ──
if [ ! -x ".venv/bin/python" ]; then
  info "创建独立 Python 环境（不影响系统环境）…"
  "$PY" -m venv .venv
fi
info "安装依赖…"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
ok "核心依赖安装完成"

# K 线形态识别是可选功能，本机已有 ta-lib 库时才顺带装上
if command -v brew >/dev/null 2>&1 && brew list ta-lib >/dev/null 2>&1; then
  .venv/bin/python -m pip install --quiet -r requirements-patterns.txt 2>/dev/null \
    && ok "K 线形态识别已启用" || true
else
  info "未检测到 ta-lib 库，K 线形态识别暂不可用（其余功能正常）"
  info "如需启用：brew install ta-lib 后重新运行本脚本"
fi

echo
c "1;32" "  安装完成，进入配置向导"
echo

exec .venv/bin/python scripts/quickstart.py
