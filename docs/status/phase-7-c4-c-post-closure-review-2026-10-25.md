# Phase 7-C4-C — Independent post-closure review (2026-10-25)

**Disposition:** Preserve C4-C as implemented/merged and its full CI acceptance; select a narrow **C4-C-R1 — Readiness Next-Step Command Safety and Context Fidelity**. No owner approval, strict-v2 activation, or rule change is authorized by this review.

## 1. Exact reviewed baseline and evidence provenance

- Repository: `blooddrunk/turtle-value-engine`, main HEAD at review: **`3357b81a70228d129938402f681ba6e519f5b2e3`** (post-closure docs-only commit, parent `79fbdf8b52b5da67bdd5e07c3a732a04f67e72cc`).
- Implementation [PR #32](https://github.com/blooddrunk/turtle-value-engine/pull/32), head `e7debac5749e6ff9c1d2aaa0c37f83e323d3f0ad`, merged as `79fbdf8b52b5da67bdd5e07c3a732a04f67e72cc`.
- GitHub Actions **exact implementation PR-head** run [40169924902](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40169924902): `success`. **Merge-head** run [40170296742](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40170296742): `success`. **Reviewed latest main** run [40170876140](https://github.com/blooddrunk/turtle-value-engine/actions/runs/40170876140): `success`. Each workflow's job steps are green; the latest-main raw job log confirms **7516 passed / 2 skipped / 9 warnings**, Dashboard **55 passed**, with remaining CI stages green.
- Inspected `src/turtle_value_engine/evolution/owner_readiness.py`, the C4-C CLI diff, `tests/test_owner_readiness_summary.py`, checked-in schema, operator manual, goal, closure record, and changed filenames.
- **Independent local checkout and full pytest were NOT run by this reviewer**: the reviewer execution container cannot resolve `github.com`. Remote exact-SHA Actions logs are verified evidence, not a substitute claim for local execution.
- Protected rule/profile/manifest/template blobs and strict-v1 default are reported identical by the closure record; the implementation PR changed exactly six scoped files. The reviewer did not independently re-run the engine or verify real private activation.

## 2. Confirmed findings (new operator-facing surface only)

### F1 — P1: unquoted `<placeholder>` fragments are shell redirections

`_next_steps_zh` inserts `--decision-record <决策记录>`, `--policy-exception <策略例外>`, `--trust-root <信任根>`, `--authority-evidence <证据束>`, `--activation-root <执行存储>` and `--output <你的路径>.md` into command-looking strings. In POSIX shells, `<` and `>` redirect input/output; they are **not** inert placeholders. The operations manual calls the next-step hints copyable, and the code calls preview read-only.

Independent isolated proof without repo execution: in a disposable empty directory with two created placeholder input files and a stub `tve()` function, executing the structurally identical form `tve evolution activate-profile --decision-record <decision_record> --policy-exception <policy_exception> --project-config project_config` created unexpected files named `--policy-exception` and `--project-config`; the stub received only `evolution activate-profile --decision-record project_config`. This proves shell interpretation and surprise writes; it **does not** prove any real production apply occurred.

### F2 — P2: generated retry commands drop authority/decision context

The generated `summary_command` includes base/target/manifest/config and optional activation root but drops every other supplied input: repeatable decision records, exceptions, revocations, trust root, evidence bundle, signed lifecycle statements and boundary input. Therefore copy/pasting the displayed retry after a successful authenticated `PREVIEW_READY` inspection may silently produce an unrelated no-decision/unverified-authority inspection. No test checks generated-command argv equivalence.

### F3 — P2: output-writing tools described as read-only inspection

The `ACTIVATION_BLOCKED` hint tells the operator to run `plan-activation ... --output <路径>` as a “只读计划” check; the existing CLI's `plan-activation` parser **requires** `--output` and the command persists a file. Likewise `decision-dossier --output` writes a specified Markdown file. These operations may be acceptable with explicit consent and a safe path, but must not be represented as zero-write/copy-ready commands.

### Follow-up diagnostic only, **not** a C4-C-R1 acceptance claim

The present `summary_id` derives from audit/plan identity, `store.status`, config SHA, and journey state, but not from every store problem/guidance; distinct projections in the same status could share the same `summary_id`. `content_sha256` does independently hash the complete projection. Prove a material collision with a controlled regression before selecting any separately scoped identity-contract repair; do not silently broaden R1 or assert a verified collision without executing a test.

## 3. Selected next bounded task

[Phase 7-C4-C-R1 goal](../goals/phase-7-c4-c-r1-readiness-next-step-fidelity.md): fix F1–F3 **tests first**. Do not introduce a new CLI, authorization source, executor operation, profile, or persisted contract for a cosmetic phase label. Preserve the published C4-C functionality, readonly summary and fixed literals. No C4-A/C4-B R6 or automatic activation is selected.

## 4. Acceptance and owner boundary

- Automated failing regression on the unmodified latest main, with a **safe** shell argv/redirection proof in a temporary directory; implement minimum repair and run targeted suite twice, then full unchanged CI.
- Cover zero-writing and precise opt-in writing labels, shell quoting with spaces/metacharacters, replay of every supplied optional and repeatable argument, absent activation-root behavior, no `--apply` suggestion, no secret material and no accidental authorization state drift.
- Inspect exact PR-head SHA and full CI job success; only then merge and check merged-main CI. Record exact commands, SHAs, results and exclusions.
- **Engineering acceptance requires no manual owner step.** Real economic ACCEPT/REJECT, local key management/signing, explicit apply and rollback remain **optional, separately authorized human actions**, strictly out of R1.
