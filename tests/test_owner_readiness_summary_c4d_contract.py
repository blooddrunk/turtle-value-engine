"""Phase 7-C4-D: characterization of the v1 summary identity contract.

Contract decision under test (Option A,
``docs/status/phase-7-c4-d-2026-10-29.md``): v1 ``summary_id`` stays the
**semantic observed-core identity** of a journey observation and
``content_sha256`` stays the **exact full-projection identity**.  These
probes *describe* the deliberately distinct roles; they change no
production behavior, expect no fix, and pin the current v1 semantics so
that any future change to them is a deliberate contract decision.

Relationship to the established suites (deliberately distinguished):

* byte-exact replay equality is already pinned by
  ``tests/test_owner_readiness_summary.py::test_summary_id_deterministic_and_bound``
  and the R2/R3 literal-replay probes;
* the store-problem collision is already pinned by the committed R1
  diagnostic
  ``test_diagnostic_summary_id_shared_across_distinct_store_problems``
  (a corrupt applied receipt plus one foreign entry);
* zero-write/socket-free execution is already pinned across the C4-C
  suites.

The new controls here independently re-anchor those properties through
*different* mechanisms (foreign-entry sets instead of a tampered receipt;
path-spelling and hint-presence variants instead of record substitution)
and add the previously undocumented characterization dimensions: the
decision-record path spelling is presentation-only, the supplied
project-config path spelling **is** identity-bearing (transitively,
through the plan's config inventory), a stale or forged self-hash fails
model validation, and an honestly-rehashed tampered payload validates
with a *different* content identity (integrity, not authenticity).

All fixtures are disposable; every key is a throwaway runtime-generated
Ed25519 key; no activation is applied; nothing leaves the tmp_path.
"""

import hashlib
import json
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.test_activation_execution import (
    PRIVATE_CONFIG_TEMPLATE,
    _Env,
)
from tests.test_activation_status import (
    _assert_zero_writes,
    _tree_snapshot,
)
from tests.test_owner_readiness_summary import (
    _bare_summary,
    _env_summary,
    _observed_paths,
    _summary_cli,
)
from turtle_value_engine.evolution.owner_readiness import (
    OwnerReadinessSummaryV1,
    ReadinessReplayInputsV1,
    summarize_owner_readiness,
)
from turtle_value_engine.providers.models import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]


def _foreign_store_summary(capsys, env: _Env, name: str) -> dict:
    """One STORE_NEEDS_ATTENTION observation via a named foreign entry.

    Two different ``name`` values produce the same store status class
    with different named problems — the presentation-only store dimension
    the R1 diagnostic pins through a tampered applied receipt.
    """

    receipts = env.activation_root / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / name).write_text("c4-d characterization probe\n", "utf-8")
    code, out = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        decision_records=[env.record_path],
        policy_exceptions=[env.exception_path],
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
    )
    assert code == 0, out
    return json.loads(out)


# ---------------------------------------------------------------------------
# (a) exact replay equality covers BOTH identities
# ---------------------------------------------------------------------------


def test_exact_replay_equality_covers_both_identities(tmp_path, capsys):
    """Identical inputs replay to byte-identical output: one summary_id
    AND one content_sha256 (control; established since C4-C)."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    code1, out1 = _env_summary(capsys, env)
    code2, out2 = _env_summary(capsys, env)
    assert code1 == 0 and code2 == 0
    assert out1 == out2, "identical inputs must replay byte-identically"
    first, second = json.loads(out1), json.loads(out2)
    assert first["summary_id"] == second["summary_id"]
    assert first["content_sha256"] == second["content_sha256"]


# ---------------------------------------------------------------------------
# (b) distinct store problem sets: one semantic id, different content
# ---------------------------------------------------------------------------


def test_store_problem_sets_share_semantic_id_not_content(tmp_path, capsys):
    """Two genuinely different corrupt-store observations of the SAME
    status class share summary_id but never content_sha256.

    This is the independently constructed twin of the committed R1
    diagnostic (which uses an applied receipt tampered between runs);
    here both observations exist under the same foreign-entry mechanism,
    so the discrimination comes only from the differing problem sets.
    """

    env = _Env(tmp_path).setup(capsys)
    first = _foreign_store_summary(capsys, env, "aaa-probe-one.txt")
    second = _foreign_store_summary(capsys, env, "bbb-probe-two.txt")

    assert first["activation_store_status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert second["activation_store_status"] == "CORRUPT_OR_UNVERIFIABLE"
    assert first["activation_store_problems"] != second[
        "activation_store_problems"
    ]
    # the deliberate v1 contract: semantic id equal, exact content differs
    assert first["summary_id"] == second["summary_id"]
    assert first["content_sha256"] != second["content_sha256"]
    assert first["journey_state"] == second["journey_state"] == (
        "STORE_NEEDS_ATTENTION"
    )


# ---------------------------------------------------------------------------
# (c) presentation-only changes: id stable, content discriminating
# ---------------------------------------------------------------------------


def test_decision_record_path_spelling_is_presentation_only(
    tmp_path, capsys
):
    """The SAME record bytes supplied at a different path keep the
    semantic id and change only the exact content (the path spelling
    appears solely in the next-step hint text; the plan binds the record
    by id and content hash, never by path)."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    code1, out1 = _env_summary(capsys, env)
    assert code1 == 0, out1
    first = json.loads(out1)

    alt_dir = tmp_path / "decisions-elsewhere"
    alt_dir.mkdir()
    alt_record = alt_dir / "the-same-record-under-another-name.json"
    alt_record.write_bytes(env.record_path.read_bytes())
    code2, out2 = _summary_cli(
        capsys,
        project_config=env.config_path,
        activation_root=env.activation_root,
        decision_records=[alt_record],
        policy_exceptions=[env.exception_path],
        trust_root=env.trust_root,
        authority_evidence=env.bundle_path,
    )
    assert code2 == 0, out2
    second = json.loads(out2)

    assert first["decision_record_id"] == second["decision_record_id"]
    assert first["summary_id"] == second["summary_id"]
    assert first["content_sha256"] != second["content_sha256"]
    # the only payload difference class is the displayed hint spelling
    assert str(alt_record) in "\n".join(second["next_steps_zh"])
    assert str(env.record_path) in "\n".join(first["next_steps_zh"])


def test_hint_text_presence_is_presentation_only(tmp_path, capsys):
    """Library boundary: the same facts with and without replay hint
    provenance (``replay_inputs``) keep summary_id and differ in
    content_sha256 — pinning that hint provenance feeds ONLY the
    next-step text, never any identity path."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    argv = [
        "evolution",
        "readiness-summary",
        "--base-profile",
        str(ROOT / "rules" / "strict-v1.yaml"),
        "--target-profile",
        str(ROOT / "rules" / "strict-v2.yaml"),
        "--release-manifest",
        str(ROOT / "docs" / "releases" / "strict-v2" / "release-candidate.json"),
        "--project-config",
        str(env.config_path),
        "--activation-root",
        str(env.activation_root),
        "--decision-record",
        str(env.record_path),
        "--policy-exception",
        str(env.exception_path),
        "--trust-root",
        str(env.trust_root),
        "--authority-evidence",
        str(env.bundle_path),
    ]
    from turtle_value_engine.cli import _build_parser, _prepare_activation_inputs

    args = _build_parser().parse_args(argv)
    args.decision_record = list(args.decision_record)
    prepared = _prepare_activation_inputs(args)

    def summarize(replay):
        return summarize_owner_readiness(
            base_profile_path=args.base_profile,
            target_profile_path=args.target_profile,
            release_manifest_path=args.release_manifest,
            project_config_path=args.project_config,
            boundary_input=prepared["boundary_input"],
            decision_records=prepared["decision_records"],
            revocations=prepared["revocations"],
            policy_exceptions=prepared["policy_exceptions"],
            authority_verifier=prepared["authority_verifier"],
            authority_evidence=prepared["authority_evidence"],
            signed_revocations=prepared["signed_revocations"],
            signed_supersessions=prepared["signed_supersessions"],
            lifecycle_trust_root=prepared["lifecycle_trust_root"],
            activation_root=args.activation_root,
            replay_inputs=replay,
        )

    with_hints = summarize(
        ReadinessReplayInputsV1(decision_records=(str(env.record_path),))
    )
    without_hints = summarize(None)
    assert with_hints.journey_state == without_hints.journey_state == (
        "PREVIEW_READY"
    )
    assert with_hints.summary_id == without_hints.summary_id
    assert with_hints.content_sha256 != without_hints.content_sha256
    assert with_hints.next_steps_zh != without_hints.next_steps_zh


# ---------------------------------------------------------------------------
# (d) meaningful core changes DO change the semantic id
# ---------------------------------------------------------------------------


def test_core_fact_changes_change_summary_id(tmp_path, capsys):
    """Identity-bearing source facts change summary_id: observed config
    bytes, and the decision context itself."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)

    bare = json.loads(_bare_summary(capsys, env)[1])
    authenticated = json.loads(_env_summary(capsys, env)[1])
    assert bare["journey_state"] == "OWNER_DECISION_REQUIRED"
    assert authenticated["journey_state"] == "PREVIEW_READY"
    assert bare["summary_id"] != authenticated["summary_id"]
    assert bare["content_sha256"] != authenticated["content_sha256"]

    # same decision context, different observed config BYTES
    env.config_path.write_text(
        PRIVATE_CONFIG_TEMPLATE.replace(
            'id = "turtle-value-engine"', 'id = "other-project"'
        ),
        "utf-8",
    )
    changed = json.loads(_env_summary(capsys, env)[1])
    assert changed["project_config_sha256"] != (
        authenticated["project_config_sha256"]
    )
    assert changed["summary_id"] != authenticated["summary_id"]
    assert changed["content_sha256"] != authenticated["content_sha256"]


def test_supplied_config_path_spelling_is_identity_bearing(tmp_path, capsys):
    """The supplied project-config PATH SPELLING is part of the semantic
    identity (transitively: the plan's PROJECT_DEFAULT_PROFILE inventory
    entry carries the exact path string inside plan.content_sha256, which
    is a direct summary_id component).  This corrects the looser
    'excludes the config path' phrasing in the R3 follow-up scoping: the
    config BYTES are bound directly, and the supplied path spelling is
    bound through the plan — unlike decision-record path spellings,
    which are presentation-only."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    first = json.loads(_env_summary(capsys, env)[1])

    alt_dir = tmp_path / "private-elsewhere"
    alt_dir.mkdir()
    alt_config = alt_dir / "same-bytes-project.toml"
    alt_config.write_bytes(env.config_path.read_bytes())
    second = json.loads(
        _summary_cli(
            capsys,
            project_config=alt_config,
            activation_root=env.activation_root,
            decision_records=[env.record_path],
            policy_exceptions=[env.exception_path],
            trust_root=env.trust_root,
            authority_evidence=env.bundle_path,
        )[1]
    )

    assert second["project_config_sha256"] == first[
        "project_config_sha256"
    ], "identical config bytes"
    assert second["summary_id"] != first["summary_id"]
    assert second["content_sha256"] != first["content_sha256"]


# ---------------------------------------------------------------------------
# (e) the self-hash boundary: stale and forged hashes fail closed
# ---------------------------------------------------------------------------


def test_model_rejects_stale_and_forged_self_hash(tmp_path, capsys):
    """A tampered full projection with the stale content_sha256 fails
    model validation, as does any forged (well-formed but wrong) hash."""

    env = _Env(tmp_path).setup(capsys)
    payload = _foreign_store_summary(capsys, env, "aaa-probe-one.txt")
    OwnerReadinessSummaryV1.model_validate(payload)  # the source validates

    stale = dict(payload)
    stale["activation_store_problems"] = [
        *payload["activation_store_problems"],
        "FABRICATED_PROBLEM:never-observed",
    ]
    with pytest.raises(ValidationError):
        OwnerReadinessSummaryV1.model_validate(stale)

    forged = dict(payload)
    forged["content_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        OwnerReadinessSummaryV1.model_validate(forged)


def test_honest_rehash_of_tampered_content_validates_differently(
    tmp_path, capsys
):
    """content_sha256 is INTEGRITY, not authenticity: an editor who
    changes content and recomputes the hash produces a model-valid
    summary with a different content identity — which is exactly why the
    field must never be treated as authorization or provenance of
    authenticity (the fixed literals already say so)."""

    env = _Env(tmp_path).setup(capsys)
    payload = _foreign_store_summary(capsys, env, "aaa-probe-one.txt")

    tampered = dict(payload)
    tampered["activation_store_problems"] = [
        *payload["activation_store_problems"],
        "EDITED_PROBLEM:honestly-rehashed",
    ]
    del tampered["content_sha256"]
    tampered["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(tampered)
    ).hexdigest()
    model = OwnerReadinessSummaryV1.model_validate(tampered)
    assert model.content_sha256 != payload["content_sha256"]
    assert model.summary_id == payload["summary_id"], (
        "the semantic observed core is unchanged by the fabricated "
        "problem list; only the exact projection identity moves"
    )
    assert model.summary_is_informational_not_authorization is True


# ---------------------------------------------------------------------------
# (f) identity-producing executions stay zero-write and socket-free
# ---------------------------------------------------------------------------


def test_identity_producing_paths_are_zero_write_and_socket_free(
    tmp_path, capsys, monkeypatch
):
    """The summarized journeys that produce every identity dimension in
    this characterization (authenticated, bare, corrupt-store) execute
    without writes, sockets or any mutation of the observed trees."""

    env = _Env(tmp_path).setup(capsys)
    env.activation_root.mkdir(parents=True)
    receipts = env.activation_root / "receipts"
    receipts.mkdir()
    (receipts / "aaa-probe-one.txt").write_text("probe\n", "utf-8")
    before = _tree_snapshot(*_observed_paths(env))

    def no_sockets(*args, **kwargs):
        raise AssertionError("the readiness summary constructed a socket")

    monkeypatch.setattr(socket, "socket", no_sockets)
    monkeypatch.setattr(socket, "create_connection", no_sockets)
    for run in (
        lambda: _env_summary(capsys, env),
        lambda: _bare_summary(capsys, env),
    ):
        code, out = run()
        assert code == 0, out
        assert json.loads(out)["summary_id"]
    _assert_zero_writes(before, _tree_snapshot(*_observed_paths(env)))


# ---------------------------------------------------------------------------
# the C4-D documentation deliverable itself is drift-checked
# ---------------------------------------------------------------------------


def test_schema_documents_both_identity_roles():
    """The checked-in schema (and therefore the Pydantic model, whose
    drift parity the base suite enforces) must carry the normative
    two-identity contract on exactly the two fields it governs."""

    schema = json.loads(
        (ROOT / "schemas" / "owner-readiness-summary.schema.json").read_text(
            "utf-8"
        )
    )
    semantic = schema["properties"]["summary_id"].get("description", "")
    exact = schema["properties"]["content_sha256"].get("description", "")

    assert semantic, "summary_id must document its semantic-core role"
    assert "content_sha256" in semantic, (
        "the summary_id contract must be stated relative to the exact "
        "content identity"
    )
    assert "NOT a unique identity of the complete projection" in semantic
    assert "deduplication" in semantic

    assert exact, "content_sha256 must document its exact-content role"
    assert "summary_id" in exact, (
        "the content_sha256 contract must be stated relative to the "
        "semantic identity"
    )
    assert "EXCLUDING this field itself" in exact, (
        "the no-hash-cycle rule must stay documented"
    )
    assert "never authenticity" in exact
