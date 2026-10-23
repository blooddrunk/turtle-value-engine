# 档案启用执行器操作手册（Phase 7-C4-A）

本手册描述 `tve evolution activate-profile` / `tve evolution rollback-activation`
两个离线命令的完整操作流程：预览（默认、只读）、显式应用（`--apply`）、
中断恢复与回滚。所有示例均可在本地按字面执行；测试与 CI 使用一次性
Ed25519 密钥与临时私有配置，**不需要也不应该使用真实所有者密钥**。

边界声明：执行器只修改**一个**文件——显式提供的私有项目配置
（如 `.tve-private/project.toml`）中的 `[profiles] default` 一个值。它不会
修改 `rules/`、发布清单、`config/project.example.toml`、监控状态、投研
历史工件，也不会触发任何网络请求、模型调用、监控回放或通知重发。

## 0. 前置条件

```bash
cd ~/research/turtle-value-engine
python -m pip install --user ".[provenance]"
```

工作目录建议放在仓库之外（执行器会拒绝仓库内的受保护目录）：

```text
~/tve-trust/trust-root/     信任根（注册表快照）
~/tve-trust/evidence/       证据束
~/tve-trust/decisions/      决策记录
~/tve-trust/activation/     执行器私有存储（日志/备份/回执/回滚）
~/tve-private/project.toml  私有项目配置（启用目标；含 [profiles] default）
```

前置条件与 `docs/operations/owner-provenance-walkthrough.md` 相同：需要
已完成密钥生成、`registry init`、决策签名、`record-decision --evidence-root`
（即存在一个有效的 `bundle.json` 与 `record.json`）。

## 1. 预览（默认，严格只读）

```bash
python -m turtle_value_engine evolution activate-profile \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json \
  --policy-exception ~/tve-trust/bundle/exception.json \
  --decision-record ~/tve-trust/decisions/record.json \
  --project-config ~/tve-private/project.toml \
  --trust-root ~/tve-trust/trust-root \
  --authority-evidence ~/tve-trust/evidence/<bundle_id>/bundle.json \
  --activation-root ~/tve-trust/activation
```

预期输出（JSON）关键字段：

| 字段 | 含义 |
| --- | --- |
| `preview_state` | `READY_FOR_APPLY`（可应用）或 `BLOCKED` |
| `plan_id` / `plan_state` | 新鲜派生的只读计划身份与状态 |
| `blockers` | 计划阻塞项与执行器阻塞项的并集（`plan_blockers` + `executor_blockers`） |
| `original_config_sha256` | 当前配置字节 SHA-256（应用时必须原样提供） |
| `prior_default_profile` / `proposed_config_sha256` | 变更前默认档案 / 变更后配置哈希 |
| `config_diff` | 精确统一 diff（只有 `default` 一行变化） |
| `before_image_path` / `receipt_path` | 计划中的备份与回执路径 |
| `rollback_command` | 完整、安全 shell 引用的逐字可用回滚命令（含空格路径） |
| `apply_command_hint` | 完整、安全 shell 引用的逐字可用应用命令（含你本次输入的全部参数与两个期望值；可直接复制执行） |

预览**不写入任何字节**（连 activation-root 都不会创建）。退出码：`0` =
READY；`1` = BLOCKED（载荷含阻塞项）；`2` = 输入不可用（路径/符号链接/
受保护目录等分类错误）。

存储布局约束（fail-closed）：`activation-root` 下的 `locks/`、`journal/`、
`receipts/`、`before-images/`、`rollbacks/` 任一子目录若是指向别处的
符号链接（`ACTIVATION_STORE_SYMLINK`）或非目录文件
（`ACTIVATION_STORE_NOT_DIRECTORY`），apply/rollback 会在**任何写入之前**
拒绝——锁文件、日志、备份、回执与回滚结果都不可能被引出私有存储之外。
预览保持只读语义，不因未使用的子目录布局而失败。

执行器级阻塞项（`executor_blockers`）中最重要的一类是
`EVIDENCE_RECORD_*`：**当前生效的决策记录必须与证据束内嵌的记录字节
完全一致**（同一 `decision_record_id` 且同一内容哈希）。2026-10-22 的
基线复现证明只读计划本身接受"同 id、不同内容哈希"的记录仍给出 READY
（签名仍绑定同一决策内容，因此不构成授权绕过），但作为**变更凭证**这
不够——执行器因此独立强制精确关联。

## 2. 应用（显式变更）

预览输出的 `apply_command_hint` 就是**完整的逐字命令**：它包含你本次
预览输入的全部参数（含空格路径的安全 shell 引用）加上
`--apply --expected-plan-id <preview.plan_id>
--expected-config-sha256 <preview.original_config_sha256>`。直接复制执行即可：

```bash
# 预览（第 1 节命令）输出的 JSON 中：
#   apply_command_hint = "tve evolution activate-profile --base-profile ... --apply ..."
# 逐字复制该字段值并执行（等价于：
python -m turtle_value_engine evolution activate-profile \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json \
  --policy-exception ~/tve-trust/bundle/exception.json \
  --decision-record ~/tve-trust/decisions/record.json \
  --project-config ~/tve-private/project.toml \
  --trust-root ~/tve-trust/trust-root \
  --authority-evidence ~/tve-trust/evidence/<bundle_id>/bundle.json \
  --activation-root ~/tve-trust/activation \
  --apply \
  --expected-plan-id <preview.plan_id> \
  --expected-config-sha256 <preview.original_config_sha256> \
)
```

预期：退出码 `0`，`status = "ACTIVATED"`，配置中 `default = "strict-v2"`
（该行注释与所有其他字节原样保留）。验证：

```bash
grep -n 'default = ' ~/tve-private/project.toml     # 只应看到 default = "strict-v2"
python -m turtle_value_engine config validate --input ~/tve-private/project.toml
sha256sum ~/tve-private/project.toml                # 等于 receipt.activated_config_sha256
cat ~/tve-trust/activation/receipts/<activation_id>.json
sha256sum ~/tve-trust/activation/before-images/<prior_sha>.toml
```

`before-images/<prior_config_sha256>.toml` 是启用前配置字节的**内容寻址
私有备份**（创建后不可变）；`journal/<activation_id>.json` 是意图日志；
`receipts/<activation_id>.json` 是确定性回执（绑定计划、决策记录、证据束、
信任根、前后配置哈希与回滚引用）。

写入顺序（崩溃一致性，真实边界）：意图日志 → 备份 → 同目录临时文件 +
fsync + CAS 复读 + 原子 `os.replace`（+ 目录 fsync）→ 回执。每次发布
（日志/备份/回执/回滚意图/回滚结果）都在 fsync 文件体**之后**同步 fsync
其父目录项（新建存储子目录时再 fsync 根目录项），使先于配置替换的发布
在目录项层面也是持久的；这是模拟中断与 fsync 调用序层面的证据，**不是**
物理掉电认证。配置替换本身是原子的；**回执/备份的发布不是跨文件事务**
——中断状态由下一次调用按名分类并确定性恢复（见第 4 节），本执行器不
承诺不可能的跨文件原子性。

## 3. 回滚（显式、字节精确）

```bash
python -m turtle_value_engine evolution rollback-activation \
  --receipt ~/tve-trust/activation/receipts/<activation_id>.json \
  --activation-root ~/tve-trust/activation
```

预期：退出码 `0`，`status = "ROLLED_BACK"`，配置字节恢复为
`receipt.prior_config_sha256` 的精确内容（`sha256sum` 必须一致）。重复
执行同一回滚命令 → `status = "ALREADY_RESTORED"`，零写入。

回滚的审计可恢复性：恢复配置**之前**先持久化不可变恢复意图
`rollbacks/<rollback_id>.intent.json`（绑定回执、配置路径与字节哈希），
恢复**之后**再 create-only 发布结果 `rollbacks/<rollback_id>.json`。若在
"配置已恢复、结果未发布"之间中断，重试同一回滚命令会从恢复意图确定性
补齐结果（`FINALIZED_AFTER_INTERRUPTED_RESTORE`，配置零变动）；若配置
已是 prior 字节但既无结果也无意图（例如所有者手工恢复了字节），回滚
如实报告 `ALREADY_RESTORED` 并**不伪造**审计结果。

回滚前置条件（全部 fail-closed）：回执可验证；当前配置哈希等于回执的
`activated_config_sha256`（或已经是 `prior_config_sha256` → 幂等
ALREADY_RESTORED）；备份存在且哈希一致。**任何中间改动**（哪怕是注释）
都会得到 `ROLLBACK_PRECONDITION_VIOLATED`（退出码 `1`），配置保持原样，
不会被覆盖——此时人工检查 `before-images/` 后自行处置。

回滚不回放已提交的监控运行、不重发通知、不改写历史投研工件（固定排除
项 `NO_AUTOMATIC_MONITORING_REPLAY` / `NO_AUTOMATIC_NOTIFICATION_REPLAY` /
`NO_HISTORICAL_ARTIFACT_REWRITE`），也不撤销启用期间已产生的分析决策。

## 4. 中断恢复（确定性）

执行器按可观察的磁盘状态分类，不需要人工猜测：

| 观察状态 | 含义 | 下一步 |
| --- | --- | --- |
| journal 存在；配置哈希 = `activated_config_sha256`；回执存在 | 已完成 | 再次 apply → `COMPLETED_ALREADY`（退出码 0，零写入） |
| journal 存在；配置哈希 = `activated_config_sha256`；回执缺失 | 替换后、回执发布前崩溃 | 再次 apply → `FINALIZED_AFTER_INTERRUPTED_REPLACE`（从日志确定性补写回执，配置零变动） |
| journal 存在；配置哈希 = `prior_config_sha256` | 替换前崩溃 | 再次同一 apply → `ACTIVATED_RESUMED`（从备份/日志幂等续作） |
| journal 存在；配置哈希两者皆非 | 日志之后配置被外部改动 | `ACTIVATION_CONFIG_DIVERGED`（退出码 1；备份保留，人工处置） |
| 另一未完成意图的日志与本次派生不同 | 意图冲突 | `ACTIVATION_INTENT_CONFLICT`（退出码 1；人工检查 journal/） |
| 配置哈希 = `prior_config_sha256`；`.intent.json` 存在、结果缺失 | 回滚恢复后、结果发布前崩溃 | 再次 rollback → `FINALIZED_AFTER_INTERRUPTED_RESTORE`（从恢复意图确定性补写结果，配置零变动） |
| 配置哈希 = `prior_config_sha256`；结果存在且有效 | 回滚已完成 | 再次 rollback → `ALREADY_RESTORED`（零写入；结果损坏 → `ROLLBACK_OUTCOME_CORRUPT` 退出码 2） |
| 配置哈希 = `prior_config_sha256`；结果与意图都不存在 | 无本回滚已运行的持久证据 | 再次 rollback → `ALREADY_RESTORED`（如实报告，不伪造结果） |
| 恢复意图被篡改/绑定不符 | 审计证据损坏 | `ROLLBACK_INTENT_CORRUPT` / `ROLLBACK_INTENT_MISMATCH`（退出码 2；不补写任何结果） |

## 5. 失败码速查

| 退出码 | status / code | 含义 |
| --- | --- | --- |
| 1 | `ACTIVATION_BLOCKED` + `blockers` | 新鲜计划非 READY（含 revoked 密钥 `OWNER_AUTHORITY_REVERIFICATION_*`、REJECT `DECISION_IS_REJECT`、冲突 `DECISIONS_CONFLICTING`、例外缺失/伪造 `DECISION_EXCEPTION_BINDING_STALE`、已为目标 `DEFAULT_ALREADY_TARGET`、证据关联 `EVIDENCE_RECORD_*` 等） |
| 1 | `PLAN_ID_MISMATCH` | 提供的 plan id 与新鲜派生不一致（重跑预览取新 id） |
| 1 | `ACTIVATION_CONFIG_UNSTABLE` | 预览后配置字节变化（含注释级变化） |
| 1 | `ACTIVATION_CONFIG_CHANGED_DURING_APPLY` | 应用临界区内检测到外部写入者；staged 写入已丢弃 |
| 1 | `ROLLBACK_PRECONDITION_VIOLATED` | 回滚前置条件不满足（配置已被中间改动） |
| 2 | `CONFIG_PATH_SYMLINK` / `CONFIG_PATH_PROTECTED` / `ACTIVATION_ROOT_PROTECTED` | 目标/存储路径为符号链接或解析进受保护仓库目录（模板、rules、发布清单、源码等） |
| 2 | `ACTIVATION_STORE_SYMLINK` / `ACTIVATION_STORE_NOT_DIRECTORY` / `ACTIVATION_STORE_ESCAPE` / `ACTIVATION_STORE_UNAVAILABLE` | activation-root 子目录（locks/journal/receipts/before-images/rollbacks）为符号链接、非目录或解析出根；任何写入之前拒绝 |
| 2 | `CONFIG_TOML_INVALID` / `CONFIG_PROFILES_TABLE_MISSING` / `CONFIG_DEFAULT_VALUE_UNSUPPORTED` / `CONFIG_DEFAULT_KEY_AMBIGUOUS` | 配置形态不可编辑（缺表、非单行字符串 default 等） |
| 2 | `RECEIPT_INVALID` / `RECEIPT_CORRUPT` / `BEFORE_IMAGE_HASH_MISMATCH` | 回执或备份不可验证 |
| 2 | `ROLLBACK_OUTCOME_CORRUPT` / `ROLLBACK_INTENT_CORRUPT` / `ROLLBACK_INTENT_MISMATCH` | 回滚结果/恢复意图损坏或绑定不符（不补写任何审计工件） |
| 3 | `ACTIVATION_BUSY` | 另一进程持有该配置的排他锁（flock）；零变更 |

并发语义：同一配置的 apply/rollback 由 `activation-root/locks/` 下的
非阻塞排他 flock 串行化；竞争者立即以退出码 3 结束且不做任何工作。
替换前的 CAS 复读捕获未持锁的外部写入者。

## 6. 完整自动化复现（工程师可重跑）

`tests/test_activation_execution.py`（48 项）用运行期生成的一次性
Ed25519 密钥端到端驱动真实 CLI：签名 → 捕获 → 严格加载 → 新鲜 READY
计划 → 预览（字节级只读证明）→ apply（注释保留、唯一值变更、回执/备份
哈希验证）→ `config validate` → 回滚（字节精确）→ 幂等重复；负矩阵覆盖
上述全部失败码、并发（双进程 0/3）、两个中断阶段的注入恢复、伪造记录/
证据束关联（基线复现的缺口）、篡改回执/备份、回滚后中间改动等。
`tests/test_activation_execution_r1_regressions.py`（24 项，C4-A-R1）在
原始 main 上以 21 红 / 3 绿复现了三类缺陷（子目录符号链接越界写入、
回滚结果中断后不可补齐、`...` 缩略的不可执行应用命令）及父目录 fsync
缺失，并在修复树上全绿；其中 3 项是本来就正确的只读预览/零写入语义的
保留性固定。每项均断言命名错误、退出码与失败时哈希不变。

## 7. 真实 strict-v2 启用（可选，所有者人工边界）

工程验收不需要以下任何步骤；真实启用是所有者本人的政策决策（CDC 14%
门槛高于 S 档 12% 的例外是否可接受），只能由真实签名决策授权：

1. 阅读 `tve evolution decision-dossier` 生成的决策材料（含 13% 行为对照）。
2. 独立做出 ACCEPT/REJECT 决策；按 `owner-provenance-walkthrough.md`
   用自己的密钥签名并 `record-decision --evidence-root` 记录。
3. 用**真实私有配置**路径运行第 1 节预览，核对 diff 只有一行、
   `plan_id`/`original_config_sha256` 与你看到的一致。
4. 逐字执行 `apply_command_hint`（含两个期望值）。
5. 事后核对：`config validate`、回执哈希、备份哈希；必要时执行第 3 节
   回滚命令。

若不接受，则到此为止：仓库默认保持 strict-v1，已发布的 strict-v2 仅作为
研究工件存在。
