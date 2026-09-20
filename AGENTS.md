# 给 AI 助手的操作手册

本文件写给 AI 编程助手（Claude Code、Cursor、Codex、Gemini CLI、Windsurf 等）。
如果你是 AI，正在帮用户使用这个项目，请先完整读完本文件再动手。

如果你是人类：把这个仓库地址发给任意 AI 编程助手，对它说
**「帮我安装并使用这个项目」**，它会读到本文件并带你走完全程。

---

## 这是什么

一套美股量化筛选工具：采集公开数据 → 计算因子 → 按条件选股 → 历史验证 → 生成可视化报告。

- 333 个筛选条件（19 类）、61 种 K 线形态、20 个内置策略、70 个技术指标
- 数据来自 SEC EDGAR、Nasdaq、FINRA、CBOE，**全部公开免费，不需要任何 API Key**
- 所有数据存在用户本机的 SQLite 里，不上传

## 最重要的前提

**这是研究工具，输出的股票列表不是投资建议。**
每次向用户呈现选股结果时都要保留这一点，并说明所用策略的已知局限
（每个策略对象都带 `note` 字段，里面写明了适用场景与失效情形）。

---

## 第一步：先问用户，不要直接开跑

安装很快，但**采集数据的耗时差异极大**，取决于股票池范围。
动手前必须先问清楚，并把时间成本讲明白：

| 范围 | 股票数 | 首次采集耗时 | 适合谁 |
| --- | --- | --- | --- |
| `config/watchlist_100.json` | 100 | **约 3 分钟** | 第一次用、想快速看到结果 |
| `--scope index` | 约 520 | 约 8 分钟 | 想覆盖标普500 + 纳指100 + 道指 |
| `--scope all` | 约 7000 | **约 50 分钟** | 想扫全市场，适合放着跑 |

**建议默认推荐 100 只那档**，让用户几分钟内就能看到成果，之后再按需扩大。

还要顺带说明的两件事：

1. **需要用户提供一个邮箱**。美国证券交易委员会（SEC）要求所有自动化访问
   声明真实联系方式，否则会限制访问。这个邮箱只随请求发给 SEC，程序不上传到别处。
2. **机构持仓（13F）首次采集要额外约 10 分钟**，因为需要把持仓里的证券编号
   映射成股票代码。可以先跳过，之后随时补。

---

## 第二步：安装

```bash
git clone https://github.com/SC0511-dev/us-stock-screener.git
cd us-stock-screener
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

需要 Python 3.10+。核心依赖只有 pandas / numpy / lxml / certifi，都是纯 Python 轮子，
不需要编译，`pip install` 基本不会失败。

**K 线形态识别是可选的**：它需要 TA-Lib，而 TA-Lib 依赖一个 C 库。

```bash
brew install ta-lib                                 # macOS；其他系统见 requirements-patterns.txt
.venv/bin/pip install -r requirements-patterns.txt
```

不装也能正常用，只是 61 种形态识别与依赖形态的策略不可用，其余功能不受影响。
**不要因为装不上 TA-Lib 就中止整个流程**，继续往下走即可，并告诉用户少了哪部分能力。

写配置（把邮箱换成用户提供的）：

```bash
cp config/settings.example.json config/settings.json
```

然后把 `sec_user_agent` 改成 `us-stock-screener/1.0 (用户的邮箱)`。

> 也可以直接运行 `.venv/bin/python scripts/quickstart.py`，
> 它是一个交互式向导，会自己问邮箱、问范围并跑完全部采集。
> 但如果你（AI）在替用户操作，建议按下面的步骤自己控制，这样能边跑边解释。

---

## 第三步：采集数据

按顺序执行。每一步都可以单独重跑，已是最新的会自动跳过。

```bash
# 股票池（三选一）
.venv/bin/python scripts/fetch_universe.py --watchlist config/watchlist_100.json
.venv/bin/python scripts/fetch_universe.py --scope index
.venv/bin/python scripts/fetch_universe.py --scope all

.venv/bin/python scripts/fetch_prices.py --years 3    # 日线行情，最慢的一步
.venv/bin/python scripts/fetch_fundamentals.py        # SEC 财报
.venv/bin/python scripts/fetch_profile.py             # 市值 / 行业 / 分析师目标价
.venv/bin/python scripts/fetch_short.py --days 20     # FINRA 做空数据
.venv/bin/python scripts/fetch_events.py              # 财报日历
.venv/bin/python scripts/fetch_options.py --source nasdaq   # 期权情绪
.venv/bin/python scripts/fetch_13f.py                 # 机构持仓（首次约 10 分钟，可跳过）

.venv/bin/python scripts/status.py                    # 数据体检
```

行情采集是耗时大头，会打印进度与预计剩余时间。**建议在后台运行并定期汇报进度**，
不要让用户面对一个没有任何反馈的长时间等待。

某个数据源失败不影响其他部分，对应的因子会显示为空。如实告诉用户缺了什么即可，
**不要用估算值填补**。

---

## 第四步：选股与呈现

### 生成可视化报告（首选的呈现方式）

```bash
.venv/bin/python scripts/report.py --html report.html
```

产出一个自包含的网页文件，可离线打开：八个因子家族切换、点表头排序、
按主题筛选、叠加任一策略高亮命中股票。
**向用户展示结果时优先生成这个报告，而不是只在终端里贴表格。**

### 运行内置策略

```bash
.venv/bin/python scripts/screen.py --strategy minervini --top 20
.venv/bin/python scripts/screen.py --list-strategies
```

### 自由组合条件

```bash
.venv/bin/python scripts/screen.py --conditions above_ma200,rs_leader,rev_growth_20
.venv/bin/python scripts/screen.py --list-conditions --category 基本面
```

条件之间默认取「与」，加 `--mode or` 改为「或」。
**任何筛选都建议带上流动性条件**（如 `liquid_10000000`），否则容易选出
成交清淡、技术指标失真的股票。

### 历史验证

```bash
.venv/bin/python scripts/backtest.py --strategy momentum_leader --top 20
```

---

## 把用户的话翻译成条件

用户通常用自然语言提需求，你需要把它映射成条件组合。几个例子：

| 用户说 | 条件组合 |
| --- | --- |
| 「找强势股」 | `rs_leader,above_ma200,ma_bull_stack,liquid_10000000` |
| 「跌下来的好公司」 | `above_ma200,rsi_oversold,profitable,roe_15,liquid_10000000` |
| 「便宜又赚钱的」 | `pe_below_25,profitable,fcf_positive,roe_15,liquid_10000000` |
| 「高成长」 | `rev_growth_30,gross_margin_50,liquid_10000000` |
| 「快创新高的」 | `near_52w_high,volume_up,above_ma50,liquid_10000000` |
| 「财务最稳健的」 | `f_score_8,altman_safe,profitable,liquid_10000000` |
| 「被大量做空的」 | `short_heavy,short_spike,liquid_10000000` |
| 「机构扎堆的」 | `inst_many_holders,inst_own_high,liquid_10000000` |
| 「快出财报的」 | `earnings_soon_14,liquid_10000000` |

完整条件清单见 `references/因子字典.md`，也可以用
`scripts/screen.py --list-conditions --category <分类>` 现查。

---

## 解读结果时必须提醒用户的事

这几条很容易被误读，**呈现结果时要主动说明**：

1. **做空占比高 ≠ 市场看空**。全市场中位数就有约 50%，其中大量是做市商对冲
   与 ETF 套利。应该看 `short_ratio_z`（相对自身历史的异常度），而不是绝对值。
2. **市盈率为空表示公司当期亏损**，不是数据缺失。
3. **空白单元格是真的没有数据**，不是 0。例如外国发行人（台积电、ASML 等）提交
   20-F 而非 10-K，SEC 的 XBRL 覆盖不同；银行采用非分类资产负债表，算不出 Altman Z 值。
4. **选不出股票往往是正常的**。例如 Minervini 趋势模板在熊市里本就该是空结果，
   这本身就是有意义的市场信号。**不要为了凑出结果去偷偷放宽条件**；
   如果要放宽，必须明确告诉用户你改了什么。
5. **回测结论要打折**。股票池取自当前成分，存在幸存者偏差；财报因子未还原
   披露时点，存在前视偏差；且未计滑点与手续费。

---

## 数据更新

用户之后想更新数据时，重跑对应脚本即可，已是最新的会自动跳过：

| 数据 | 建议频率 |
| --- | --- |
| 日线行情、做空数据 | 每个交易日 |
| 财报、财报日历 | 每周 |
| 股票池、机构持仓 | 每月 / 每季 |

或者直接重跑向导：`.venv/bin/python scripts/quickstart.py`

---

## 更多文档

| 文件 | 内容 |
| --- | --- |
| `references/因子字典.md` | 333 个筛选条件完整清单 |
| `references/策略说明.md` | 20 个策略的逻辑、条件与局限 |
| `references/K线形态.md` | 61 种形态中英文对照与可靠度 |
| `references/数据源说明.md` | 各数据源接口细节、覆盖率实测与已知坑 |
| `SKILL.md` | 作为 Claude Skill 安装时的入口 |
