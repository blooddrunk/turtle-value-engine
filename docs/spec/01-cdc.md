# 01 — Core CDC / All-in CDC

> Status: draft specification

## 1. Purpose

CDC is the engine's primary measure of **real owner-distributable cash generation**. It is intentionally more conservative than reported net profit and more explicit than generic free cash flow.

The model separates two questions:

- **Core CDC**: how much cash the existing business itself leaves after unavoidable operating and capital needs.
- **All-in CDC**: how much cash remains after management's acquisitions and strategic investments.

This prevents a good operating business from looking weak merely because management made a large acquisition, while still exposing poor capital allocation.

---

## 2. Core CDC

Baseline formula:

\[
CoreCDC = AdjustedCFO - EconomicGrossCapEx - LeasePrincipalOutsideCFO
\]

Parent-share version:

\[
ParentCoreCDC = CoreCDC \times ParentEconomicShare
\]

The preferred production implementation should perform subsidiary-level attribution when minority interests are material rather than relying on the approximation above.

---

## 3. Adjusted CFO

\[
AdjustedCFO = ReportedCFO
- InterestOutsideCFO
- NonRecurringOperatingInflows
+ OperatingOutflowsMisclassifiedOutsideCFO
\]

### 3.1 Interest normalization

Required fields:

```text
cash_interest_paid_total
cash_interest_in_cfo
cash_interest_outside_cfo
```

\[
InterestOutsideCFO = InterestPaidTotal - InterestAlreadyIncludedInCFO
\]

Do not double-count interest already included in reported CFO.

If interest classification cannot be established and cash interest is material (default: >= 10% of reported CFO), return `SPECIAL_REVIEW` rather than silently assuming a classification.

### 3.2 Non-recurring operating inflows

Remove material cash inflows that do not represent normalized business economics, including where applicable:

- one-off government grants;
- one-off tax refunds;
- insurance settlements;
- non-operating related-party cash movements;
- investment/treasury income classified inside operating cash flow for a non-financial operating company.

Materiality must be parameterized.

---

## 4. Gross CapEx

Use **gross** cash expenditure on long-term operating assets, not net CapEx after asset disposals.

Typical components:

- purchase of property, plant and equipment;
- purchase of intangible assets;
- other long-term operating assets.

\[
GrossCapEx = PPEPurchaseCash + IntangiblePurchaseCash + OtherOperatingLongTermAssetCash
\]

Asset-sale proceeds are recorded separately and must not reduce Gross CapEx for operating-quality analysis.

### 4.1 Capitalized development

Capitalized R&D/development expenditure must **not** be deducted twice.

If already included in intangible/long-term-asset purchase cash flow:

```text
capitalized_dev_already_in_capex = true
```

No additional deduction is made.

Only add a separate adjustment when evidence proves the cash expenditure is outside Gross CapEx.

### 4.2 CapEx payables

Where identifiable and material:

\[
EconomicGrossCapEx = CashGrossCapEx + \Delta CapExPayables
\]

Relevant balances include equipment payables, project/construction payables and other long-term-asset purchase obligations.

Default trigger for explicit adjustment:

\[
|\Delta CapExPayables| > 10\% \times |CoreCDC|
\]

---

## 5. Lease normalization

Lease-heavy businesses require explicit adjustment.

If lease principal is outside CFO:

\[
CoreCDC = AdjustedCFO - EconomicGrossCapEx - LeasePrincipalOutsideCFO
\]

Do not deduct short-term lease, low-value lease or variable lease cash payments a second time if already included in CFO.

Relevant sectors include retail, restaurants, hotels, aviation and other location/asset-rental-heavy models.

---

## 6. Working-capital distortion

A temporary release of receivables/inventory can overstate a single year's CFO.

Calculate:

```text
working_capital_contribution
```

If:

\[
|WCContribution| > 30\% \times |CFO|
\]

flag:

```text
WORKING_CAPITAL_DISTORTION
```

A distorted year must not be extrapolated directly into normalized CDC.

---

## 7. Factoring and supplier finance

### Recourse factoring

If economic risk remains with the company, treat proceeds as financing rather than genuine operating cash generation.

Flag:

```text
CASH_FLOW_QUALITY_WARNING
```

### Supplier finance

If trade payables have effectively become financing obligations (bank/intermediary settlement, extended financing period, explicit financing economics), reclassify the financing component out of normal operating cash flow and into debt-equivalent analysis.

If the amount cannot be reliably quantified:

```text
SPECIAL_REVIEW
```

---

## 8. Minority interests

Approximation when NCI is immaterial:

\[
ParentEconomicShare = Median_{3Y}\left(\frac{ParentNetProfit}{ConsolidatedNetProfit}\right)
\]

Hard clamp:

\[
0 \le ParentEconomicShare \le 1
\]

Materiality triggers:

```text
minority_profit / consolidated_profit > 15%
OR
minority_equity / total_equity > 20%
```

Then set:

```text
NCI_MATERIAL = true
```

and require subsidiary-level review or lower confidence.

---

## 9. All-in CDC

\[
AllInCDC = CoreCDC - AcquisitionCash - StrategicInvestmentCash
\]

All-in CDC is a **capital-allocation diagnostic**, not a single-year hard gate.

Use cumulative multi-year behavior:

\[
CumulativeAllInCDC_{5Y}
\]

If:

\[
\sum AcquisitionCash_{5Y} > \sum CoreCDC_{5Y}
\]

flag:

```text
CAPITAL_ALLOCATION_WARNING
```

If this coexists with falling ROIC, rising goodwill/impairments or weak shareholder returns, escalate toward `FAIL`.

Cash-management instruments and near-cash deposits are not strategic investment cash outflows merely because they appear in investing cash flow.

---

## 10. Normalization

For a standard non-cyclical operating company:

\[
NormalizedCoreCDC = min(Average(CoreCDC_{3Y}), Median(CoreCDC_{5Y}))
\]

Preferred final metric:

\[
NormalizedParentCoreCDC
\]

Cyclicals should use full-cycle normalization (typically 7–10 years) rather than this default.

---

## 11. CDC gates

Base continuity rules:

```text
positive Core CDC years in last 5 >= 4
cumulative Core CDC over last 5 > 0
NormalizedCoreCDC > 0
```

CDC yield:

\[
CDCYield = \frac{NormalizedParentCoreCDC}{CurrentMarketCap}
\]

Default strict-mode bands:

| CDC Yield | Result |
|---:|---|
| >= 12% | S |
| 10%–12% | A |
| 8%–10% | B / PASS |
| 6%–8% | WATCH |
| < 6% | FAIL |

The numeric thresholds are strategy parameters, not accounting truths, and must live in machine-readable configuration.

---

## 12. Required output fields

```json
{
  "reported_cfo": null,
  "adjusted_cfo": null,
  "economic_gross_capex": null,
  "lease_principal_outside_cfo": null,
  "core_cdc": null,
  "parent_core_cdc": null,
  "normalized_parent_core_cdc": null,
  "cdc_yield": null,
  "all_in_cdc": null,
  "flags": [],
  "confidence": "HIGH|MEDIUM|LOW"
}
```

Every adjusted field must retain data lineage and the reason for adjustment.