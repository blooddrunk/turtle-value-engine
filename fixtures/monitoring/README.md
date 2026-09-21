# Phase 6-A monitoring fixtures

Deterministic, offline fixtures for the watchlist/event planning foundation.

- `watchlist-basic.json` — valid watchlist: two enabled listings plus one
  disabled entry (`000001.SZ`).
- `watchlist-invalid-duplicate.json` — duplicate listing identity; must be
  rejected by validation.
- `events-basic.json` — canonical event batch input covering: an annual
  report and a regulatory penalty for `600519.SH` (same source), an interim
  report for `HK00288`, one future event beyond the fixture `as_of`, one
  event for the disabled entry, and one event for a listing outside the
  watchlist.

These files intentionally contain raw event payloads without derived
`content_sha256` fields; the engine computes canonical identities.
