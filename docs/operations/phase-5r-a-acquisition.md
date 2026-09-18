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
覆盖；若 request 声明 `expected_sessions_by_listing`，probe 还会逐标的检查声明的
session 是否全部出现；中间缺失也保持 fail closed。HTTP 200 或签名 URL 本身不构成
可用历史数据证据。缺少可选的 `historical`
依赖或 schema 不可识别时保持 fail closed，签名 URL 不写入 receipt/CAS。

H 股没有默认的免费权威完整来源。H 股来源必须先 probe；Futu 本轮仅在 bounded
unadjusted daily `MARKET_BAR` 个人研究角色上完成选择。未确认历史范围、退市、
corporate action 完整性或合法自动访问时，较宽声明仍输出
`H_SOURCE_UNQUALIFIED`，不会改用机构源、当前快照或 scraping workaround。

### BaoStock A 股生命周期/交易日（M3）

M3 的最小 adapter identity 是
`baostock-a-share-lifecycle`，可处理两种 DATA request：

```json
{
  "source_kind": "LISTING_LIFECYCLE",
  "artifact_kind": "LISTING_LIFECYCLE",
  "schema_version": "historical-listing-lifecycle-v1",
  "listing_ids": ["SH600000"],
  "start_date": "2020-01-01",
  "end_date": "2020-01-03",
  "parameters": {
    "calendar_id": "SSE",
    "timezone": "Asia/Shanghai",
    "currency": "CNY"
  }
}
```

交易日 request 只把 `artifact_kind` 改为 `TRADING_SESSION`，并把
`schema_version` 改为 `historical-trading-session-v1`。两者都保留
`source_kind: "LISTING_LIFECYCLE"`，因为 `TRADING_SESSION` 是新增 shard
artifact kind，不新增 source category。adapter 将 `query_stock_basic` 的
完整 SDK export 映射为 A 股 listing lifecycle，将 `query_trade_dates` 的
每个日期（含非交易日）映射为带 `calendar_id`、timezone、source hash 的
session row；缺少日期、额外/改变字段、非法 status/outDate、H 股 ID 或
calendar/lifecycle 不一致都会 fail closed。

BaoStock 使用 SDK decoded result，因此 raw CAS 中冻结的是完整、无凭据的
`baostock-sdk-export-v1` provider envelope，而不是声称为 wire bytes。只有
`tve historical source probe`/`acquire` 带 `--network=allow` 时才会创建 SDK
session；`compile`、replay 和 `historical accept` 不会 import/call SDK。
calendar row 可以为没有手工 expected sessions 的价格 request 派生预期交易
日；缺少价格仍是 missing/`PARTIAL`，不能推断为停牌，也不补零。

当前 adapter 只支持 A 股。`query_stock_basic` 是当前/basic source evidence，
不证明 PIT historical membership、code-change、完整退市保留、terminal
economics、source terms 或 A/H company mapping；因此 M3 不扩大任何 H-share
coverage 声明。

2026-09-18 owner-authorized smoke run 已实际验证这条路径：`baostock 0.9.3` 成功
登录，`SH600000` 的 `query_stock_basic` 与 `2024-01-01..2024-01-05` 的
`query_trade_dates` 均返回可解码结果；两个 raw envelope 已进入私有 CAS，随后
完全离线 `compile --verify-replay` 生成 1 条 lifecycle row 和 5 条 calendar rows。
本次使用的官方来源 URI、owner 的非公开使用声明和 provenance hash 已记录在私有
official plan 中；这只用于追溯，不要求项目先证明“免费开放许可”，也不妨碍未来把
私有 eligible artifacts 镜像到 private R2。因为该 smoke plan 没有
membership、价格、行为、benchmark、FX、filing、H 或完整终止经济资料，
`dataset validate`/`historical accept` 继续按设计 fail closed。

### BaoStock A 股采样价格参考（M4-A/B/C）

M4 的价格参考使用一个新增、采样用途的 adapter identity：
`baostock-a-share-price-reference`。它不改变 M3 的
`baostock-a-share-lifecycle` request，也不取代 Hithink 的 bounded canonical
A 股价格来源。request 必须显式声明每日、未复权和 CNY：

```json
{
  "source_kind": "PRICES",
  "artifact_kind": "MARKET_BAR",
  "schema_version": "market-bar-v1",
  "listing_ids": ["SH600000"],
  "start_date": "2020-01-01",
  "end_date": "2020-01-03",
  "parameters": {
    "source_uri": "https://www.baostock.com",
    "frequency": "d",
    "adjustflag": "3",
    "price_basis": "UNADJUSTED",
    "currency": "CNY"
  }
}
```

SDK 返回的完整 decoded export 先作为
`baostock-sdk-price-export-v1` envelope 写入私有 raw CAS，再由离线
`BaoStockAsharePriceReferenceDecoder` 生成 canonical `MARKET_BAR`。字段漂移、
复权模式、H 股 identity、越界日期、非法数字和重复 natural key 都会
fail closed。缺少某个日期不会被补成停牌或零价，后续 reconciliation 会保留
该日期的 `MISSING` counterpart。

采样比较使用 `HistoricalReconciliationSampleSpec` 和
`reconcile_sampled_market_bars`。sample 必须保存固定 listing/date 范围、两边
source/adapter/provider/upstream identity、CNY、price basis、`close` 字段、
绝对/相对 tolerance 和选择理由。不同 `source_id`/`adapter_id` 不能替代
provider/upstream 独立性；未解析的 upstream（包括没有实际上游标识的
AKShare wrapper）会输出稳定 blocker
`RECONCILIATION_SOURCE_INDEPENDENCE_UNPROVEN`。M4-A/B/C 的 ordinary CI 只使用
冻结 fake SDK export，不要求 live BaoStock 访问。

官方 filing 适配器可接入现有的 discovery/cache 回调，按 listing、日期和文件类型
自动选择记录；`filing_ids` 仅是已冻结回放/测试的兼容输入，不是生产获取时要求操作者
手工整理的清单。它会把本次请求只覆盖所选官方文件的事实记录为
`FILING_SCOPE_LIMITED` warning，而不是把一个合法的最小 filing 样本伪装成完整
历史 filing index；若要宣称 category `COMPLETE`，仍必须提供显式 source-scope
coverage evidence。

### FQGate 历史日 K：deployment-neutral endpoint（M1/M2-T）

M1 的 legacy 路径仍然通过本机 HTTP 边界访问 FQGate：

```text
POST http://127.0.0.1:17281/v1/market/history/klines
```

旧计划继续使用 `adapter_id: "fqgate-local-market-history"`，并且每个 request
只声明一个 listing。旧参数没有 `endpoint_kind` 时按 legacy `LOCAL_DIRECT` 解码，
不会被静默改写；现有 receipt/batch 可以继续离线读取和 replay。`parameters` 必须
显式保留实际运行环境中的路由和身份：

```json
{
  "source_uri": "http://127.0.0.1:17281/v1/market/history/klines",
  "market": "USHA",
  "code": "600519",
  "canonical_market": "A",
  "currency": "CNY"
}
```

M1 使用 `start_date`/`end_date` 日期范围查询，因此 plan 不要再加 `count`；FQGate
接口不允许数量模式和日期范围同时提交。这里的 A-share `USHA`/字段含义来自公开
FQGate client/UI 实现；适配器只接受
`adjust: ""` 和 `interval: "day"`，并将公开实现中的字段 `1/7/8/9/11/13/19`
分别映射为时间、开、高、低、收、量、额。响应原始字节先进入 raw CAS，之后
才由离线 compiler 验证 `code=0 -> data -> records` 形状并生成
`MARKET_BAR`。缺少必需 OHLC/时间字段、未知 envelope、非法数字或 schema 漂移
都会 fail closed；量和额缺失时保留为 `null`，不会补零。

H-share 计划必须由操作者填写实际 probe 观察到的值，不能把公开 client 的
`hk` market group 当成历史 endpoint 的已证实 market identifier：

```json
{
  "market": "<owner-observed-fqgate-h-market>",
  "code": "<owner-observed-fqgate-h-code>",
  "canonical_market": "H",
  "currency": "HKD"
}
```

上述 H 片段是模板，不是能力声明；没有实际成功 probe 时，readiness 不会声称
H 历史能力、覆盖范围、退市保留或 corporate-action 能力。legacy `LOCAL_DIRECT`
使用正在运行的本机会话，不需要在 plan 中放 API key 或 credential reference。

M2-T 为新请求增加 deployment-neutral 的 `adapter_id: "fqgate-market-history"`。
新请求必须显式写 `endpoint_kind`，并使用已支持的
`response_contract: "fqgate-envelope-v1"`：

```json
{
  "endpoint_kind": "LOCAL_DIRECT",
  "source_uri": "http://127.0.0.1:17281/v1/market/history/klines",
  "response_contract": "fqgate-envelope-v1",
  "market": "USHA",
  "code": "600519",
  "canonical_market": "A",
  "currency": "CNY"
}
```

新增 `fqgate-market-history` 的 `LOCAL_DIRECT` 保持 loopback FQGate 路径；明文 HTTP
只允许 loopback host，不能把远程 host 当成本地路径。旧的
`fqgate-local-market-history` 计划继续按 v1 解析和回放，保留其原先接受的显式
HTTP(S) endpoint 形状，不会被新 adapter identity 取代。`REMOTE_BRIDGE` 则必须把完整的
machine endpoint 和 bridge-owned operation path 写进显式 HTTPS `source_uri`，例如：

```json
{
  "endpoint_kind": "REMOTE_BRIDGE",
  "source_uri": "https://<explicit-machine-endpoint>/<bridge-owned-operation-path>",
  "response_contract": "fqgate-envelope-v1",
  "market": "<owner-observed-market>",
  "code": "<owner-observed-code>",
  "canonical_market": "A",
  "currency": "CNY"
}
```

上例的 hostname/path 只是配置形状，不是当前 bridge route 证据。REMOTE_BRIDGE
拒绝 HTTP、userinfo、query、fragment 和空/根路径；不会推导 hostname/path、动态
发现 API docs、在 local/remote 间 fallback，也不会在 Turtle 内实现 Tunnel、Access
policy 或 FQGate lifecycle。

如果已冻结的 remote endpoint contract 要求 machine authentication，使用已有的
`credential_ref`、resolver 和可配置 header/scheme；resolved secret 只存在于该次
outbound request，不会进入 parameters、source URI、receipt、probe report、日志或
Git。内置 CLI 仍只接受声明的 `ENVIRONMENT` reference 并在触网前解析；fake/受控
runner 才可使用 `INJECTED`/其他 resolver。缺少 required credential 会在 transport
之前 fail closed。内置 HTTP transport 默认拒绝 redirect，FQGate adapter 也会拒绝
返回 URL 改变的响应，避免 authenticated remote request 跨 origin 泄漏。

参考实现：[FQGate Python client](https://github.com/zhuyifang/tonghuasun-agent/blob/main/sdk/python/src/fqgate_client/client.py)
和[公开 UI 的 K 线字段映射](https://github.com/zhuyifang/tonghuasun-agent/blob/main/AI-plugins/ui-apps/src/adapters/local-api/FqgateCandleService.ts)。

### M2-A/M2-T FQGate 失败诊断

FQGate probe 仍只写入既有 `SourceProbeReportV1.blockers` 字段，并使用稳定前缀区分
可观察事实。诊断边界如下：

- `LOCAL_DIRECT` transport 连接失败写为 `FQGATE_LOCAL_GATEWAY_UNREACHABLE`；它只
  说明本机网关路径不可达，不说明 H 路由、账户权限或历史覆盖。
- `REMOTE_BRIDGE` DNS/TLS/Tunnel/连接路径失败写为
  `FQGATE_REMOTE_ENDPOINT_UNREACHABLE`；它不是本机 gateway failure。
- `REMOTE_BRIDGE` HTTP `401/403` 写为 `FQGATE_REMOTE_AUTH_DENIED`，且
  `account_entitlement` 保持 `UNKNOWN`，不自动写成 FQGate entitlement denial。
  未证明响应来源层的 remote HTTP failure（包括 5xx）写为
  `FQGATE_REMOTE_HTTP_ERROR_UNCLASSIFIED`，不会重标为 FQGate/provider failure。
- 仅 `LOCAL_DIRECT` 保留 M2-A 的 HTTP `401/403` -> `FQGATE_ENTITLEMENT_DENIED`。
  HTTP `504` 在没有独立证据证明上游原因时写为 `FQGATE_HTTP_504_UNCLASSIFIED`，
  不会仅凭状态码写成 `FQGATE_UPSTREAM_TIMEOUT_CONFIRMED`。
- 非成功响应或成功 envelope 中的结构化 `code`/`api_error` 只保留经过长度和字符
  限制的标量值，写为 `FQGATE_PROVIDER_ERROR_CODE`，并同时保留
  `FQGATE_PROVIDER_ERROR_UNCLASSIFIED`；不会把 `message`、`details` 或完整响应正文
  放入 blocker、异常或日志。当前公开 client/UI 资料没有建立 timeout 或 route
  rejection code 的闭集语义，因此不会发明 `FQGATE_H_ROUTE_REJECTED` 或
  `FQGATE_UPSTREAM_TIMEOUT_CONFIRMED` 的映射。
- H request 缺少实际 `market` 或 `code`，或仍是模板值时写为
  `FQGATE_H_ROUTE_UNVERIFIED`，并在触碰网络前阻断；适配器不会推导替代 ID。
- 合法 `200` 响应无可用行写为 `HISTORICAL_NO_ROWS`；有行但日期/声明 session 不
  完整写为 `HISTORICAL_COVERAGE_INSUFFICIENT`，而不是 route failure。响应形状
  无法安全解码时写为 `SOURCE_SCHEMA_UNSUPPORTED`。

这些诊断不改变 FQGate 的 retry policy、A-share 成功路径、raw CAS、receipt、离线
compile/replay、PIT/A6 或 H-share readiness。失败 probe 仍不会产生 H 历史能力声明；
只有实际观察到的成功行、日期和 listing identity 才能进入相应证据字段。当前
`fqgate-remote-bridge` 尚未发布 Phase 3/4 的 stable remote market-history route、
error contract 或 machine-auth contract，因此 remote live 状态明确为
`REMOTE_BRIDGE_LIVE_UNPROVEN`；fake transport 成功不升级该结论。

### M2-C Futu OpenD：bounded H 日线（C1/C2 完成；`FUTU_SELECTED`）

Futu adapter 的 identity 是 `futu-opend-market-history`，canonical schema 是
`market-bar-v1`，provider representation 是
`futu-opend-sdk-export-v1`。它只在现有 historical acquisition boundary 中调用
本机 OpenD；Futu Python SDK 通过 lazy/injected factory 接入，普通 import、offline
compiler 和 deterministic analysis 不需要安装 SDK。SDK/DataFrame 结果会先冻结为
完整、可 hash 的 provider envelope 写入 raw CAS，再由 offline decoder 投影为
`MARKET_BAR`；这个 envelope 不是 raw OpenD wire bytes。

SDK 是可选 extra，固定在当前已验证版本 `futu-api==10.10.7008`；在 VPS 或新机器上应先创建独立 virtualenv，
再执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[futu]'
```

OpenD 本体不放进 Git 或 Python environment。建议安装到版本化用户目录，例如
`~/.local/opt/futu-opend/<version>/`，运行状态和日志放到
`~/.local/state/futu-opend/<version>/`；只监听 `127.0.0.1`。首次启动必须由 owner
交互登录并完成协议确认；之后可在不把密码放进 plan、环境变量或命令行的前提下使用
OpenD 的 remembered-login 机制。Hermes 只负责启动、健康检查和只读采集，不负责
接收或保存登录密码。

每个 request 必须显式提供以下非秘密参数；`futu_code` 必须是 owner OpenD 实际接受或
返回的 H identity，不能从 FQGate 的 `market`/`code` 推导，也不能把下面的示例值当作
owner 证据：

```json
{
  "source_uri": "https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html",
  "futu_code": "<owner-runtime-accepted-futu-code>",
  "canonical_market": "H",
  "currency": "HKD",
  "kline_type": "K_DAY",
  "adjustment": "NONE",
  "timezone": "Asia/Shanghai",
  "max_count": 1000,
  "max_pages": 1024,
  "opend_host": "127.0.0.1",
  "opend_port": 11111
}
```

不要在 Futu request 中放 `credential_ref`、brokerage password、login material 或
session secret；OpenD 的登录状态由 owner 运行时管理。即使 request 不需要 provider
credential，CLI live operation 仍必须显式使用 `--network=allow`。适配器会在实际
history call 前调用 `get_history_kl_quota(get_detail=True)`（若 runtime 支持），把
quota 状态限制为可审计的 bounded diagnostic；page key 只保存类型/长度/hash identity，
不会把 opaque token 原文写入 CAS。

M2-C2 已通过 genuine owner runtime 完成。OpenD 版本为 `10.11.7108`，监听
`127.0.0.1:11111`，SDK 为 `10.10.7008`；`get_stock_basicinfo(Market.H,
SecurityType.STOCK)` 返回 3,790 条港股股票记录，实际返回的 H identity 是
`HK.00001`。历史 K 线 quota 预检为 `used=0, remaining=100`。两份私有 plan 使用同一
runtime identity 和明确的 canonical `listing_id`，窗口不重叠且相隔至少一年：

```bash
# 以下 plan、report、raw CAS、batch 和 manifest 只能放在 .tve-private。
# recent: 2026-09-15..2026-09-17, HK.00001
# older:  2025-09-15..2025-09-17, HK.00001

python3 -m turtle_value_engine historical source probe \
  --plan .tve-private/plans/futu-h-recent-20260915-17.json \
  --network=allow \
  --output .tve-private/live/futu-h-recent-20260915-17.json

python3 -m turtle_value_engine historical source probe \
  --plan .tve-private/plans/futu-h-older-20250915-17.json \
  --network=allow \
  --output .tve-private/live/futu-h-older-20250915-17.json
```

两份 probe 都是 `PASS`，各返回 3 条 usable rows，schema、identity/date coverage 均成立，
且报告明确记录 `K_DAY`、`adjustment=NONE`。只有在这两份 owner evidence 成功后，才执行
一次 bounded acquire -> private CAS/provider envelope -> compile -> `--verify-replay`：

```bash
python3 -m turtle_value_engine historical acquire \
  --plan .tve-private/plans/futu-h-recent-20260915-17.json \
  --network=allow \
  --raw-store .tve-private/raw/futu-h-recent-20260915-17 \
  --batch-output .tve-private/batches/futu-h-recent-20260915-17.json \
  --report-output .tve-private/live/futu-h-recent-20260915-17-readiness.json

python3 -m turtle_value_engine historical compile \
  --batch .tve-private/batches/futu-h-recent-20260915-17.json \
  --raw-store .tve-private/raw/futu-h-recent-20260915-17 \
  --store .tve-private/artifacts/futu-h-recent-20260915-17 \
  --output .tve-private/manifests/futu-h-recent-20260915-17.json \
  --verify-replay
```

本次 acquire 的 provider envelope 是明确的 `futu-opend-sdk-export-v1`（不是 raw
OpenD wire bytes），包含 3 条 canonicalizable rows，raw envelope SHA-256 为
`ee75f454b86aaf98e71b1bedff4443e743a97d7d67b1ca52d2da817e33d94be2`，batch 为
`batch-d1ef177190b7cd1f25870315fb15af7b`，离线 compile/`--verify-replay` 成功。
`H_PRICE_SOURCE_SELECTED_FUTU` 只覆盖 bounded H unadjusted daily `MARKET_BAR`；
membership、lifecycle、terminal、corporate actions、完整覆盖和 source terms 仍然
fail closed。M2-D 不因这些更宽 blocker 启动，也没有在 M2-C 中实现。

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

本轮既保留既有 owner-authorized A-share 价格切片，也完成了 Futu owner-authorized
H bounded probe/acquire；没有读取或复用聊天中的 key，也没有把任何 key 写入仓库或报告。
当前本地
`compile`、shard replay 和数据研究可以继续离线运行；`historical accept` 的
blocker 只限制完整 A/H、完整类别和生产级覆盖声明，不是本地 replay 的使用前置
条件。

当前仍未声称 `PERSONAL_RESEARCH_READY` 或 `PRODUCTION_ELIGIBLE`。下列事项在
对应的完整声明上保持 fail closed：

- `H_SOURCE_UNQUALIFIED`：Futu 已被选择为 bounded H 未复权日线 `MARKET_BAR` 来源，
  但完整 H membership/lifecycle/action/terminal、市场范围 coverage 及自动访问条款
  仍未证明。
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
- `HISTORICAL_CAPABILITY_UNVERIFIED`：Futu 仅对本次 bounded PRICES 证明历史能力，
  其他来源类别或更宽范围仍未证明提供历史数据，而非当前快照。
- `CURRENT_SNAPSHOT_UNUSABLE`：当前快照不能替代历史来源。

这些 blocker 不能通过要求机构商业订阅、手工整理数据、使用当前成分股或
放宽既有 `--require-production` 校验来解决；它们也不应被解释为个人继续进行
本地实验和回放前必须完成的用户待办。实际本轮结果与下一步入口见
`docs/status/phase-5r-a-2026-09-17.md`。

## 6. M2-T 验证记录（2026-09-17）

```text
python3 -m pytest tests/test_fqgate_historical.py -q -> 44 passed
python3 -m pytest tests/test_phase_5r_acquisition.py -q -> 60 passed
python3 -m ruff check . -> PASS
python3 -m pytest -> 6212 passed, 2 skipped
```

相对 M2-A 的 `6191 passed, 2 skipped`，新增 21 个离线 endpoint/auth/diagnostic/
compatibility 测试。`fqgate-remote-bridge` `main=ce30a4f` 仍未提供 Phase 3/4 的
live machine market-history contract，故 `REMOTE_BRIDGE_LIVE_UNPROVEN` 仍是明确
blocker；本记录不启动 M2-B。

## 7. M2-C 验证记录（2026-09-17）

```text
python3 -m pytest tests/test_futu_opend_historical.py -q -> 18 passed
python3 -m pytest tests/test_phase_5r_acquisition.py -q -> 60 passed
python3 -m ruff check . -> PASS
python3 -m pytest -> 6230 passed, 2 skipped
```

M2-C2 结果为 `FUTU_SELECTED`：真实 owner OpenD 返回/接受 `HK.00001`，两个窗口
`2026-09-15..17` 与 `2025-09-15..17` 均为 PASS，且后续 bounded acquire、private
CAS/provider envelope、offline compile 与 `--verify-replay` 均成功。M2-D 没有实现；
完整 H membership/lifecycle/action/terminal/coverage/source-terms 仍保持 fail closed。
