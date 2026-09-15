# turtle-value-engine

一个面向 **A 股 / H 股价值投资研究** 的确定性、可审计分析引擎。

`turtle-value-engine` 的目标，是把“龟龟投资法”中原本依赖人工判断、表格计算和经验复核的流程，逐步转换成一套：

- 可执行
- 可重复
- 可测试
- 可追溯
- 不依赖 LLM 临场重算

的分析系统。

> 本项目用于投资研究与软件实验，不构成任何投资建议。

## 它解决什么问题？

传统股票分析很容易把不同问题混在一起，例如：

> “公司很好，所以股票值得买。”

`turtle-value-engine` 刻意把它拆成几个相互独立的问题。

### 1. 公司安全吗？

关注现金、债务、潜在债务和资产负债表风险。

### 2. 公司真的赚钱吗？

不是只看会计利润，而是关注企业真正能产生多少可供股东支配的现金。

项目中将这一核心现金能力称为 **CDC**。

### 3. 股东真正获得了多少回报？

关注：

- 分红
- 回购
- 股份稀释
- 实际流向股东的经济利益

并计算 **Through Return（穿透回报率）**。

### 4. 生意本身是不是好生意？

例如：

- 商业模式是否容易理解
- 盈利是否可持续
- 是否高度依赖资本投入
- 是否存在明显治理风险
- 是否拥有长期竞争力

这部分必须由可追溯证据支持，而不是由模型凭感觉打分。

### 5. 当前价格是否足够便宜？

只有前面的安全性、现金能力、股东回报和商业质量达到要求后，估值才有意义。

换句话说：

```text
好公司 ≠ 好股票
便宜公司 ≠ 值得投资
高分红 ≠ 高股东回报
账面现金多 ≠ 真正安全
```

## 核心流程

整个分析流程可以简化为：

```text
原始数据 / 财报证据
        ↓
Normalized Facts
        ↓
CDC / Net Cash / Through Return
        ↓
Hard Gates
        ↓
Valuation
        ↓
CompanyAnalysis
        ↓
PASS / WATCH / FAIL / SPECIAL_REVIEW
```

计算规则由版本化 rule profile 控制，例如：

```text
strict-v1
```

相同输入、相同规则版本，应产生相同结果。

数据准备和计算是两个明确的边界：

```text
NETWORKED / REPLAYABLE
A/H listing + as_of → tve prepare → cache / normalization
                  → NormalizedCompanyInput.json

OFFLINE / DETERMINISTIC
NormalizedCompanyInput.json → tve analyze → CompanyAnalysis.json
```

`tve analyze` 不会偷偷联网。

## 为什么强调“可审计”？

系统尽量避免：

```text
AI 觉得这家公司不错
```

这样的不可验证结论。

理想情况下，一个最终结论应该可以反向追溯：

```text
Decision
  ↓
Gate
  ↓
Metric
  ↓
Adjustment
  ↓
Fact
  ↓
Evidence
  ↓
Source / Filing
```

这样可以知道：

- 某个数字来自哪里
- 是否做过调整
- 为什么调整
- 谁批准了调整
- 哪份公告或财报支持这个判断

# Quick Start

## 环境要求

- Python 3.11+

克隆项目：

```bash
git clone https://github.com/blooddrunk/turtle-value-engine.git
cd turtle-value-engine
```

创建虚拟环境并安装：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows PowerShell 激活虚拟环境：

```powershell
.venv\Scripts\Activate.ps1
```

## 运行一个示例分析

仓库提供了一组 synthetic fixtures，可以直接用于体验 deterministic engine。

例如：

```bash
tve analyze \
  --input fixtures/healthy_cash_cow.json \
  --profile strict-v1
```

输出是 JSON 格式的 `CompanyAnalysis`。

如果从 provider/cache 开始准备一个 A/H 标的：

```bash
tve prepare 600519.SH \
  --as-of 2026-09-14 \
  --provider akshare \
  --name "示例公司" \
  --sector "示例行业" \
  --reporting-currency CNY \
  --output normalized.json
```

`tve prepare` 的公司名称、行业和报告货币必须由调用者显式提供，或
通过 `--company-json` 提供；准备层不会猜测这些核心上下文。重复执行时
可以使用 `--offline` 从 raw cache replay，之后把生成的 JSON 交给
`tve analyze --input normalized.json --profile strict-v1`。

也可以保存到文件：

```bash
tve analyze \
  --input fixtures/healthy_cash_cow.json \
  --profile strict-v1 \
  > analysis.json
```

# 当前已经实现什么？

## Deterministic Engine

已经实现：

- CDC
- Net Cash
- Through Return
- Business Quality structured assessment
- Hard Gates
- Valuation
- Final `CompanyAnalysis`

## Structured Data Infrastructure

已经建立：

- provider abstraction
- local cache / replay
- A/H 股结构化数据适配
- AKShare provider
- provider-backed `tve prepare` with canonical A/H listing and `as_of`
- raw cache replay and injected/frozen provider preparation
- provenance tracking
- missing-data handling
- schema validation

大量 provider 字段如果无法确认经济含义、期间、单位或会计口径，会保留为 **raw evidence**，而不是被强行映射成 canonical fact。

## Filing & Evidence Infrastructure

已经建立：

```text
Filing Discovery
→ Document Download / Cache
→ Text Extraction
→ Evidence Store
→ Adjustment Proposal / Review
→ explicit acceptance → effective input → deterministic analysis trace
```

系统会保留：

- filing identity
- official source
- document hash
- page / section locator
- evidence identity
- adjustment provenance
- source-fact/effective-fact lineage
- Decision → Gate → Metric → Adjustment → Fact → Evidence → Filing trace

## Phase 4：证据研究与 Business Quality

Phase 4 在上述确定性边界之上增加了可恢复、可审计的 agent-assisted research
流程。外部运行时只需要注入一个 model-neutral 的 `AnalystClient`，就可以消费
同一套 typed contracts；核心包不依赖 OpenAI、Anthropic、ChatGPT、Hermes 或
其他厂商 SDK。

```text
NormalizedCompanyInput
  → bounded EvidencePacket（带 as_of）
  → Quality Analyst
  → Skeptic
  → Adjudicator
  → deterministic Business Quality validation
  → accepted-adjustment materialization（如有明确批准）
  → deterministic analysis
  → ResearchReport
```

八个 Business Quality 维度都使用同一套固定的
Quality Analyst → Skeptic → Adjudicator 结构。模型只能提交带证据引用的
研究结论和 `PROPOSED` adjustment；证据 ID、as_of、分数上限、置信度、覆盖率
和 gate 语义由规则引擎校验。只有现有 Phase 3 workflow 接受的
`HUMAN` / `RULE_ENGINE` adjustment 才能进入 effective input。

可复用的 Python 边界包括：

- `EvidencePacketBuilder`：按问题组装有大小上限的点时证据包；
- `run_business_quality_dimension` / `run_business_quality_research`：运行单个维度或全部 B01–B08；
- `ResearchOrchestrator`：连接研究、批准后的确定性分析和报告；
- `ResearchWorkspace`：保存 packet、task、analyst run、session、analysis、trace 和 report，支持另一个进程恢复；
- `compose_report`：从已验证 artifacts 生成不修改分析结果的可读报告。

普通测试使用 `ScriptedAnalystClient`，live model integration 不属于 CI 必需项。

## Phase 5R：历史数据冻结与离线回放

Phase 5R 增加了带来源、覆盖率和许可证声明的历史数据边界。大数据通过
content-addressed JSONL shard 保存；缺失或 hash 不一致时会失败，不会偷偷联网。
仓库内的 compact corpus 只是离线验收 fixture，不代表完整 A/H 市场覆盖：

```bash
tve dataset validate \
  --manifest fixtures/historical/phase5r-compact-v1/manifest.json \
  --store fixtures/historical/phase5r-compact-v1/store
tve dataset freeze \
  --manifest fixtures/historical/phase5r-compact-v1/manifest.json \
  --store fixtures/historical/phase5r-compact-v1/store \
  --output backtest-manifest.json
```

`tve dataset snapshot`、`tve backtest` 和 `tve calibrate` 只消费已经冻结的
manifest、decision artifact 和 research archive；校准只输出 proposal。要声明
生产级历史覆盖，必须另行提供可审计、具备访问/再分发条件的来源及完整覆盖证据，
并使用 `--require-production` 验证。

## Phase 5R-A：个人优先的原始数据获取

Phase 5R-A 增加了独立的 source probe、raw-byte receipt、私有本地 CAS 和离线
compiler。live 网络默认关闭，只有命令显式带 `--network=allow` 才会访问来源；
默认 CLI 的内置真实 transport 还要求 plan 中每个 request 的必需凭据都声明为
`ENVIRONMENT` credential reference，并在首次触网前解析为非空值。OS keyring 或
显式注入 resolver 只用于受控 library runner 和 fake transport；凭据绝不从聊天读取。

```bash
tve historical source probe --plan plan.json --network=allow
tve historical acquire --plan plan.json --network=allow \
  --raw-store .tve-private/raw --batch-output .tve-private/batch.json
tve historical compile --batch .tve-private/batch.json \
  --raw-store .tve-private/raw --store .tve-private/artifacts \
  --output .tve-private/historical-manifest.json
tve historical accept --batch .tve-private/batch.json \
  --probe-report .tve-private/live/probe.json \
  --raw-store .tve-private/raw \
  --manifest .tve-private/historical-manifest.json \
  --store .tve-private/artifacts \
  --output .tve-private/live/acceptance.json
```

获取和编译边界、条款证据、备份/删除及当前精确 blocker 见
[`docs/operations/phase-5r-a-acquisition.md`](docs/operations/phase-5r-a-acquisition.md)。
`historical accept` 是离线 A6 审计；它会在未证明 A/H 能力、来源覆盖、授权或
终止经济时 fail closed，并把精确 blocker 写入报告。
H 股来源、历史 membership、退市经济和授权未核实前不会自动升级为生产级
历史覆盖，也不会要求机构商业源或手工整理 CSV。

# 当前还不能做什么？

目前：

```bash
tve analyze
```

仍然是一个 **离线 deterministic 命令**。

它要求输入已经符合 `NormalizedCompanyInput` 数据契约。

因此目前还不能直接这样使用：

```bash
tve analyze 600519
```

并自动完成：

```text
获取行情
→ 获取财报
→ 解析公告
→ 形成证据
→ 应用已审核调整
→ 最终投资分析
```

现在已经闭合 provider/cache/normalization、accepted-adjustment materialization
和 filing-to-decision traceability 的确定性组合路径。仍然不会自动猜测公司
核心上下文、让 LLM 批准 adjustment，或让 LLM 重算指标。Phase 4 的研究入口
接受已经准备好的 `NormalizedCompanyInput`；它不会把联网和模型调用隐藏进
`tve analyze`。

## 关于 Business Quality

Business Quality 不会由引擎根据几个财务数字自动猜测。

如果没有提供经过证据支持的结构化 Business Quality assessment：

```text
Business Quality Gate
→ NOT_EVALUATED
```

系统不会因此自动给出投资通过结论。

这是刻意设计的安全边界。

## 关于 LLM

Phase 4 允许外部 agent / LLM 协助：

- 阅读财报
- 查找 restricted cash
- 分析租赁与利息分类
- 理解收购与处置
- 分析分红政策
- 查找治理风险
- 分析客户集中度
- 收集 Business Quality 证据

运行时通过 `AnalystClient.analyze(task)` 接收 bounded `ResearchTask`，返回
`ResearchFinding` 或等价 JSON；每次调用的 prompt/protocol/provider metadata
会进入 `AnalystRun`。`Quality Analyst` 先建立支持论点，`Skeptic` 主动寻找
反证，`Adjudicator` 只能使用已经提供给它的 evidence 和前两次 finding。

但 LLM 不负责重新计算确定性指标，也不能直接覆盖 engine facts。

原则是：

```text
LLM
→ 找证据 / 提建议 / 提出 Adjustment

Deterministic Engine
→ 做计算 / 执行规则 / 生成最终状态
```

# 项目结构

```text
src/turtle_value_engine/
├── calculations/       # deterministic calculations
├── gates/              # hard-gate evaluation
├── providers/          # structured data / filing providers and cache
├── models/             # typed contracts
├── adjustments.py      # auditable adjustment workflow
├── effective_input.py  # accepted-adjustment materialization boundary
├── preparation.py      # provider/cache/normalization orchestration
├── research/            # bounded agent contracts, BQ workflow and report
├── historical/          # source-aware shards, coverage, archive and compiler
├── traceability.py     # deterministic decision trace projection
├── pipeline.py         # deterministic analysis pipeline
└── cli.py              # command-line interface

rules/
└── strict-v1.yaml

schemas/
├── normalized-input.schema.json
├── company-analysis.schema.json
└── ...

docs/
├── spec/
├── architecture/
├── data/
└── roadmap.md
```

# 重要文档

如果只是想了解和使用项目，从本 README 开始即可。

如果希望进一步了解设计：

- **投资规则**：`docs/spec/`
- **系统架构**：`docs/architecture/`
- **数据映射与来源**：`docs/data/`
- **开发路线**：`docs/roadmap.md`
- **机器可读规则**：`rules/strict-v1.yaml`

# 设计原则

`turtle-value-engine` 尽量遵循：

```text
No fabrication
No silent defaults
No hidden LLM calculations
No future-data leakage
No untraceable adjustments
No silent rule changes
```

缺失的数据应该保持缺失。

无法确定的事项应该进入：

```text
WATCH
SPECIAL_REVIEW
NOT_EVALUATED
```

而不是由系统自动补出一个看似合理的数字。

# 当前状态

```text
Deterministic analysis engine
        ✅

Structured A/H data infrastructure
        ✅

Official filing / evidence infrastructure
        ✅

Provider preparation + filing-backed deterministic closure
        ✅

Accepted-adjustment → effective-facts integration
        ✅

LLM-assisted evidence analysis
        ✅

Business-quality agents / model-neutral runtime boundary
        ✅

Backtesting / calibration
        ✅

Production historical corpus / research archive
        ⏳（边界已实现；权威来源、许可与完整 A/H 覆盖待补）

Phase 5R-A acquisition/compiler
        ⚠️（A0–A5/A7 已实现；真实私有 A/H acceptance 待 live probe）

Watchlist / event-driven monitoring
        ⏳
```

项目仍处于快速开发阶段，接口和数据契约可能继续演进。

当前实现范围与下一阶段计划以 `docs/roadmap.md` 和仓库中的 active goal 文档为准。
