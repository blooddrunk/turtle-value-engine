# Issue #67 — A 股 cached-source → 离线研究面操作员旅程收口（2026-11-07）

Status: implemented; PR pending exact-head CI. PR #66（本 Issue 的前置依赖）
已由所有者于 2026-11-07T10:10:35Z 合并（merge commit
`6605a742fb961afd27aba4db6e1f8fb91c515d4e`），合并前其最终 head
`24332616cde1b093496b6e5980e519fe228f4200` 已有成功 Actions run
`42361700014`。

## Baseline

- Baseline `main` SHA: `6605a742fb961afd27aba4db6e1f8fb91c515d4e`
  （fast-forward 同步；工作树干净）。
- Phase 7 维持 stop-and-wait；未制造任何 owner 决策、签名或激活。

## Gate A — journey reproduction（先检查后编辑）

受控 raw cache 用仓库冻结 provider fixtures（注入 `FrozenAKShare`，
纯本地文件读取）按生产代码唯一写法（live `prepare` → 六个信封）构造，
模拟"操作员已有一次在线获取产物"的真实状态。随后**全部命令在
`unshare -rn` 内核级网络命名空间隔离下**用未打补丁的真实 CLI 执行
（标的 `600000.SH`，`--as-of 2026-09-12`，`strict-v1`）：

| Step | Command | Result（baseline 实测） |
| --- | --- | --- |
| prepare --offline | `tve prepare 600000.SH --as-of 2026-09-12 --offline --name … --sector … --reporting-currency CNY --cache-dir … --output normalized.json` | exit 0；21 facts / 6 evidence；每条 `evidence.source.document_id` == 对应 raw-cache 信封文件名（sha256） |
| analyze | `tve analyze --input normalized.json --profile strict-v1 --output … --trace-output … --report-output …` | exit 0；`SPECIAL_REVIEW`（预期的失败关闭状态）；三工件 `analysis_id` 关联 |
| surface build | `tve surface build --analysis … --trace … --report … --output snapshot.json` | exit 0；`surface_id == content_sha256`；两个 reference 非空 |
| surface validate | `tve surface validate --input snapshot.json` | exit 0 |
| surface serve | `--port 8787` + `/healthz`、`/v1/surfaces`、`GET {id}=200`、`POST {id}=405` | 全部通过（netns 内仅 lo） |
| 确定性 | 重复 prepare --offline 与 analyze 三工件 | 全部逐字节一致 |
| fail-closed：缺类别 | 删除 `market_quote` 信封后重放 | exit 2 `no replayable cache entry for 1bf04684…`；零输出文件 |
| fail-closed：as_of 过早 | `--as-of 2026-09-11`（< retrieved_at） | exit 2 `was retrieved on 2026-09-12, after as_of 2026-09-11`；零输出 |
| fail-closed：身份篡改 | 改信封 `request.entity_id` | exit 2 `cache entry identity does not match requested key` |

结论：**功能路径已存在且完全离线可用**。复现的实质性缺口是"缺失的
操作员步骤"而非引擎缺陷：

1. Issue #65 runbook 第 0 步把 provider/cache 入口显式委托给 README，
   但 README 仅有一句"重复执行时可以使用 `--offline` 从 raw cache
   replay"——没有任何文档记录完成该入口到第 1–4 步所需的真实约束
   （六个默认类别必须齐全否则 `CacheMissError`；`--as-of` 不得早于
   缓存 `retrieved_at`；重放同样需要显式公司上下文；
   `document_id`==信封摘要的溯源审计链）。现实中极易触发：本机
   `.tve-private/provider-cache` 中的真实 HK00288 缓存即为 5/6 类别的
   部分缓存，重放必然失败关闭。
2. 该链式 CLI 旅程在既有套件中两半各自被证明、从未连成一条：
   `tests/test_phase_2_3_closure.py` 证明 prepare CLI 重放（注入
   failing provider），`tests/test_offline_journey_cli.py` 证明
   fixture → analyze → surface；没有任何测试证明 raw cache →
   prepare --offline → analyze 三工件 → surface，也没有 socket-guard
   覆盖 prepare。

## Gate B — smallest coherent change（无生产代码改动）

1. `docs/operations/a-share-offline-research-journey.md` 新增中文
   **第 0B 步（可选）：从已有 raw cache 离线重放 prepare**：适用场景、
   三条失败关闭前提（含真实报错原文）、与 Gate A 逐字一致的命令、
   溯源/确定性/只读校验点，以及信封不含 raw payload 内容摘要的显式
   边界说明。
2. `README.md` prepare 段落补齐约束摘要（六类别齐全、as_of 不早于
   缓存获取日期、否则失败关闭）并指向 runbook 第 0B 步。
3. `tests/test_offline_journey_cli.py` 新增两个聚焦测试（复用
   `FrozenAKShare`、`_deny_network` socket-guard 与冻结 fixtures）：
   - `test_cached_source_offline_replay_completes_the_surface_chain`：
     以生产代码唯一写法构造受控 cache 后，**不注入 provider** 直接跑
     真实 `tve prepare --offline` CLI（socket 全禁即证明重放零网络、
     零 akshare import），断言溯源 `document_id` 集合 == 信封摘要集合、
     cache 只读不变、prepare 重放逐字节一致，再接 analyze 三工件与
     surface build/validate 链。
   - `test_cached_source_offline_replay_fails_closed_on_missing_category`：
     部分缓存（删 `market_quote`）→ exit 2、stderr 点名类别与摘要、
     零输出副作用、cache 不变。
   两个测试在 baseline 上即为 GREEN：本 Issue 修复的是缺失的操作员
   说明与未覆盖旅程（Gate B 规则"repairing behavior 才要求 RED-first；
   既有套件已证明的行为不加测试"），不改变任何引擎行为。

## Verification

- `python -m ruff check .` — clean。
- 聚焦：`tests/test_offline_journey_cli.py` — 7 passed（含 2 新增）。
- 全量：`python -m pytest -n auto --dist loadgroup` —
  **7802 passed / 2 skipped**（7804 collected；baseline 6605a742 为
  7802 collected / 7800 passed，净增即 2 个新测试）。
- `python -m turtle_value_engine config validate --input
  config/project.example.toml` — valid，`default_profile: strict-v1`。
- 受保护工件与 baseline 字节一致（sha256 前 16 hex）：
  `rules/strict-v1.yaml` `e3618f78b2f8e4d1`、`rules/strict-v2.yaml`
  `adba44b799fdb42a`、`docs/releases/strict-v2/release-candidate.json`
  `604226f405fe0330`、`config/project.example.toml` `9c621217285ade01`、
  `config/monitoring-runner.example.json` `c81008c9886326ae`。
- surface/OpenAPI/Dashboard/cross-stack smoke 未受影响（未触碰任何
  surface/API/Dashboard 代码），按 Issue 规则未重复执行。

## Changed files

- `tests/test_offline_journey_cli.py` — 链式旅程覆盖 +2 测试。
- `docs/operations/a-share-offline-research-journey.md` — 第 0B 步。
- `README.md` — prepare 约束摘要与 runbook 指针。
- `docs/status/issue-67-cached-source-journey-2026-11-07.md` — 本记录。

## Residual risks / non-claims

- 信封按设计只做文件级完整性（可解析、身份可再推导）校验，不含 raw
  payload 内容摘要：手改信封内数值不会被拦截（Gate A 探针实测
  `current_price` 被改为 1.23 后 exit 0 重放）。这是
  `docs/architecture/provider-and-cache.md` §9 既定政策，本 Issue 未
  改变；raw cache 属操作员受控输入。
- 不声称 Phase 5R/A6 `production_eligible`；快照
  `historical_status.claim_state` 仍为 `NOT_AVAILABLE`。
- `strict-v2` 保持已发布但非默认、未应用；无任何 owner 决策被制造。
- 首次在线获取（写 cache 的那一次）仍需网络，不在本 Issue 范围。
- 无 H 股扩展、provider 端点扫描、brokerage/trading、部署变更。

## Human-only boundary

无。真实私有标的的在线获取、strict-v2 owner 决策与任何生产部署仍在本
Issue 之外；它们不阻塞本里程碑。
