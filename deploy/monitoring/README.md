# Phase 6-D2A unattended runner reference deployment

These files are a **reference template only**. The real owner host, user,
paths, cadence and any credentials are Phase 6-E acceptance inputs and are
deliberately absent from this repository.

## Units

- `turtle-value-monitor.service` — a `Type=oneshot` unit that runs only the
  non-interactive CLI:

  ```text
  python3 -m turtle_value_engine watch unattended-run --runner-config <path>
  ```

  It exits `0` when the wake ended with a terminal runner receipt
  (`COMPLETED_NEW`, `COMPLETED_RESUMED`, `COMPLETED_REPAIRED` or
  `COMPLETED_REUSED`), `3` when another live invocation owned the lease
  (`LEASE_BUSY`, no work performed — treated as success by the unit), and
  `2` on fail-closed errors.

- `turtle-value-monitor.timer` — a `Persistent=true` daily timer with a
  randomized delay. `Persistent=true` makes a missed activation (host was
  off) run once when the host comes back; the runner's durable activation
  semantics, not the timer, guarantee no duplicated D1 work.

## Non-credentials

Neither unit nor the runner configuration contains credentials. The runner
config (`config/monitoring-runner.example.json`) holds only non-secret paths
and explicit policy flags. Live CNINFO acquisition still requires the
explicit `network_allowed` policy flag; offline cache replay is the default
template mode.

## Verify the units

```bash
systemd-analyze verify deploy/monitoring/turtle-value-monitor.service \
  deploy/monitoring/turtle-value-monitor.timer
```

This runs in ordinary CI (`.github/workflows/ci.yml`).

## Install (Phase 6-E, automated)

Do not hand-edit these reference units. Phase 6-E provides
`scripts/monitoring_live_acceptance.py`, which renders owner-specific units
from one explicit non-secret acceptance configuration
(`config/monitoring-acceptance.example.json` is the checked-in template;
the real file lives under `.tve-private/`), validates them with
`systemd-analyze verify`, and installs/enables them when it has enough
privilege:

```bash
python3 scripts/monitoring_live_acceptance.py --acceptance-config <config> gate
python3 scripts/monitoring_live_acceptance.py --acceptance-config <config> preflight
python3 scripts/monitoring_live_acceptance.py --acceptance-config <config> render
python3 scripts/monitoring_live_acceptance.py --acceptance-config <config> apply     # or the printed owner commands
python3 scripts/monitoring_live_acceptance.py --acceptance-config <config> verify
python3 scripts/monitoring_live_acceptance.py --acceptance-config <config> live-smoke --network allow
python3 scripts/monitoring_live_acceptance.py --acceptance-config <config> disable   # stop the acceptance timer
```

`apply` enables the timer without starting it by default so the first
classification is deterministic; `live-smoke` starts the timer itself when it
observes the cadence fire (or pass `apply --start-timer` for production
behaviour).

`scope = "user"` renders/installs user-level units (no root required);
`scope = "system"` renders system units and, without non-interactive
privilege, stops at the exact `MANUAL_SUDO_INSTALL_REQUIRED` commands.  The
helper verifies the effective installed state through `systemctl show`
(after any owner command) — a successful manual command is never itself
acceptance evidence.

The lease, activation and receipt state live under the runner root declared
in the runner config; nothing else on the host is mutated by the runner.
