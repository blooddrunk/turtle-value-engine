# Owner Provenance Operations — Practical Local Walkthrough (Phase 7-C3-B)

This is the optional real-owner procedure for the personal-research
provenance workflow. It is documentation, **not** a prerequisite for
development/test closure — the automated end-to-end tests
(`tests/test_owner_trust_operations.py`) prove the same code paths with
throwaway runtime-generated Ed25519 keys.

Nothing here ever puts a private key into the repository, Git, chat, CI
logs or any persisted artifact. The engine only ever sees public key
material and detached signatures.

## 0. Prerequisites

```bash
cd ~/research/turtle-value-engine
python -m pip install --user ".[provenance]"   # or your established install
```

All commands below assume `python -m turtle_value_engine` (abbreviated
`tve`). Create the working directories **outside the repository** first,
then confirm where they live before proceeding:

```bash
mkdir -p ~/tve-trust/trust-root ~/tve-trust/bundle ~/tve-trust/decisions \
         ~/tve-trust/evidence
mkdir -m 700 ~/tve-trust/private
ls -ld ~/tve-trust/*   # every path printed must be outside the repository;
                       # private must print mode drwx------ (0700)
realpath ~/tve-trust   # resolve symlinks; use a plain directory, not one
                       # inside ~/research/turtle-value-engine
```

```text
~/tve-trust/trust-root/     the trust root (registry snapshots; nothing else)
~/tve-trust/bundle/         one submission bundle (decision input, statement,
                            exception, your public key)
~/tve-trust/private/        the ENCRYPTED private key (never committed anywhere)
~/tve-trust/decisions/      recorded decision records and plans
~/tve-trust/evidence/       captured proof bundles
```

The CLI refuses a trust root located inside a submitted decision bundle
directory (and decision artifacts stored inside the trust root) — a bundle
can never smuggle its own trust root.

## 1. Generate an owner key and persist it ENCRYPTED, outside the repository

The private key is generated once, written as an **encrypted PKCS#8 PEM**
(passphrase prompted interactively, never on the command line), and reloaded
from that file by every later signing run — including after a process
restart or reboot. The key file is created **exclusively** (`O_CREAT |
O_EXCL`, refusing any existing path or symlink destination) with mode
**0600 from the first open**, independent of your `umask`, and the private
directory is forced to 0700. Nothing below ever puts a private key into the
repository, Git, CI logs or chat.

```bash
python - <<'EOF'
import base64, getpass, os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PRIVATE_DIR = Path.home() / "tve-trust/private"
PRIVATE_PEM = PRIVATE_DIR / "owner.pem"
PUBLIC_KEY  = Path.home() / "tve-trust/bundle/owner.pub"

PRIVATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(PRIVATE_DIR, 0o700)  # also repairs a pre-existing loose directory

key = Ed25519PrivateKey.generate()
passphrase = getpass.getpass("New private-key passphrase: ").encode("utf-8")
pem = key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.BestAvailableEncryption(passphrase),
)
try:
    # One-time exclusive create: refuses an existing file OR symlink
    # destination atomically, and is owner-only from the first byte.
    descriptor = os.open(
        PRIVATE_PEM,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
except FileExistsError:
    raise SystemExit(
        f"refusing to overwrite {PRIVATE_PEM}: an owner key is write-once; "
        "move the existing file aside yourself first if you really mean to"
    )
with os.fdopen(descriptor, "wb") as handle:
    handle.write(pem)
    handle.flush()
    os.fsync(handle.fileno())
PUBLIC_KEY.parent.mkdir(parents=True, exist_ok=True)
PUBLIC_KEY.write_text(base64.b64encode(
    key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
).decode() + "\n")
print("wrote", PRIVATE_PEM, "and", PUBLIC_KEY)
EOF
ls -l ~/tve-trust/private/owner.pem   # must print: -rw------- (0600)
head -1 ~/tve-trust/private/owner.pem   # must print:
                                         # -----BEGIN ENCRYPTED PRIVATE KEY-----
```

Back the `owner.pem` file and its passphrase up in your password manager /
offline medium NOW; the passphrase cannot be recovered. Only `owner.pub`
(public key material) is ever registered with the engine. A hardware
security key that supports Ed25519 may replace the encrypted PEM; keep the
same generate-then-reload discipline either way.

This whole procedure — encrypted on-disk key, fresh-process reload, sign,
capture, replay — is executed automatically with throwaway keys and a
throwaway passphrase by
`tests/test_owner_evidence_replay_integrity.py::test_walkthrough_encrypted_key_round_trip_across_processes`.

## 2. Register only the public key (create the trust root)

```bash
tve provenance registry init \
  --trust-root ~/tve-trust/trust-root \
  --public-key ~/tve-trust/bundle/owner.pub \
  --owner-identity "Your Name" \
  --valid-from 2026-01-01 --valid-until 2026-12-31
```

Output includes the derived `key_id` (keep it; revocation/rotation name
it). Later lifecycle:

```bash
tve provenance registry enroll   --trust-root ... --public-key new.pub --owner-identity ... --valid-from ... --valid-until ...
tve provenance registry rotate   --trust-root ... --old-key-id <id> --reference "routine rotation" --public-key new.pub --owner-identity ... --valid-from ... --valid-until ...
tve provenance registry revoke   --trust-root ... --key-id <id> --reference "key compromised"
tve provenance registry status   --trust-root ...
```

Every operation appends one immutable versioned snapshot
(`snapshots/snapshot-00000N.json`, full-content SHA-256 chained to its
parent); committed snapshots are never rewritten, and every load validates
the whole chain.

## 3. Sign an exact decision payload (reload the encrypted key)

1. Produce the decision input JSON (fields listed in
   `docs/architecture/owner-policy-decision-and-activation-plan.md`; take
   the audit id/content hash from a fresh
   `tve evolution audit-profile`/`decision-dossier` run).
2. Serialize it canonically, sign the domain-prefixed message, assemble
   the statement — a short script, run where the encrypted key file lives.
   The key is reloaded from disk with the passphrase prompted again, so a
   fresh process (or a later day) signs with exactly the same persisted
   key:

```python
import getpass, json
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from turtle_value_engine.evolution.owner_decision import OwnerPolicyDecisionInputV1
from turtle_value_engine.evolution.owner_provenance import (
    build_owner_signed_decision_statement,
    owner_decision_input_signature_message,
)
from turtle_value_engine.providers.models import canonical_json_bytes

private = serialization.load_pem_private_key(
    (Path.home() / "tve-trust/private/owner.pem").read_bytes(),
    getpass.getpass("Private-key passphrase: ").encode("utf-8"),
)
key_id = ...   # from `tve provenance registry status`

payload = json.loads((Path.home() / "tve-trust/bundle/decision-input.json").read_text("utf-8"))
model = OwnerPolicyDecisionInputV1.model_validate(payload)
(Path.home() / "tve-trust/bundle/decision-input.json").write_bytes(
    canonical_json_bytes(model.model_dump(mode="json"))  # canonical byte form only
)
statement = build_owner_signed_decision_statement(
    signature=private.sign(owner_decision_input_signature_message(model)),
    key_id=key_id,
    decision_input=model,
)
(Path.home() / "tve-trust/bundle/statement.json").write_text(
    json.dumps(json.loads(statement.model_dump_json()), indent=2, sort_keys=True) + "\n"
)
```

## 4. Capture (record with real verification + evidence bundle)

```bash
tve evolution record-decision \
  --decision-input ~/tve-trust/bundle/decision-input.json \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json \
  --policy-exception ~/tve-trust/bundle/exception.json \
  --signed-statement ~/tve-trust/bundle/statement.json \
  --trust-root ~/tve-trust/trust-root \
  --evidence-root ~/tve-trust/evidence \
  --record-output ~/tve-trust/decisions/record.json
```

Expected: exit 0, `validation.state=VALID`,
`record.authority.authority_status=OWNER_AUTHORITY_VERIFIED`, and a proof
bundle under `evidence/<bundle_id>/` containing the exact decision-input
bytes, the statement, the trust-root snapshot used, the verification
dossier and the record. Without `--signed-statement/--trust-root` the very
same command records visibly unverified decisions exactly as before.

## 5. Re-verify captured evidence offline (any time)

```bash
tve provenance verify-evidence --bundle ~/tve-trust/evidence/<bundle_id>/bundle.json
```

Exit codes:

| exit | meaning |
| --- | --- |
| 0 | `REPLAYS_BYTE_IDENTICAL` — every persisted component (decision-input bytes, statement, registry snapshot and its internal registry identity, `verification.json`, and `record.json` for a record-bearing bundle) matches the manifest binding, the recomputed dossier equals the captured one byte-for-byte, the record embeds the owner-signed decision fields verbatim, and the captured authority claims are consistent with the recomputed verification facts |
| 1 | `MISMATCH` — the replay completed and names the divergences (e.g. `RECORD_FILE_DIVERGED`, `VERIFICATION_FILE_DIVERGED`, `REGISTRY_IDENTITY_DIVERGED`, `RECORD_SIGNED_CONTENT_DIVERGED`, `AUTHORITY_STATUS_INCONSISTENT`, `ATTESTED_KEY_DIVERGED`, `ATTESTED_REGISTRY_DIVERGED`, `EVIDENCE_HASH_DIVERGED`, `VALID_STATE_WITH_BLOCKERS`) |
| 2 | classified fail-closed store error — a component is missing, unexpected (e.g. a `record.json` inside an INVALID no-record bundle), symlinked, unparseable, or the bundle path is unusable |

`REPLAYS_BYTE_IDENTICAL` is an **integrity and capture-coherence**
statement only, never an authorization: it also holds for an honestly
captured `REJECTED` bundle (a signature that failed at capture time stays
honestly rejected), and a record claiming `OWNER_AUTHORITY_VERIFIED` over a
signature whose recomputed verification is `REJECTED` can never replay
clean. A later `plan-activation` still re-attests the signature freshly
against the trust root's *current* latest snapshot. No network is involved
at any point.

## 6. Derive the read-only activation plan

```bash
tve evolution plan-activation \
  --base-profile rules/strict-v1.yaml \
  --target-profile rules/strict-v2.yaml \
  --release-manifest docs/releases/strict-v2/release-candidate.json \
  --policy-exception ~/tve-trust/bundle/exception.json \
  --decision-record ~/tve-trust/decisions/record.json \
  --project-config .tve-private/project.toml \
  --trust-root ~/tve-trust/trust-root \
  --authority-evidence ~/tve-trust/evidence/<bundle_id>/bundle.json \
  --output ~/tve-trust/decisions/plan.json
```

Authority is re-attested **fresh** against the trust root's *current*
latest snapshot: if the key was revoked or rotated in the meantime, the
plan is BLOCKED (exit 1) with `OWNER_AUTHORITY_REVERIFICATION_*`. A READY
plan still fixes `execution_performed=false` /
`automatic_activation_allowed=false` — it is authorization evidence, never
an execution.

## 7. Signed revocation / supersession of a decision (optional)

To withdraw a recorded decision (or replace it with a newer one), sign the
matching payload outside the repository and pass the assembled evidence to
the plan:

```python
from turtle_value_engine.evolution.owner_lifecycle import (
    OwnerRevocationPayloadV1,
    build_owner_signed_revocation_statement,
    owner_revocation_signature_message,
)
payload = OwnerRevocationPayloadV1.model_validate({
    "contract": "owner_signed_revocation_payload_v1",
    "revoked_decision_record_id": "<record id>",
    "revoked_record_content_sha256": "<record content_sha256>",
    "target_profile_id": "strict-v2",
    "target_profile_sha256": "adba44b7...<full hash>",
    "revoked_by": "Your Name",
    "revoked_at": "2026-10-15",
    "rationale": "At least twenty characters of withdrawal rationale.",
    "source_revision": "your-revision-label",
})
statement = build_owner_signed_revocation_statement(
    signature=private.sign(owner_revocation_signature_message(payload)),
    key_id=key_id,
    payload=payload,
)
Path("signed-revocation.json").write_text(
    json.dumps({"payload": json.loads(payload.model_dump_json()),
                "statement": json.loads(statement.model_dump_json())},
               indent=2, sort_keys=True) + "\n")
```

Then `tve evolution plan-activation ... --signed-revocation
<path.json>` (supersession: same pattern with
`OwnerSupersessionPayloadV1`, binding BOTH records by id and content
hash). Verification is fresh against the trust root inside the plan; an
unsigned withdrawal still never increases authorization.

## 8. Revoking trust itself

`tve provenance registry revoke --key-id ... --reference ...` appends a
snapshot in which the key is revoked. Every future verification (record
capture, plan re-attestation, lifecycle statements) under that trust root
fails closed for that key. Already-captured evidence remains auditable and
still replays byte-identically — the snapshot inside each bundle records
the trust content that was valid *at capture time*.

## Failure handling

| symptom | meaning |
| --- | --- |
| `OWNER_PROVENANCE_SOURCE_BYTES_MISMATCH` | submitted bytes are not the exact signed canonical bytes (re-serialize canonically, re-sign) |
| `SIGNATURE_VERIFIED` failed in dossier | signature/key mismatch — wrong key, tampered bytes, or cross-purpose replay |
| `trust root must not be located inside the submitted decision bundle directory` | separate the trust root from the bundle (by design) |
| `trust root has no snapshots directory` | `--trust-root` does not point at an initialized store (`registry init` first) |
| verify-evidence exit 1, `*_DIVERGED` / `*_INCONSISTENT` mismatch | a persisted component or captured authority claim is valid-looking but disagrees with the manifest binding or the recomputed verification facts — inspect which divergence the code names; evidence directories are immutable, so recapture rather than edit |
| verify-evidence exit 2, `missing components` / `unexpected entries` / `symlink` | the bundle directory no longer holds exactly its six-file (VALID) or five-file (INVALID) component shape |
| keygen refuses to overwrite `owner.pem` | an owner key is write-once by design; move the existing file aside yourself first, or choose a different key file |
| plan BLOCKED `OWNER_AUTHORITY_REVERIFICATION_REQUIRED` | plan run without `--trust-root`/`--authority-evidence` |
| plan BLOCKED `SIGNED_REVOCATION_REJECTED:*` | the signed lifecycle statement failed fresh verification |
