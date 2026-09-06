# 02 — Net Cash Safety

> Status: draft specification

## 1. Purpose

This module distinguishes between cash that merely appears on the balance sheet and cash that is genuinely useful to the enterprise and realizable by common shareholders.

The engine therefore maintains three layers:

1. **Book Net Cash** — quick screening only.
2. **Strict Net Cash** — economic balance-sheet safety.
3. **Owner Realizable Net Cash** — shareholder-level margin of safety.

---

## 2. Book Net Cash

\[
BookNetCash = ReportedCash - ReportedInterestBearingDebt
\]

Use only for first-pass screening.

```text
quality = SCREENING_ONLY
```

---

## 3. Strict cash assets

Classify liquid assets by economic quality rather than line-item label.

### C0 — Hard cash

Weight: 100%.

Includes unrestricted cash, demand deposits and genuine cash equivalents.

### C1 — Near cash

Default weight: 95%.

Examples: unrestricted time deposits, CDs, treasury bills, money-market funds and very low-risk cash-management instruments.

### C2 — Liquid financial assets

Default weight: 80%.

Examples: short-duration bonds, some structured deposits and other liquid financial assets with measurable market/credit/liquidity risk.

### C3 — Investment assets

Default strict-cash weight: 0%.

Examples: equities, PE/VC interests, strategic stakes, long-term equity investments and illiquid funds.

These may have value, but they are not cash safety.

Baseline:

\[
StrictCashAssets = C0 + 0.95C1 + 0.80C2
\]

Haircuts must be parameterized.

---

## 4. Restricted and trapped cash

Restricted cash is not freely available and is therefore excluded from general strict cash.

Examples:

- frozen cash;
- pledged deposits;
- LC/bank-acceptance margins;
- performance guarantees;
- regulatory accounts;
- earmarked funds.

Where restricted cash is directly matched to a specific liability, allow a matched-collateral offset against that liability instead of treating the restricted cash as free cash.

---

## 5. Subsidiary ownership and upstreamability

Consolidated cash may not be fully attributable or distributable to listed-company shareholders.

Preferred approach:

\[
ParentShareNetCash_i = Ownership_i \times (AdjustedCash_i - Debt_i)
\]

Then:

\[
OwnerNetCash = ParentStandaloneNetCash + \sum ParentShareNetCash_i
\]

When subsidiary-level data is unavailable, apply an `UpstreamabilityFactor` based on ownership, regulation, covenants, capital controls and dividend restrictions.

Suggested default bands:

| Factor | Interpretation |
|---:|---|
| 1.00 | fully controllable and distributable |
| 0.75 | moderate tax/FX/time friction |
| 0.50 | meaningful regulatory/minority/covenant constraints |
| 0.00 | legally/economically unavailable |

For VIEs or complex offshore structures, inability to establish cash upstreamability triggers:

```text
TRAPPED_CASH_WARNING
```

---

## 6. Debt equivalents

Do not limit debt to short- and long-term bank loans.

\[
DebtEquivalent = StandardDebt + LeaseDebt + SupplierFinance + RecourseFactoring + DebtLikeHybrids + MaterialQuasiDebt
\]

### Standard debt

100% deduct:

- short-term borrowings;
- long-term borrowings;
- current maturities;
- bonds/notes/commercial paper;
- other explicit interest-bearing borrowings.

### Lease liabilities

Track separately but include in obligation-adjusted safety analysis.

Report both:

\[
FinancialNetCash = StrictCash - FinancialDebt
\]

and:

\[
ObligationAdjustedNetCash = StrictCash - FinancialDebt - LeaseLiabilities
\]

Lease-heavy sectors should emphasize the latter.

### Trade payables

Normal trade payables are not debt by default.

Reclassify supplier-finance components when economic substance is financing.

### Recourse factoring

Outstanding recourse factoring is debt-equivalent when the company retains repayment risk.

### Convertibles / perpetuals / preferreds

Classify by expected cash obligation, not instrument name.

Suggested debt weights for perpetual/hybrid instruments:

```text
PURE_EQUITY_LIKE: 0%–25%
HYBRID:           50%
DEBT_LIKE:       100%
```

Weights are strategy-risk parameters, not accounting classifications.

### Quasi-debt

Material expected cash obligations may include:

- litigation;
- environmental remediation;
- mine/site restoration;
- guarantee exposure;
- pension deficits.

Only material items should be adjusted automatically.

---

## 7. Core net-cash measures

\[
StrictNetCash = StrictCashAssets - DebtEquivalentLiabilities
\]

\[
OwnerRealizableNetCash = OwnerAccessibleCash - OwnerEconomicDebt
\]

The primary margin-of-safety ratio is:

\[
OwnerNetCashRatio = \frac{OwnerRealizableNetCash}{MarketCap}
\]

Default bands:

| Owner Net Cash / Market Cap | Grade |
|---:|---|
| >= 60% | S+ |
| 50%–60% | S |
| 30%–50% | A |
| 20%–30% | B |
| 0%–20% | C |
| < 0% | Net debt |

A ratio >= 50% is an exceptionally thick margin of safety, not a universal requirement.

---

## 8. Liquidity and refinancing stress

### Liquidity coverage

\[
LiquidityCoverage = \frac{AccessibleCash + NormalizedCoreCDC}{DebtDueWithin1Year}
\]

Suggested bands:

```text
>= 2.0       S
1.5–2.0      A
1.2–1.5      B
1.0–1.2      WATCH
< 1.0        FAIL / SPECIAL_REVIEW
```

### Stress coverage

Assume a 30% drop in normalized CDC:

\[
StressedCDC = NormalizedCDC \times 70\%
\]

\[
StressCoverage = \frac{AccessibleCash + StressedCDC}{DebtDueWithin1Year}
\]

Strict candidate preference:

```text
StressCoverage >= 1.2
```

Ideal:

```text
StressCoverage >= 2.0
```

If one-year debt maturity exceeds internally available cash plus normalized CDC, flag:

```text
REFINANCING_DEPENDENCY
```

---

## 9. Cash origin analysis

A growing cash balance is not automatically evidence of good economics.

Decompose changes where possible:

\[
\Delta NetCash = CDC - Dividend - Buyback - Acquisition + EquityFinancing + DebtFinancing + Other
\]

If net cash is largely created by issuance or borrowing while cumulative CDC is weak/negative, flag:

```text
CASH_ORIGIN_WARNING
```

---

## 10. Cash traps and governance discount

Distinguish:

- **Safety Cash**: money that helps the company survive.
- **Valuation Cash**: money that common shareholders can reasonably expect to realize.

A company may have large safety cash but poor shareholder realizability due to chronic hoarding, low-ROIC acquisitions, weak payout behavior or governance risk.

Introduce a `CashGovernanceFactor (CGF)` for valuation only.

Suggested starting values:

| CGF | Typical interpretation |
|---:|---|
| 1.00 | strong payout/capital allocation/governance |
| 0.85 | generally sound |
| 0.70 | persistent hoarding / weak returns |
| 0.50 | repeated poor capital allocation |
| 0–0.30 | severe governance risk; often a separate FAIL |

\[
ValuationNetCash = OwnerRealizableNetCash \times CGF
\]

Do not use CGF to rewrite the accounting balance sheet; it is a valuation haircut.

---

## 11. Cash-adjusted enterprise value

\[
AdjustedEV = MarketCap - ValuationNetCash
\]

\[
ExCashCDCYield = \frac{NormalizedCDC}{AdjustedEV}
\]

If `AdjustedEV <= 0`, do not report an infinite/meaningless yield. Flag:

```text
NET_NET_SPECIAL_CASE
```

If owner-realizable net cash exceeds market cap and normalized CDC is positive with acceptable governance, the company may enter a deep-value priority pool. Otherwise treat it as a potential value trap.

---

## 12. Hard gates

Suggested base gates:

```text
IF StrictNetCash < 0 AND NetDebt/EBITDA > 2:
    FAIL

IF InterestCoverage < 4:
    FAIL

IF StressCoverage < 1:
    FAIL_OR_SPECIAL_REVIEW

IF REFINANCING_DEPENDENCY is material:
    FAIL_OR_SPECIAL_REVIEW

IF major illegal guarantee / controlling-shareholder fund occupation:
    GOVERNANCE_FAIL
```

---

## 13. Required output fields

```json
{
  "book_cash": null,
  "strict_cash": null,
  "owner_accessible_cash": null,
  "financial_debt": null,
  "lease_debt": null,
  "debt_equivalent": null,
  "book_net_cash": null,
  "strict_net_cash": null,
  "owner_realizable_net_cash": null,
  "valuation_net_cash": null,
  "owner_net_cash_ratio": null,
  "liquidity_coverage": null,
  "stress_coverage": null,
  "adjusted_ev": null,
  "ex_cash_cdc_yield": null,
  "flags": [],
  "confidence": "HIGH|MEDIUM|LOW"
}
```

Every material classification or haircut must be explainable and traceable to source evidence.