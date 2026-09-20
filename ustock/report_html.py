"""
交互式 HTML 报告生成。

输出单个自包含的 HTML 文件：不依赖任何外部资源，可离线打开、直接分享。
之所以不做成 Web 服务，是因为本项目定位是工具包而非常驻应用——
一个能双击打开的文件，比一个需要先启动服务器的页面更容易分发和存档。

页面提供的交互：
    因子分组切换   技术面 / 基本面 / 估值 / 财务评分 / 市场结构 / 期权 / 机构 / 事件
    排序与搜索     点击表头排序，搜索框支持代码与公司名
    主题筛选       按股票池的主题分组过滤
    策略叠加       选择内置策略后，高亮命中的股票并可只看命中项
"""
from __future__ import annotations

import datetime as dt
import html
import json

import numpy as np
import pandas as pd

# 列定义：键 → (中文名, 类型, 小数位)
# 类型决定格式化与配色：pct 百分比、money 金额、num 数值、int 整数、text 文本
COLUMNS: dict[str, tuple[str, str, int]] = {
    "symbol": ("代码", "text", 0),
    "name": ("公司", "text", 0),
    "theme": ("主题", "text", 0),
    # 技术面
    "close": ("现价", "money0", 2),
    "rs_rating": ("RS评级", "score", 0),
    "mom_1m": ("1月", "pct", 1),
    "mom_3m": ("3月", "pct", 1),
    "mom_12m": ("12月", "pct", 1),
    "pct_from_52w_high": ("距52周高", "pct", 1),
    "rsi14": ("RSI", "num", 1),
    "adx": ("ADX", "num", 1),
    "natr": ("ATR%", "num", 2),
    "vol_ratio": ("量比", "num", 2),
    "px_vs_ma200": ("距200日线", "pct", 1),
    # 基本面
    "revenue_yoy": ("营收增速", "pct", 1),
    "net_income_yoy": ("净利增速", "pct", 1),
    "gross_margin": ("毛利率", "pct", 1),
    "net_margin": ("净利率", "pct", 1),
    "op_margin": ("营业利润率", "pct", 1),
    "roe": ("ROE", "pct", 1),
    "fcf_margin": ("FCF利润率", "pct", 1),
    # 估值
    "market_cap": ("市值", "bigmoney", 0),
    "pe": ("市盈率", "num", 1),
    "ps": ("市销率", "num", 1),
    "pb": ("市净率", "num", 1),
    "fcf_yield": ("FCF收益率", "pct", 1),
    "upside_to_target": ("距目标价", "pct", 1),
    # 财务评分
    "f_score": ("F分", "fscore", 0),
    "altman_z": ("Z值", "zscore", 2),
    "magic_rank": ("神奇排名", "rank", 0),
    "roce": ("ROCE", "pct", 1),
    "earnings_yield": ("息税前收益率", "pct", 1),
    # 市场结构
    "short_ratio": ("做空占比", "pct", 1),
    "short_ratio_z": ("做空异常度", "num", 2),
    # 期权
    "iv30": ("隐含波动率", "num", 1),
    "put_call_vol": ("认沽认购比", "num", 2),
    "put_call_oi": ("持仓比", "num", 2),
    "iv_skew": ("波动率偏斜", "num", 3),
    "opt_stock_vol": ("期权/正股", "num", 2),
    # 机构
    "inst_holders": ("机构家数", "int", 0),
    "inst_own_pct": ("机构占比", "pct", 1),
    # 事件
    "days_to_earnings": ("距财报", "days", 0),
}

GROUPS: dict[str, list[str]] = {
    "技术面": ["close", "rs_rating", "mom_1m", "mom_3m", "mom_12m",
              "pct_from_52w_high", "px_vs_ma200", "rsi14", "adx", "natr", "vol_ratio"],
    "基本面": ["revenue_yoy", "net_income_yoy", "gross_margin", "net_margin",
              "op_margin", "roe", "fcf_margin"],
    "估值": ["market_cap", "pe", "ps", "pb", "fcf_yield", "upside_to_target"],
    "财务评分": ["f_score", "altman_z", "magic_rank", "roce", "earnings_yield"],
    "市场结构": ["short_ratio", "short_ratio_z"],
    "期权情绪": ["iv30", "put_call_vol", "put_call_oi", "iv_skew", "opt_stock_vol"],
    "机构持仓": ["inst_holders", "inst_own_pct"],
    "事件": ["days_to_earnings"],
}

BASE = ["symbol", "name", "theme"]


def _clean(v):
    """把 NaN / Inf 转成 None，保证能安全序列化成 JSON。"""
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        return None if not np.isfinite(v) else round(float(v), 6)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if pd.isna(v):
        return None
    return str(v)


def build(snap: pd.DataFrame, strategies_hits: dict[str, dict] | None = None,
          title: str | None = None) -> str:
    """把因子快照渲染成单文件 HTML。

    strategies_hits 形如 {策略key: {"name":..., "desc":..., "note":..., "symbols":[...]}}，
    用于在页面上叠加策略命中结果。
    """
    cols = [c for c in COLUMNS if c in snap.columns]
    data = [{c: _clean(r.get(c)) for c in cols} for _, r in snap.iterrows()]

    from . import __author__, __title__, __version_label__
    meta = {
        "date": str(snap["date"].max()) if "date" in snap.columns else "",
        "count": len(snap),
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "title": title or __title__,
        "version": __version_label__,
        "author": __author__,
    }
    themes = sorted({d.get("theme") for d in data if d.get("theme")})

    # 覆盖率：每个因子有多少只股票拿到了数据
    coverage = {c: int(snap[c].notna().sum()) for c in cols if c not in BASE}

    payload = {
        "meta": meta,
        "columns": {c: list(COLUMNS[c]) for c in cols},
        "groups": {g: [c for c in cs if c in cols] for g, cs in GROUPS.items()},
        "base": [c for c in BASE if c in cols],
        "rows": data,
        "themes": themes,
        "coverage": coverage,
        "strategies": strategies_hits or {},
    }
    return _TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)) \
                    .replace("__TITLE__", html.escape(title or __import__("ustock").__title__))


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --bg:#0d1117; --panel:#161b22; --panel2:#1c2129; --line:#2a313c;
  --txt:#e6edf3; --dim:#8b949e; --accent:#2f81f7;
  --up:#3fb950; --down:#f85149; --warn:#d29922;
}
@media (prefers-color-scheme:light){
  :root:not([data-theme="dark"]){
    --bg:#f6f8fa; --panel:#fff; --panel2:#f0f3f6; --line:#d8dee4;
    --txt:#1f2328; --dim:#636c76; --accent:#0969da;
    --up:#1a7f37; --down:#cf222e; --warn:#9a6700;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
  font:13px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:100%;padding:16px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;margin-bottom:14px}
h1{font-size:19px;margin:0;font-weight:650}
.sub{color:var(--dim);font-size:12px}
.ver{background:var(--panel2);border:1px solid var(--line);border-radius:10px;
  padding:1px 8px;font-size:11px;color:var(--dim);font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.card .k{color:var(--dim);font-size:11px;margin-bottom:3px}
.card .v{font-size:17px;font-weight:650;font-variant-numeric:tabular-nums}
.bar{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:10px;margin-bottom:12px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.bar label{color:var(--dim);font-size:12px;margin-right:2px}
select,input,button{background:var(--panel2);color:var(--txt);border:1px solid var(--line);
  border-radius:6px;padding:5px 9px;font-size:12px;font-family:inherit}
input{min-width:180px}
button{cursor:pointer}
button:hover{border-color:var(--accent)}
button.on{background:var(--accent);border-color:var(--accent);color:#fff}
.tabs{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px}
.tab{padding:5px 11px;border-radius:6px;border:1px solid var(--line);
  background:var(--panel);cursor:pointer;font-size:12px}
.tab.on{background:var(--accent);border-color:var(--accent);color:#fff}
.tablewrap{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  overflow:auto;max-height:72vh}
table{border-collapse:separate;border-spacing:0;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 9px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
th{position:sticky;top:0;background:var(--panel2);cursor:pointer;font-weight:600;
  font-size:11px;color:var(--dim);z-index:2;user-select:none}
th:hover{color:var(--txt)}
th.sorted{color:var(--accent)}
td.t,th.t{text-align:left}
tbody tr:hover{background:var(--panel2)}
tr.hit{background:rgba(47,129,247,.10)}
tr.hit td:first-child{box-shadow:inset 3px 0 var(--accent)}
.sym{font-weight:650}
.nm{color:var(--dim);max-width:200px;overflow:hidden;text-overflow:ellipsis;display:inline-block;vertical-align:bottom}
.up{color:var(--up)} .down{color:var(--down)} .na{color:var(--line)}
.pill{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;font-weight:600}
.p-hi{background:rgba(63,185,80,.16);color:var(--up)}
.p-mid{background:rgba(210,153,34,.16);color:var(--warn)}
.p-lo{background:rgba(248,81,73,.16);color:var(--down)}
.note{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--warn);
  border-radius:6px;padding:10px 12px;margin-bottom:12px;font-size:12px;color:var(--dim);display:none}
.note.show{display:block}
.note b{color:var(--txt)}
footer{color:var(--dim);font-size:11px;margin-top:14px;line-height:1.7}
.cov{display:flex;gap:4px;align-items:center}
.covbar{width:34px;height:4px;background:var(--line);border-radius:2px;overflow:hidden}
.covbar i{display:block;height:100%;background:var(--accent)}
@media(max-width:700px){.nm{display:none}.wrap{padding:10px}}
</style></head><body><div class="wrap">

<header>
  <h1 id="title"></h1>
  <span class="ver" id="ver"></span>
  <span class="sub" id="meta"></span>
</header>

<div class="cards" id="cards"></div>

<div class="bar">
  <label>主题</label><select id="fTheme"><option value="">全部</option></select>
  <label>策略</label><select id="fStrat"><option value="">不叠加</option></select>
  <button id="onlyHit">只看命中</button>
  <input id="q" placeholder="搜索代码或公司名…">
  <button id="reset">重置</button>
  <span class="sub" id="cnt" style="margin-left:auto"></span>
</div>

<div class="note" id="stratNote"></div>
<div class="tabs" id="tabs"></div>
<div class="tablewrap"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>

<footer>
  数据来源：SEC EDGAR · Nasdaq · FINRA · CBOE，均为公开免费接口。
  表头可点击排序；列组标签切换不同因子家族；选择策略后命中股票会高亮。<br>
  <b>本页面仅为投资研究工具，所有内容不构成投资建议。</b>
  空白单元格表示该项数据缺失（例如亏损公司没有市盈率、银行不披露流动资产），并非计算错误。
</footer>
</div>

<script>
const D = __PAYLOAD__;
const COL = D.columns, ROWS = D.rows;
let group = Object.keys(D.groups)[0];
let sortKey = "rs_rating", sortDir = -1, onlyHit = false;

const el = id => document.getElementById(id);
const fmtInt = n => n==null?"":n.toLocaleString();

function money(v){ // 市值：按亿/万亿显示
  if(v==null) return "";
  if(v>=1e12) return (v/1e12).toFixed(2)+"万亿";
  if(v>=1e8)  return (v/1e8).toFixed(0)+"亿";
  return fmtInt(Math.round(v));
}

function cell(key,v){
  const [ , type, dp] = COL[key];
  if(v==null||v==="") return '<span class="na">–</span>';
  switch(type){
    case "text": return key==="symbol" ? '<span class="sym">'+v+'</span>'
                 : key==="name" ? '<span class="nm">'+v+'</span>' : v;
    case "pct": {
      const s=(v*100).toFixed(dp)+"%";
      return '<span class="'+(v>0?"up":v<0?"down":"")+'">'+(v>0?"+":"")+s+'</span>';
    }
    case "bigmoney": return money(v);
    case "money0": return v.toFixed(dp);
    case "int": return fmtInt(v);
    case "days": return v<0?"":v+"天";
    case "score": { // RS 评级 0-99
      const c=v>=80?"p-hi":v>=50?"p-mid":"p-lo";
      return '<span class="pill '+c+'">'+v.toFixed(0)+'</span>';
    }
    case "fscore": {
      const c=v>=8?"p-hi":v>=5?"p-mid":"p-lo";
      return '<span class="pill '+c+'">'+v+'</span>';
    }
    case "zscore": { // Altman：>2.99 安全，<1.81 困境
      const c=v>2.99?"p-hi":v>1.81?"p-mid":"p-lo";
      return '<span class="pill '+c+'">'+v.toFixed(dp)+'</span>';
    }
    case "rank": return v.toFixed(0);
    default: return v.toFixed(dp);
  }
}

function currentCols(){ return D.base.concat(D.groups[group]); }

function hits(){
  const k = el("fStrat").value;
  return k && D.strategies[k] ? new Set(D.strategies[k].symbols) : null;
}

function filtered(){
  const th = el("fTheme").value, q = el("q").value.trim().toUpperCase(), H = hits();
  let r = ROWS.filter(x =>
    (!th || x.theme===th) &&
    (!q || (x.symbol||"").includes(q) || (x.name||"").toUpperCase().includes(q)) &&
    (!onlyHit || !H || H.has(x.symbol)));
  const dir = sortDir;
  r.sort((a,b)=>{
    let va=a[sortKey], vb=b[sortKey];
    if(va==null&&vb==null) return 0;
    if(va==null) return 1;          // 缺失值恒排在后面
    if(vb==null) return -1;
    if(typeof va==="string") return dir*va.localeCompare(vb);
    return dir*(va-vb);
  });
  return r;
}

function render(){
  const cols = currentCols(), rows = filtered(), H = hits();

  el("thead").innerHTML = "<tr>"+cols.map(c=>{
    const [nm,type] = COL[c];
    const cov = D.coverage[c];
    const covHtml = cov!=null && cov<D.meta.count
      ? '<div class="cov"><div class="covbar"><i style="width:'+(cov/D.meta.count*100)+'%"></i></div></div>' : "";
    return '<th data-k="'+c+'" class="'+(type==="text"?"t ":"")+(c===sortKey?"sorted":"")+'">'
      + nm + (c===sortKey?(sortDir<0?" ↓":" ↑"):"") + covHtml + '</th>';
  }).join("")+"</tr>";

  el("tbody").innerHTML = rows.map(r=>{
    const hit = H && H.has(r.symbol);
    return '<tr class="'+(hit?"hit":"")+'">'+cols.map(c=>
      '<td class="'+(COL[c][1]==="text"?"t":"")+'">'+cell(c,r[c])+'</td>').join("")+'</tr>';
  }).join("") || '<tr><td colspan="'+cols.length+'" style="text-align:center;padding:26px;color:var(--dim)">'
    +'没有符合条件的股票。<br>这通常不是程序出错，而是当前条件下确实没有标的。</td></tr>';

  el("cnt").textContent = rows.length+" / "+ROWS.length+" 只";
  document.querySelectorAll("th").forEach(t=>t.onclick=()=>{
    const k=t.dataset.k;
    if(k===sortKey) sortDir=-sortDir; else {sortKey=k; sortDir=(COL[k][1]==="text")?1:-1;}
    render();
  });
}

function init(){
  document.title = D.meta.title;
  el("title").textContent = D.meta.title;
  el("ver").textContent = D.meta.version;
  el("meta").textContent = "数据日期 "+D.meta.date+" · "+D.meta.count
    +" 只股票 · 生成于 "+D.meta.generated+" · 作者 "+D.meta.author;

  // 顶部概览卡片
  const num = k => ROWS.map(r=>r[k]).filter(v=>v!=null);
  const avg = a => a.length? a.reduce((x,y)=>x+y,0)/a.length : null;
  const card = (k,v)=>'<div class="card"><div class="k">'+k+'</div><div class="v">'+v+'</div></div>';
  const up = num("mom_3m").filter(v=>v>0).length, tot = num("mom_3m").length;
  el("cards").innerHTML =
    card("股票数", D.meta.count) +
    card("3月上涨占比", tot?Math.round(up/tot*100)+"%":"–") +
    card("RS 中位数", Math.round(avg(num("rs_rating"))||0)) +
    card("F分≥8", num("f_score").filter(v=>v>=8).length+" 只") +
    card("距52周高<5%", num("pct_from_52w_high").filter(v=>v>-0.05).length+" 只") +
    card("隐含波动率中位", (avg(num("iv30"))||0).toFixed(1));

  D.themes.forEach(t=>el("fTheme").add(new Option(t,t)));
  Object.entries(D.strategies).forEach(([k,v])=>el("fStrat").add(new Option(v.name+"（"+v.symbols.length+"）",k)));

  el("tabs").innerHTML = Object.keys(D.groups).map(g=>
    '<div class="tab'+(g===group?" on":"")+'" data-g="'+g+'">'+g+'</div>').join("");
  document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{
    group=t.dataset.g;
    document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x===t));
    render();
  });

  el("fStrat").onchange = ()=>{
    const k=el("fStrat").value, n=el("stratNote");
    if(k && D.strategies[k]){
      const s=D.strategies[k];
      n.innerHTML = "<b>"+s.name+"</b>　"+s.desc+(s.note?"<br><b>局限：</b>"+s.note:"");
      n.classList.add("show");
    } else n.classList.remove("show");
    render();
  };
  el("onlyHit").onclick = ()=>{
    onlyHit=!onlyHit; el("onlyHit").classList.toggle("on",onlyHit); render();
  };
  ["fTheme","q"].forEach(id=>el(id).oninput=render);
  el("reset").onclick=()=>{
    el("fTheme").value=""; el("fStrat").value=""; el("q").value="";
    onlyHit=false; el("onlyHit").classList.remove("on");
    el("stratNote").classList.remove("show"); render();
  };
  render();
}
init();
</script></body></html>
"""
