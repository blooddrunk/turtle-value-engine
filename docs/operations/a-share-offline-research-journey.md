# A 股个人研究离线全流程操作手册（Issue #65）

本手册描述一条**完全离线、可复现**的 A 股个人研究操作路径：从冻结的
normalized input 出发，经确定性引擎产出分析、决策追踪与研究报告，再投影为
只读研究面（research surface），最后通过本地 API / Dashboard 查看。
全程只使用仓库现有 CLI，不需要编写任何 Python 胶水代码。

## 目的与边界

- 这是**个人研究可用性路径**，不构成投资建议，也不声称 Phase 5R/A6 的
  生产级历史语料覆盖（`production_eligible`）。历史数据状态在快照中始终
  显式为 `NOT_AVAILABLE`。
- 全程离线：`tve analyze`、`tve surface build|validate|serve` 不发起任何
  网络请求、不调用任何模型或 provider。
- 规则档案保持默认 `strict-v1`；本流程不激活 `strict-v2`，不产生任何
  owner 决策、签名或审批。
- 引擎对缺失的 Business Quality 证据**失败关闭**：未提供结构化评估时，
  该 gate 保持 `NOT_EVALUATED`，估值保持指示性，最终决策为
  `SPECIAL_REVIEW`/`WATCH` 等显式状态，不会因文字描述而变成通过。

## 前置条件

1. 克隆仓库并按 `README.md` Quick Start 安装（`pip install -e .`）。
2. **在仓库根目录执行命令**。`strict-v1` 等规则档案按
   `--rules-dir` → 当前目录 `rules/` → 仓库 `rules/` 的顺序解析；
   从其他目录运行且未安装为 editable 时，需显式传
   `--rules-dir <仓库>/rules`。
3. 不需要任何真实账户凭据、不需要外网。

## 第 0 步：选择标的与输入

最简单的离线入口是仓库自带的合成 A 股 normalized fixture（本手册以
`healthy_cash_cow.json`，标的 `SH600001` 为例；`fixtures/README.md`
列出了其余 7 个覆盖不同风险场景的 fixture）。

如需从 provider/cache 准备真实 A 股标的，参见 `README.md` 的
`tve prepare` 说明（首次获取需要网络）或下一节的离线重放入口；本手册
第 1 步起不依赖该步骤。

## 第 0B 步（可选）：从已有 raw cache 离线重放 prepare

适用场景：你已经对某个 A 股标的完成过一次在线 `tve prepare`（或等价地
持有一份该标的的 raw cache），之后希望全程离线复现研究。以下命令均不
发起任何网络请求；CI 中的
`tests/test_offline_journey_cli.py::test_cached_source_offline_replay_completes_the_surface_chain`
在 socket 全禁条件下证明了这一点。

前提（任一不满足都会失败关闭，退出码 2，且不写出任何输出文件）：

1. raw cache 中该标的的**六个默认类别全部存在**：`company_metadata`、
   `listing_metadata`、`market_quote`、`cash_flow_statement`、
   `income_statement`、`balance_sheet`（缺任何一个会报
   `no replayable cache entry for <sha256>`）。部分缓存（例如旧版本
   只抓过部分类别）不能重放，也不会静默补抓。
2. `--as-of` 不早于缓存信封的 `retrieved_at` 日期（更早会报
   `was retrieved on ..., after as_of ...`）。
3. 与首次运行一样显式提供公司上下文（`--name/--sector/
   --reporting-currency` 或 `--company-json`），准备层不会猜测。

**预检（推荐先执行）**：不必先尝试一次注定失败的重放来发现缓存问题。
`tve prepare --check-readiness` 是只读、零网络、零写入的缓存就绪诊断，
一次报告六个类别各自的状态（Issue #69）：

```bash
tve prepare 600519.SH \
  --as-of <打算重放的日期> \
  --provider akshare \
  --check-readiness \
  --cache-dir <与首次获取相同的 cache 目录>
```

- 退出码：`0` 全部就绪 / `1` 至少一个类别未就绪 / `2` 输入无效。
- 每个类别报告 `READY`（信封存在、身份可再推导、`retrieved_at` 不晚于
  `as_of`）、`MISSING`（当前身份下无信封，附 `expected_path` 与同目录
  下自描述的其他信封 `cache_candidates`）、`FUTURE_DATA`（信封晚于
  `as_of`，`detail` 给出可用日期）或 `CORRUPT`（身份/解析失败，附路径）。
- `earliest_replayable_as_of` 仅在全部必需类别信封完整且可读取时给出；它同时考虑 `retrieved_at` 与现有点时约束元数据，是原始缓存符合重放时间门槛的最小 `as_of`。任何类别 `MISSING` / `CORRUPT` 时为 `null`，不可将其解释为已经可重放。
- 该命令不使用也不接受 `--output`、`--allow-stale`、`--max-age-days`
  和公司上下文参数（它们与只读预检语义不符，会被拒绝）。
- 特别注意 `MISSING` 且 `cache_candidates` 非空的情况：适配器版本号
  （`provider_version`）参与缓存身份摘要，仓库升级后旧的完好信封会整体
  变为 `MISSING`，而 `cache_candidates` 会指出它们仍躺在同一目录下
  （由哪个版本写入）。此时需要用当前版本重新在线获取一次。

```bash
tve prepare 600519.SH \
  --as-of <与首次获取一致或更晚的日期> \
  --provider akshare \
  --offline \
  --cache-dir <与首次获取相同的 cache 目录> \
  --name "<公司名>" \
  --sector "<行业>" \
  --reporting-currency CNY \
  --output work/normalized.json
```

随后把第 1 步的 `--input fixtures/healthy_cash_cow.json` 换成
`--input work/normalized.json`，其余步骤（第 1–4 步）完全不变。

**校验点**：

- 溯源链：`normalized.json` 中每条 `evidence_index[].source.document_id`
  就是 raw cache 中对应信封文件的 sha256 文件名（`<cache-dir>/akshare/
  <category>/<sha256>.json`），可直接审计到源。
- 确定性：同一 cache 重复执行 `--offline` 重放，产出的
  `normalized.json` 逐字节一致；后续 `analyze`/`surface build` 亦然。
- 重放只读：`--offline` 重放不会改写 raw cache 中的任何信封。

**边界**：信封按设计只做文件级完整性（可解析、身份可再推导）校验，
不含 raw payload 内容摘要——自行手改信封内的行情数值不会被拦截。因
此 raw cache 应作为操作员受控输入保管，与本仓库其他受保护输入同等
对待。

## 第 0C 步（可选）：为宇宙门槛补齐带证据的时点上下文事实

适用场景：分析结果中 `gates.universe` 的 `UNIVERSE.LISTING_YEARS`、
`UNIVERSE.SPECIAL_TREATMENT` 或 `UNIVERSE.PARENT_EQUITY` 报
`... is missing at the analysis point-in-time period AS_OF_<日期>`，而
你作为操作员**持有可追溯、能证明该字段在分析日有效的证据**
（例如注明状态有效日及覆盖范围的权威记录，或明确披露该分析日权益
余额的独立文件），希望把这三个时点事实补进第 0B 步产出的
normalized input，而不是让宇宙门槛保持 `SPECIAL_REVIEW`。

这一步是纯手工证据工作。引擎永远不会把财年事实改标成时点事实，
也永远不会替你猜测缺失值；三条宇宙规则在上下文缺失时保持失败
关闭。补齐之后**只有宇宙门槛**可能变为 `PASS`，最终决策仍会因
Business Quality 未评估等原因保持 `SPECIAL_REVIEW`——这是预期
行为，不是流程错误。

### 三种机制的边界

- **provider 观测**（第 0B 步产物自带）：`listing_years` 只有当
  listing metadata 行带有上市日期时才在 `AS_OF_<as_of>` 期间产出；
  默认六类获取不含风控板类别，且即使获取，风控板 endpoint 也是正向
  成员快照，无法证明"非 ST"，因此 `special_treatment` 保持缺失；
  `parent_equity` 只以财年期间（如 `2025-12-31`）产出。重放财年
  数据不会补齐时点上下文。
- **手工补充的带证据事实**（本步骤）：直接向 normalized input 追加
  `AS_OF_<as_of>` 期间的事实及其证据条目。这是本仓库支持的唯一
  补齐途径，形状与 `fixtures/*.json` 中时点事实的登记方式一致。
- **已接受的调整（accepted adjustment）**：只能修改**已存在**的
  数值型源事实（`materialize_effective_input` 要求目标事实已在输入
  中存在），不能新增一个缺失期间的事实，也不覆盖布尔/枚举字段；
  它不是本场景的机制。

### 治理时点事实同理

`accounting_opinion` 与 `governance_risk_level` 也是只读取逐字符等于
`AS_OF_<as_of>` 标签的时点事实（Issue #81）。当这两条事实缺失或期间
标签写错时，`GOVERNANCE.ACCOUNTING_OPINION` / `GOVERNANCE.RISK_LEVEL`
会以 `... is missing at the analysis point-in-time period AS_OF_<日期>`
报告缺失——与三条 `UNIVERSE.*` 规则同一形状。补齐方式与上文完全一致：
按本步骤在 `AS_OF_<as_of>` 期间登记带证据的事实。已登记但显式为
`null` 的事实保持原有的一般性措辞（`unavailable or unresolved` /
`is missing`），以区分"根本没有该期间事实"与"显式未知"。

### 净现金覆盖分母时点事实同理

`debt_due_within_one_year`（一年内到期债务，压力/流动性覆盖比率的分母）
同样是只读取逐字符等于 `AS_OF_<as_of>` 标签的时点事实（Issue #83）。
当该事实缺失或期间标签写错时，`NET_CASH.STRESS_COVERAGE` /
`NET_CASH.LIQUIDITY_COVERAGE` 会以
`... is unavailable: debt_due_within_one_year is missing at the analysis
point-in-time period AS_OF_<日期>.` 报告缺失并附带
`DEBT_DUE_WITHIN_ONE_YEAR_MISSING` 标志——与 `UNIVERSE.*` /
`GOVERNANCE.*` 缺失消息同一形状。补齐方式一致：在 `AS_OF_<as_of>`
期间登记带证据的事实。已登记但显式为 `null` 的事实、以及覆盖比率因
受限现金真实性未决（`owner_accessible_cash` 为空，如
`cash_rich_dying_business` 场景）而不可得的情况，都保持原有的一般性
措辞 `... is unavailable.`——后者需要真实的人证证据而不是机械补数，
两类原因因此保持可区分。

### 操作步骤

1. 复制 `work/normalized.json` 为 `work/normalized-context.json`。
   永远不要改写 raw cache；保留原始文件便于对照审计（两个输入的
   `analysis_id` 相同，靠内容哈希区分）。
2. 在 `evidence_index` 数组末尾为每个待补字段追加**至少一条**证据
   条目，在 `facts` 数组末尾追加对应事实条目。三条事实的 `period`
   必须**逐字符等于** `AS_OF_<as_of>`（`as_of` 用输入自身的
   `as_of` 字段值，不是当天日期）。
3. 用 `--input work/normalized-context.json` 重新执行第 1 步。

证据与事实条目的最小形状（完整字段见 `schemas/evidence.schema.json`
与 `schemas/normalized-input.schema.json`；`id` 在 `facts` 与
`evidence_index` 各自列表内必须唯一）：

```json
{
  "evidence_index": [
    {
      "id": "evidence-context-equity-0001",
      "direction": "SUPPORT",
      "strength": "E3",
      "statement": "合成示例：假设独立文件明确证明归母权益在 2026-09-12 为 7,250,000,000 元；这不是实际上市公司披露。",
      "source": {
        "type": "COMPANY_ANNOUNCEMENT",
        "title": "<公司> 分析日权益时点证明（合成示例）",
        "published_date": "2026-09-12",
        "document_id": "<你留存的真实文件标识>",
        "locator": "<能够定位到该时点权益的段落或表格>"
      },
      "confidence": 0.95
    }
  ],
  "facts": [
    {
      "id": "fact-context-parent-equity-0001",
      "field": "parent_equity",
      "value": 7250000000,
      "unit": "reported_currency_amount",
      "currency": "CNY",
      "period": "AS_OF_2026-09-12",
      "source_evidence_ids": ["evidence-context-equity-0001"],
      "confidence": 0.95
    }
  ]
}
```

以上 JSON 是**合成形状示例**，不是 SH600000 或任何真实公司的
权益披露，也不能把示例数值直接填入生产研究输入。若没有独立证据能
证明权益**在分析日这个时点**的数值，应保留缺失和 `SPECIAL_REVIEW`；
财报在分析日前公开只证明其信息当时可知，并不改变其原始报告期。

### 诚实性责任（引擎无法代劳）

- `parent_equity` 必须由**明确以分析日为有效日期**的独立观测支持。
  季报、半年报或年报即使在分析日前发布，通常也只报告其原始期末权益；
  **禁止**将季度末、半年末或 `2025-12-31` 等财年值改标为分析日
  时点值来满足门槛。若仅有这种报告则保持缺失。引擎不会自动
  审查有效日期或识别改标；事实 → 证据 → 来源的真实性属于操作员责任。
- 每条证据的 `source.published_date` **不得**晚于 `as_of`。`tve analyze`
  会在分析边界对整份输入失败关闭（退出码 2，不写出任何输出文件，
  错误消息点名每条违规证据）：出版日期晚于分析日的来源是机器可证明的
  未来数据泄漏，不可能在分析日可知。`published_date` 缺失（`null`）
  表示日期未知，保持未知、不会被猜测，也不会因此被拒绝；来源日期
  是否真实仍属操作员责任。同理，任何事实的 `period` 标签内嵌的日期
  （含 `AS_OF_` 前缀标签）晚于 `as_of` 时同样失败关闭。
- `special_treatment=false` 的证据必须能支撑"分析日当天不是 ST/*ST"
  （状态有效日期、权威来源、全量覆盖范围）。仅凭正向成员快照中
  **查不到该股票**，又不能证明快照完整性和时点有效性时，不得反推
  `false`；保持缺失。
- `listing_years` 由上市日期推导：`(as_of - 上市日期).days / 365.25`，
  证据条目应注明上市日期及其来源文件。

### 预期结果与失败关闭行为

- 成功：三条 `UNIVERSE.*` 规则变为 `PASS`，各规则的 `evidence_ids`
  指向你登记的证据；`decision.state` 仍为 `SPECIAL_REVIEW`（只要
  Business Quality 未评估或其他 gate 未通过）；重复执行
  `tve analyze` 输出逐字节一致。
- 失败关闭（退出码 2，不写出任何输出文件）：同字段同期间出现重复
  事实、`source_evidence_ids` 引用不存在的证据 ID、标量类型错误
  （如 `special_treatment` 给字符串、`listing_years` 给字符串）、
  证据 `published_date` 晚于 `as_of`、事实 `period` 内嵌日期晚于
  `as_of`。
- 静默忽略（不报错但**不生效**，宇宙规则按 `AS_OF_<as_of>` 查找并
  继续报缺失）：`period` 写错（如写成 `2026-09-12`、别的**不晚于
  分析日**的日期或别的标签）的事实。时点类规则（宇宙/治理/商业质量
  硬规则）**只读取逐字符等于 `AS_OF_<as_of>` 的标签**：即使输入中
  只有这一个别的 `AS_OF_` 期间标签（例如整体早一天的
  `AS_OF_<as_of 前一天>`，或带上市后缀的附加上市标签），引擎也不会
  把它当作分析日上下文——昨日语境不会被静默当作今日事实。CDC 产出的
  `cdc_yield` 所用的现价市值（`current_market_cap`/
  `listing_equivalent_market_cap`）同样**只读取逐字符等于
  `AS_OF_<as_of>` 的标签**：市值标签写错时 CDC 产量按缺失处理
  （`CDC.YIELD` 为 `SPECIAL_REVIEW`），不会借用别的期间的市值。
  持有"该
  观测在分析日仍然有效"证据的操作员，应按本步骤把事实登记在
  `AS_OF_<as_of>` 期间并附上该证据。请核对缺失消息中点名的期间与
  你的 `period` 逐字符一致；晚于分析日的日期标签不属于静默忽略，
  而是上一条的失败关闭。

## 第 1 步：确定性分析并产出三类工件

```bash
tve analyze \
  --input fixtures/healthy_cash_cow.json \
  --profile strict-v1 \
  --output work/analysis.json \
  --trace-output work/decision-trace.json \
  --report-output work/research-report.json
```

- `--output`：`CompanyAnalysis` JSON（`company_analysis_v1`）。
- `--trace-output`：确定性决策追踪（`decision_trace_v1`，Decision →
  Gate → Metric → Fact → Evidence → Filing 链条）。
- `--report-output`：人类可读研究报告（`research_report_v1`，内嵌分析与
  追踪并带内容哈希绑定）。

三个参数都是可选的；只显式请求的文件才会写入。不传任何输出参数时行为与
旧版本完全一致（stdout 打印 JSON，可用 shell 重定向保存）。命令仍会向
stdout 打印完整 `CompanyAnalysis`。

**校验点**：三个文件中的 `analysis_id` 一致；`research-report.json` 的
`analysis_sha256` 与 `analysis.json` 内容绑定（引擎自动计算）。

## 第 2 步：投影为只读研究面快照

```bash
tve surface build \
  --analysis work/analysis.json \
  --trace work/decision-trace.json \
  --report work/research-report.json \
  --output work/snapshot.json
```

产出 `research_surface_snapshot_v1`。引擎会重新校验 trace/report 与
analysis 的身份和内容一致性（不一致即失败关闭），并把两者登记为
`decision_trace_reference` / `research_report_reference`。

**校验点**：`surface_id == content_sha256`；两个 reference 字段非空；
重复执行产出逐字节相同的快照（确定性）。

## 第 3 步：验证快照

```bash
tve surface validate --input work/snapshot.json
```

退出码 0 即通过 schema 与内容校验。

## 第 4 步：本地只读查看

```bash
tve surface serve --snapshot work/snapshot.json --host 127.0.0.1 --port 8787
```

另开终端检查：

```bash
curl -s http://127.0.0.1:8787/healthz
curl -s http://127.0.0.1:8787/v1/surfaces
# 将下面的值替换为 /v1/surfaces 响应或 work/snapshot.json 中的真实 surface_id
SURFACE_ID='paste-actual-surface-id-here'
curl -fsS "http://127.0.0.1:8787/v1/surfaces/${SURFACE_ID}" | head -c 400
```

所有 mutation 方法（POST/PUT/PATCH/DELETE）返回 405。Dashboard 本地
预览（`apps/dashboard`，Vite 构建后经同源 Worker 代理）参见
`docs/architecture/agent-api-web-surface.md` 与
`scripts/dashboard_cross_stack_smoke.py`（CI 中的跨栈冒烟）。

## 结果解读

- `decision.state` 为 `SPECIAL_REVIEW`：确定性引擎要求人工复核，未给出
  自动投资结论——这是 fixture 未附结构化 Business Quality 评估时的
  预期状态，不是流程错误。
- `business_quality` 为 `NOT_EVALUATED`、估值标记
  `NON_PRICE_GATES_UNRESOLVED`：与上一条同因。
- universe 门槛报 `... is missing at the analysis point-in-time period
  AS_OF_<日期>`（如 `Parent equity is missing at ... AS_OF_2026-09-12.`）：
  引擎的时点类检查只读取**分析日时点事实**（`AS_OF_<as_of>` 期间的事实），
  不用年报期间的事实代替。第 0B 步的 provider 归一化输入只带
  `2024-12-31`/`2025-12-31` 这类**财年期间**事实（报告的 facts 列表里
  `parent_equity` 因此有值），缺少时点上下文事实，所以这些原因是
  预期的失败关闭行为，**不是数据丢失或引擎缺陷**。要解除该原因，
  需要为 `AS_OF_<as_of>` 期间补充带证据的时点事实（操作步骤与
  诚实性责任见第 0C 步；`fixtures/healthy_cash_cow.json` 中
  `listing_years`、`parent_equity`、`special_treatment` 都登记在其
  `AS_OF_` 期间，可作为形状参考），而不是重新抓取财年数据。
- 快照的 `historical_status.claim_state == "NOT_AVAILABLE"`：个人研究
  路径不携带历史语料声明。

## 常见问题

- **`tve: rule profile not found`**：不在仓库根目录运行且非 editable
  安装。回到仓库根目录，或传 `--rules-dir` 指向仓库 `rules/`。
- **`decision trace content does not match analysis`**：trace/report 与
  analysis 不是同一次 `tve analyze` 产出，或工件被手工改动。请用同一组
  输出重新执行第 1 步。注意 `tve analyze --output` 保存的 analysis 保持
  构造键序（与 `tve prepare --output` 相同），请勿用排序类工具重排后再
  喂给 `tve surface build`。
- **端口占用**：`tve surface serve` 换一个 `--port`。

## 本流程明确不做什么

- 不访问真实账户凭据、不联网、不调用模型；
- 不改变 `strict-v1` 默认档案、不激活 `strict-v2`、不合成 owner 决策；
- 不声称生产级历史语料能力（见 Phase 5R/A6 状态）；
- 不触发任何 mutation 面（API/Dashboard 均为只读）。
