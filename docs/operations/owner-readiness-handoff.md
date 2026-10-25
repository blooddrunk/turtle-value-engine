# 所有者就绪单一旅程操作手册（Phase 7-C4-C）

本手册描述所有者（或其代理人）如何用**一条只读命令**看清
strict-v2 受控启用工作流的当前全貌：正在评估哪个发布配对、字节是否
验证通过、CDC 14% 门槛与 12% S 档的政策问题意味着什么、是否存在有效
的所有者决策及其授权是否刚刚被重新验证、激活存储当前证明了什么状态、
以及下一步**最安全的只读操作**是什么。

新命令：

```bash
python -m turtle_value_engine evolution readiness-summary \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json \
  --project-config ~/tve-private/project.toml \
  --activation-root ~/tve-trust/activation
```

`--activation-root` 可选（不提供则跳过存储分类，缺失的存储保持缺失）；
`--decision-record/--policy-exception/--revocation/--trust-root/
--authority-evidence/--signed-revocation/--signed-supersession/
--boundary-input` 与既有契约一致，均可选——**没有决策记录也能运行**，
这正是旅程起点的状态视图。

## 0. 边界声明（先读）

- **零写入**：本命令不创建任何目录/文件/锁/日志/回执，不修复、不签名、
  不批准、不应用、不回滚、不发任何网络请求。它没有 `--output`。
- **仅供信息**：`summary_is_informational_not_authorization` 恒为
  `true`。本摘要**不是授权凭证**；即使它观察到 READY 计划，应用边界仍会
  在自己的锁与期望哈希下重新推导一切。
- 授权事实的**唯一来源**是摘要内部新跑的 C2-R1 计划：
  `owner_authority_revalidated=true` 当且仅当该计划刚刚以当前信任根
  （`--trust-root` + `--authority-evidence`）重新验证了 ACCEPT 决策；
  历史回执、`activation-status` 或摘要自身都永远不会把它置真。
- 退出码：`0` = 摘要成功产出（所有就绪状态——包括缺决策、授权未证明、
  计划阻塞、待恢复——都是**信息性事实**，不是命令失败）；`2` = 输入不可
  用（路径缺失/符号链接/受保护目录、决策记录损坏等分类错误）。

## 1. 输出速查

| 字段 | 含义 |
| --- | --- |
| `journey_state` | **单一状态答案**（下表 11 个值之一） |
| `base/target_profile_id`、`*_sha256`、`release_manifest_id/_content_sha256` | 正在评估的发布配对身份与哈希 |
| `published_bytes_verified` | 发布字节/身份是否全部通过结构校验 |
| `audit_activation_readiness`、`uncovered_policy_findings` | 新鲜 C1 审计就绪状态与未覆盖发现 |
| `policy_question_zh` | 政策问题的中文解释（14% 门槛 vs 12% S 档/估值档，含原始小数） |
| `behavior_contrast_zh` | 行为对照（真实引擎回放中分歧区间内第一个行为不同的收益率，即 13.0%） |
| `decision_authority_state`、`decision_record_id`、`decision` | 决策解析与生效记录 |
| `owner_authority_revalidated` | 授权是否**刚刚**被当前信任根重新验证 |
| `plan_state`、`plan_blockers` | 新鲜只读计划的状态与命名阻塞项（沿用既有代码，不改名） |
| `project_config_sha256`、`current_default_profile` | 观察到的私有配置字节哈希与当前默认档案 |
| `activation_store_status/_problems/_guidance_zh` | 原样嵌入的 C4-B `activation-status` 投影 |
| `informational_blockers` | 信息性阻塞项（如 `OWNER_DECISION_REQUIRED`、审计政策发现、计划阻塞项并集） |
| `next_steps_zh` | 针对当前状态的下一步提示（Phase 7-C4-C-R1 起遵守下述"提示安全约定"） |

### 提示安全约定（Phase 7-C4-C-R1）

`next_steps_zh` 中的命令提示按以下规则生成，避免误导或 Shell 意外：

- **只有"完整已知输入的只读命令"才会以可复制命令形式出现**，且置于该条
  提示最后一个全角冒号"："之后、整条结尾；命令由参数向量经
  `shlex.join` 精确引用拼出，**绝不含裸 `<占位符>`**（POSIX Shell 会把
  `<决策记录>` 解析成输入/输出重定向，历史上曾意外创建名为
  `--policy-exception` 之类的文件并破坏 argv）。路径含空格、引号、
  分号、`$`、反引号或重定向字符时会被安全引用并逐字节保留。
- **重放保真**：标注为"重新运行本命令"的 `readiness-summary` 重试命令会
  原样携带本次显式提供的全部输入（`--decision-record`/`--revocation`/
  `--policy-exception`/`--trust-root`/`--authority-evidence`/
  `--signed-revocation`/`--signed-supersession`/`--boundary-input`/
  `--activation-root`，可重复项保持顺序与次数）。直接复制粘贴即可复现
  同一观察（含已验证授权的 `PREVIEW_READY`），不会退回起点视图。
- **写文件命令绝不伪装成只读**：`decision-dossier` 与 `plan-activation`
  都必须显式 `--output` 并会写入文件，它们只以文字说明出现（明确披露
  写入、要求你自选输出路径），永不以可复制命令形式出现。
- **不完整的命令不生成**：例如未提供 `--activation-root` 时不会给出
  号称可直接运行的 `activate-profile` 预览命令（该参数是解析器必填），
  而是文字说明需要补齐什么。

## 2. `journey_state` 速查

| journey_state | 含义 | 下一步（摘要会给出逐字命令） |
| --- | --- | --- |
| `OWNER_DECISION_REQUIRED` | 尚无（可用）所有者决策——旅程起点 | 读决策材料 → 人工决策/签名/记录 |
| `REJECTED_BY_OWNER` | 所有者已拒绝（终局） | 无需处理；默认保持 strict-v1 |
| `DECISION_CONFLICT` | 决策记录互相冲突（如同时 ACCEPT+REJECT） | 以签名撤销/取代澄清 |
| `OWNER_AUTHORITY_NOT_PROVEN` | 决策存在但授权未经当前信任根全新验证（缺证据、密钥被撤销/轮换） | 重新捕获证据或重新签名 |
| `PUBLISHED_PAIR_BLOCKED` | 发布配对结构校验失败（字节/身份/清单） | 核对字节，勿启用 |
| `ACTIVATION_BLOCKED` | 计划被其他原因阻塞（绑定过期、例外缺失、配置已是目标等） | 逐项处理 `plan_blockers` |
| `RECOVERY_PENDING` | 存在中断的 apply/rollback 步骤 | 先 `activation-status` 定位，再重执行同一命令 |
| `STORE_NEEDS_ATTENTION` | 存储分歧/歧义/损坏 | 人工比对 `before-images/`；命令不修复 |
| `ALREADY_APPLIED` | 配置已是目标且有已验证激活记录 | 如需恢复用回执绑定回滚 |
| `ROLLED_BACK` | 已回滚并字节验证 | 无需处理 |
| `PREVIEW_READY` | 新鲜计划 READY（授权已重新验证、无阻塞） | 跑只读预览核对，再由你显式决定是否应用 |

优先级：存储待恢复/需关注 > 已应用/已回滚 > 发布配对阻塞 > 决策类状态
> 计划 READY。回滚后即便旧决策仍使计划 READY，状态也如实报告
`ROLLED_BACK`（字节已恢复；再次启用需按 `profile-activation-executor.md`
第 4 节的语义走新决策）。

## 3. 完整旅程（与既有命令的衔接）

```text
readiness-summary（起点：OWNER_DECISION_REQUIRED）
  -> decision-dossier（唯一写文件步骤：--output 由你指定；以文字说明给出）
  -> 所有者人工 ACCEPT/REJECT + 签名 + record-decision
     （见 owner-provenance-walkthrough.md；绝不把私钥放进仓库/聊天/CI）
  -> readiness-summary（带 --decision-record/--trust-root/--authority-evidence；
     摘要给出的重试命令会原样保留全部输入） -> PREVIEW_READY
     + owner_authority_revalidated=true
  -> activate-profile 默认预览（只读，核对 config_diff 与期望哈希；
     摘要会给出完整的可复制预览命令——前提是必填输入完整）
  -> 仅在你显式决定时：逐字执行预览输出的 apply_command_hint
  -> activation-status / readiness-summary 复核（ALREADY_APPLIED 等）
  -> rollback-activation（如需恢复；字节精确）
```

每一步的完整语义、失败码与中断恢复见
`docs/operations/profile-activation-executor.md`；密钥、信任根、签名与
证据捕获见 `docs/operations/owner-provenance-walkthrough.md`。本摘要只是
把上述分散输出合并为一个可读视图，**不替代其中任何授权边界**。

## 4. 判定不变量（工程边界）

- 输出确定性：相同字节重复运行逐字节一致（`content_sha256` 自校验）。
- 秘密零泄漏：输出不含私钥材料、不合成所有者身份或许可；
  `requires_human_policy_approval=true`、`automatic_activation_allowed=false`、
  `execution_performed=false` 为固定字面量。
- REJECT 不声称授权重验（`owner_authority_revalidated=false`）：计划的
  重验只作用于 ACCEPT_VERIFIED 决议。
- 缺失的激活存储保持缺失；损坏/符号链接/受保护路径输入按既有分类以
  退出码 2 拒绝，输出无回溯。
- 自动化测试：`tests/test_owner_readiness_summary.py`（30 项）覆盖旅程
  起点、认证 ACCEPT、REJECT、撤销密钥、冲突决策、已应用/已回滚/中断/
  损坏存储、恶意输入、零写入前后快照、套接字禁用执行、确定性、schema
  漂移校验、真实子进程演练与"真实 apply→回滚→幂等"兼容性对照；
  `tests/test_owner_readiness_summary_r1_probes.py`（14 项，C4-C-R1）
  另以一次性沙箱内 no-op `tve` stub（绝不执行真实激活）复现并钉死：
  命令提示的 Shell 安全（无裸占位符、argv 逐字节一致、零副作用文件、
  含空格/引号/分号/`$`/反引号/重定向符路径）、重试命令的完整上下文
  保真（可重复项顺序与次数、重放同一 summary_id 与已验证授权状态）、
  写文件命令（`--output`）永不以可复制只读命令出现、缺 `--activation-root`
  时不出预览命令，以及 summary_id 存储问题集碰撞的诊断性记录。
