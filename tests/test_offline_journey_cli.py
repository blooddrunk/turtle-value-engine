"""Issue #65/#67 operator-journey coverage: the complete offline A-share
research chain must be reachable through the real CLI alone.

The journey under test is the one an operator can follow from the README:
``tve analyze`` (with explicit artifact outputs) -> ``tve surface build``
(consuming the analysis, decision trace and research report files) ->
``tve surface validate``.  Before this coverage the two halves existed only
in separate tests: the analyze CLI wrote nothing to disk, and the surface
build CLI was fed by library-built artifacts, so no test proved that an
operator without Python glue could produce a snapshot whose
``decision_trace_reference`` and ``research_report_reference`` are populated.

Issue #67 adds the cached-source entry leg: an operator holding a raw
provider cache (from a previous online ``tve prepare``) replays preparation
through the real ``tve prepare --offline`` CLI — with no provider injection,
so the socket guard itself proves the replay never touches the network — and
feeds the prepared normalized input into the same analyze/surface chain.
Before this coverage the two halves existed only in separate tests: the
prepare CLI replay was proven against an injected failing provider, and the
analyze/surface journey started from a frozen normalized fixture, so no test
proved the operator chain raw cache -> prepare --offline -> analyze
artifacts -> surface snapshot, nor its cache provenance linkage.

Issue #69 adds the readiness preflight leg: before attempting an offline
replay, the operator can ask ``tve prepare --check-readiness`` for a
read-only, zero-network, zero-write per-category diagnosis of the raw cache.
Gate A reproduction on pristine post-#68 main proved the material gap this
closes: a partial cache reports only the FIRST missing category per failed
replay run, and an adapter version bump (``AKSHARE_ADAPTER_VERSION`` moved
192 -> 193 -> 194 across consecutive feature commits; the digest includes
``provider_version``) invalidates every existing envelope with six opaque
``no replayable cache entry for <digest>`` misses that name digests existing
nowhere in the operator's cache directory, while the still-valid envelopes
sit in plain sight under the same provider/category directories.

Issue #73 pins the runbook step-0C completion recipe (characterization, not
a defect regression — Gate A proved the machinery already works): an
operator holding dated evidence completes the three universe point-in-time
context facts by hand in a copy of the prepared normalized input, and the
real analyze CLI turns exactly the universe gate PASS while every other
fail-closed boundary (business quality NOT_EVALUATED, SPECIAL_REVIEW
decision, duplicate/unresolved/integrity rejection, wrong-period-label
silence, byte determinism, raw-cache immutability) is preserved.

Issue #75 adds the temporal-integrity leg: the runbook 0C edit path feeds
``tve analyze`` directly, and Gate A reproduced on pristine post-#74 main
that the analyze boundary enforced none of the prepare boundary's
point-in-time rules — context evidence published AFTER ``as_of`` flipped
``UNIVERSE.PARENT_EQUITY`` and ``UNIVERSE.SPECIAL_TREATMENT`` from
SPECIAL_REVIEW to PASS (exit 0, universe PASS), and a future-dated
``AS_OF_`` fact period label resolved through the ``FactBook.as_of_period``
single-candidate fallback.  Both are mechanically provable future-data
leakage; the analyze boundary now fails closed on exactly the rule the
prepare boundary already enforces, while genuinely unknown dates (``null``)
and earlier hand-prepared point-in-time labels stay preserved.
"""

import json
import socket
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.test_phase_2_3_closure import (
    RETRIEVED_AT,
    FrozenAKShare,
    akshare_provider,
)
from turtle_value_engine.cli import main
from turtle_value_engine.models import Company
from turtle_value_engine.preparation import (
    AcquisitionRequest,
    NormalizedCompanyInputBuilder,
)
from turtle_value_engine.providers import FilesystemRawResponseCache
from turtle_value_engine.providers.akshare import (
    AKSHARE_ADAPTER_VERSION,
    AKShareProvider,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "healthy_cash_cow.json"

_COMPANY_NAME = "Frozen journey company"
_COMPANY_SECTOR = "frozen-sector"


def _deny_network(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("the offline journey must make no network request")

    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)


def _populate_frozen_raw_cache(cache_dir: Path) -> FrozenAKShare:
    """Stand in for the operator's pre-existing raw cache.

    Populates the cache the only way production code ever does: a live
    ``NormalizedCompanyInputBuilder.prepare`` through the frozen fixture
    client, which reads repository fixtures and performs no I/O beyond the
    six envelope writes.
    """

    fake = FrozenAKShare()
    builder = NormalizedCompanyInputBuilder(
        akshare_provider(fake), FilesystemRawResponseCache(cache_dir)
    )
    builder.prepare(
        AcquisitionRequest(
            listing_id="SH600000",
            as_of=RETRIEVED_AT.date(),
            provider="akshare",
            company=Company(
                name=_COMPANY_NAME,
                primary_listing="SH600000",
                sector=_COMPANY_SECTOR,
                reporting_currency="CNY",
            ),
        )
    )
    assert len(fake.calls) == 6
    return fake


def _prepare_offline_argv(cache_dir: Path, output: Path) -> list[str]:
    return [
        "prepare",
        "600000.SH",
        "--as-of",
        RETRIEVED_AT.date().isoformat(),
        "--provider",
        "akshare",
        "--offline",
        "--name",
        _COMPANY_NAME,
        "--sector",
        _COMPANY_SECTOR,
        "--reporting-currency",
        "CNY",
        "--cache-dir",
        str(cache_dir),
        "--output",
        str(output),
    ]


def _cache_snapshot(cache_dir: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(cache_dir)): path.read_bytes()
        for path in sorted(cache_dir.rglob("*.json"))
    }


def test_analyze_cli_emits_artifacts_and_full_surface_chain_is_reachable(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    analysis_path = tmp_path / "analysis.json"
    trace_path = tmp_path / "decision-trace.json"
    report_path = tmp_path / "research-report.json"
    snapshot_path = tmp_path / "snapshot.json"

    assert (
        main(
            [
                "analyze",
                "--input",
                str(FIXTURE),
                "--profile",
                "strict-v1",
                "--output",
                str(analysis_path),
                "--trace-output",
                str(trace_path),
                "--report-output",
                str(report_path),
            ]
        )
        == 0
    )
    stdout_analysis = json.loads(capsys.readouterr().out)
    assert stdout_analysis["profile_id"] == "strict-v1"

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    analysis_id = analysis["analysis_id"]
    assert analysis == stdout_analysis
    # The frozen fixture carries no structured assessment, so the journey must
    # surface the explicit fail-closed states rather than a confident pass.
    assert analysis["gates"]["business_quality"]["status"] == "NOT_EVALUATED"
    assert analysis["decision"]["state"] == "SPECIAL_REVIEW"
    assert trace["contract"] == "decision_trace_v1"
    assert trace["analysis_id"] == analysis_id
    assert report["contract"] == "research_report_v1"
    assert report["analysis"]["analysis_id"] == analysis_id
    assert report["decision_trace"]["analysis_id"] == analysis_id

    assert (
        main(
            [
                "surface",
                "build",
                "--analysis",
                str(analysis_path),
                "--trace",
                str(trace_path),
                "--report",
                str(report_path),
                "--output",
                str(snapshot_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["surface", "validate", "--input", str(snapshot_path)]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["analysis_id"] == analysis_id
    assert validated["decision_trace_reference"] is not None
    assert validated["decision_trace_reference"]["artifact_id"] == analysis_id
    assert validated["research_report_reference"] is not None
    assert validated["research_report_reference"]["artifact_id"] is not None

    replay_path = tmp_path / "snapshot-replay.json"
    assert (
        main(
            [
                "surface",
                "build",
                "--analysis",
                str(analysis_path),
                "--trace",
                str(trace_path),
                "--report",
                str(report_path),
                "--output",
                str(replay_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert replay_path.read_bytes() == snapshot_path.read_bytes()


def test_analyze_cli_rejects_colliding_output_paths(tmp_path, capsys, monkeypatch):
    _deny_network(monkeypatch)
    shared = tmp_path / "shared.json"
    exit_code = main(
        [
            "analyze",
            "--input",
            str(FIXTURE),
            "--profile",
            "strict-v1",
            "--output",
            str(shared),
            "--trace-output",
            str(shared),
        ]
    )
    assert exit_code == 2
    assert "must be distinct" in capsys.readouterr().err
    assert not shared.exists()


@pytest.mark.parametrize("artifact_flag", ["--output", "--trace-output", "--report-output"])
def test_analyze_cli_never_overwrites_its_source_input(
    artifact_flag, tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    source = tmp_path / "original-normalized.json"
    original = FIXTURE.read_bytes()
    source.write_bytes(original)
    independent_output = tmp_path / "analysis.json"

    # Cover both direct source overwrite and a later colliding artifact:
    # a preflight refusal must leave all existing/new files unchanged.
    outputs = [artifact_flag, str(source)]
    if artifact_flag != "--output":
        outputs = ["--output", str(independent_output), *outputs]
    exit_code = main([
        "analyze", "--input", str(source), "--profile", "strict-v1", *outputs
    ])

    assert exit_code == 2
    assert "must not overwrite --input" in capsys.readouterr().err
    assert source.read_bytes() == original
    assert not independent_output.exists()


def test_cached_source_offline_replay_completes_the_surface_chain(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    fake = _populate_frozen_raw_cache(cache_dir)
    envelope_digests = {path.stem for path in cache_dir.rglob("*.json")}
    cache_before = _cache_snapshot(cache_dir)

    # The CLI leg constructs the real AKShareProvider (no injection): the
    # socket guard is therefore the proof that --offline replay never calls
    # a provider or imports the akshare client at all.
    normalized_path = tmp_path / "normalized.json"
    assert main(_prepare_offline_argv(cache_dir, normalized_path)) == 0
    capsys.readouterr()
    assert len(fake.calls) == 6  # the CLI replay added zero fixture fetches
    normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
    assert normalized["company"]["primary_listing"] == "SH600000"
    assert normalized["as_of"] == RETRIEVED_AT.date().isoformat()
    assert normalized["profile_id"] == "strict-v1"
    # Source provenance is auditable: every evidence document_id is exactly
    # the sha256 digest naming its raw-cache envelope.
    assert {
        evidence["source"]["document_id"]
        for evidence in normalized["evidence_index"]
    } == envelope_digests
    # The operator's raw cache is replayed read-only, never rewritten.
    assert _cache_snapshot(cache_dir) == cache_before

    replay_path = tmp_path / "normalized-replay.json"
    assert main(_prepare_offline_argv(cache_dir, replay_path)) == 0
    capsys.readouterr()
    assert replay_path.read_bytes() == normalized_path.read_bytes()

    analysis_path = tmp_path / "analysis.json"
    trace_path = tmp_path / "decision-trace.json"
    report_path = tmp_path / "research-report.json"
    snapshot_path = tmp_path / "snapshot.json"
    assert (
        main(
            [
                "analyze",
                "--input",
                str(normalized_path),
                "--profile",
                "strict-v1",
                "--output",
                str(analysis_path),
                "--trace-output",
                str(trace_path),
                "--report-output",
                str(report_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    analysis_id = analysis["analysis_id"]
    # The prepared input carries no structured assessment either: the chain
    # must keep surfacing the fail-closed decision, not a confident pass.
    assert analysis["company"]["primary_listing"] == "SH600000"
    assert analysis["decision"]["state"] == "SPECIAL_REVIEW"
    assert trace["analysis_id"] == analysis_id
    assert report["analysis_sha256"] is not None
    # Issue #71: the provider-normalized input DOES carry fiscal-period
    # parent_equity facts, so the universe reason must name the
    # point-in-time period it actually looked up instead of bare
    # "Parent equity is missing.", which contradicts the visible facts.
    provider_equity_periods = sorted(
        fact["period"]
        for fact in analysis["facts"]
        if fact["field"] == "parent_equity"
    )
    assert provider_equity_periods == ["2024-12-31", "2025-12-31"]
    equity_rule = next(
        rule
        for rule in analysis["gates"]["universe"]["rules"]
        if rule["rule_id"] == "UNIVERSE.PARENT_EQUITY"
    )
    assert f"AS_OF_{RETRIEVED_AT.date().isoformat()}" in equity_rule["message"]

    assert (
        main(
            [
                "surface",
                "build",
                "--analysis",
                str(analysis_path),
                "--trace",
                str(trace_path),
                "--report",
                str(report_path),
                "--output",
                str(snapshot_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["surface", "validate", "--input", str(snapshot_path)]) == 0
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["analysis_id"] == analysis_id
    assert snapshot["company"]["primary_listing"] == "SH600000"
    assert snapshot["decision_trace_reference"] is not None
    assert snapshot["research_report_reference"] is not None


def test_cached_source_offline_replay_fails_closed_on_missing_category(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    _populate_frozen_raw_cache(cache_dir)
    # A partial cache (the realistic operator state after an interrupted or
    # older acquisition) misses one of the six default categories.
    (next((cache_dir / "akshare" / "market_quote").glob("*.json"))).unlink()
    cache_before = _cache_snapshot(cache_dir)

    output = tmp_path / "normalized.json"
    assert main(_prepare_offline_argv(cache_dir, output)) == 2
    stderr = capsys.readouterr().err
    assert "market_quote" in stderr
    assert "no replayable cache entry" in stderr
    # Fail-closed means no output side effects and an untouched source cache.
    assert not output.exists()
    assert _cache_snapshot(cache_dir) == cache_before


def _readiness_argv(cache_dir: Path, as_of: str | None = None) -> list[str]:
    argv = [
        "prepare",
        "600000.SH",
        "--as-of",
        as_of or RETRIEVED_AT.date().isoformat(),
        "--provider",
        "akshare",
        "--check-readiness",
        "--cache-dir",
        str(cache_dir),
    ]
    return argv


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _readiness_stdout(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_check_readiness_ready_cache_reports_every_category_ready(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    fake = _populate_frozen_raw_cache(cache_dir)
    cache_before = _cache_snapshot(cache_dir)
    tree_before = _tree_snapshot(tmp_path)

    assert main(_readiness_argv(cache_dir)) == 0
    report = _readiness_stdout(capsys)
    assert report["listing_id"] == "SH600000"
    assert report["as_of"] == RETRIEVED_AT.date().isoformat()
    assert report["provider"] == "akshare"
    assert report["provider_version"] == AKSHARE_ADAPTER_VERSION
    assert report["ready"] is True
    assert [entry["category"] for entry in report["categories"]] == [
        "company_metadata",
        "listing_metadata",
        "market_quote",
        "cash_flow_statement",
        "income_statement",
        "balance_sheet",
    ]
    assert all(entry["status"] == "READY" for entry in report["categories"])
    assert all(entry["retrieved_at"].startswith(RETRIEVED_AT.date().isoformat())
               for entry in report["categories"])
    # The report names the exact envelope the current identity expects, so a
    # miss is no longer an opaque digest.
    expected_paths = {
        entry["category"]: entry["expected_path"]
        for entry in report["categories"]
    }
    assert all(
        (cache_dir / "akshare" / category / f"{Path(path).name}").exists()
        for category, path in expected_paths.items()
    )
    assert report["earliest_replayable_as_of"] == RETRIEVED_AT.date().isoformat()

    # Read-only and deterministic: the preflight added zero provider calls
    # (the six fixture calls happened during cache population), zero writes.
    assert len(fake.calls) == 6
    assert _cache_snapshot(cache_dir) == cache_before
    assert _tree_snapshot(tmp_path) == tree_before
    assert main(_readiness_argv(cache_dir)) == 0
    assert _readiness_stdout(capsys) == report


def test_check_readiness_reports_every_missing_category_in_one_run(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    _populate_frozen_raw_cache(cache_dir)
    # Gate A reproduced that a failed replay names only the FIRST missing
    # category; the readiness preflight must surface all of them at once.
    for category in ("market_quote", "balance_sheet"):
        (next((cache_dir / "akshare" / category).glob("*.json"))).unlink()
    cache_before = _cache_snapshot(cache_dir)

    assert main(_readiness_argv(cache_dir)) == 1
    report = _readiness_stdout(capsys)
    assert report["ready"] is False
    statuses = {entry["category"]: entry["status"] for entry in report["categories"]}
    assert statuses["market_quote"] == "MISSING"
    assert statuses["balance_sheet"] == "MISSING"
    assert statuses["company_metadata"] == "READY"
    assert statuses["income_statement"] == "READY"
    missing = [
        entry for entry in report["categories"] if entry["status"] == "MISSING"
    ]
    for entry in missing:
        assert entry["expected_path"].startswith(str(cache_dir))
        assert not Path(entry["expected_path"]).exists()
        # No foreign envelope exists to explain the miss.
        assert entry["cache_candidates"] == []
    # A missing required category has no guaranteed replayable date.
    assert report["earliest_replayable_as_of"] is None
    assert _cache_snapshot(cache_dir) == cache_before


def test_check_readiness_diagnoses_adapter_version_churn(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    # The operator's cache was written by the previous adapter version (the
    # git-history churn case 193 -> 194); the envelopes are complete and
    # valid, but every digest moved because provider_version is part of the
    # cache identity.
    previous_version = "193"
    assert previous_version != AKSHARE_ADAPTER_VERSION
    fake = FrozenAKShare()
    stale_provider = AKShareProvider(
        fake,
        provider_version=previous_version,
        clock=lambda: RETRIEVED_AT,
    )
    NormalizedCompanyInputBuilder(
        stale_provider, FilesystemRawResponseCache(cache_dir)
    ).prepare(
        AcquisitionRequest(
            listing_id="SH600000",
            as_of=RETRIEVED_AT.date(),
            provider="akshare",
            company=Company(
                name=_COMPANY_NAME,
                primary_listing="SH600000",
                sector=_COMPANY_SECTOR,
                reporting_currency="CNY",
            ),
        )
    )
    assert len(fake.calls) == 6
    cache_before = _cache_snapshot(cache_dir)

    assert main(_readiness_argv(cache_dir)) == 1
    report = _readiness_stdout(capsys)
    assert report["provider_version"] == AKSHARE_ADAPTER_VERSION
    assert report["ready"] is False
    # All six categories miss under the current identity, and every miss is
    # explained by the same-directory envelopes written by the older adapter.
    assert len(report["categories"]) == 6
    for entry in report["categories"]:
        assert entry["status"] == "MISSING"
        assert not Path(entry["expected_path"]).exists()
        candidates = entry["cache_candidates"]
        assert len(candidates) == 1
        assert candidates[0]["provider_id"] == "akshare"
        assert candidates[0]["provider_version"] == previous_version
        assert candidates[0]["entity_id"] == "SH600000"
        assert Path(candidates[0]["file"]).exists()
    # No envelope was readable, so no replayable as_of can be derived.
    assert report["earliest_replayable_as_of"] is None
    # The preflight added zero provider calls beyond the six population calls.
    assert len(fake.calls) == 6
    assert _cache_snapshot(cache_dir) == cache_before


def test_check_readiness_classifies_future_and_corrupted_entries(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)

    future_cache = tmp_path / "future-cache"
    _populate_frozen_raw_cache(future_cache)
    early_argv = _readiness_argv(
        future_cache,
        as_of=(RETRIEVED_AT.date() - timedelta(days=1)).isoformat(),
    )
    assert main(early_argv) == 1
    future_report = _readiness_stdout(capsys)
    assert future_report["ready"] is False
    for entry in future_report["categories"]:
        assert entry["status"] == "FUTURE_DATA"
        assert RETRIEVED_AT.date().isoformat() in (entry["detail"] or "")
    assert future_report["earliest_replayable_as_of"] == (
        RETRIEVED_AT.date().isoformat()
    )

    # A tampered envelope identity must surface as CORRUPT with its path,
    # while the other categories are still individually reported.
    cache_dir = tmp_path / "corrupt-cache"
    _populate_frozen_raw_cache(cache_dir)
    target = next((cache_dir / "akshare" / "market_quote").glob("*.json"))
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["request"]["entity_id"] = "SH999999"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert main(_readiness_argv(cache_dir)) == 1
    corrupt_report = _readiness_stdout(capsys)
    statuses = {
        entry["category"]: entry["status"] for entry in corrupt_report["categories"]
    }
    assert statuses["market_quote"] == "CORRUPT"
    assert statuses["balance_sheet"] == "READY"
    assert corrupt_report["earliest_replayable_as_of"] is None
    corrupt_entry = next(
        entry
        for entry in corrupt_report["categories"]
        if entry["category"] == "market_quote"
    )
    assert corrupt_entry["expected_path"] in (corrupt_entry["detail"] or "")


def test_check_readiness_earliest_date_respects_source_metadata(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    _populate_frozen_raw_cache(cache_dir)
    target = next((cache_dir / "akshare" / "market_quote").glob("*.json"))
    envelope = json.loads(target.read_text(encoding="utf-8"))
    # A source-level point-in-time date can be later than retrieved_at.
    # _validate_as_of rejects such a record at the earlier requested as_of.
    publication_date = (RETRIEVED_AT.date() + timedelta(days=3)).isoformat()
    envelope["response_metadata"]["publication_date"] = publication_date
    target.write_text(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    cache_before = _cache_snapshot(cache_dir)

    assert main(_readiness_argv(cache_dir)) == 1
    report = _readiness_stdout(capsys)
    assert report["ready"] is False
    statuses = {entry["category"]: entry["status"] for entry in report["categories"]}
    assert statuses["market_quote"] == "FUTURE_DATA"
    assert report["earliest_replayable_as_of"] == publication_date

    # The exact reported date must now satisfy the shared replay constraints.
    assert main(_readiness_argv(cache_dir, as_of=publication_date)) == 0
    assert _readiness_stdout(capsys)["ready"] is True
    assert _cache_snapshot(cache_dir) == cache_before


def test_check_readiness_marks_unparseable_candidate_envelopes(tmp_path, monkeypatch):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    _populate_frozen_raw_cache(cache_dir)
    quote_dir = cache_dir / "akshare" / "market_quote"
    (next(quote_dir.glob("*.json"))).unlink()
    # Stray non-envelope files sit where the identity expects one; the
    # candidate scan must report them as unreadable instead of guessing an
    # identity — including JSON that parses but fails the identity typing.
    stray = quote_dir / "not-an-envelope.json"
    stray.write_text("{not json", encoding="utf-8")
    mistyped = quote_dir / "mistyped-envelope.json"
    mistyped.write_text(
        json.dumps({"provider": {"id": 123}, "request": {"entity_id": 456}}),
        encoding="utf-8",
    )

    builder = NormalizedCompanyInputBuilder(
        AKShareProvider(), FilesystemRawResponseCache(cache_dir)
    )
    report = builder.inspect_readiness(
        AcquisitionRequest(
            listing_id="SH600000",
            as_of=RETRIEVED_AT.date(),
            provider="akshare",
        )
    )
    entry = next(
        item for item in report.categories if item.category == "market_quote"
    )
    assert entry.status == "MISSING"
    assert [candidate.file for candidate in entry.cache_candidates] == [
        str(mistyped),
        str(stray),
    ]
    for candidate in entry.cache_candidates:
        assert candidate.provider_id is None
        assert candidate.provider_version is None
        assert candidate.entity_id is None


def test_check_readiness_rejects_flags_it_cannot_honor_faithfully(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    _populate_frozen_raw_cache(cache_dir)
    base = _readiness_argv(cache_dir)
    conflicting = [
        ["--output", str(tmp_path / "normalized.json")],
        ["--allow-stale"],
        ["--max-age-days", "30"],
        ["--name", _COMPANY_NAME],
        ["--sector", _COMPANY_SECTOR],
        ["--reporting-currency", "CNY"],
        ["--company-json", str(tmp_path / "company.json")],
    ]
    for flags in conflicting:
        assert main([*base, *flags]) == 2
        stderr = capsys.readouterr().err
        assert "--check-readiness" in stderr
        assert flags[0] in stderr
    assert not (tmp_path / "normalized.json").exists()


# Issue #73 runbook step 0C: the operator completes the three universe
# point-in-time context facts by hand, with dated evidence, directly in a
# copy of the prepared normalized input.  The values mirror the runbook
# recipe: listing_years derived from the 1999-11-10 listing date,
# special_treatment false from a hypothetical complete AS_OF status register,
# and parent_equity from a hypothetical same-day AS_OF equity statement.
# These are SYNTHETIC fixture-only evidence, not real issuer disclosures or
# relabeled fiscal/half-year values.
_AS_OF = RETRIEVED_AT.date().isoformat()
_AS_OF_PERIOD = f"AS_OF_{_AS_OF}"
_FISCAL_PARENT_EQUITY = (6_800_000_000.0, 7_000_000_000.0)
_CONTEXT_EVIDENCE = [
    {
        "id": "evidence-context-listing-0001",
        "direction": "SUPPORT",
        "strength": "E3",
        "statement": (
            "Exchange listing record: the listing date is 1999-11-10, so "
            "listing_years at the analysis date is "
            "(2026-09-12 - 1999-11-10).days / 365.25 = 26.8392 years."
        ),
        "source": {
            "type": "EXCHANGE_FILING",
            "title": "Exchange listing record for 600000",
            "published_date": "1999-11-10",
            "document_id": "listing-record-600000-1999-11-10",
        },
        "confidence": 0.95,
    },
    {
        "id": "evidence-context-st-0001",
        "direction": "SUPPORT",
        "strength": "E2",
        "statement": (
            "Synthetic complete authority status registry, effective at "
            "2026-09-12, explicitly classifies SH600000 as ordinary (not "
            "ST/*ST) and declares complete coverage; fixture only."
        ),
        "source": {
            "type": "REGULATOR",
            "title": "Synthetic complete ST status as-of snapshot (fixture)",
            "published_date": "2026-09-12",
            "document_id": "synthetic-st-status-600000-2026-09-12",
        },
        "confidence": 0.85,
    },
    {
        "id": "evidence-context-equity-0001",
        "direction": "SUPPORT",
        "strength": "E3",
        "statement": (
            "Synthetic company statement explicitly attests parent equity "
            "of 7,250,000,000 CNY AS OF 2026-09-12 (effective date, not "
            "just publication date), independent of the fiscal facts. "
            "Fixture only; no real issuer disclosure is claimed."
        ),
        "source": {
            "type": "COMPANY_ANNOUNCEMENT",
            "title": "Synthetic AS_OF equity attestation (fixture)",
            "published_date": "2026-09-12",
            "document_id": "synthetic-equity-asof-600000-2026-09-12",
        },
        "confidence": 0.95,
    },
]
_CONTEXT_FACTS = [
    {
        "id": "fact-context-listing-years-0001",
        "field": "listing_years",
        "value": 26.8392,
        "unit": "years",
        "period": _AS_OF_PERIOD,
        "source_evidence_ids": ["evidence-context-listing-0001"],
        "confidence": 0.95,
    },
    {
        "id": "fact-context-special-treatment-0001",
        "field": "special_treatment",
        "value": False,
        "period": _AS_OF_PERIOD,
        "source_evidence_ids": ["evidence-context-st-0001"],
        "confidence": 0.85,
    },
    {
        "id": "fact-context-parent-equity-0001",
        "field": "parent_equity",
        "value": 7_250_000_000.0,
        "unit": "reported_currency_amount",
        "currency": "CNY",
        "period": _AS_OF_PERIOD,
        "source_evidence_ids": ["evidence-context-equity-0001"],
        "confidence": 0.95,
    },
]


def _completed_context_input(source: Path, target: Path) -> None:
    """Apply the runbook 0C edit: append dated evidence plus AS_OF facts."""

    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["evidence_index"] = payload["evidence_index"] + _CONTEXT_EVIDENCE
    payload["facts"] = payload["facts"] + _CONTEXT_FACTS
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_hand_provided_as_of_context_facts_complete_the_universe_gate(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    _populate_frozen_raw_cache(cache_dir)
    cache_before = _cache_snapshot(cache_dir)
    prepared = tmp_path / "normalized.json"
    assert main(_prepare_offline_argv(cache_dir, prepared)) == 0
    capsys.readouterr()

    # The runbook honesty invariant is representable in the test input
    # itself: the point-in-time parent equity is a distinct dated value,
    # never one of the provider's fiscal-period figures.
    fiscal_values = {
        fact["value"]
        for fact in json.loads(prepared.read_text(encoding="utf-8"))["facts"]
        if fact["field"] == "parent_equity"
    }
    assert fiscal_values == set(_FISCAL_PARENT_EQUITY)
    assert 7_250_000_000.0 not in fiscal_values

    completed = tmp_path / "normalized-context.json"
    _completed_context_input(prepared, completed)

    analysis = tmp_path / "analysis-context.json"
    argv = [
        "analyze",
        "--input",
        str(completed),
        "--profile",
        "strict-v1",
        "--output",
        str(analysis),
    ]
    assert main(argv) == 0
    capsys.readouterr()
    result = json.loads(analysis.read_text(encoding="utf-8"))

    # Only the universe gate completes; every other fail-closed boundary is
    # preserved and the decision cannot become an automatic pass.
    rules = {
        rule["rule_id"]: rule for rule in result["gates"]["universe"]["rules"]
    }
    assert result["gates"]["universe"]["status"] == "PASS"
    assert rules["UNIVERSE.LISTING_YEARS"]["status"] == "PASS"
    assert rules["UNIVERSE.LISTING_YEARS"]["evidence_ids"] == [
        "evidence-context-listing-0001"
    ]
    assert rules["UNIVERSE.SPECIAL_TREATMENT"]["status"] == "PASS"
    assert rules["UNIVERSE.SPECIAL_TREATMENT"]["actual"] is False
    assert rules["UNIVERSE.PARENT_EQUITY"]["status"] == "PASS"
    assert rules["UNIVERSE.PARENT_EQUITY"]["actual"] == 7_250_000_000.0
    assert rules["UNIVERSE.PARENT_EQUITY"]["evidence_ids"] == [
        "evidence-context-equity-0001"
    ]
    assert result["gates"]["business_quality"]["status"] == "NOT_EVALUATED"
    assert result["decision"]["state"] == "SPECIAL_REVIEW"
    assert "BUSINESS_QUALITY_NOT_EVALUATED" in result["flags"]

    # The audit chain keeps both sides auditable: the operator facts and
    # evidence are carried into the analysis unchanged, and the provider's
    # fiscal parent-equity facts stay at their fiscal periods — the engine
    # never relabels a fiscal value as a point-in-time value.
    facts_by_id = {fact["id"]: fact for fact in result["facts"]}
    assert facts_by_id["fact-context-parent-equity-0001"]["period"] == _AS_OF_PERIOD
    assert facts_by_id["fact-context-parent-equity-0001"]["source_evidence_ids"] == [
        "evidence-context-equity-0001"
    ]
    evidence_by_id = {item["id"]: item for item in result["evidence_index"]}
    assert (
        evidence_by_id["evidence-context-equity-0001"]["source"]["document_id"]
        == "synthetic-equity-asof-600000-2026-09-12"
    )
    # The fixture can illustrate an actual AS_OF claim, but never silently
    # promote an interim/annual report period into an analysis-date fact.
    assert evidence_by_id["evidence-context-equity-0001"]["source"]["type"] == (
        "COMPANY_ANNOUNCEMENT"
    )
    assert (
        evidence_by_id["evidence-context-equity-0001"]["source"]["published_date"]
        == _AS_OF
    )
    assert (
        evidence_by_id["evidence-context-st-0001"]["source"]["published_date"]
        == _AS_OF
    )
    assert sorted(
        fact["period"]
        for fact in result["facts"]
        if fact["field"] == "parent_equity"
    ) == ["2024-12-31", "2025-12-31", _AS_OF_PERIOD]

    # Deterministic rerun and an untouched raw cache.
    replay = tmp_path / "analysis-context-replay.json"
    assert main([*argv[: -1], str(replay)]) == 0
    capsys.readouterr()
    assert replay.read_bytes() == analysis.read_bytes()
    assert _cache_snapshot(cache_dir) == cache_before


def test_hand_provided_context_facts_keep_integrity_and_period_failures_closed(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    _populate_frozen_raw_cache(cache_dir)
    prepared = tmp_path / "normalized.json"
    assert main(_prepare_offline_argv(cache_dir, prepared)) == 0
    capsys.readouterr()

    # A duplicate field/period fact never resolves to a silent winner: the
    # input is rejected before any output file is written.  The duplicate
    # carries a distinct id, so the failure is the field/period collision
    # itself, not the id-uniqueness validator.
    duplicated = tmp_path / "normalized-duplicate.json"
    _completed_context_input(prepared, duplicated)
    payload = json.loads(duplicated.read_text(encoding="utf-8"))
    conflicting_fact = dict(payload["facts"][-1])
    conflicting_fact["id"] = "fact-context-parent-equity-0002"
    payload["facts"].append(conflicting_fact)
    duplicated.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output = tmp_path / "analysis-duplicate.json"
    assert (
        main(["analyze", "--input", str(duplicated), "--output", str(output)]) == 2
    )
    stderr = capsys.readouterr().err
    assert "duplicate normalized fact" in stderr
    assert not output.exists()

    # An unknown evidence reference fails closed the same way.
    unresolved = tmp_path / "normalized-unresolved.json"
    _completed_context_input(prepared, unresolved)
    payload = json.loads(unresolved.read_text(encoding="utf-8"))
    payload["facts"][-1]["source_evidence_ids"] = ["evidence-does-not-exist"]
    unresolved.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert (
        main(["analyze", "--input", str(unresolved), "--output", str(output)]) == 2
    )
    stderr = capsys.readouterr().err
    assert "undefined evidence ID reference" in stderr
    assert not output.exists()

    # A wrong period label (fiscal-style instead of AS_OF_) is not an error,
    # but it never satisfies the point-in-time lookup: the universe gate
    # keeps failing closed and names the exact expected period.
    mislabeled = tmp_path / "normalized-mislabeled.json"
    _completed_context_input(prepared, mislabeled)
    payload = json.loads(mislabeled.read_text(encoding="utf-8"))
    payload["facts"] = [
        {**fact, "period": _AS_OF} if fact["id"].startswith("fact-context-") else fact
        for fact in payload["facts"]
    ]
    mislabeled.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    mislabeled_output = tmp_path / "analysis-mislabeled.json"
    assert (
        main(
            ["analyze", "--input", str(mislabeled), "--output", str(mislabeled_output)]
        )
        == 0
    )
    capsys.readouterr()
    result = json.loads(mislabeled_output.read_text(encoding="utf-8"))
    assert result["gates"]["universe"]["status"] == "SPECIAL_REVIEW"
    equity_rule = next(
        rule
        for rule in result["gates"]["universe"]["rules"]
        if rule["rule_id"] == "UNIVERSE.PARENT_EQUITY"
    )
    assert equity_rule["status"] == "SPECIAL_REVIEW"
    assert _AS_OF_PERIOD in equity_rule["message"]


# Issue #75: the analyze boundary must reject mechanically provable future
# data in hand-completed inputs.  The prepare boundary already enforces the
# same rule (preparation._validate_normalized_point_in_time); these tests
# pin the mirrored guard at the ``tve analyze`` boundary that Gate A proved
# missing on pristine post-#74 main.
def test_future_published_context_evidence_fails_closed_at_analyze(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    cache_dir = tmp_path / "raw-cache"
    _populate_frozen_raw_cache(cache_dir)
    cache_before = _cache_snapshot(cache_dir)
    prepared = tmp_path / "normalized.json"
    assert main(_prepare_offline_argv(cache_dir, prepared)) == 0
    capsys.readouterr()

    # Runbook 0C completion, except the equity and ST evidence claim a
    # publication date 30 days AFTER the analysis as_of.  A source published
    # after as_of cannot be knowable at as_of: this is mechanically provable
    # future-data leakage, so the analyze boundary must fail closed instead
    # of turning the point-in-time universe rules into PASS.
    future = (RETRIEVED_AT.date() + timedelta(days=30)).isoformat()
    payload = json.loads(prepared.read_text(encoding="utf-8"))
    evidence = json.loads(json.dumps(_CONTEXT_EVIDENCE))
    for item in evidence:
        if item["id"] in {"evidence-context-equity-0001", "evidence-context-st-0001"}:
            item["source"]["published_date"] = future
    payload["evidence_index"] = payload["evidence_index"] + evidence
    payload["facts"] = payload["facts"] + _CONTEXT_FACTS
    completed = tmp_path / "normalized-future-evidence.json"
    completed.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    output = tmp_path / "analysis-future-evidence.json"
    assert main(["analyze", "--input", str(completed), "--output", str(output)]) == 2
    stderr = capsys.readouterr().err
    # Every future-published evidence item is named, so a hand-editting
    # operator fixes all of them in one round trip.
    assert "evidence-context-st-0001" in stderr
    assert "evidence-context-equity-0001" in stderr
    assert f"publication date {future} is after as_of {_AS_OF}" in stderr
    assert not output.exists()
    assert _cache_snapshot(cache_dir) == cache_before


def test_future_dated_fact_period_label_fails_closed_at_analyze(
    tmp_path, capsys, monkeypatch
):
    _deny_network(monkeypatch)
    # The frozen hand-prepared fixture resolves its point-in-time lookups at
    # AS_OF_<as_of>.  Relabeling every point-in-time fact one day past as_of
    # must not slide the whole point-in-time context through the
    # single-AS_OF-candidate fallback of FactBook.as_of_period.
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    as_of = payload["as_of"]
    future_period = f"AS_OF_{(date.fromisoformat(as_of) + timedelta(days=1)).isoformat()}"
    payload["facts"] = [
        {**fact, "period": future_period}
        if fact["period"] == f"AS_OF_{as_of}"
        else fact
        for fact in payload["facts"]
    ]
    future_input = tmp_path / "healthy-future-period.json"
    future_input.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    output = tmp_path / "analysis-future-period.json"
    assert main(["analyze", "--input", str(future_input), "--output", str(output)]) == 2
    stderr = capsys.readouterr().err
    assert future_period in stderr
    assert f"is after as_of {as_of}" in stderr
    assert not output.exists()
