# M6-C2 private Dashboard deployment

This directory contains non-secret production templates. The checked-in
Dashboard Wrangler config explicitly disables `workers.dev` and preview URLs;
`scripts/dashboard_deploy.py` generates the final custom-domain config from the
exact built commit and refuses an implicit deployment.

The intended topology is:

```text
owner browser
  -> Access-protected Dashboard hostname
  -> Dashboard Worker /api/* allowlist
  -> HTTPS Access-protected surface hostname
  -> Cloudflare Tunnel
  -> http://127.0.0.1:8787
  -> tve surface serve --snapshot <explicit-file>
```

On the origin host, start only the explicit M6-B snapshot surface:

```bash
python3 scripts/dashboard_deploy.py origin \
  --snapshot /srv/turtle-value-engine/research-surface.json \
  --port 8787
```

The process remains bound to `127.0.0.1`. Never change this command to
`0.0.0.0` for Tunnel connectivity. The example Tunnel ingress maps exactly one
public hostname to that loopback port and ends with `http_status:404`.

## Owner-authorized inputs

Populate the non-secret values in `production.env.example` through the host's
environment or secret manager. The following secret names are read only from
runtime environment references and are never printed or committed:

- `CLOUDFLARE_API_TOKEN` — API token with the minimum Worker, Access, Tunnel
  and DNS permissions needed by the command;
- `SURFACE_API_ACCESS_CLIENT_ID` and
  `SURFACE_API_ACCESS_CLIENT_SECRET` — the Worker-to-origin Access service
  token pair;
- `TVE_DASHBOARD_ACCESS_CLIENT_ID` and
  `TVE_DASHBOARD_ACCESS_CLIENT_SECRET` — a separate service-token pair used by
  the automated live smoke. The Dashboard Access application also has the
  owner-selected interactive email policy from `TVE_DASHBOARD_ACCESS_EMAIL`.

The account ID, zone ID, hostnames, Tunnel ID/name, snapshot path and approved
interactive identity are owner-specific facts. The deployment tool validates
them before any POST/PUT/secret mutation. It does not infer an email, domain,
account, Tunnel, snapshot, or token from chat or repository contents.

## Reproducible commands

Run from the repository root, after the runtime references are loaded:

```bash
python3 scripts/dashboard_deploy.py preflight
python3 scripts/dashboard_deploy.py deploy --dry-run
python3 scripts/dashboard_deploy.py deploy --apply
python3 scripts/dashboard_deploy.py verify
python3 scripts/dashboard_live_smoke.py
```

`deploy --apply` creates/updates only the named Dashboard Access application,
the named origin service-auth application, the named remotely-managed Tunnel
ingress, the named origin CNAME and the named Worker secrets. It performs
read-only Cloudflare permission/resource checks and a Wrangler dry-run before
any live mutation. `--create-tunnel` and
`--create-origin-service-token` are explicit opt-ins; a missing service-token
pair is never silently replaced.

For a local-management Tunnel, validate the checked-in shape on the origin
host before running it:

```bash
cloudflared tunnel ingress validate \
  --config /etc/cloudflared/tve-surface-config.yml
cloudflared tunnel run <tunnel-uuid>
```

The remote-management path writes the same loopback-only ingress through the
Cloudflare API and then the origin host still needs its authorized
`cloudflared` connector process. A connector token is not stored in Git or
printed by this repository.

`dashboard_live_smoke.py` sends service-token headers only from its process
memory. It verifies unauthenticated Dashboard and origin blocking, authenticated
origin `/healthz`, same-origin Dashboard health/list/detail, identity/hash
preservation, unknown `404`, mutation `405`, and `ETag`/`304`. Alternate URLs
can be supplied through `TVE_ALT_DASHBOARD_URLS` and `TVE_ALT_ORIGIN_URLS`; the
resource verifier separately fails if `workers.dev`, preview URLs, extra Worker
domains, or extra Tunnel ingress entries remain enabled.

M5-C/R2 remains deferred: the persistent M6-B origin serves the existing
validated surface directly, so remote artifact mirroring is not required by
this deployment.
