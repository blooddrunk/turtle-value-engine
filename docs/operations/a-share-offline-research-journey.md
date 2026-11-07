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
