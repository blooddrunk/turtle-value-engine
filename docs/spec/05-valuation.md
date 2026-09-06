# 05 — Valuation Engine

> Status: scaffold / next active design module

## 1. Purpose

Valuation is allowed only after the company independently passes:

```text
Balance Sheet Safety
CDC
Through Return
Business Quality
```

The valuation engine answers a narrower question:

> At what market value and share price does an already-qualified business offer a sufficient margin of safety?

The engine should avoid relying primarily on PE/PB/PEG and instead anchor valuation to owner-realizable cash, normalized Core CDC, sustainable shareholder return and business durability.

---

## 2. Core valuation anchors

### 2.1 CDC hurdle valuation

For a required CDC yield `Y_cdc`:

\[
MaxMarketCap_{CDC} = \frac{NormalizedParentCoreCDC}{Y_{cdc}}
\]

Example hurdle set to design/backtest:

```text
12% -> extreme safety / very cheap
10% -> strict turtle entry
8%  -> acceptable candidate threshold
```

### 2.2 Through-return hurdle valuation

Let normalized expected recurring shareholder cash return be:

\[
ExpectedShareholderReturnCash = DistributableBase \times CPR
\]

with net share reduction handled separately or translated to economic ownership return.

For required through-return hurdle `Y_tr`:

\[
MaxMarketCap_{TR} = \frac{ExpectedRecurringShareholderReturn}{Y_{tr}}
\]

The precise treatment of buybacks in price-target calculations remains to be finalized.

### 2.3 Cash-adjusted operating valuation

\[
AdjustedEV = MarketCap - ValuationNetCash
\]

\[
ExCashCDCYield = \frac{NormalizedParentCoreCDC}{AdjustedEV}
\]

This view asks what price the market is effectively assigning to the operating business after conservatively crediting realizable cash.

If `AdjustedEV <= 0`, switch to a dedicated `NET_NET_SPECIAL_CASE` model rather than reporting meaningless infinite yields.

---

## 3. Price tiers to produce

The final valuation module should output at least four price levels:

```text
Observation Price
Fair / Acceptable Price
Turtle Entry Price
Extreme Safety Price
```

Proposed semantics:

### Observation Price

Business is high quality but valuation still fails at least one strict hurdle. Worth monitoring, not purchasing under the strict model.

### Fair / Acceptable Price

Meets minimum formal hurdles (for example CDC >= 8% and Through Return >= 5%) but margin of safety is not unusually wide.

### Turtle Entry Price

Meets stricter cash-return hurdles (candidate baseline to test: CDC >=10%) while preserving all other hard gates.

### Extreme Safety Price

Very wide margin of safety, potentially characterized by CDC >=12%, thick owner-realizable net cash and high shareholder return.

These are strategy definitions and require historical validation before finalization.

---

## 4. Combining valuation constraints

The engine should not average independent valuation limits.

Baseline conservative rule:

\[
MaxAcceptableMarketCap = min(
MaxMarketCap_{CDC},
MaxMarketCap_{TR},
OtherValidatedCaps
)
\]

This preserves the hard-gate philosophy: valuation must satisfy each required return constraint rather than allowing one strong dimension to compensate for another weak one.

---

## 5. From market cap to share price

For a normalized fully diluted share count:

\[
TargetPrice = \frac{TargetMarketCap}{NormalizedDilutedShares}
\]

The engine must adjust for:

- dual listings / fungibility where relevant;
- treasury shares;
- material options/RSUs;
- convertibles likely to dilute;
- stock splits / consolidations;
- H-share vs total-company ownership structure.

Share-count normalization must be auditable.

---

## 6. Quality premium: intentionally disabled in v1

A future version may permit:

\[
RequiredCDCYield = BaseYield - QualityAdjustment
\]

But the strict v1 model should **not** lower hurdle rates merely because a company has a high Business Score.

Reason:

> This is the easiest way for the framework to drift back into “great company at any price.”

For v1, business quality and valuation pass independently.

---

## 7. Risk-free-rate adaptation: future extension

Potential later design:

\[
RequiredReturn = max(FixedFloor, R_f + RequiredSpread)
\]

This may apply to Through Return and/or CDC hurdle rates, but must be validated by backtest and regime analysis before replacing fixed strict-mode thresholds.

---

## 8. Net-net / negative EV handling

If:

\[
OwnerRealizableNetCash > MarketCap
\]

or:

\[
AdjustedEV \le 0
\]

flag:

```text
NET_NET_SPECIAL_CASE
```

Do not auto-upgrade the company to `PASS`.

Mandatory investigation:

- Is cash real and unrestricted?
- Can shareholders access it?
- Is the operating business destroying cash?
- Are there hidden liabilities?
- Is governance poor?
- Is the business structurally dying?
- Are legal/regulatory risks material?

Only positive normalized CDC + acceptable governance + credible cash realizability can move such a company into a deep-value priority pool.

---

## 9. Valuation consistency checks

The engine should reject internally contradictory valuations.

Examples:

```text
Target price implies CDC Yield below configured minimum -> invalid
Target price implies Through Return below configured minimum -> invalid
Target price assumes more cash than OwnerRealizableNetCash -> invalid
Target price uses single-year peak earnings for cyclical company -> invalid
```

---

## 10. Planned outputs

```json
{
  "current_market_cap": null,
  "current_price": null,
  "normalized_diluted_shares": null,
  "valuation_net_cash": null,
  "adjusted_ev": null,
  "max_market_cap_cdc_8": null,
  "max_market_cap_cdc_10": null,
  "max_market_cap_cdc_12": null,
  "max_market_cap_through_return": null,
  "observation_market_cap": null,
  "acceptable_market_cap": null,
  "turtle_entry_market_cap": null,
  "extreme_safety_market_cap": null,
  "observation_price": null,
  "acceptable_price": null,
  "turtle_entry_price": null,
  "extreme_safety_price": null,
  "margin_of_safety": null,
  "flags": [],
  "confidence": "HIGH|MEDIUM|LOW"
}
```

---

## 11. Open design questions

The next iteration should resolve these explicitly:

1. Should CDC hurdle valuation use total market cap or cash-adjusted EV as the primary anchor?
2. How should net buyback yield translate into a target market cap without double-counting value already embedded in CDC?
3. Should Through Return hurdle be fixed at 5% or dynamic versus the risk-free rate?
4. Should different business-quality tiers receive different required returns, or should strict mode keep a universal hurdle?
5. How should cyclical companies derive target prices from full-cycle CDC?
6. How should state-owned enterprises with persistent excess cash but limited payout flexibility be discounted?
7. How should H-share/A-share dual listings and different market prices be handled while keeping one underlying company valuation?
8. How should special dividends and asset disposals affect one-time entry value without contaminating normalized recurring return?

These questions must be settled before implementation is considered stable.