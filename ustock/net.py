"""
网络层：统一的 HTTP 获取、SSL 证书自愈、分站点节流、失败退避与磁盘缓存。

本项目所有数据源都走这里，好处有三：
1. 少数网络环境会对 HTTPS 做中间人解密，此时可按需开启证书兼容，无需手工配环境变量；
2. 每个站点独立节流，避免把数据源打挂或被限流（Yahoo 对密集请求尤其敏感）；
3. 磁盘缓存让重复跑批几乎不产生额外请求，既快又礼貌。
"""
from __future__ import annotations

import hashlib
import json
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ──────────────────────────────── 基本配置 ────────────────────────────────

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

# SEC 要求所有自动化请求声明真实联系方式，否则可能被封禁。
# 请在 config/settings.json 里把 sec_user_agent 改成你自己的“程序名 (邮箱)”。
DEFAULT_SEC_UA = "ustock-screener/0.1 (your-email@example.com)"

CA_PATH = Path.home() / ".certs" / "ca-bundle.pem"

_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = _ROOT / "data" / "cache"

# 各站点的最小请求间隔（秒）。SEC 官方限速为 10 次/秒，这里取更保守的值。
_HOST_GAP = {
    "data.sec.gov": 0.12,
    "www.sec.gov": 0.12,
    "api.nasdaq.com": 0.35,
    "query1.finance.yahoo.com": 0.80,
    "query2.finance.yahoo.com": 0.80,
    "cdn.finra.org": 0.30,
    "en.wikipedia.org": 0.50,
    # CBOE 单次响应约 1.4 MB 且限流严格（实测 1.5 秒间隔仍会被 429），间隔必须放宽
    "cdn.cboe.com": 3.50,
    "stockanalysis.com": 0.50,
}
_DEFAULT_GAP = 0.40

_last_hit: dict[str, float] = {}
# 节流状态是跨线程共享的，必须加锁。
# 加锁后各线程按序取得“发车时刻”，但网络等待彼此重叠，
# 因此并发能显著提速，同时整体请求速率仍受 _HOST_GAP 约束，不会打挂数据源。
_throttle_lock = threading.Lock()


def _wait_turn(host: str) -> None:
    """取得本次请求的发车时刻，必要时休眠以满足该站点的最小间隔。"""
    gap = _HOST_GAP.get(host, _DEFAULT_GAP)
    with _throttle_lock:
        now = time.time()
        earliest = _last_hit.get(host, 0.0) + gap
        wait = max(0.0, earliest - now)
        _last_hit[host] = max(now, earliest)
    if wait > 0:
        time.sleep(wait)


# ──────────────────────────── SSL：可选的企业证书兼容 ────────────────────────────
#
# 绝大多数使用者不需要关心这一节，保持默认即可。
#
# 少数企业网络会对 HTTPS 做中间人解密（由网关签发临时证书），
# 此时 Python 的默认信任库里没有该网关的根证书，访问部分站点会报
# CERTIFICATE_VERIFY_FAILED。若你恰好处在这类网络中，可以在
# config/settings.json 里打开开关：
#
#     "corporate_ca_fix": true
#
# 打开后程序会从系统证书库导出企业根证书、与 certifi 合并，
# 结果缓存到 ~/.certs/ca-bundle.pem。默认为 false，不做任何额外操作。


def _corporate_ca_settings() -> tuple[bool, list[str]]:
    """读取企业证书兼容相关配置。配置缺失时一律视为关闭。"""
    try:
        from . import config
        cfg = config.load()
        return bool(cfg.get("corporate_ca_fix", False)), list(
            cfg.get("corporate_ca_keywords", []))
    except Exception:
        return False, []


def build_ca_bundle(keywords: list[str]) -> str | None:
    """把系统证书库中匹配的根证书与 certifi 合并，返回合并后的 bundle 路径。

    keywords 是证书通用名里的关键词，由使用者在配置中指定，
    程序本身不预设任何厂商名称。
    """
    try:
        import certifi
    except ImportError:
        return None
    try:
        merged = Path(certifi.where()).read_text()
        found = False
        if sys.platform == "darwin":
            for kw in keywords:
                out = subprocess.run(
                    ["security", "find-certificate", "-a", "-c", kw, "-p",
                     "/Library/Keychains/System.keychain"],
                    capture_output=True, text=True, timeout=20).stdout
                if "BEGIN CERTIFICATE" in out:
                    merged += "\n" + out
                    found = True
        if not found:
            return None
        CA_PATH.parent.mkdir(parents=True, exist_ok=True)
        CA_PATH.write_text(merged)
        return str(CA_PATH)
    except Exception:
        return None


def _make_context() -> ssl.SSLContext:
    """构造 SSL 上下文。默认使用系统信任库，仅在显式开启时才合并企业证书。"""
    enabled, keywords = _corporate_ca_settings()
    if not enabled:
        return ssl.create_default_context()
    if CA_PATH.exists() and CA_PATH.stat().st_size > 100_000:
        return ssl.create_default_context(cafile=str(CA_PATH))
    path = build_ca_bundle(keywords)
    return ssl.create_default_context(cafile=path) if path \
        else ssl.create_default_context()


CTX = _make_context()


# ──────────────────────────────── 磁盘缓存 ────────────────────────────────

def _cache_path(url: str) -> Path:
    """按 URL 哈希定位缓存文件，并用主机名分目录，方便人工排查。"""
    host = urllib.parse.urlparse(url).netloc or "misc"
    digest = hashlib.sha1(url.encode()).hexdigest()[:20]
    return CACHE_DIR / host / f"{digest}.bin"


def cache_clear(host: str | None = None) -> int:
    """清理缓存，返回删除的文件数。传 host 只清某个站点。"""
    base = CACHE_DIR / host if host else CACHE_DIR
    if not base.exists():
        return 0
    n = 0
    for f in base.rglob("*.bin"):
        f.unlink()
        n += 1
    return n


# ──────────────────────────────── 核心获取函数 ────────────────────────────────

class FetchError(RuntimeError):
    """所有重试都失败后抛出，调用方据此决定降级还是中止。"""


def fetch(url: str, *, ua: str | None = None, timeout: int = 30, tries: int = 3,
          cache_ttl: int | None = 3600, quiet: bool = False) -> bytes:
    """抓取 URL 并返回原始字节。

    参数：
        ua        自定义 User-Agent；访问 SEC 时应传入含邮箱的标识
        cache_ttl 缓存有效期（秒）。None 表示不使用缓存；0 表示永久有效
        tries     总尝试次数，遇 429/5xx 时按指数退避重试
    """
    cp = _cache_path(url)
    if cache_ttl is not None and cp.exists():
        age = time.time() - cp.stat().st_mtime
        if cache_ttl == 0 or age < cache_ttl:
            return cp.read_bytes()

    host = urllib.parse.urlparse(url).netloc
    last_err: Exception | None = None

    for attempt in range(tries):
        _wait_turn(host)

        req = urllib.request.Request(
            url, headers={"User-Agent": ua or UA,
                          "Accept": "*/*",
                          "Accept-Encoding": "identity"})
        try:
            body = urllib.request.urlopen(req, timeout=timeout, context=CTX).read()
            if cache_ttl is not None:
                cp.parent.mkdir(parents=True, exist_ok=True)
                cp.write_bytes(body)
            return body
        except urllib.error.HTTPError as e:
            last_err = e
            # 429=限流，5xx=服务端抖动，这两类值得重试；其余（404/403）直接失败
            if e.code in (429, 500, 502, 503, 504):
                wait = 1.5 * (2 ** attempt)
                if not quiet:
                    print(f"    {host} 返回 {e.code}，{wait:.0f}s 后重试 "
                          f"({attempt + 1}/{tries})", file=sys.stderr)
                time.sleep(wait)
                continue
            break
        except Exception as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))

    raise FetchError(f"{url} 获取失败：{type(last_err).__name__}: {last_err}")


def fetch_json(url: str, **kw):
    """抓取并解析 JSON。"""
    return json.loads(fetch(url, **kw))


def fetch_text(url: str, encoding: str = "utf-8", **kw) -> str:
    """抓取并按指定编码解码为文本。"""
    return fetch(url, **kw).decode(encoding, errors="replace")


def try_fetch_json(url: str, **kw):
    """抓取 JSON，失败时返回 None 而不抛异常。

    用于可选数据源（例如被限流的 Yahoo）：拿不到就降级，不影响主流程。
    """
    try:
        return fetch_json(url, **kw)
    except Exception:
        return None
