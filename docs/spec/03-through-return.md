# 03 — Through Return

> Status: draft specification

## 1. Purpose

Through Return estimates how much sustainable economic value can reasonably reach common shareholders at the current market value.

It is **not** the same as trailing dividend yield.

The model separates:

- sustainable distributable earnings;
- conservative payout behavior;
- genuine net share-count reduction;
- special/non-recurring shareholder returns.

---

## 2. Distributable base

Use the lower of normalized accounting earnings and normalized owner-distributable cash:

\[
DistributableBase = min(NormalizedParentProfit, NormalizedParentCoreCDC)
\]

This prevents accounting profit from overstating payout capacity and prevents temporary working-capital releases from overstating sustainable earnings.

---

## 3. Conservative payout ratio

Define:

\[
ConservativePayoutRatio = CPR
\]

### 3.1 Formal minimum payout policy

If the company has a formal, durable and sufficiently unconditional minimum payout commitment, use:

\[
CPR = min(PolicyFloor, MedianPayout_{5Y})
\]

Only use the policy floor when:

```text
POLICY_CONFIDENCE = HIGH
```

The analyst must verify:

- policy is formally disclosed;
- policy has a meaningful effective period;
- conditions/escape clauses are not so broad that the floor is economically unreliable.

### 3.2 No formal policy

Use a conservative historical statistic rather than the median alone:

\[
CPR = P25(PayoutRatio_{5Y})
\]

This approximates what the company still tends to distribute in weaker years.

### 3.3 Suspended ordinary dividends

If ordinary cash dividends are suspended in a normal operating year without a convincing reason, flag:

```text
PAYOUT_STABILITY_WARNING
```

A few unusually high payout years must not compensate mechanically for a suspension.

---

## 4. Special dividends

Special dividends funded by asset sales, extraordinary transactions or one-off balance-sheet releases are **not** part of sustainable Through Return.

Record them separately:

```text
SPECIAL_RETURN
```

They may matter for event-driven valuation but are excluded from normalized ongoing shareholder return.

---

## 5. Dividend Through Return

\[
DividendThroughReturn = \frac{DistributableBase \times CPR}{MarketCap}
\]

This answers:

> Given conservative sustainable earnings and payout behavior, what recurring cash return can a shareholder reasonably expect at today's market value?

---

## 6. Buybacks: use ownership change, not headline spending

Headline buyback amount is not sufficient.

A company can repurchase shares while simultaneously issuing stock through compensation, acquisitions or financing.

The preferred metric is economic change in fully diluted share count.

\[
NetShareReductionYield_t = -\frac{FullyDilutedShares_t - FullyDilutedShares_{t-1}}{FullyDilutedShares_{t-1}}
\]

Examples:

- share count falls 3% -> +3% shareholder ownership yield;
- share count rises 3% -> -3% dilution yield.

Stock splits, reverse splits, technical reorganizations and stock dividends must be normalized away.

---

## 7. Normalized buyback yield

Default:

\[
NormalizedNetShareReduction = Median(NetShareReduction_{3Y})
\]

Also inspect the 5-year trend to avoid extrapolating a single large repurchase year.

If repurchases are material but diluted share count does not fall meaningfully, do not award full buyback credit.

---

## 8. Total Through Return

\[
ThroughReturn = DividendThroughReturn + NormalizedNetShareReduction
\]

A negative net share-reduction term is allowed and represents dilution.

Default strict-mode bands:

| Through Return | Result |
|---:|---|
| >= 8% | S |
| 6%–8% | A |
| 5%–6% | B / PASS |
| 4%–5% | WATCH |
| < 4% | FAIL |

The default formal candidate threshold is:

```text
ThroughReturn >= 5%
```

Thresholds must be parameterized.

---

## 9. Sustainability checks

Through Return must not pass solely because the most recent dividend was high.

At minimum inspect:

- payout coverage by DistributableBase;
- whether dividends required incremental debt;
- whether ordinary payout behavior is stable across 5 years;
- whether buybacks genuinely reduce diluted share count;
- whether payout coexists with deteriorating balance-sheet safety;
- whether payout is driven by a one-time event.

If payout exceeds normalized distributable capacity materially for multiple years, flag:

```text
UNSUSTAINABLE_PAYOUT_WARNING
```

---

## 10. Dynamic hurdle: future extension

The framework may later allow a hurdle linked to the risk-free rate, for example:

\[
RequiredThroughReturn = max(BaseFloor, R_f + Spread)
\]

The initial strict specification should keep the fixed threshold separate until backtesting validates the dynamic version.

---

## 11. Required output fields

```json
{
  "normalized_parent_profit": null,
  "normalized_parent_core_cdc": null,
  "distributable_base": null,
  "payout_policy_floor": null,
  "conservative_payout_ratio": null,
  "dividend_through_return": null,
  "normalized_net_share_reduction": null,
  "through_return": null,
  "special_return": null,
  "flags": [],
  "policy_confidence": "HIGH|MEDIUM|LOW",
  "confidence": "HIGH|MEDIUM|LOW"
}
```

Every policy assumption and share-count adjustment must be traceable to formal disclosures or normalized market data.