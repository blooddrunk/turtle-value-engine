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
`tve prepare` 说明（首次获取需要网络，之后可用 `--offline` 从本地 raw
cache 重放；本手册不依赖该步骤）。

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
curl -s http://127.0.0.1:8787/v1/surfaces/<surface_id> | head -c 400
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
