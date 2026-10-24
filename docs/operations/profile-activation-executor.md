# 档案启用执行器操作手册（Phase 7-C4-A）

本手册描述 `tve evolution activate-profile` / `tve evolution rollback-activation`
两个离线命令的完整操作流程：预览（默认、只读）、显式应用（`--apply`）、
中断恢复与回滚，以及第 4 节的只读状态检查命令
`tve evolution activation-status`（Phase 7-C4-B）。所有示例均可在本地按字面
执行；测试与 CI 使用一次性 Ed25519 密钥与临时私有配置，**不需要也不应该
使用真实所有者密钥**。

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

最终锁条目约束（C4-A-R2 F2 / C4-A-R3 F2，fail-closed）：即便 `locks/`
目录本身合法，预先存在的 `locks/<digest>.lock` 若是指向外部文件的符号链接
（`ACTIVATION_LOCK_SYMLINK`）、任何非常规文件（FIFO 等，
`ACTIVATION_LOCK_NOT_REGULAR`），或具有**多个目录硬链接**的常规文件
（`ACTIVATION_LOCK_HARDLINK`，即 `st_nlink != 1`——外部普通文件通过
`os.link` 植入/反向链接后与锁共享同一 inode，会把执行器的互斥绑定到存储
外可达、可被外部 flock 的 inode 上），apply/rollback 都会在**打开或加锁
任何 inode 之前**按名拒绝——锁永远绑定存储内**单链接**的常规文件 inode，
外部文件既不会被打开也不会被加锁，敌意条目及其外部孪生链接不会被删除或
改写（不存在"删除陈旧锁恢复"流程）。`O_NOFOLLOW` 语义在 Linux/POSIX
（CI 主机）生效；缺少该标志的平台由打开后的 `fstat` 常规文件校验兜底。
`ACTIVATION_BUSY`（退出码 3）只表示存储内真实锁的 flock 竞争。

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

执行边界授权新鲜度（C4-A-R2 F1 + C4-A-R3 F1，fail-closed）：CLI 在取锁
**之前**准备签名证据、信任根快照、授权验证器以及全部预加载命名输入文件
（决策记录、未签名撤销、政策例外、边界输入、签名生命周期声明）；apply 在
锁内于两个锚点重新校验这些 on-disk 权威来源仍是准备时的同一状态——第一个
锚点在本次尝试的首次持久写入之前，第二个锚点在受保护的配置替换
（`os.replace`）之前。若最新信任根快照已被取代
（`AUTHORITY_TRUST_ROOT_SUPERSEDED`，含密钥撤销/轮换/新登记）、不可读
（`AUTHORITY_TRUST_ROOT_UNREADABLE`）、证据束已变化
（`AUTHORITY_EVIDENCE_CHANGED` / `AUTHORITY_EVIDENCE_UNREADABLE`），或
**任一实际提供的预加载命名输入文件**在准备之后被替换/删除
（`AUTHORITY_INPUT_CHANGED:<label>` / `AUTHORITY_INPUT_UNREADABLE:<label>`，
`<label>` 形如 `policy-exception[0]`、`decision-record[0]`、`boundary-input`），
apply 以 `ACTIVATION_AUTHORITY_STALE`（退出码 1）命名拒绝，**配置不被
替换**；被拒尝试已写入的意图日志/备份属于不可变审计历史，保留不删。
明确边界：该校验只在锚点时刻观察权威状态，**不承诺跨文件/跨进程全局
原子性**——锚点之后至 `os.replace` 之前落地的变更超出单机执行器在无
全局原子性前提下可防御的范围。库调用方显式传入内存 verifier/信任根
对象的既有契约不变（缺省不注入该校验）；回滚不消耗新的签名所有者
决策，因此不做该校验（但受益于同一加固的锁条目约束）。

写入顺序（崩溃一致性，真实边界）：意图日志 → 备份 → 同目录临时文件 +
fsync + CAS 复读 + 原子 `os.replace`（+ 目录 fsync）→ 回执。每次发布
（日志/备份/回执/回滚意图/回滚结果）都在 fsync 文件体**之后**同步 fsync
其父目录项（新建存储子目录时再 fsync 根目录项），使先于配置替换的发布
在目录项层面也是持久的；这是模拟中断与 fsync 调用序层面的证据，**不是**
物理掉电认证。配置替换本身是原子的；**回执/备份的发布不是跨文件事务**
——中断状态由下一次调用按名分类并确定性恢复（见第 5 节），本执行器不
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

## 4. 只读状态检查（Phase 7-C4-B：`activation-status`）

在执行任何操作（尤其是重试一次中断的 apply/rollback）之前，先用一条
命令看清当前状态：

```bash
python -m turtle_value_engine evolution activation-status \
  --activation-root ~/tve-trust/activation \
  --project-config ~/tve-private/project.toml
```

该命令**严格只读**：不创建目录、不加锁、不修复、不写任何文件（因此
没有 `--output`），不发任何网络请求，也不会代替你执行激活或回滚。重复
执行输出逐字节一致。可选 `--receipt <回执路径>` 附加检查某一份回执文件
本身（有效性、是否绑定本配置、日志/备份/回滚工件是否存在），它不改变
整体状态判定。

输出 JSON 顶层的 `status` 就是稳定状态码：

| status | 退出码 | 含义 | 下一步 |
| --- | --- | --- | --- |
| `NO_HISTORY` | 0 | 该配置在本存储中没有任何激活/回滚历史 | 无需处理；需要启用时先跑第 1 节预览 |
| `ACTIVATED_VERIFIED` | 0 | 回执、日志、备份全部有效，当前配置字节等于激活后哈希 | 如需恢复，执行回执绑定的回滚命令 |
| `ROLLED_BACK_VERIFIED` | 0 | 回滚已完成并经字节验证（回滚结果有效） | 无需处理 |
| `RECEIPT_FINALIZATION_PENDING` | 1 | 配置已替换，但回执尚未发布（应用在替换后中断） | 重新执行同一 apply 命令补写回执；不会再次改配置 |
| `APPLY_RESUMABLE` | 1 | 存在未完成意图，配置仍是激活前字节（应用在替换前中断） | 可重新执行同一 apply；成功仍要求授权链当前有效 |
| `ROLLBACK_FINALIZATION_PENDING` | 1 | 配置已恢复、回滚意图存在，但回滚结果未发布（回滚在恢复后中断） | 重新执行同一 rollback 命令补写结果；不会再次改配置 |
| `CONFIG_DIVERGED` | 1 | 当前配置字节与存储可证明的任何状态都不一致（可能被手工修改） | 人工比对 `before-images/` 备份后自行决定；命令不修复 |
| `AMBIGUOUS_HISTORY` | 1 | 存在多份未完成激活意图，无法判断哪份代表当前意图 | 人工检查 `journal/`；执行器会拒绝进一步激活直至澄清 |
| `CORRUPT_OR_UNVERIFIABLE` | 1 | 存在损坏/被篡改/越界/无法验证的工件（见 `problems` 列表） | 按 `problems` 逐项人工处理；命令不修复 |

`problems` 列表给出具体损坏条目（如 `BEFORE_IMAGE_HASH_MISMATCH:<文件>`、
`RECEIPT_CORRUPT:<文件>`、`JOURNAL_FILE_SYMLINK:<文件>`、
`ACTIVATION_ROOT_FOREIGN_ENTRY:<名字>`）；`observations` 列表给出额外事实
（如 `RESTORED_WITHOUT_DURABLE_PROOF`＝字节等于激活前但无回滚证据、
`STALE_ROLLBACK_OUTCOME_PRESENT`＝回滚后字节又被重新激活、
`UNRELATED_HISTORIES_PRESENT`＝存储里有其他配置的历史——它们不会被算作
本配置的状态）；`guidance_zh` 是中文下一步建议；`focal` 是判定所依据的那
次激活的已验证身份（activation_id、前后哈希与默认策略、回执/日志/备份/
回滚工件存在性）。

边界（重要）：

- **历史回执不证明当前所有者同意。** `owner_authority_revalidated` 恒为
  `false`：状态检查不重新验证签名授权、不重新派生计划。要知道"现在是否
  仍获授权"，请重跑第 1 节预览。
- **单遍读取，无全局原子快照。** `global_atomic_snapshot_claimed` 恒为
  `false`：并发 apply/rollback 可能改变读取间隙中的字节。
- 输入不可用（activation-root/存储子目录为符号链接或非目录、配置缺失/
  符号链接/在受保护仓库目录内、`--receipt` 文件非法）是退出码 `2` 的分类
  错误，与上表的状态判定（退出码 0/1）分开。
- `locks/` 中遗留的锁文件不影响判定（锁是运行状态，不是历史）。

## 5. 中断恢复（确定性）

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

## 6. 失败码速查

| 退出码 | status / code | 含义 |
| --- | --- | --- |
| 1 | `ACTIVATION_BLOCKED` + `blockers` | 新鲜计划非 READY（含 revoked 密钥 `OWNER_AUTHORITY_REVERIFICATION_*`、REJECT `DECISION_IS_REJECT`、冲突 `DECISIONS_CONFLICTING`、例外缺失/伪造 `DECISION_EXCEPTION_BINDING_STALE`、已为目标 `DEFAULT_ALREADY_TARGET`、证据关联 `EVIDENCE_RECORD_*` 等） |
| 1 | `PLAN_ID_MISMATCH` | 提供的 plan id 与新鲜派生不一致（重跑预览取新 id） |
| 1 | `ACTIVATION_CONFIG_UNSTABLE` | 预览后配置字节变化（含注释级变化） |
| 1 | `ACTIVATION_CONFIG_CHANGED_DURING_APPLY` | 应用临界区内检测到外部写入者；staged 写入已丢弃 |
| 1 | `ACTIVATION_AUTHORITY_STALE` + `blockers` | 执行边界权威新鲜度校验失败：信任根快照被取代/不可读（`AUTHORITY_TRUST_ROOT_SUPERSEDED` / `AUTHORITY_TRUST_ROOT_UNREADABLE`）、证据束变化/不可读（`AUTHORITY_EVIDENCE_CHANGED` / `AUTHORITY_EVIDENCE_UNREADABLE`）或预加载命名输入文件被替换/不可读（`AUTHORITY_INPUT_CHANGED:<label>` / `AUTHORITY_INPUT_UNREADABLE:<label>`）；配置不被替换 |
| 1 | `ROLLBACK_PRECONDITION_VIOLATED` | 回滚前置条件不满足（配置已被中间改动） |
| 2 | `CONFIG_PATH_SYMLINK` / `CONFIG_PATH_PROTECTED` / `ACTIVATION_ROOT_PROTECTED` | 目标/存储路径为符号链接或解析进受保护仓库目录（模板、rules、发布清单、源码等） |
| 2 | `ACTIVATION_STORE_SYMLINK` / `ACTIVATION_STORE_NOT_DIRECTORY` / `ACTIVATION_STORE_ESCAPE` / `ACTIVATION_STORE_UNAVAILABLE` | activation-root 子目录（locks/journal/receipts/before-images/rollbacks）为符号链接、非目录或解析出根；任何写入之前拒绝 |
| 2 | `ACTIVATION_LOCK_SYMLINK` / `ACTIVATION_LOCK_NOT_REGULAR` / `ACTIVATION_LOCK_HARDLINK` | 最终锁条目 `locks/<digest>.lock` 为符号链接、非常规文件或具有多个目录硬链接（`st_nlink != 1`，外部 inode 可达）；打开/加锁任何 inode 之前按名拒绝，外部目标与敌意条目不被触碰 |
| 2 | `CONFIG_TOML_INVALID` / `CONFIG_PROFILES_TABLE_MISSING` / `CONFIG_DEFAULT_VALUE_UNSUPPORTED` / `CONFIG_DEFAULT_KEY_AMBIGUOUS` | 配置形态不可编辑（缺表、非单行字符串 default 等） |
| 2 | `RECEIPT_INVALID` / `RECEIPT_CORRUPT` / `BEFORE_IMAGE_HASH_MISMATCH` | 回执或备份不可验证 |
| 2 | `ROLLBACK_OUTCOME_CORRUPT` / `ROLLBACK_INTENT_CORRUPT` / `ROLLBACK_INTENT_MISMATCH` | 回滚结果/恢复意图损坏或绑定不符（不补写任何审计工件） |
| 3 | `ACTIVATION_BUSY` | 另一进程持有该配置的排他锁（flock）；零变更 |

并发语义：同一配置的 apply/rollback 由 `activation-root/locks/` 下的
非阻塞排他 flock 串行化；竞争者立即以退出码 3 结束且不做任何工作。
替换前的 CAS 复读捕获未持锁的外部写入者。

## 7. 完整自动化复现（工程师可重跑）

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
`tests/test_activation_execution_r2_regressions.py`（15 项，C4-A-R2）在
原始 main `2acc5a8` 上以 9 红 / 6 绿复现了两类缺陷（同一 apply 调用内
授权加载后的撤销/轮换/证据篡改仍完成激活；最终锁符号链接/FIFO 绑定
外部 inode——含持有陷阱锁时的伪 `ACTIVATION_BUSY`），并在修复树上全绿；
其中 6 项是本来就正确的控制语义（普通授权 apply、两次调用间撤销、
常规锁文件、目录锁目标、双进程 0/3、一次性 fixture 边界）的保留性固定。
`tests/test_activation_execution_r3_probes.py`（11 项，C4-A-R3）在原始
main `4247f20` 上以 8 红 / 3 绿复现了两类残余缺陷（同一 apply 调用内
预加载命名输入文件——政策例外/决策记录——被替换或删除后仍以陈旧内存
对象完成激活，而信任根与证据束字节不变；外部普通文件通过 `os.link`
与最终锁共享 inode——apply/rollback 照常完成或被外部 flock 伪造
`ACTIVATION_BUSY` 退出码 3），并在修复树上全绿；其中 3 项是本来就正确的
真值/控制固定（新鲜调用对被替换文件必然阻塞 ×2、执行器自建与复用的
单链接锁生命周期）。硬链接探针在不支持 `os.link` 的文件系统上显式
skip 并在 Linux CI 主机上执行。
`tests/test_activation_status.py`（47 项，C4-B）覆盖第 4 节的九个状态
分类：每个正/负用例都用真实签名 apply/rollback 或具名故障点
（journal-persisted、config-replaced、config-restored、
rollback-intent-persisted）构造真实磁盘状态，再由真实 CLI 判定，并对每
次调用做调用前后全树哈希对比（零写入证明）与重复调用字节一致证明；负
矩阵覆盖缺失/篡改备份、篡改回执、伪造回滚关联、符号链接工件、根级异物、
多历史歧义、无关历史隔离、`--receipt` 检查与全部输入拒绝路径，另含一条
字面 `python -m` 子进程的完整操作演练（含空格路径与三个中断状态的恢复
路径衔接）。

## 8. 真实 strict-v2 启用（可选，所有者人工边界）

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
