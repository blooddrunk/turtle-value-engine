# Frozen normalized-input fixtures

These eight JSON files are fully offline, synthetic normalized inputs for the
deterministic engine. They contain only source-side facts, evidence, explicit
adjustments and data-quality metadata. They intentionally do not contain
metrics, gates, valuation results or decisions.

`expectations.json` is kept separate from the raw inputs. Its scenario notes
describe the intended rule coverage and review risks; they are not engine
outputs and do not claim that the not-yet-implemented modules have validated
those scenarios.

| Fixture | Purpose | Expected review/risk focus |
| --- | --- | --- |
| `healthy_cash_cow.json` | Stable positive CDC, strong cash safety, recurring dividends and genuine net share reduction. | Baseline pass path; CDC normalization, net cash, through return and valuation tier inputs. |
| `high_dividend_bad_cashflow.json` | High reported profit/dividends with negative Core CDC after maintenance capex and one-off inflow removal. | Bad cash-flow quality; payout cannot rescue a failed CDC gate. |
| `cash_rich_dying_business.json` | Large apparent cash balance with declining revenue/CDC and unresolved restricted or trapped cash. | Cash-box/liquidation review; structural decline and explicit `null` missing data. |
| `excellent_business_too_expensive.json` | Strong operating history and business evidence paired with a market cap above strict return ceilings. | Quality is separate from price; expected too-expensive state. |
| `leveraged_dividend_trap.json` | Positive but thin CDC, high dividend, debt equivalents, supplier finance and weak coverage. | Leverage, interest coverage, refinancing dependency and hard-gate precedence. |
| `negative_ev_governance_risk.json` | Verified excess cash exceeds market cap, while governance and related-party risks are severe. | Negative-EV special case; cash governance haircut and manual review. |
| `cyclical_peak_false_cheap.json` | Seven-year trough-to-peak cycle with the latest period at peak conditions. | Full-cycle median normalization; do not capitalize peak CDC. |
| `share_dilution_offsets_buyback.json` | Large recurring buybacks coexist with rising fully diluted shares from issuance. | Net share reduction and buyback-credit guard; headline buybacks are insufficient. |

All monetary values use synthetic CNY millions unless a fact's `unit` says
otherwise. Evidence sources use `OTHER` with stable local fixture locators;
they are not network URLs or claims about real issuers.

The metadata-only fixture at `filings/discovery_a_h.json` is separate from
these normalized-input fixtures. It supplies deterministic CNINFO and HKEXnews
source-client rows for the Phase 3.84 discovery tests, contains no document
body and is not an evidence-store fixture.
