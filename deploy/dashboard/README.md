# Project runtime configuration and M6-C2 private Dashboard deployment

The project-wide runtime configuration is
[`config/project.example.toml`](../../config/project.example.toml). Copy it to
`.tve-private/project.toml` and extend that same file in later phases; do not
create a phase-specific environment file. It contains only non-secret values
and names of environment variables/secret-manager references.

Create it with:

```bash
tve config init
tve config validate
```

For this M6-C2 package, the only values normally needed in the file are:

```toml
[surface]
snapshot_path = ".tve-private/surface/research-surface.json"

[cloudflare]
zone_name = "your-domain.example"
dashboard_access_email = "you@example.com"
```

The Dashboard hostname (`dashboard.<zone>`), origin hostname
(`surface.<zone>`), account/zone IDs, Tunnel name and Access application names
are derived from this configuration. Explicit values remain available when an
owner has an existing non-default resource. Environment variables override
the file for CI or a one-off run.

The checked-in Dashboard Wrangler config explicitly disables `workers.dev` and
preview URLs; `scripts/dashboard_deploy.py` generates the final custom-domain
config from the exact built commit and refuses an implicit deployment.

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

## One Cloudflare API token

Create one custom Cloudflare API token named
`tve-private-dashboard-deployer` and restrict it to the account and zone that
contain this project. In the current Cloudflare token editor, select:

Account permissions:

- `Access: Apps and Policies` — `Edit` (Cloudflare may display the newer
  equivalent `Write`);
- `Access: Service Tokens` — `Edit`/`Write`;
- `Cloudflare Tunnel` — `Edit`/`Write`;
- `Workers Scripts` — `Edit`/`Write`.

Zone permissions, restricted to the selected zone:

- `Zone` — `Read`;
- `DNS` — `Edit`/`Write`;
- `Workers Routes` — `Edit`/`Write`.

Put the one-time token value in the deployment host's secret manager or
environment under exactly `CLOUDFLARE_API_TOKEN`. Do not put it in TOML, Git,
chat, command-line arguments, logs or a browser. Cloudflare shows a token
secret only once.

The two Access service-token pairs are not Cloudflare API tokens. Once the API
token is available, Codex creates/names them as follows and uses the returned
one-time secrets only through the configured secret manager/environment:

- `tve-private-dashboard-origin`: Worker → origin;
- `tve-private-dashboard-smoke`: automated live smoke → Dashboard.

Their references are already in `[cloudflare.secret_refs]`; no client ID,
client secret, account ID, zone ID or Tunnel UUID needs to be guessed or
written into the project file. The API token and all other secret references
are read only at runtime and are never printed or committed.

The deployment tool resolves account/zone IDs from the configured zone using
read-only Cloudflare API calls before any POST/PUT/secret mutation. It rejects
incomplete route listings or legacy Worker routes that could provide an
alternate Dashboard ingress. It cannot infer the owner's zone name, approved
interactive email, or which validated snapshot should be served; those are
the three real project facts in the template.

## Reproducible commands

Run from the repository root, after the API token reference is loaded:

```bash
python3 scripts/dashboard_deploy.py preflight --project-config .tve-private/project.toml
python3 scripts/dashboard_deploy.py deploy --project-config .tve-private/project.toml --dry-run
python3 scripts/dashboard_deploy.py deploy --project-config .tve-private/project.toml --apply
python3 scripts/dashboard_deploy.py verify --project-config .tve-private/project.toml
python3 scripts/dashboard_live_smoke.py --project-config .tve-private/project.toml
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
cloudflared tunnel \
  --config /etc/cloudflared/tve-surface-config.yml \
  ingress validate
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
