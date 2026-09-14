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
```

系统会保留：

- filing identity
- official source
- document hash
- page / section locator
- evidence identity
- adjustment provenance

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

Provider、filing 和 evidence 基础设施已经存在，但完整的真实公司端到端工作流仍在收口中。

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

项目未来允许 LLM 协助：

- 阅读财报
- 查找 restricted cash
- 分析租赁与利息分类
- 理解收购与处置
- 分析分红政策
- 查找治理风险
- 分析客户集中度
- 收集 Business Quality 证据

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

End-to-end real-company workflow
        🚧

Accepted-adjustment → effective-facts integration
        🚧

LLM-assisted evidence analysis
        🚧

Business-quality agents / ChatGPT Skill
        ⏳

Backtesting / calibration
        ⏳

Watchlist / event-driven monitoring
        ⏳
```

项目仍处于快速开发阶段，接口和数据契约可能继续演进。

当前实现范围与下一阶段计划以 `docs/roadmap.md` 和仓库中的 active goal 文档为准。
