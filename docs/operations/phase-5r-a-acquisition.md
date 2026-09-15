# Phase 5R-A 数据获取运行手册

本手册描述个人研究项目的安全默认路径。它只负责把来源原始字节保存
并编译成现有 Phase 5R manifest；不会计算 CDC、Net Cash、Through Return、
估值或任何 strict-v1 gate。

## 1. 默认边界

- 原始字节和 receipt 放在本机私有目录，例如 `.tve-private/raw`；Git 只保存
  代码、schema、计划模板和脱敏报告。
- `tve historical source probe` 与 `tve historical acquire` 默认拒绝网络。
  每次 live 操作都必须显式带 `--network=allow`。
- CLI 使用内置真实 transport 时，plan 中每个 request 的必需凭据都必须声明为
  `ENVIRONMENT` credential reference，并在触碰网络前解析为非空值；任一缺失都会
  fail closed。多 request 计划不会先获取一部分数据再发现凭据缺失。
  `KEYRING`/`INJECTED` 只适用于显式注入的受控 runner 或 fake transport，不会成为
  默认 CLI 的 live 授权。
- 凭据只在计划中写“引用”：环境变量名、OS keyring 的 service/account，或
  进程内显式注入。不要把 key 写进 plan、shell 参数、日志、receipt、manifest
  或聊天；本项目不会读取聊天中的 key。
- `compile`、`dataset validate/freeze/snapshot`、`backtest` 和 `calibrate` 不
  创建 provider、transport 或 model client，也不会网络 fallback。
- `LOCAL_ONLY` 是默认存储策略。个人账户数据即使可访问，也默认按
  `RESTRICTED_INTERNAL` 处理；访问许可和再分发许可是两件事。

## 2. 计划与来源选择

计划必须声明 target、A/H listing identity、日期范围、所需类别、来源条款
证据和 credential reference。不要把当前成分股快照写成历史 membership；
也不要把复权价格当作“未复权价格 + 显式 corporate action”。

Hithink market-dump 适配器只接受官方文档定义的三个 `dump_type`：
`daily-k`、`daily-k-10d` 和 `adjustment-factors`。官方文档证明端点和字段形状，
不证明个人账户权限、历史退市保留、缓存权或再分发权；这些必须由 probe 和
条款证据确认。adjustment factor 在其 basis 未经确认前只能作为 reconciliation
输入。Hithink probe 还会在内存中检查实际 Parquet schema、日期跨度和 listing
覆盖；HTTP 200 或签名 URL 本身不构成可用历史数据证据。缺少可选的 `historical`
依赖或 schema 不可识别时保持 fail closed，签名 URL 不写入 receipt/CAS。

H 股没有默认的免费权威来源。H 股来源必须先 probe；未确认历史范围、退市、
corporate action 完整性或合法自动访问时，系统输出
`H_SOURCE_UNQUALIFIED`，不会改用机构源、当前快照或 scraping workaround。
官方 filing 适配器可接入现有的 discovery/cache 回调，按 listing、日期和文件类型
自动选择记录；`filing_ids` 仅是已冻结回放/测试的兼容输入，不是生产获取时要求操作者
手工整理的清单。它会把本次请求只覆盖所选官方文件的事实记录为
`FILING_SCOPE_LIMITED` warning，而不是把一个合法的最小 filing 样本伪装成完整
历史 filing index；若要宣称 category `COMPLETE`，仍必须提供显式 source-scope
coverage evidence。

## 3. Probe、获取与编译

```bash
# 只验证 plan 格式，不联网
tve historical source probe --plan plan.json

# 显式允许一次 live probe；没有凭据时会 fail closed
tve historical source probe --plan plan.json --network=allow \
  --output .tve-private/live/probe.json

# 项目自动下载原始响应并写入本地 CAS；不需要手工 CSV/Parquet
tve historical acquire --plan plan.json --network=allow \
  --raw-store .tve-private/raw \
  --batch-output .tve-private/batches/batch.json \
  --report-output .tve-private/live/readiness.json

# 该命令只读本地 bytes；可断网执行并应产生稳定 shard/manifest hash
tve historical compile \
  --batch .tve-private/batches/batch.json \
  --raw-store .tve-private/raw \
  --store .tve-private/artifacts \
  --output .tve-private/manifests/historical.json \
  --verify-replay

tve dataset validate \
  --manifest .tve-private/manifests/historical.json \
  --store .tve-private/artifacts

# 只读取本地 batch、probe 报告、CAS 和 manifest，审计 A6 最小私有验收。
# 即使失败也会写出精确 blocker，并以退出码 2 fail closed。
tve historical accept \
  --batch .tve-private/batches/batch.json \
  --probe-report .tve-private/live/probe.json \
  --raw-store .tve-private/raw \
  --manifest .tve-private/manifests/historical.json \
  --store .tve-private/artifacts \
  --output .tve-private/live/acceptance.json
```

`--verify-replay` 会在完全离线条件下重复 compile 并自动比较 manifest 和 JSONL
shard identity；同一 batch 的 hash 必须相同。缺失或
损坏 raw blob、未知 schema、冲突 natural key、超出日期/标的范围、未知终止
经济结果和不完整 calendar 都应失败，不应补零或生成终值。
一个 acquisition batch 还必须为计划中的每个 request 保留至少一个 receipt；
缺少 request 的部分 batch 不得进入 compiler。新 batch 还会为每个来源持久化
`RawSourceAggregateV1`，列出全部 child receipt/blob hash；因此多页响应不会用
任意一页的 hash 冒充整个来源。旧版 v1 batch 若未包含该可选字段仍可读取。

`--probe-report` 应指向前一步 `historical source probe` 输出的 readiness report；
`historical accept` 不会重新 probe、解析凭据、调用 provider 或模型。它会对已持久化
batch 做离线重编译，核对 manifest/shard hash，并逐项审计 A/H、两整年、calendar/
lifecycle、类别 coverage、terminal/suspension、benchmark/FX、A/H 官方 filing、
corporate actions、limitations 和独立 reconciliation。缺少 probe、授权、H 股能力、
来源覆盖或任何证明时，报告保留精确 blocker；它不会把失败状态升级为
`PERSONAL_RESEARCH_READY`。

## 4. 条款、凭据、备份与删除

在来源选择时把官方条款/个人账户授权页面的稳定 URI 与其内容 SHA-256 写入
source spec；`RESTRICTED_INTERNAL` 还要写非秘密 access-grant reference。
官方 filing 的 receipt 会保留 filing ID、发布日期、文档 SHA-256/大小、媒体类型、
获取时间、最终 URL 和 revision identity；离线 compiler 会把这些非内容元数据
投影到 `FILING_DOCUMENT` shard，不解析 PDF/HTML。`available_at` 采用本地
检索完成时间作为保守上界，不从发布日期猜测来源可用时刻；不同版本的文档不会
覆盖同一个 raw blob。
只备份私有 CAS、receipts、batch 和 manifest；备份介质应由操作者自行加密，
并定期用 hash 校验恢复。远程对象存储是后续可选镜像，不是 replay 的隐式
依赖，且不得上传 `LOCAL_ONLY` 内容。

轮换 key 时先更新本机环境变量或 keyring，再重新 probe；旧 receipt 不需要
重写，也不包含旧 key。删除时先确认要删除的精确 raw-store、receipt 或
quarantine 路径，按来源条款要求清理本地、备份和临时 `.part` 文件；已生成
的 manifest 只在仍能访问其 CAS 时可 replay。

## 5. 当前 blocker 记录

本仓库没有读取或复用任何账户 key，也没有执行 live probe，因此尚未声称
`PERSONAL_RESEARCH_READY` 或 `PRODUCTION_ELIGIBLE`。没有真实 probe 结果时，
下列事项保持 fail closed：

- `H_SOURCE_UNQUALIFIED`：缺少已确认的个人可用 H 股历史价格/生命周期/行动
  来源及自动访问条款。
- `HISTORICAL_MEMBERSHIP_UNVERIFIED`：没有有效日期的 A/H membership 与 code
  change/lifecycle 证据。
- `TERMINAL_COVERAGE_UNVERIFIED`：不能证明退市、收购取消、转板和长期停牌的
  处理及终值经济。
- `PERSONAL_COVERAGE_UNVERIFIED`：计划声明的 source category 在目标标的/日期
  范围内没有 `COMPLETE` coverage evidence。
- `SOURCE_TERMS_UNVERIFIED` / `SOURCE_LICENSE_STATUS_UNVERIFIED`：来源条款或
  许可状态证据缺失。
- `SOURCE_LICENSE_PROHIBITED`：来源明确禁止当前存储/研究路径。
- `ACCESS_GRANT_UNVERIFIED`：受限来源缺少非秘密个人访问授权引用。
- `SOURCE_AUTHORITY_UNVERIFIED`：来源 authority 仍是未知或仅为测试 fixture。
- `HISTORICAL_CAPABILITY_UNVERIFIED`：来源尚未证明提供历史数据，而非当前快照。
- `CURRENT_SNAPSHOT_UNUSABLE`：当前快照不能替代历史来源。

这些 blocker 不能通过要求机构商业订阅、手工整理数据、使用当前成分股或
放宽既有 `--require-production` 校验来解决。
