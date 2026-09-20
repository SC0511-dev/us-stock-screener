---
name: ustock-screener
description: 美股选股与量化筛选工具箱。当用户需要按条件筛选美股、运行选股策略、计算技术指标、识别K线形态、查询SEC财报基本面、分析机构持仓13F、期权情绪或做空数据，或验证选股策略历史表现时使用。支持 333 个筛选条件自由组合与 20 个内置策略，数据全部来自公开免费源（SEC EDGAR、Nasdaq、FINRA、CBOE），无需 API Key。
---

# 美股选股器（US Stock Screener）　测试版 1.0

一套完整的美股筛选工具链：采集数据 → 计算因子 → 组合条件选股 → 历史验证。
所有数据源都是公开免费的，不需要任何 API Key。

> 完整的操作手册见仓库根目录的 [AGENTS.md](AGENTS.md)：
> 里面写明了动手前该问用户什么、各档股票范围的耗时、
> 如何把用户的自然语言需求翻译成筛选条件，以及解读结果时必须提醒的事项。

## 何时使用本技能

- 用户想按条件筛选美股（"找出站上200日线且相对强弱前20%的股票"）
- 用户想运行经典选股策略（Minervini 趋势模板、VCP、CANSLIM、神奇公式等）
- 用户想查某只股票的技术指标、K线形态、财报数据、机构持仓或做空占比
- 用户想验证某个选股思路在历史上的表现
- 用户问"最近哪些股票突破52周新高"这类市场扫描问题

**不适用**：实时行情报价、盘中交易、期权定价、个股深度基本面研究。

## 重要前提

**本工具只做研究与筛选，输出的股票列表不是投资建议。**
在向用户呈现结果时，务必保留这一点，并说明相应策略的已知局限（每个策略都带 `note` 字段）。

## 快速开始

首次使用前，先复制配置模板并把 `sec_user_agent` 改成使用者自己的邮箱
（SEC 要求声明真实联系方式）：

```bash
cp config/settings.example.json config/settings.json
```

然后采集数据（约 6~8 分钟）：

```bash
cd <项目目录>
.venv/bin/python scripts/fetch_universe.py        # 股票池，约 520 只（10 秒）
.venv/bin/python scripts/fetch_prices.py          # 日线行情（4~5 分钟）
.venv/bin/python scripts/fetch_fundamentals.py    # SEC 财报（1 分钟）
.venv/bin/python scripts/fetch_short.py           # FINRA 做空数据（40 秒）
.venv/bin/python scripts/fetch_profile.py         # 市值/行业/分析师目标价（1 分钟）
.venv/bin/python scripts/fetch_options.py         # 期权情绪（Nasdaq 源较快）
.venv/bin/python scripts/fetch_events.py          # 财报日历
.venv/bin/python scripts/fetch_13f.py             # 机构持仓（首次含 CUSIP 映射，约 10 分钟）
```

也可以用自选股票池代替全市场：

```bash
.venv/bin/python scripts/fetch_universe.py --watchlist config/watchlist_100.json
```

数据落在 `data/ustock.db`（SQLite）。之后每天重跑 `fetch_prices.py` 即可增量更新，
已是最新的股票会自动跳过。

## 核心用法

### 1. 运行内置策略

```bash
.venv/bin/python scripts/screen.py --strategy minervini --top 20
.venv/bin/python scripts/screen.py --list-strategies      # 查看全部 12 个策略
```

### 2. 自由组合条件

```bash
.venv/bin/python scripts/screen.py --conditions above_ma200,rs_leader,rev_growth_20
.venv/bin/python scripts/screen.py --conditions rsi_oversold,above_ma200 --mode and
.venv/bin/python scripts/screen.py --list-conditions --category 基本面
```

条件之间默认取「与」，`--mode or` 改为「或」。
浏览条件时优先用 `--category` 过滤，共 14 个分类、304 个条件。

### 3. 全因素快照报告

```bash
.venv/bin/python scripts/report.py --coverage          # 数据覆盖率体检
.venv/bin/python scripts/report.py --group AI与算力     # 按主题查看全部因子
.venv/bin/python scripts/report.py --csv factors.csv   # 导出完整因子表
.venv/bin/python scripts/report.py --html report.html  # 生成交互式网页报告
```

HTML 报告是单个自包含文件，可离线打开与分享：支持因子家族切换、排序、
按主题筛选、搜索，并能叠加任一内置策略高亮其命中股票。
向用户展示筛选结果时，优先生成这个报告而不是只贴终端表格。

### 4. 历史验证

```bash
.venv/bin/python scripts/backtest.py --strategy momentum_leader --top 20
```

### 5. 在 Python 里直接调用

```python
from ustock import store, screen, factors, strategies

prices = store.load_prices()
prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")
u = store.query("SELECT * FROM universe")
bench = prices[prices.symbol == "SPY"]

snap = screen.build_snapshot(prices[prices.symbol.isin(set(u.symbol))], bench=bench)
fund = factors.add_valuation(factors.fundamental_snapshot(), snap[["symbol", "close"]])
snap = factors.merge_all(snap, fund, factors.short_snapshot(), u)

s, picks = strategies.run("quality_growth", snap, u, top=20)
```

## 条件分类速查

| 分类 | 数量 | 典型条件 |
| --- | --- | --- |
| K线形态 | 154 | `pat_cdlhammer_bull`、`pat_any_bull_hq` |
| 趋势均线 | 38 | `above_ma200`、`ma_bull_stack` |
| 动量摆荡 | 29 | `rsi_oversold`、`macd_golden` |
| 基本面 | 23 | `rev_growth_20`、`roe_15` |
| 估值 | 10 | `pe_below_25`、`ps_below_5` |
| 波动通道 | 9 | `boll_squeeze`、`atr_tight` |
| 量能 | 9 | `volume_surge`、`volume_dry_5d` |
| 财务评分 | 9 | `f_score_8`、`altman_safe`、`magic_top50` |
| 价格位置 | 8 | `at_52w_high`、`near_52w_high` |
| 期权情绪 | 8 | `iv_elevated`、`pc_bearish`、`option_unusual` |
| 事件驱动 | 6 | `earnings_soon_5`、`pead_window` |
| 市值 | 5 | `large_cap`、`small_cap` |
| 市场结构 | 5 | `short_spike` |
| 流动性 | 4 | `liquid_10000000` |
| 机构持仓 | 4 | `inst_many_holders`、`inst_own_high` |
| 相对强弱 | 3 | `rs_leader` |
| 指数归属 | 3 | `in_sp500` |
| 政要持仓 | 3 | `politician_bought`（需自备数据源） |
| 分析师预期 | 3 | `target_upside_20` |

**建议**：任何筛选都加上流动性条件（如 `liquid_10000000`），
否则容易选出成交清淡、技术指标失真的股票。

## 解读结果时的注意事项

1. **做空占比高 ≠ 看空**。全市场中位数就有约 50%，其中大量是做市商对冲与 ETF 套利。
   应看 `short_ratio_z`（相对自身历史的异常度），而不是绝对值。
2. **市盈率为空**表示公司当期亏损，不是数据缺失。
3. **毛利率覆盖约八成**：约六成公司不单独披露毛利，系统会用「营收 − 营业成本」推导，
   仍有部分公司（尤其金融股）无法计算。
4. **回测结论要打折**：股票池取自当前指数成分，存在幸存者偏差；
   财报因子未还原披露时点，含基本面条件的策略还有前视偏差。
5. **选不出股票往往是正常的**。例如 Minervini 模板在熊市里本就该是空结果，
   这本身就是有意义的市场信号，不要通过放宽条件去"凑"出结果。

## 更多文档

- `references/数据源说明.md` —— 每个数据源的接口、字段、限制与已知坑
- `references/因子字典.md` —— 全部因子的计算口径
- `references/策略说明.md` —— 12 个内置策略的逻辑与适用场景
- `references/K线形态.md` —— 61 种形态的中英文对照与可靠度

## 项目结构

```
ustock/            核心库
  net.py           网络层（证书自愈、分站点节流、磁盘缓存）
  store.py         SQLite 存储
  universe.py      股票池
  indicators.py    技术指标（67 个）
  patterns.py      K线形态（61 种）
  factors.py       基本面与做空因子加工
  screen.py        选股引擎与条件库
  strategies.py    内置策略
  backtest.py      历史验证
  sources/         各数据源适配器
scripts/           命令行入口
references/        详细文档
```
