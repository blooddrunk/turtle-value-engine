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
`tve`). Choose three directories **outside the repository**:

```text
~/tve-trust/trust-root/     the trust root (registry snapshots; nothing else)
~/tve-trust/bundle/         one submission bundle (decision input, statement,
                            exception, your public key)
~/tve-trust/decisions/      recorded decision records and plans
~/tve-trust/evidence/       captured proof bundles
```

The CLI refuses a trust root located inside a submitted decision bundle
directory (and decision artifacts stored inside the trust root) — a bundle
can never smuggle its own trust root.

## 1. Generate an owner key outside the repository

```bash
python - <<'EOF'
import base64
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()
Path("bundle/owner.pub").write_text(base64.b64encode(
    key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
).decode() + "\n")
# Store the private half in your password manager / offline medium NOW;
# this script deliberately does not persist it.
print("public key registered in bundle/owner.pub")
EOF
```

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

## 3. Sign an exact decision payload

1. Produce the decision input JSON (fields listed in
   `docs/architecture/owner-policy-decision-and-activation-plan.md`; take
   the audit id/content hash from a fresh
   `tve evolution audit-profile`/`decision-dossier` run).
2. Serialize it canonically, sign the domain-prefixed message, assemble
   the statement — a short script, run where the private key lives:

```python
import json, sys
from pathlib import Path
from turtle_value_engine.evolution.owner_decision import OwnerPolicyDecisionInputV1
from turtle_value_engine.evolution.owner_provenance import (
    build_owner_signed_decision_statement,
    owner_decision_input_signature_message,
)
from turtle_value_engine.providers.models import canonical_json_bytes

payload = json.loads(Path("decision-input.json").read_text("utf-8"))
model = OwnerPolicyDecisionInputV1.model_validate(payload)
Path("decision-input.json").write_bytes(          # canonical byte form only
    canonical_json_bytes(model.model_dump(mode="json"))
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
private = ...  # load from your offline medium
key_id = ...   # from `tve provenance registry status`
statement = build_owner_signed_decision_statement(
    signature=private.sign(owner_decision_input_signature_message(model)),
    key_id=key_id,
    decision_input=model,
)
Path("statement.json").write_text(
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

Exit 0 + `REPLAYS_BYTE_IDENTICAL` means the persisted bytes still
reproduce the captured dossier byte-for-byte; exit 1 names the mismatch.
No network is involved at any point.

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
| plan BLOCKED `OWNER_AUTHORITY_REVERIFICATION_REQUIRED` | plan run without `--trust-root`/`--authority-evidence` |
| plan BLOCKED `SIGNED_REVOCATION_REJECTED:*` | the signed lifecycle statement failed fresh verification |
