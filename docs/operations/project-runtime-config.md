# Project runtime configuration

`config/project.example.toml` is the single project-level runtime template.
Copy it to `.tve-private/project.toml`; the private copy is ignored by Git and
is reused by later phases. It is intentionally separate from `rules/strict-v1`
and cannot change investment calculations.

## What the owner supplies

Edit only these facts for the first private Dashboard deployment:

```toml
[surface]
snapshot_path = ".tve-private/surface/research-surface.json"

[cloudflare]
zone_name = "your-domain.example"
dashboard_access_email = "you@example.com"
```

`zone_name` is the root zone already managed in the owner's Cloudflare account,
not a hostname to invent. `dashboard_access_email` is the identity that should
be allowed by the interactive Access policy. `snapshot_path` is the explicit,
already validated `ResearchSurfaceSnapshotV1` that the origin is authorized to
serve. The repository cannot safely infer any of those three facts.

The following are derived or discovered automatically:

- `tve-private-dashboard.<zone_name>` and `tve-private-surface.<zone_name>`;
- account ID and zone IDs through read-only Cloudflare API lookup;
- Tunnel and Access application names:
  `tve-private-dashboard-origin`, `tve-private-dashboard` and
  `tve-private-surface-origin`;
- the snapshot `surface_id` and `content_sha256` for an in-process live smoke.

Explicit IDs/hostnames may be added later to the same file when an existing
Cloudflare layout requires them.

## The one API token to create

In Cloudflare, create a custom API token named
`tve-private-dashboard-deployer`. Scope it to the relevant account and only the
zone in `zone_name`.

Select these account permissions:

- `Access: Apps and Policies` — `Edit` (or the UI's equivalent `Write`);
- `Access: Service Tokens` — `Edit`/`Write`;
- `Cloudflare Tunnel` — `Edit`/`Write`;
- `Workers Scripts` — `Edit`/`Write`.

Select these zone permissions for the selected zone:

- `Zone` — `Read`;
- `DNS` — `Edit`/`Write`;
- `Workers Routes` — `Edit`/`Write`.

Store the generated one-time secret in the deployment host's secret manager or
environment under `CLOUDFLARE_API_TOKEN`. Never put it in the TOML file, Git,
chat, a command argument, a log or the Dashboard bundle. Cloudflare documents
that the token secret is shown only once; its current [token creation
guide](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)
and [permission reference](https://developers.cloudflare.com/fundamentals/api/reference/permissions/)
are the authoritative UI names.

### Injecting the token without exposing it

The repository reads the token only from the process environment. On the
current Linux/zsh deployment host, the simplest one-time setup is:

```bash
cd /home/jelinenaro/research/turtle-value-engine
umask 077
read -r -s 'token?Cloudflare API token (input is hidden): '
printf '\n'
printf '%s' "$token" > .tve-private/cloudflare.token
unset token
chmod 600 .tve-private/cloudflare.token
```

The ignored `.tve-private/cloudflare.token` file is only a local secret
handoff file; it is not read by application code and is never committed. When
running a command, inject it for that process only:

```bash
export CLOUDFLARE_API_TOKEN="$(<.tve-private/cloudflare.token)"
```

Do not run `echo "$CLOUDFLARE_API_TOKEN"`, `env`, or a verbose shell trace.
Verify presence without printing the value:

```bash
if [[ -n "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  echo "CLOUDFLARE_API_TOKEN is set (value hidden)"
else
  echo "CLOUDFLARE_API_TOKEN is absent"
fi
```

An external secret manager is preferred for a persistent host. Its retrieval
command should populate the same environment variable; the TOML file still
contains only `{ env = "CLOUDFLARE_API_TOKEN" }`. Do not paste the token into
chat. Once the variable is available to the Codex execution environment, the
deployment checks below are run automatically.

The Access client ID/secret pairs used by the Worker and smoke are service
tokens, not Cloudflare API tokens. With the API token available, the deployment
helper can create them with the names above and consume newly generated
one-time secrets in memory during `--live-smoke`. Cloudflare's [service token
documentation](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
confirms that the client secret is displayed only at creation time.

## Commands

```bash
tve config init
# edit .tve-private/project.toml
tve config validate
export CLOUDFLARE_API_TOKEN='loaded-from-your-secret-manager'
python3 scripts/dashboard_deploy.py preflight --project-config .tve-private/project.toml
python3 scripts/dashboard_deploy.py deploy \
  --project-config .tve-private/project.toml \
  --dry-run
python3 scripts/dashboard_deploy.py deploy \
  --project-config .tve-private/project.toml \
  --apply \
  --create-tunnel \
  --create-origin-service-token \
  --create-dashboard-service-token \
  --live-smoke
```

The last command performs all resource/API/Tunnel/secret operations available
to the token, and refuses to print generated secrets. The origin process still
must be running with the explicit snapshot and remain bound to `127.0.0.1`; a
Cloudflare Tunnel connector must be running on that origin host. Codex checks
the connector ingress and runs the machine-verifiable live smoke whenever the
connector is reachable. The final interactive Access/IdP browser check remains
the only owner interaction specified by M6-C2.
