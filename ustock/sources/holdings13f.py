"""
机构持仓：SEC Form 13F。

管理资产超过一亿美元的机构必须每季度申报持仓，SEC 把这些申报整理成结构化数据集公开发布。
这是一类完全免费公开、且能落到个股层面的机构持仓信息。

两个工程上的坑：

1. **下载路径会变**
   SEC 近年多次调整数据集的命名与目录（既有 `2023q4_form13f.zip` 这种季度式，
   也有 `01jun2026-31aug2026_form13f.zip` 这种日期区间式；目录前缀还从
   structureddata 换成过 datastandardsinnovation）。
   因此本模块**从落地页动态解析链接**，不写死任何 URL。

2. **持仓用 CUSIP 标识，不是股票代码**
   需要额外做 CUSIP → 代码映射。这里用 OpenFIGI 的免费接口（无需密钥），
   并按持仓市值从高到低只映射头部标的——绝大部分机构资金集中在这些标的上，
   全量映射数万个 CUSIP 既慢也没必要。映射结果会缓存复用。
"""
from __future__ import annotations

import io
import json
import re
import time
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

from .. import net

LANDING = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
OPENFIGI = "https://api.openfigi.com/v3/mapping"
CUSIP_CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "cusip_map.json"

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _sort_key(name: str) -> tuple:
    """把两种命名格式统一成可排序的时间键，用于挑出最新一期。"""
    m = re.search(r"(\d{2})([a-z]{3})(\d{4})-", name)
    if m:                                    # 01jun2026-31aug2026 形式
        return (int(m.group(3)), _MONTHS.get(m.group(2), 0))
    m = re.search(r"(\d{4})q(\d)", name)
    if m:                                    # 2023q4 形式
        return (int(m.group(1)), int(m.group(2)) * 3)
    return (0, 0)


def list_datasets(ua: str | None = None) -> list[str]:
    """从落地页解析出全部数据集下载链接，按时间从新到旧排序。"""
    html = net.fetch_text(LANDING, ua=ua or net.DEFAULT_SEC_UA, cache_ttl=86400)
    hrefs = set(re.findall(r'href="([^"]*form13f\.zip)"', html, re.I))
    urls = [h if h.startswith("http") else "https://www.sec.gov" + h for h in hrefs]
    return sorted(urls, key=lambda u: _sort_key(u.rsplit("/", 1)[-1]), reverse=True)


def fetch_dataset(url: str, ua: str | None = None) -> zipfile.ZipFile:
    """下载并打开一期数据集（约 100 MB，已走磁盘缓存）。"""
    b = net.fetch(url, ua=ua or net.DEFAULT_SEC_UA, cache_ttl=86400 * 30, timeout=300)
    return zipfile.ZipFile(io.BytesIO(b))


def aggregate_holdings(z: zipfile.ZipFile, chunksize: int = 500_000) -> pd.DataFrame:
    """把逐笔持仓按标的（CUSIP）汇总。

    分块读取以控制内存——未压缩的持仓明细接近 400 MB。
    同时剔除期权头寸（PUTCALL 非空），只统计正股持仓。
    """
    name = next(n for n in z.namelist() if n.upper().startswith("INFOTABLE"))
    cols = ["CUSIP", "NAMEOFISSUER", "VALUE", "SSHPRNAMT", "SSHPRNAMTTYPE",
            "PUTCALL", "ACCESSION_NUMBER"]
    parts = []
    with z.open(name) as f:
        for chunk in pd.read_csv(f, sep="\t", usecols=cols, dtype=str,
                                 chunksize=chunksize, on_bad_lines="skip"):
            chunk = chunk[chunk["PUTCALL"].isna() | (chunk["PUTCALL"] == "")]
            chunk = chunk[chunk["SSHPRNAMTTYPE"] == "SH"]      # 只要股数口径
            chunk["VALUE"] = pd.to_numeric(chunk["VALUE"], errors="coerce")
            chunk["SSHPRNAMT"] = pd.to_numeric(chunk["SSHPRNAMT"], errors="coerce")
            g = chunk.groupby("CUSIP").agg(
                value=("VALUE", "sum"),
                shares=("SSHPRNAMT", "sum"),
                holders=("ACCESSION_NUMBER", "nunique"),
                name=("NAMEOFISSUER", "first"))
            parts.append(g)
    if not parts:
        return pd.DataFrame()
    out = (pd.concat(parts).groupby(level=0)
           .agg({"value": "sum", "shares": "sum", "holders": "sum", "name": "first"}))
    return out.reset_index().rename(columns={"CUSIP": "cusip"})


# ───────────────────────── CUSIP → 股票代码 映射 ─────────────────────────

def _load_cache() -> dict:
    if CUSIP_CACHE.exists():
        try:
            return json.loads(CUSIP_CACHE.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(m: dict) -> None:
    CUSIP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CUSIP_CACHE.write_text(json.dumps(m))


def map_cusips(cusips: list[str], ua: str | None = None,
               batch: int = 10, verbose: bool = True) -> dict[str, str]:
    """用 OpenFIGI 把 CUSIP 映射成股票代码。

    OpenFIGI 免费层不需要密钥，但有速率限制（约每分钟 25 次请求、每次 10 个标的），
    因此这里做了节流并把结果永久缓存，后续运行只映射新出现的 CUSIP。
    """
    cache = _load_cache()
    todo = [c for c in cusips if c and c not in cache]
    if verbose and todo:
        print(f"  需新映射 {len(todo)} 个 CUSIP（已缓存 {len(cache)} 个），"
              f"预计 {len(todo) / batch * 2.6 / 60:.0f} 分钟")

    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        body = json.dumps([{"idType": "ID_CUSIP", "idValue": c} for c in part]).encode()
        try:
            req = urllib.request.Request(
                OPENFIGI, data=body,
                headers={"Content-Type": "application/json",
                         "User-Agent": ua or net.UA})
            res = json.loads(urllib.request.urlopen(
                req, timeout=30, context=net.CTX).read())
            for c, item in zip(part, res):
                rows = item.get("data") or []
                # 只保留美国普通股的代码
                tk = next((r.get("ticker") for r in rows
                           if r.get("exchCode") == "US" and r.get("ticker")), None)
                cache[c] = tk or ""
        except Exception:
            # 失败的这批留待下次，不写入缓存以免把错误结果固化
            time.sleep(3)
            continue
        time.sleep(2.6)          # 免费层速率限制
        # 增量落盘：映射耗时较长，中途中断也不至于前功尽弃
        if (i // batch) % 20 == 0 and i:
            _save_cache(cache)
            if verbose:
                print(f"    已映射 {i}/{len(todo)}（已存盘）", flush=True)

    _save_cache(cache)
    return {c: cache[c] for c in cusips if cache.get(c)}


def build(top_n: int = 4000, ua: str | None = None,
          verbose: bool = True) -> pd.DataFrame:
    """下载最新一期 13F 并返回按股票代码汇总的机构持仓。

    top_n 控制映射规模：按持仓市值取前 N 个标的做代码映射。
    机构资金高度集中，前几千个标的已覆盖绝大部分持仓市值。
    """
    urls = list_datasets(ua)
    if not urls:
        raise RuntimeError("未能从 SEC 落地页解析到 13F 数据集链接")
    if verbose:
        print(f"  最新数据集：{urls[0].rsplit('/', 1)[-1]}")

    z = fetch_dataset(urls[0], ua)
    agg = aggregate_holdings(z)
    if agg.empty:
        return pd.DataFrame()
    if verbose:
        print(f"  持仓标的 {len(agg):,} 个，总市值 "
              f"{agg['value'].sum() / 1e6:,.0f} 百万美元")

    top = agg.nlargest(top_n, "value")
    m = map_cusips(top["cusip"].tolist(), ua, verbose=verbose)
    top = top.assign(symbol=top["cusip"].map(m))
    out = top[top["symbol"].notna() & (top["symbol"] != "")].copy()
    out["symbol"] = out["symbol"].str.upper().str.replace(".", "-", regex=False)
    return out[["symbol", "cusip", "name", "value", "shares", "holders"]]
