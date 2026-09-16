# 交给 ChatGPT 的下一阶段规划 Prompt

```text
你是 turtle-value-engine 的下一位开发规划者。请先阅读仓库根目录的
AGENTS.md，以及以下文件：

- docs/goals/phase-5r-a-production-source-acquisition.md
- docs/status/phase-5r-a-2026-09-16.md
- docs/operations/phase-5r-a-acquisition.md
- docs/goals/phase-5r-production-historical-corpus.md
- rules/strict-v1.yaml
- docs/spec/ 和 schemas/ 中与历史数据、覆盖、PIT、回放相关的契约

当前事实：

- main 已包含提交 4a3f985；A0–A5/A7 的实现、离线 compiler、A-only
  Hithink probe/acquire 和稳定 hash replay 已完成。
- 私有本地批次已编译为一个 486 行的 SH600000 日线 shard；raw/CAS、API key、
  签名 URL 和受限内容不能进入 Git、prompt、日志或普通 CI。
- 当前完整 A/H A6 acceptance 仍是 ACTIVE / PARTIAL。不要把它描述成项目无法
  使用，也不要把条款 URI、license hash 或 access-grant reference 作为用户的
  手工待办；它们只用于完整/生产级声明的审计层。

请为下一阶段提出一个可执行的开发计划，并明确回答：

1. 是否应新增一个明确的 LOCAL_ONLY / EXPERIMENTAL 本地研究状态，使已编译的
   私有数据可以被回放、统计和研究，同时继续保留 A6 与 --require-production
   的 fail-closed 语义；如需要，给出最小 schema、CLI、代码和测试变更。
2. 在不要求机构商业源、不要求用户手工整理数据、不使用 scraping workaround、
   不修改 strict-v1、且普通 CI 不访问网络或模型的前提下，H-share、lifecycle/
   membership、corporate actions、benchmark、FX、filings 和 reconciliation
   的自动来源扩展顺序是什么？若某项没有可验证来源，请提出可运行的降级边界，
   不要编造“已完成”。
3. 把工作拆成小的可合并 milestone；每个 milestone 给出目标、受影响文件、
   新增测试、离线/网络验证命令、完成条件和明确 blocker。
4. 先指出当前文档或代码中仍然把“完整 A/H acceptance blocker”误写成“个人
   本地 replay 不能使用”的地方，并提出文档修正。
5. 最后给出推荐的下一次实现任务，但先不要修改代码；计划必须保持 provider/
   evidence/orchestration/calculation 分层，不能让 agent 重算 CDC、Net Cash、
   Through Return、hard gate 或 valuation。

输出以中文为主，先给结论，再给按优先级排序的计划。不要索取或复述任何 API key。
```
