"""
全局配置。

首次使用请修改 config/settings.json 里的 sec_user_agent，填上你自己的邮箱。
SEC 明确要求自动化访问必须声明真实联系方式，否则可能被限速甚至封禁 IP。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "settings.json"

DEFAULTS = {
    # SEC 要求格式："程序名/版本 (联系邮箱)"
    "sec_user_agent": "ustock-screener/0.1 (your-email@example.com)",
    # 默认股票池范围：index / all
    "default_scope": "index",
    # 默认行情回溯年数
    "default_years": 3,
    # 相对强弱基准
    "benchmark": "SPY",
    # 筛选结果默认最少日均成交额（美元），用于过滤流动性差的票
    "min_dollar_volume": 5_000_000,
}


def load() -> dict:
    """读取配置，缺失项用默认值补齐。"""
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except Exception as e:
            print(f"  提示：配置文件解析失败（{e}），改用默认配置")
    return cfg


def save(cfg: dict) -> None:
    """写回配置文件。"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


def sec_ua() -> str:
    """取 SEC 专用 User-Agent，并在仍是占位邮箱时提醒。"""
    ua = load()["sec_user_agent"]
    if "your-email@example.com" in ua:
        print("  提示：请在 config/settings.json 中把 sec_user_agent 改成你的真实邮箱，"
              "否则 SEC 可能限制访问")
    return ua
