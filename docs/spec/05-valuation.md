# 05 — Valuation Engine

> Status: strict-v1 design specification

## 1. Purpose

Valuation is allowed only after the company independently passes the required non-price gates:

```text
Balance Sheet Safety
CDC
Through Return
Business Quality
Governance / Data Quality
```

The valuation engine answers one narrow question:

> **At what market value and share price does an already-qualified business provide enough cash return and margin of safety to become investable under the strict Turtle framework?**

The engine does not attempt to forecast short-term prices and does not primarily rely on PE, PB, PEG or narrative DCF assumptions.

---

## 2. Strict-v1 design principles

### 2.1 Price does not repair a broken business

A cheaper price cannot turn a failed balance sheet, unreliable cash flow, unacceptable governance or structurally broken business model into a normal `PASS`.

Special situations remain separate.

### 2.2 Net cash is primarily a safety margin, not permission to overpay

The strict profile deliberately separates:

- **return on total purchase price**; and
- **asset support from realizable net cash**.

The primary entry-price cap is therefore based on total-market-value CDC and recurring shareholder cash return.

Cash-adjusted / ex-cash valuation is retained as a diagnostic and second valuation lens, but does **not** automatically raise the strict-v1 purchase ceiling.

This preserves the intuitive Turtle requirement:

> “每100元市值，企业本身每年真正赚多少，并且有多少真正回到股东手里？”

### 2.3 Independent valuation constraints are combined with `min`, never averaged

A company does not become cheap because one valuation dimension is exceptionally strong while another required return dimension fails.

---

## 3. Core normalized inputs

Use the following audited/normalized inputs from prior modules:

```text
NCDC = NormalizedParentCoreCDC
DB   = DistributableBase
CPR  = ConservativePayoutRatio
VNC  = ValuationNetCash
NDS  = NormalizedDilutedShares
```

Normalized recurring dividend cash:

\[
RecurringDividendCash = DB \times CPR
\]

All monetary values must be converted into a declared common valuation currency before formulas are evaluated.

Investor-specific dividend withholding tax is **not** part of the core hard gate. The engine may additionally display an after-tax investor view.

---

## 4. Price-target treatment of buybacks

The current Through Return metric may include normalized net diluted-share reduction:

\[
ThroughReturn = DividendThroughReturn + NormalizedNetShareReduction
\]

However, a historical percentage reduction in shares cannot safely be inverted into a future target market capitalization because the same buyback cash retires very different amounts of stock at different prices.

Therefore strict-v1 uses this rule:

```text
Buybacks may help the Through Return gate,
but target-price capitalization credits recurring buyback CASH only
when that cash amount is independently verified and sustainable.
```

Define:

```text
VerifiedRecurringBuybackCash
```

Default:

```text
0
```

It may be positive only when all are true:

1. at least three years of disclosed repurchase cash data are available;
2. diluted share count genuinely fell after stock compensation, acquisition issuance and other dilution;
3. repurchases were not a one-off event;
4. the recurring amount is covered by normalized distributable cash;
5. `BUYBACK_CREDIT_CONFIDENCE = HIGH`.

Then:

\[
RecurringShareholderCashRaw = RecurringDividendCash + VerifiedRecurringBuybackCash
\]

Cap it conservatively:

\[
RecurringShareholderCash = min(NCDC, DB, RecurringShareholderCashRaw)
\]

If verified buyback cash is unavailable, strict-v1 target prices capitalize dividends only. This is intentionally conservative.

---

## 5. Two valuation lenses

### 5.1 Lens A — whole-company cash-return valuation (PRIMARY)

For required whole-company CDC yield `Y_cdc`:

\[
MarketCapCap_{CDC} = \frac{NCDC}{Y_{cdc}}
\]

For required recurring shareholder cash yield `Y_return`:

\[
MarketCapCap_{Return} = \frac{RecurringShareholderCash}{Y_{return}}
\]

The strict tier cap is:

\[
TierMarketCap = min(MarketCapCap_{CDC}, MarketCapCap_{Return})
\]

This is the primary purchase-price model.

### 5.2 Lens B — cash-adjusted operating valuation (DIAGNOSTIC)

\[
AdjustedEV = MarketCap - VNC
\]

\[
ExCashCDCYield = \frac{NCDC}{AdjustedEV}
\]

For a chosen operating-business hurdle `Y_op`:

\[
AssetSupportedMarketCap = VNC + \frac{NCDC}{Y_{op}}
\]

This second lens answers:

> After conservatively crediting realizable net cash, what valuation is the market assigning to the operating business?

In strict-v1, `AssetSupportedMarketCap` is **not** allowed to raise `TierMarketCap`.

It is used for:

- diagnosing cash-rich deep value;
- understanding the operating-business price;
- distinguishing cash boxes from genuine cash-generating businesses;
- identifying discrepancies worth deeper review.

---

## 6. Four price tiers

Strict-v1 starts with four explicit tiers.

| Tier | Required CDC Yield | Required recurring shareholder cash yield | Meaning |
|---|---:|---:|---|
| Observation | 6% | 4% | worth monitoring, not a strict buy |
| Acceptable | 8% | 5% | minimum formal valuation pass |
| Turtle Entry | 10% | 5% | preferred strict Turtle entry |
| Extreme Safety | 12% | 6% | unusually wide cash-return margin |

These are strategy parameters, not universal financial truths. They must live in versioned machine-readable configuration and later be validated by historical testing.

### 6.1 Observation tier

\[
ObservationCap = min(\frac{NCDC}{0.06}, \frac{RecurringShareholderCash}{0.04})
\]

Crossing this threshold only moves the company into an active watch zone.

### 6.2 Acceptable tier

\[
AcceptableCap = min(\frac{NCDC}{0.08}, \frac{RecurringShareholderCash}{0.05})
\]

This is the highest price at which the strict model's minimum valuation requirements are satisfied.

### 6.3 Turtle Entry tier

\[
TurtleEntryCap = min(\frac{NCDC}{0.10}, \frac{RecurringShareholderCash}{0.05})
\]

This captures the intended shorthand:

> “每100元市值，正常年份至少约10元真实可支配现金，并且至少约5元形成可持续股东现金回报。”

### 6.4 Extreme Safety tier

\[
ExtremeSafetyCap = min(\frac{NCDC}{0.12}, \frac{RecurringShareholderCash}{0.06})
\]

This is not automatically a stronger recommendation. Extremely low prices can signal hidden liabilities, governance failures or structural decline, so deep-value flags remain mandatory.

---

## 7. Tier monotonicity

The engine must verify:

\[
ObservationCap \ge AcceptableCap \ge TurtleEntryCap \ge ExtremeSafetyCap
\]

If configuration changes violate this ordering:

```text
VALUATION_PROFILE_INVALID
```

and no automated target prices may be published.

---

## 8. Current valuation state

Given current listing-equivalent market capitalization `CurrentMCap`:

```text
IF CurrentMCap <= ExtremeSafetyCap:
    EXTREME_SAFETY
ELSE IF CurrentMCap <= TurtleEntryCap:
    TURTLE_ENTRY
ELSE IF CurrentMCap <= AcceptableCap:
    ACCEPTABLE
ELSE IF CurrentMCap <= ObservationCap:
    WATCH
ELSE:
    TOO_EXPENSIVE_FOR_STRICT_MODEL
```

This status is valid only when all prerequisite non-price gates remain valid.

---

## 9. From market cap to share price

For a normal single-class company:

\[
TargetPrice = \frac{TargetMarketCap}{NormalizedDilutedShares}
\]

Use normalized fully diluted economic shares, not merely period-end basic shares.

Adjust for:

- treasury shares;
- options and RSUs;
- convertibles likely to dilute;
- stock splits / consolidations;
- class conversion ratios;
- material post-reporting-date issuance/cancellation.

Every adjustment must be auditable.

---

## 10. A-share / H-share and multi-listing treatment

The engine must distinguish **company economics** from **listing price**.

When different listed classes represent equivalent economic claims but trade at different prices, do not force the investor's entry yield to use a weighted-average actual market capitalization that they are not paying.

For each investable listing, compute a listing-equivalent capitalization:

\[
ListingEquivalentMarketCap
=
ListingPrice_{common\ currency}
\times TotalEquivalentEconomicShares
\]

with class-right / share-ratio adjustment where necessary.

Then evaluate CDC Yield and return hurdles using the listing-equivalent capitalization.

This permits the H share and A share of the same underlying company to have different investment states while using the same normalized company fundamentals.

Also retain the actual aggregate class-by-class market value for reporting and reconciliation.

If economic rights differ materially between classes:

```text
MULTI_CLASS_SPECIAL_REVIEW
```

---

## 11. Margin of safety

Do not publish one ambiguous `margin_of_safety` field.

Calculate separately:

\[
MOS_{Acceptable} = 1 - \frac{CurrentMCap}{AcceptableCap}
\]

\[
MOS_{Turtle} = 1 - \frac{CurrentMCap}{TurtleEntryCap}
\]

\[
MOS_{Extreme} = 1 - \frac{CurrentMCap}{ExtremeSafetyCap}
\]

Interpretation:

```text
positive -> current price is below that tier ceiling
zero     -> exactly at tier ceiling
negative -> current price is above that tier ceiling
```

Example:

```text
Turtle Entry price = 10.00
Current price      = 8.00
MOS_Turtle         = 20%
```

---

## 12. Net-cash safety overlay

Net cash is displayed alongside entry prices rather than automatically added to them.

At each target cap calculate:

\[
OwnerNetCashRatio_{tier}
=
\frac{OwnerRealizableNetCash}{TierMarketCap}
\]

and:

\[
ValuationNetCashRatio_{tier}
=
\frac{VNC}{TierMarketCap}
\]

This tells the analyst how much of the proposed purchase price is backed by realizable cash.

Suggested descriptive labels:

```text
>= 50%  THICK_CASH_CUSHION
30–50%  STRONG_CASH_CUSHION
20–30%  MODERATE_CASH_CUSHION
< 20%   LOW_CASH_CUSHION
```

These labels do not override the separate balance-sheet gate.

---

## 13. Why strict-v1 does not add net cash to the buy price

Consider:

```text
NCDC = 10
ValuationNetCash = 60
```

A pure sum-of-parts approach could justify:

\[
60 + \frac{10}{10\%} = 160
\]

But at a market value of 160:

\[
WholeCompanyCDCYield = 6.25\%
\]

That violates the strict Turtle shorthand that the *entire purchase price* should itself provide strong cash-generation yield.

Therefore strict-v1 reports the 160 asset-supported value as a secondary lens, but its 10% CDC Turtle ceiling remains:

\[
100
\]

The extra cash strengthens safety and deep-value support; it does not automatically justify paying more.

A future non-strict profile may explicitly adopt sum-of-parts valuation, but it must be a separate strategy profile.

---

## 14. Net-net / negative adjusted EV

If:

\[
OwnerRealizableNetCash > CurrentMCap
\]

or:

\[
AdjustedEV \le 0
\]

set:

```text
NET_NET_SPECIAL_CASE
```

Never report infinite Ex-Cash CDC yield.

Mandatory review:

- cash authenticity and restrictions;
- shareholder accessibility;
- hidden liabilities / guarantees;
- normalized CDC positivity;
- cash burn trend;
- governance and related-party risk;
- structural business decline;
- delisting / legal / regulatory risk.

A company may enter `DEEP_VALUE_PRIORITY` only if:

```text
NormalizedParentCoreCDC > 0
Governance PASS
Cash realizability confidence != LOW
No unresolved material hidden-liability flag
```

Even then, the normal price-tier label should carry the special-case flag rather than silently treating negative EV as ordinary valuation.

---

## 15. Cash box / dying-business handling

High net cash does not create a valid valuation when the operating business fails the CDC or Business Quality gate.

Examples:

```text
Owner Net Cash / Market Cap = 70%
Normalized CDC <= 0
```

Result:

```text
NO_NORMAL_VALUATION
POTENTIAL_CASH_BOX_OR_LIQUIDATION_CASE
```

Likewise, a shrinking business with positive historical CDC but a structural-disruption hard gate cannot receive a normal Turtle target price until analyzed under a dedicated run-off / liquidation model.

---

## 16. Cyclical companies

A cyclical company must never use recent peak CDC to derive a target price.

Required:

```text
normalization_method = FULL_CYCLE
```

Use a sector-specific full-cycle normalized CDC derived from at least one meaningful cycle (typically 7–10 years where data permit).

The general valuation engine consumes that normalized value but does not invent a universal cyclical adjustment factor.

If full-cycle normalization is unavailable:

```text
CYCLICAL_VALUATION_UNAVAILABLE
```

No automated Turtle price is produced.

---

## 17. Special dividends and asset disposals

Special dividends are not recurring Through Return.

When a special distribution is already formally declared and economically near-certain, the engine may produce a separate event-adjusted view:

\[
EventAdjustedEntryCost
=
CurrentMarketCap
-
ExpectedNetSpecialDistribution
\]

But if the distribution is funded by selling an operating asset, normalized future CDC must be recomputed on a **pro-forma post-disposal basis**.

Never simultaneously:

1. keep the disposed asset's old CDC; and
2. subtract its sale proceeds / special dividend from purchase cost.

That would double-count value.

---

## 18. State-owned enterprises and trapped excess cash

Persistent excess cash at an SOE or otherwise constrained company is handled through the upstreamability and `CashGovernanceFactor` rules in the net-cash module.

Strict-v1 does not give a higher entry price merely because the balance sheet contains excess cash.

The cash still improves:

- survival strength;
- cash-cushion ratios;
- asset-supported diagnostic value;
- deep-value optionality.

But weak payout flexibility or governance keeps `ValuationNetCash` discounted.

---

## 19. Business-quality premium remains disabled

Strict-v1 does **not** lower required cash yields because Business Score is high.

No formula such as:

\[
RequiredCDCYield = BaseYield - QualityPremium
\]

is permitted in this profile.

Reason:

> Business quality determines whether the cash flow deserves to be trusted; it does not authorize paying any price for it.

A future profile may test a bounded quality adjustment, but it must be versioned separately and backtested.

---

## 20. Risk-free-rate adaptation remains disabled in strict-v1

Potential future model:

\[
RequiredReturn = max(FixedFloor, R_f + Spread)
\]

This is economically reasonable, but strict-v1 intentionally preserves fixed, interpretable hurdles until historical regime tests justify a dynamic version.

The engine may still display the spread over the current risk-free rate as contextual information.

---

## 21. Price-tier confidence

No automated target price may have confidence above the weakest critical input.

Critical inputs include:

```text
NormalizedParentCoreCDC
DistributableBase
ConservativePayoutRatio
NormalizedDilutedShares
listing economic-right conversion
```

If any critical input is `LOW` confidence:

```text
VALUATION_CONFIDENCE = LOW
MANUAL_REVIEW_REQUIRED
```

The engine may calculate indicative ranges but must not publish a normal `TURTLE_ENTRY` decision.

---

## 22. Consistency checks

Reject or flag valuations when any of the following occurs:

```text
Target cap implies CDC Yield below configured tier hurdle
Target cap implies recurring shareholder cash yield below tier hurdle
Tier caps are non-monotonic
Target uses more recurring shareholder cash than normalized CDC
Target credits unverified buyback cash
Target uses single-year peak CDC for a cyclical company
Target share price uses unnormalized diluted shares
Target credits special-distribution cash while retaining disposed-asset CDC
Listing currency/share-ratio conversion is unresolved
```

Any critical inconsistency:

```text
VALUATION_INVALID
```

---

## 23. Required outputs

```json
{
  "as_of": null,
  "valuation_currency": null,
  "listing": null,

  "current_price": null,
  "listing_equivalent_market_cap": null,
  "actual_aggregate_company_market_cap": null,
  "normalized_diluted_economic_shares": null,

  "normalized_parent_core_cdc": null,
  "distributable_base": null,
  "recurring_dividend_cash": null,
  "verified_recurring_buyback_cash": 0,
  "recurring_shareholder_cash": null,

  "owner_realizable_net_cash": null,
  "valuation_net_cash": null,
  "adjusted_ev": null,
  "ex_cash_cdc_yield": null,
  "asset_supported_market_cap": null,

  "tiers": {
    "observation": {
      "cdc_hurdle": 0.06,
      "return_hurdle": 0.04,
      "market_cap": null,
      "price": null
    },
    "acceptable": {
      "cdc_hurdle": 0.08,
      "return_hurdle": 0.05,
      "market_cap": null,
      "price": null
    },
    "turtle_entry": {
      "cdc_hurdle": 0.10,
      "return_hurdle": 0.05,
      "market_cap": null,
      "price": null
    },
    "extreme_safety": {
      "cdc_hurdle": 0.12,
      "return_hurdle": 0.06,
      "market_cap": null,
      "price": null
    }
  },

  "current_valuation_state": null,
  "mos_acceptable": null,
  "mos_turtle": null,
  "mos_extreme": null,

  "flags": [],
  "confidence": "HIGH|MEDIUM|LOW"
}
```

---

## 24. Strict-v1 decision pseudocode

```text
REQUIRE all non-price gates PASS
REQUIRE valuation critical inputs confidence != LOW

NCDC = NormalizedParentCoreCDC
DividendCash = DistributableBase * CPR
BuybackCash = VerifiedRecurringBuybackCash OR 0
RecurringShareholderCash = MIN(NCDC, DistributableBase, DividendCash + BuybackCash)

FOR each tier:
    CDC_CAP = NCDC / tier.cdc_hurdle
    RETURN_CAP = RecurringShareholderCash / tier.return_hurdle
    TIER_CAP = MIN(CDC_CAP, RETURN_CAP)
    TIER_PRICE = TIER_CAP / NormalizedDilutedEconomicShares

CHECK tier monotonicity
CHECK all valuation consistency rules

IF special-case flag requires manual review:
    do not auto-issue normal buy decision
ELSE:
    classify current listing-equivalent market cap
```

---

## 25. Interpretation example

Assume:

```text
Normalized Parent Core CDC      = 10
Distributable Base              = 9
CPR                             = 60%
Verified recurring buyback cash = 0
Valuation Net Cash              = 40
Normalized diluted shares       = 10
```

Then:

\[
RecurringShareholderCash = 9 \times 60\% = 5.4
\]

### Acceptable

CDC cap:

\[
10/8\%=125
\]

Return cap:

\[
5.4/5\%=108
\]

Therefore:

\[
AcceptableCap=108
\]

and:

\[
AcceptablePrice=10.8
\]

### Turtle Entry

CDC cap:

\[
10/10\%=100
\]

Return cap:

\[
5.4/5\%=108
\]

Therefore:

\[
TurtleEntryCap=100
\]

and:

\[
TurtleEntryPrice=10.0
\]

At the Turtle price:

```text
CDC Yield                = 10.0%
Recurring shareholder yield = 5.4%
Valuation net cash / cap = 40.0%
```

This is the desired interpretation:

> 100元的购买价格本身已经满足约10%的真实现金创造能力和5%以上的可持续股东现金回报，同时约40元还有经过折价后的净现金作为额外安全垫。

---

## 26. What strict-v1 deliberately does not do

The valuation engine currently does not:

- forecast stock-price appreciation;
- assign terminal multiples;
- assume multiple expansion;
- lower hurdle rates for famous/high-quality businesses;
- capitalize vague future growth;
- treat all book cash as full-value cash;
- treat headline buyback spending as shareholder return;
- extrapolate peak-cycle earnings;
- automatically convert negative EV into a buy signal.

Those exclusions are intentional. The first production version should be easy to audit and difficult to fool before becoming more sophisticated.