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

## Install (Phase 6-E, owner-operated)

Copy both units to `/etc/systemd/system/`, adjust the `WorkingDirectory`,
`ExecStart` paths and the timer calendar, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now turtle-value-monitor.timer
```

The lease, activation and receipt state live under the runner root declared
in the runner config; nothing else on the host is mutated by the runner.
