# Phase 5R-A M6-C3 — Dashboard UX and Chinese-first Localization

Status: **COMPLETE**
Date: 2026-09-20
Selected after: M6-C2 `CLOSED / OWNER_ACCEPTED`

Parent context:
- `AGENTS.md`
- `docs/architecture/agent-api-web-surface.md`
- `docs/goals/phase-5r-a-m6-c1-personal-dashboard-foundation.md`
- `docs/goals/phase-5r-a-m6-c2-private-dashboard-deployment.md`
- `docs/status/phase-5r-a-2026-09-20.md`
- `docs/roadmap.md`

## 1. Objective

Make the already deployed read-only personal Dashboard understandable to its
owner without changing the analysis engine, API contract, authentication model,
or investment semantics.

The current Dashboard is technically correct but still exposes developer-facing
English copy, raw enum names, raw API errors, hashes and implementation terms as
first-class content. M6-C3 turns that surface into a Chinese-first research UI
with progressive disclosure of audit/debug details.

This is a presentation package. It must not become Phase 6 monitoring.

## 2. Why this package is next

M6-C2 proved the real private deployment path and the owner completed the
interactive Access acceptance. That live use exposed a concrete usability gap:

- the UI is English-first;
- raw codes such as `NOT_AVAILABLE`, `BLOCKED`, `NOT_EVALUATED` and
  `SPECIAL_REVIEW` are difficult to interpret;
- technical API/contract/hash details compete with the research result;
- empty/partial states look placeholder-like;
- raw backend errors are too prominent for a normal user path.

Phase 6 will add watchlist/event state later. Building that on top of the current
developer-oriented presentation would compound the problem. Close the human
presentation boundary first, then start Phase 6 as a separate goal.

A6 remains an optional strict production-claim audit and is not a prerequisite
for this personal read-only Dashboard package.

## 3. Frozen boundaries

Preserve all of the following:

1. `strict-v1`, deterministic formulas, hard-gate semantics and valuation
   semantics are unchanged.
2. `ResearchSurfaceSnapshotV1` and the checked-in OpenAPI schema are unchanged.
3. M6-B remains read-only and consumes explicit validated snapshot files only.
4. M6-C2 Access, Worker, Tunnel, custom-domain and service-token security
   boundaries are unchanged.
5. No page request may trigger provider acquisition, filing research, model
   execution, analysis, adjustment approval, rule changes, orders, transfers,
   or other financial mutation.
6. No new API endpoint is required for this package.
7. Missing data must remain missing. Presentation code must never convert null,
   unavailable or partial data into zero, PASS, or a fabricated value.
8. Raw machine states remain available for audit/debug display even when the
   primary UI uses friendly labels.
9. Phase 6 watchlist/event monitoring, M4-D/M4-E, M2-D and M5-C/R2 are outside
   this package.
10. Ordinary CI stays deterministic and independent of Cloudflare credentials.

## 4. UX contract

### 4.1 Language

Implement a small typed presentation/copy layer rather than scattering Chinese
strings through every view.

Required behavior:

- default user-facing locale: `zh-CN`;
- optional English presentation may remain available behind a simple local
  locale switch if implemented without server state;
- locale choice, if persisted, is client-only preference data;
- API/schema identifiers, hashes, rule IDs and exact enum codes remain
  untranslated in technical details;
- no user-facing copy may alter the meaning of a deterministic state.

Do not add a heavyweight localization framework unless the implementation can
justify it. A typed in-repository dictionary is sufficient for this package.

### 4.2 State presentation

Provide one centralized state-presentation mapping used by badges, empty states
and explanations. At minimum cover:

- `PASS` → a clear Chinese pass label;
- `WATCH` → a clear watch/attention label;
- `FAIL` → a clear failed-gate label;
- `SPECIAL_REVIEW` → explicitly requires manual review;
- `NOT_EVALUATED` → explicitly not yet evaluated;
- `PARTIAL` → explicitly incomplete data/coverage;
- `BLOCKED` → explicitly blocked and unable to complete the relevant claim;
- `NOT_AVAILABLE` / null → explicitly no usable value is currently present;
- `READY`, `AVAILABLE`, `ACCEPTED`, `OK`, `UNAVAILABLE`, `UNKNOWN`
  and existing API/runtime states.

The friendly label is the primary display. The exact raw code must remain
available through a details/diagnostic affordance or accessible metadata.

Unknown future enum strings must render safely as an explicit unknown/raw state;
they must not be treated as PASS.

### 4.3 Progressive disclosure

Normal user paths should prioritize:

1. company/listing identity;
2. as-of date and rule profile;
3. deterministic decision and why it is blocked/limited;
4. valuation state and the most relevant available values;
5. data quality and Business Quality availability;
6. historical readiness only when relevant.

Move implementation-oriented material behind a clearly labeled technical/audit
details affordance where practical:

- API contract name;
- `analysis_id`, `surface_id`, content hashes;
- rule IDs;
- artifact identities/hashes;
- raw API status/error code/message.

Do not delete those fields from the payload or make them impossible to inspect.

### 4.4 Empty, partial and error states

Differentiate at least:

- no snapshots loaded;
- filters returned no matches;
- a section is genuinely not evaluated;
- data exists but coverage is partial;
- a hard blocker prevents a claim;
- the read-only API is unavailable;
- a requested surface does not exist.

For `SurfaceAPIError`, map known stable error codes to user-facing Chinese
messages. The raw HTTP status, error code and backend message belong in an
expandable technical details section, not as the first line shown to the owner.

Never hide a blocker merely to make the page look cleaner.

### 4.5 Values, dates and units

Add conservative presentation helpers for booleans, dates, identifiers and
numbers, but do not infer economic units that are not explicit in the payload.

- show dates in a consistent human-readable form while retaining exact ISO
  values where useful;
- display booleans as user-facing yes/no labels;
- keep IDs/hashes monospaced only in audit details;
- where a currency is explicit, place it visually next to the relevant
  valuation group;
- do not convert a ratio to percent unless the field contract clearly defines
  the representation;
- do not invent currency, scale, unit, or period labels.

## 5. Implementation scope

Expected files are primarily:

```text
apps/dashboard/src/presentation.ts          # new typed labels/explanations/formatters
apps/dashboard/src/presentation.test.ts     # deterministic presentation tests
apps/dashboard/src/components.tsx
apps/dashboard/src/router.tsx
apps/dashboard/src/views/overview.tsx
apps/dashboard/src/views/surface-detail.tsx
apps/dashboard/src/app.test.tsx
apps/dashboard/src/styles.css
apps/dashboard/src/test/**                  # only when fixtures need presentation cases
docs/goals/phase-5r-a-m6-c3-dashboard-ux-localization.md
docs/status/phase-5r-a-2026-09-20.md or dated successor
docs/status/phase-5r-a-next-codex-goal.md
docs/roadmap.md
AGENTS.md only if milestone state changes
```

Do not modify generated OpenAPI/TypeScript contracts unless an actual contract
defect is independently discovered. A UI preference does not justify an API
schema change.

## 6. Required automated verification

Codex must run every check that its environment can run. Routine validation is
not delegated to the owner.

### 6.1 Permanent test environment

The preferred permanent owner test root is:

```text
D:\code\research
```

Codex must first discover the actual `turtle-value-engine` checkout under that
root and use it for owner-environment verification whenever the environment is
available. Do not create a disposable alternate checkout merely to avoid using
the permanent test environment.

If executed through WSL, the equivalent path is normally under
`/mnt/d/code/research`; discover the real checkout rather than assuming a
subdirectory.

Record:

```text
git status --short --branch
git rev-parse HEAD
git remote -v
```

A dirty tree must be inspected before editing. Do not overwrite unrelated owner
changes.

### 6.2 Baseline before edits

Require the latest `main` GitHub Actions run to be green before claiming a
clean baseline.

Run:

```bash
python -m ruff check .
python -m pytest
pnpm --dir apps/dashboard install --frozen-lockfile
python scripts/export_surface_openapi.py --check
pnpm --dir apps/dashboard api:check
pnpm --dir apps/dashboard types:check
pnpm --dir apps/dashboard lint
pnpm --dir apps/dashboard typecheck
pnpm --dir apps/dashboard test --run
pnpm --dir apps/dashboard build
pnpm --dir apps/dashboard security:client-bundle
python scripts/dashboard_cross_stack_smoke.py
```

If platform-specific `python3` is required, use it consistently and record the
actual command.

### 6.3 Presentation-specific tests

Add deterministic tests proving at minimum:

1. `zh-CN` is the default user-facing locale.
2. Every known semantic state has an explicit friendly label and explanation.
3. `SPECIAL_REVIEW`, `BLOCKED`, `PARTIAL`, `NOT_EVALUATED` and
   `NOT_AVAILABLE` remain distinguishable.
4. Unknown enum strings fail safe and expose the raw value.
5. null/undefined/non-finite values never become zero.
6. overview empty state distinguishes no snapshots from no filter matches.
7. known API errors show friendly copy while raw diagnostics are available only
   in the technical detail affordance.
8. overview/detail primary headings and navigation are Chinese-first.
9. the detail page still exposes exact IDs/hashes in technical details.
10. no save/approve/delete/trade/order/run or other mutation control appears.
11. filters still encode only the existing supported API query parameters.
12. keyboard-focusable controls and semantic headings remain intact.

Keep existing security/read-only tests. Do not weaken an assertion just because
the visible label becomes localized.

### 6.4 Post-edit full verification

Run the baseline commands again plus any new focused tests. Record exact exit
codes and relevant pass counts.

After push, inspect the GitHub Actions run for the exact pushed commit. The goal
cannot close while required CI is red or still running.

## 7. Browser/layout verification

A UX package requires a real browser check in addition to jsdom tests.

Automation preference, in order:

1. use an already available browser automation capability in the execution
   environment;
2. use an already installed Chromium/Edge headless path to capture screenshots
   of the built local preview;
3. only if neither is actually available, request the bounded manual check below.

Do not add a large browser-testing dependency solely to avoid one bounded visual
acceptance unless the dependency is otherwise justified.

Automated or manual visual coverage must check at least:

- desktop viewport around 1440×900;
- mobile viewport around 390×844;
- overview with data;
- overview empty/no-match state;
- `HK00288` (or the current explicit private test snapshot) detail with
  `SPECIAL_REVIEW` and unavailable/partial content;
- expanded technical/audit details.

Expected results:

- Chinese primary copy is readable without clipped/overlapping text;
- raw codes/hashes do not dominate the normal page;
- the owner can tell why a result needs review or why data is unavailable;
- technical details remain reachable;
- mobile navigation, filters, tables/cards and details remain usable;
- there are no mutation controls.

## 8. Existing live deployment

M6-C3 must not recreate the M6-C2 security architecture.

If the permanent test environment still contains the ignored
`.tve-private/project.toml` and the declared Cloudflare API-token reference,
Codex should automatically:

1. validate the private project config without printing secrets;
2. inspect the current M6-C2 resources with the existing deployment verifier;
3. deploy the exact M6-C3 build through the existing supported deployment path;
4. rerun the machine-verifiable Dashboard/origin live smoke;
5. verify no Access/Tunnel/custom-domain/read-only boundary changed.

If those private inputs are absent, that is not a code/test blocker. Record
exactly which live-only step was skipped and why.

Never ask the owner to paste a token into chat.

## 9. Manual verification boundary

Manual work is permitted only when the actual interactive/visual behavior cannot
be automated in the available environment.

If manual verification is required, the handoff must say exactly:

1. open the final Dashboard URL in a private/incognito browser;
2. complete the existing Cloudflare Access login;
3. on the overview, confirm the page/navigation/filter/status copy is primarily
   Chinese and that no raw API URL/hash dominates the normal view;
4. open the known `HK00288` detail;
5. confirm `SPECIAL_REVIEW`, `NOT_EVALUATED`, `PARTIAL`, `BLOCKED` and
   unavailable values are explained in plain Chinese where present, without
   changing their underlying state;
6. expand the technical/audit details and confirm the raw enum/IDs/hashes are
   still available;
7. repeat at a narrow mobile-width browser window and confirm there is no
   horizontal page overflow or unusable clipped control;
8. confirm there are still no write/trading controls.

The owner should report the exact failed step and visible symptom if any item
fails. Do not replace these steps with phrases such as "please visually verify
the UI".

## 10. Acceptance

M6-C3 closes only when:

- the M6-C2 security/deployment boundary is unchanged;
- Chinese-first primary UI is implemented through a centralized presentation
  layer;
- semantic states remain exact and user-understandable;
- technical/audit identifiers remain available but de-emphasized;
- empty/partial/error states are intentional and distinct;
- automated presentation tests pass;
- the full Python + Dashboard regression suite passes;
- local real cross-stack smoke passes;
- required GitHub Actions for the exact closing commit are green;
- browser/layout verification is recorded, automated when possible and otherwise
  with the exact bounded manual steps/results above;
- no Phase 6 monitoring, M4-D/M4-E, M2-D or M5-C/R2 work is mixed into the goal.

Stop after M6-C3 closure. Select Phase 6 in a separate audit/planning step.

## 11. Implementation record — 2026-09-20

M6-C3 is complete. The implementation adds:

- `apps/dashboard/src/presentation.ts`: the centralized typed
  presentation/copy layer — `zh-CN` default locale with an optional
  client-only English switch persisted in localStorage, the full semantic
  state table (friendly label + explanation + tone for every known engine,
  historical, health and UI state, with unknown enums failing safe as an
  explicit unknown/raw state), stable API/Worker error-code mapping with raw
  HTTP status/code/message preserved for the technical affordance,
  conservative value formatters that never turn null, undefined or non-finite
  values into zero and never infer units/currency/percent, plus centralized
  gate/metric/dimension/tier label tables;
- `apps/dashboard/src/presentation.test.ts`: deterministic coverage for the
  default locale, known-state labels/explanations, negative-state
  distinguishability, unknown-enum fail-safe, null≠0 formatting, boolean
  labels, known/unknown API errors with raw diagnostics, structural labels
  and locale dictionary completeness;
- `apps/dashboard/src/components.tsx`: `LocaleProvider` (client-only
  preference), localized `StatusBadge` (friendly label primary, dim raw-code
  suffix, explanation in the title), `ErrorState` with mapped Chinese copy and
  raw diagnostics only inside an expandable technical-details block, distinct
  no-snapshots/no-matches `EmptyState` variants, a reusable
  `TechnicalDetails` affordance, and compact raw machine-flag pills;
- `apps/dashboard/src/router.tsx`: Chinese-first navigation/skip-link/footer,
  the locale toggle, and contracts moved behind a footer technical-details
  affordance;
- `apps/dashboard/src/views/overview.tsx` and `surface-detail.tsx`: Chinese
  primary copy, empty-state distinction driven by active filters, hashes/IDs/
  contract names moved behind the technical/audit details affordance
  (overview per-row and a consolidated detail-page block containing exact
  `analysis_id`, `surface_id`, `content_sha256`, request path, source
  artifacts and historical dataset identities), friendly state badges
  everywhere with raw codes retained, and explicit currency/boolean/date
  display without invented units;
- `apps/dashboard/src/app.test.tsx`: rewritten UI coverage including
  Chinese-first default rendering, both empty states, friendly-error/raw-
  details layering, locale switching, technical-details ID/hash availability,
  the 404 not-found mapping, filter encoding and the no-mutation-control
  guarantee;
- `apps/dashboard/index.html` (`lang="zh-CN"`, Chinese title) and
  `styles.css` (CJK font stack, dual-layer badge, technical/error details,
  locale toggle, mobile wrap fixes for the valuation table, hashes and
  machine-flag pills).

Frozen boundaries held: `ResearchSurfaceSnapshotV1`, the OpenAPI contract,
generated API types, the M6-B read-only API, the Worker proxy and all M6-C2
security/deployment configuration are unchanged; no payload value, enum or
missing field was rewritten; no Phase 6, M4-D/M4-E, M2-D or M5-C/R2 work was
started.

Exact local verification, real-browser layout verification (desktop
1440×900 and mobile 390×844 against the private `HK00288` snapshot), the
unchanged-boundary redeployment and the live smoke are recorded in
`docs/status/phase-5r-a-2026-09-20.md`. Two genuine mobile overflow defects
(valuation-tier `nowrap` cells and an unbounded artifact hash) were found by
the browser pass and fixed before closure.
