"""Frozen Phase 5 point-in-time, return, portfolio and calibration tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time as time_module
from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from turtle_value_engine import load_normalized_input
from turtle_value_engine.backtest import (
    BacktestDatasetManifest,
    BacktestRunSpec,
    BacktestWorkspace,
    BenchmarkObservation,
    BenchmarkReturnType,
    CalibrationError,
    CalibrationObservation,
    CalibrationRunner,
    CalibrationSearchSpace,
    ChronologicalSplit,
    CorporateAction,
    CorporateActionType,
    DatasetValidationError,
    DecisionSnapshot,
    ExecutionPrice,
    FXObservation,
    HistoricalDecisionArtifact,
    HistoricalUniverse,
    ListingLifecycle,
    Market,
    MarketBar,
    PortfolioPolicy,
    PortfolioSimulationError,
    PriceBasis,
    SignalEvaluationError,
    SignalEvaluationSpec,
    UniverseCoverage,
    UniverseMembership,
    build_dataset_manifest,
    build_decision_snapshot,
    evaluate_forward_return,
    evaluate_signals,
    is_available_at,
    replay_cash_balance,
    run_backtest,
    simulate_portfolio,
    source_hash_for,
)
from turtle_value_engine.models import BusinessQuality, NormalizedCompanyInput
from turtle_value_engine.pipeline import run_analyze
from turtle_value_engine.providers.models import canonical_json_bytes
from turtle_value_engine.research import (
    AnalystClientError,
    AnalystRole,
    CallableAnalystClient,
    CounterEvidenceClaim,
    EvidenceClaim,
    EvidencePacketError,
    ResearchFinding,
    ResearchIntent,
    ResearchQuestion,
    ResearchTask,
    UndatedEvidencePolicy,
    build_evidence_packet,
)

ROOT = Path(__file__).parents[1]
SOURCE_HASH = "a" * 64


def _session(value: date, hour: int, minute: int) -> datetime:
    return datetime.combine(value, time(hour, minute), tzinfo=UTC)


def _bar(
    listing_id: str,
    market: Market,
    currency: str,
    value: date,
    opening: float,
    closing: float,
    *,
    tradable: bool = True,
    suspended: bool = False,
    volume: float | None = 100_000.0,
) -> MarketBar:
    return MarketBar(
        bar_id=f"bar-{listing_id}-{value.isoformat()}",
        listing_id=listing_id,
        market=market,
        trading_date=value,
        session_open_at=_session(value, 9, 30),
        session_close_at=_session(value, 15, 0),
        open=opening if tradable else None,
        high=closing if tradable else None,
        low=opening if tradable else None,
        close=closing if tradable else None,
        volume=volume,
        amount=(volume * closing if volume is not None and tradable else None),
        currency=currency,
        tradable=tradable,
        suspended=suspended,
        source_hash=source_hash_for({"bar": listing_id, "date": value.isoformat()}),
    )


def _lifecycle(
    listing_id: str,
    market: Market,
    currency: str,
    *,
    listing_date: date = date(2020, 1, 1),
    delisting_date: date | None = None,
    terminal_status: str = "ACTIVE",
    sector: str = "consumer",
) -> ListingLifecycle:
    return ListingLifecycle(
        listing_id=listing_id,
        company_id="economic-company-1",
        economic_company_id="economic-company-1",
        market=market,
        currency=currency,
        listing_date=listing_date,
        delisting_date=delisting_date,
        terminal_status=terminal_status,
        trading_calendar="frozen-mini-ah-v1",
        timezone="Asia/Shanghai" if market is Market.A else "Asia/Hong_Kong",
        sector=sector,
    )


def _membership(
    listing_id: str,
    start: date = date(2020, 1, 1),
    end: date = date(2020, 2, 10),
) -> UniverseMembership:
    return UniverseMembership(
        membership_id=f"membership-{listing_id}",
        universe_id="frozen-ah",
        listing_id=listing_id,
        valid_from=start,
        valid_to=end,
    )


def _snapshot(
    listing_id: str,
    decision_time: datetime,
    *,
    final_state: str = "PASS",
    valuation_tier: str = "ACCEPTABLE",
) -> DecisionSnapshot:
    return DecisionSnapshot(
        snapshot_id=f"snapshot-{listing_id}-{decision_time.date().isoformat()}",
        analysis_id=f"analysis-{listing_id}-{decision_time.date().isoformat()}",
        listing_id=listing_id,
        company_id="economic-company-1",
        decision_time=decision_time,
        as_of=decision_time.date(),
        profile_id="strict-v1",
        input_artifact_id=f"input-{listing_id}",
        input_sha256="b" * 64,
        analysis_sha256="c" * 64,
        final_state=final_state,
        valuation_state=valuation_tier,
        valuation_tier=valuation_tier,
        gate_statuses={"universe": "PASS", "cdc": "PASS"},
        selected_metrics={"through_return.normalized": 0.2},
    )


def _manifest(*, include_fx: bool = True) -> BacktestDatasetManifest:
    lifecycles = [
        _lifecycle("A-SH600001", Market.A, "CNY"),
        _lifecycle("H-HK000001", Market.H, "HKD"),
        _lifecycle("A-LATER", Market.A, "CNY", listing_date=date(2020, 1, 5)),
        _lifecycle(
            "A-DELISTED",
            Market.A,
            "CNY",
            delisting_date=date(2020, 1, 5),
            terminal_status="DELISTED",
        ),
        _lifecycle("A-SUSPENDED", Market.A, "CNY"),
    ]
    bars: list[MarketBar] = []
    dates = [
        date(2020, 1, 2),
        date(2020, 1, 3),
        date(2020, 1, 4),
        date(2020, 1, 5),
        date(2020, 1, 6),
        date(2020, 2, 3),
    ]
    for value in dates:
        bars.append(
            _bar(
                "A-SH600001",
                Market.A,
                "CNY",
                value,
                10.0 + dates.index(value),
                11.0 + dates.index(value),
            )
        )
        bars.append(
            _bar(
                "H-HK000001",
                Market.H,
                "HKD",
                value,
                20.0 + dates.index(value),
                21.0 + dates.index(value),
            )
        )
    for value in (date(2020, 1, 5), date(2020, 1, 6)):
        bars.append(_bar("A-LATER", Market.A, "CNY", value, 30.0, 31.0))
    for value in (date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 4)):
        bars.append(_bar("A-DELISTED", Market.A, "CNY", value, 7.0, 8.0))
    bars.append(
        _bar(
            "A-DELISTED",
            Market.A,
            "CNY",
            date(2020, 1, 5),
            0.0,
            0.0,
            tradable=False,
            suspended=True,
            volume=None,
        )
    )
    bars.append(
        _bar(
            "A-SUSPENDED",
            Market.A,
            "CNY",
            date(2020, 1, 3),
            0.0,
            0.0,
            tradable=False,
            suspended=True,
            volume=None,
        )
    )
    actions = [
        CorporateAction(
            action_id="dividend-a1",
            listing_id="A-SH600001",
            action_type=CorporateActionType.CASH_DIVIDEND,
            effective_date=date(2020, 1, 4),
            ex_date=date(2020, 1, 4),
            cash_per_share=1.0,
            currency="CNY",
            available_at=_session(date(2020, 1, 3), 16, 0),
            source_hash=SOURCE_HASH,
        ),
        CorporateAction(
            action_id="split-a1",
            listing_id="A-SH600001",
            action_type=CorporateActionType.SPLIT,
            effective_date=date(2020, 1, 5),
            split_factor=2.0,
            currency="CNY",
            available_at=_session(date(2020, 1, 4), 16, 0),
            source_hash="b" * 64,
        ),
        CorporateAction(
            action_id="terminal-d1",
            listing_id="A-DELISTED",
            action_type=CorporateActionType.TERMINAL_VALUE,
            effective_date=date(2020, 1, 5),
            terminal_value_per_share=5.0,
            currency="CNY",
            available_at=_session(date(2020, 1, 4), 16, 0),
            source_hash="d" * 64,
        ),
    ]
    fx = (
        [
            FXObservation(
                observation_id="fx-hkd-cny-20200101",
                base_currency="HKD",
                quote_currency="CNY",
                observation_date=date(2020, 1, 1),
                rate=0.9,
                available_at=_session(date(2019, 12, 31), 23, 0),
                source_hash="e" * 64,
            )
        ]
        if include_fx
        else []
    )
    benchmarks = [
        BenchmarkObservation(
            observation_id=f"benchmark-mini-{value.isoformat()}",
            benchmark_id="CSI-FROZEN",
            observation_date=value,
            value=100.0 + index,
            return_type=BenchmarkReturnType.PRICE_RETURN,
            currency="CNY",
            available_at=_session(value, 16, 0),
            source_hash="f" * 64,
        )
        for index, value in enumerate(dates)
    ]
    return build_dataset_manifest(
        dataset_id="frozen-ah-mini-v1",
        dataset_version="2020-01-01-r1",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 5),
        calendar_id="frozen-mini-ah-v1",
        universe_id="frozen-ah",
        universe_coverage=UniverseCoverage.HISTORICAL,
        listing_lifecycles=lifecycles,
        universe_memberships=[
            _membership("A-SH600001"),
            _membership("H-HK000001"),
            _membership("A-LATER", date(2020, 1, 5)),
            _membership("A-DELISTED", end=date(2020, 1, 5)),
            _membership("A-SUSPENDED"),
        ],
        market_bars=bars,
        corporate_actions=actions,
        fx_observations=fx,
        benchmarks=benchmarks,
        limitations=[
            "Synthetic frozen mini-universe; not a claim of complete historical coverage."
        ],
        survivorship_bias_note=(
            "The fixture is historical-membership shaped, but production coverage "
            "requires source verification."
        ),
    )


def test_pit_manifest_rejects_future_publication_and_unknown_evidence():
    normalized_payload = load_normalized_input(
        ROOT / "fixtures" / "healthy_cash_cow.json"
    ).model_dump(mode="python", warnings=False)
    normalized_payload["evidence_index"][0]["source"]["published_date"] = date(2026, 9, 9)
    future_input = NormalizedCompanyInput.model_validate(normalized_payload)
    artifact = HistoricalDecisionArtifact(
        artifact_id="historical-input-future",
        listing_id="SH600001",
        decision_time=datetime(2026, 9, 8, 16, tzinfo=UTC),
        as_of=date(2026, 9, 8),
        available_at=datetime(2026, 9, 8, 16, tzinfo=UTC),
        normalized_input=future_input,
        source_hash=SOURCE_HASH,
    )
    with pytest.raises(DatasetValidationError, match="future evidence"):
        build_dataset_manifest(
            dataset_id="pit-future",
            dataset_version="v1",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 10),
            calendar_id="calendar",
            universe_id="universe",
            universe_coverage=UniverseCoverage.FIXED_RESEARCH_UNIVERSE,
            listing_lifecycles=[_lifecycle("SH600001", Market.A, "CNY")],
            decision_artifacts=[artifact],
        )
    assert not is_available_at(None, datetime(2026, 9, 8, 16, tzinfo=UTC))
    assert not is_available_at(date(2026, 9, 8), datetime(2026, 9, 8, 16, tzinfo=UTC))
    assert is_available_at(date(2026, 9, 7), datetime(2026, 9, 8, 9, tzinfo=UTC))


def test_date_only_publication_on_as_of_date_waits_for_next_session():
    normalized_payload = load_normalized_input(
        ROOT / "fixtures" / "healthy_cash_cow.json"
    ).model_dump(mode="python", warnings=False)
    normalized_payload["evidence_index"][0]["source"]["published_date"] = date(2026, 9, 8)
    normalized = NormalizedCompanyInput.model_validate(normalized_payload)
    artifact = HistoricalDecisionArtifact(
        artifact_id="historical-input-date-only",
        listing_id="SH600001",
        decision_time=datetime(2026, 9, 8, 16, tzinfo=UTC),
        as_of=date(2026, 9, 8),
        available_at=datetime(2026, 9, 8, 16, tzinfo=UTC),
        normalized_input=normalized,
        source_hash=SOURCE_HASH,
    )
    with pytest.raises(DatasetValidationError, match="future evidence"):
        build_dataset_manifest(
            dataset_id="pit-date-only",
            dataset_version="v1",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 10),
            calendar_id="calendar",
            universe_id="universe",
            universe_coverage=UniverseCoverage.FIXED_RESEARCH_UNIVERSE,
            listing_lifecycles=[
                _lifecycle(
                    "SH600001",
                    Market.A,
                    "CNY",
                    listing_date=date(2026, 9, 1),
                )
            ],
            decision_artifacts=[artifact],
        )


def test_undated_evidence_requires_explicit_frozen_attestation():
    normalized = load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json")
    payload = normalized.model_dump(mode="python", warnings=False)
    undated_id = payload["evidence_index"][0]["id"]
    payload["evidence_index"][0]["source"]["published_date"] = None
    normalized = NormalizedCompanyInput.model_validate(payload)
    question = ResearchQuestion(
        id="q-undated",
        intent=ResearchIntent.THESIS,
        text="Is the supplied evidence valid?",
    )
    with pytest.raises(EvidencePacketError, match="published after as_of"):
        build_evidence_packet(
            normalized,
            question=question,
            role=AnalystRole.QUALITY_ANALYST,
            evidence_ids=[undated_id],
        )
    packet = build_evidence_packet(
        normalized,
        question=question,
        role=AnalystRole.QUALITY_ANALYST,
        evidence_ids=[undated_id],
        undated_evidence_policy=UndatedEvidencePolicy.EXPLICIT_FROZEN,
        undated_evidence_attestation="frozen-source-index-v1:availability-reviewed",
    )
    assert packet.undated_evidence_ids == [undated_id]
    assert packet.undated_evidence_policy is UndatedEvidencePolicy.EXPLICIT_FROZEN


def test_external_analyst_budgets_fail_closed_at_adapter_boundary():
    normalized = load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json")
    question = ResearchQuestion(
        id="q-budget",
        intent=ResearchIntent.THESIS,
        text="Can the supplied evidence support this bounded question?",
    )
    packet = build_evidence_packet(
        normalized,
        question=question,
        role=AnalystRole.QUALITY_ANALYST,
        evidence_ids=[normalized.evidence_index[0].id],
    )
    task = ResearchTask.build(
        analysis_id=normalized.analysis_id,
        listing_id=normalized.company.primary_listing,
        as_of=normalized.as_of,
        profile_id=normalized.profile_id,
        role=AnalystRole.QUALITY_ANALYST,
        question=question,
        packet=packet,
        timeout_seconds=0.001,
        max_output_claims=1,
        max_output_bytes=128,
    )
    finding = ResearchFinding(
        id="budget-finding",
        analysis_id=task.analysis_id,
        listing_id=task.listing_id,
        as_of=task.as_of,
        role=task.role,
        question_id=task.question.id,
        summary="A bounded finding.",
        supporting_claims=[
            EvidenceClaim(
                id="claim-1",
                statement="The packet contains one cited source.",
                evidence_ids=[packet.available_evidence_ids[0]],
                confidence=1.0,
            )
        ],
        counter_evidence_claims=[
            CounterEvidenceClaim(
                id="claim-2",
                statement="The packet also requires a counter-check.",
                evidence_ids=[packet.available_evidence_ids[0]],
                confidence=1.0,
            )
        ],
        unresolved_questions=[],
        confidence="HIGH",
    )
    with pytest.raises(AnalystClientError, match="max_output_claims"):
        CallableAnalystClient(lambda _task: finding).analyze(
            task.model_copy(update={"max_output_bytes": 10_000})
        )
    with pytest.raises(AnalystClientError, match="timeout_seconds"):
        CallableAnalystClient(lambda _task: (time_module.sleep(0.02), finding)[1]).analyze(
            task.model_copy(update={"timeout_seconds": 0.001, "max_output_bytes": 10_000})
        )
    with pytest.raises(AnalystClientError, match="max_output_bytes"):
        CallableAnalystClient(lambda _task: {"summary": "x" * 1_000}).analyze(
            task.model_copy(update={"max_output_claims": 64, "max_output_bytes": 128})
        )


def test_historical_universe_lifecycle_and_ah_listing_identity():
    manifest = _manifest()
    universe = HistoricalUniverse(manifest)
    assert "A-LATER" not in universe.active_listings(date(2020, 1, 4))
    assert "A-LATER" in universe.active_listings(date(2020, 1, 5))
    assert "A-DELISTED" in universe.active_listings(date(2020, 1, 5))
    assert "A-DELISTED" not in universe.active_listings(date(2020, 1, 6))
    assert manifest.lifecycle("A-SH600001").resolved_company_id == "economic-company-1"
    assert manifest.lifecycle("H-HK000001").resolved_company_id == "economic-company-1"
    assert (
        manifest.lifecycle("A-SH600001").listing_id != manifest.lifecycle("H-HK000001").listing_id
    )
    fixed = build_dataset_manifest(
        dataset_id="fixed-lifecycle-only",
        dataset_version="v1",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 10),
        calendar_id="calendar",
        universe_id="fixed",
        universe_coverage=UniverseCoverage.FIXED_RESEARCH_UNIVERSE,
        listing_lifecycles=[manifest.lifecycle("A-SH600001")],
    )
    assert HistoricalUniverse(fixed).active_listings(date(2020, 1, 2)) == ("A-SH600001",)
    with pytest.raises(DatasetValidationError, match="current-universe"):
        build_dataset_manifest(
            dataset_id="current-universe",
            dataset_version="v1",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 10),
            calendar_id="calendar",
            universe_id="current",
            universe_coverage=UniverseCoverage.CURRENT_UNIVERSE,
            listing_lifecycles=[manifest.lifecycle("A-SH600001")],
        )


def test_forward_returns_handle_timing_dividend_split_terminal_and_suspension():
    manifest = _manifest()
    a_snapshot = _snapshot("A-SH600001", _session(date(2020, 1, 2), 16, 0))
    a_observation = evaluate_forward_return(manifest, a_snapshot, "1M")
    assert a_observation.entry_date == date(2020, 1, 3)
    assert a_observation.entry_price == 11.0
    assert a_observation.share_multiplier == 2.0
    assert a_observation.dividends_per_share == 1.0
    assert a_observation.status.value == "COMPLETE"
    assert a_observation.corporate_action_ids == ["dividend-a1", "split-a1"]

    terminal = evaluate_forward_return(
        manifest,
        _snapshot("A-DELISTED", _session(date(2020, 1, 2), 16, 0)),
        "1W",
    )
    assert terminal.status.value == "DELISTED_TERMINAL"
    assert terminal.exit_bar_id is None
    assert terminal.terminal_value_per_share == 5.0

    suspended = evaluate_forward_return(
        manifest,
        _snapshot("A-SUSPENDED", _session(date(2020, 1, 2), 16, 0)),
        "1W",
    )
    assert suspended.status.value == "SUSPENDED"
    assert suspended.entry_price is None


def test_signal_after_close_uses_next_session_and_ah_prices_are_distinct():
    manifest = _manifest()
    snapshots = [
        _snapshot("A-SH600001", _session(date(2020, 1, 2), 16, 0)),
        _snapshot("H-HK000001", _session(date(2020, 1, 2), 16, 0)),
    ]
    result = evaluate_signals(
        manifest,
        snapshots,
        spec=SignalEvaluationSpec(spec_id="frozen-signal-e2e", horizons=["1D", "1M"]),
    )
    assert len(result.observations) == 4
    assert all(item.entry_date == date(2020, 1, 3) for item in result.observations)
    assert {item.currency for item in result.observations} == {"CNY", "HKD"}
    assert any("state=PASS" in bucket.bucket_key for bucket in result.buckets)
    assert (
        result.content_sha256
        == hashlib.sha256(
            canonical_json_bytes(
                {
                    key: value
                    for key, value in result.model_dump(mode="json").items()
                    if key != "content_sha256"
                }
            )
        ).hexdigest()
    )


def test_historical_business_quality_without_frozen_artifact_fails_closed():
    normalized = load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json")
    analysis = run_analyze(normalized).model_copy(
        update={
            "business_quality": BusinessQuality(
                score=32,
                grade="A",
                confidence="HIGH",
                evidence_coverage=1.0,
            )
        }
    )
    with pytest.raises(SignalEvaluationError, match="frozen research artifact"):
        build_decision_snapshot(
            analysis,
            normalized_input=normalized,
            decision_time=_session(normalized.as_of, 16, 0),
        )


def test_double_counting_adjusted_prices_is_rejected():
    manifest = _manifest()
    raw_bars = list(manifest.bars_for("A-SH600001"))
    adjusted_payload = raw_bars[0].model_dump(mode="python", warnings=False)
    adjusted_payload["price_basis"] = PriceBasis.ADJUSTED
    adjusted_payload["adjustment_scope"] = ["CASH_DIVIDEND"]
    adjusted = MarketBar.model_validate(adjusted_payload)
    with pytest.raises(ValueError, match="double count"):
        BacktestDatasetManifest.build(
            dataset_id="adjusted-double-count",
            dataset_version="v1",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 2, 5),
            calendar_id="calendar",
            universe_id="frozen-ah",
            universe_coverage=UniverseCoverage.FIXED_RESEARCH_UNIVERSE,
            listing_lifecycles=[manifest.lifecycle("A-SH600001")],
            market_bars=[adjusted],
            corporate_actions=[manifest.actions_for("A-SH600001")[0]],
        )


def test_portfolio_e2e_is_long_only_replayable_and_costs_are_monotone(tmp_path: Path):
    manifest = _manifest()
    snapshots = [
        _snapshot("A-SH600001", _session(date(2020, 1, 2), 16, 0)),
        _snapshot("H-HK000001", _session(date(2020, 1, 2), 16, 0)),
        _snapshot("A-DELISTED", _session(date(2020, 1, 2), 16, 0)),
    ]
    policy = PortfolioPolicy(
        policy_id="ah-policy-zero-cost",
        base_currency="CNY",
        initial_cash=1_000_000.0,
        eligible_states=["PASS"],
        execution_price=ExecutionPrice.NEXT_OPEN,
        lot_size_a=100,
        lot_size_h=1,
    )
    costly_payload = policy.model_dump(mode="python", warnings=False)
    costly_payload["policy_id"] = "ah-policy-costly"
    costly_payload["transaction_costs"] = {
        "commission_bps": 50.0,
        "sell_stamp_duty_bps": 50.0,
        "slippage_bps": 25.0,
        "minimum_fee": 1.0,
    }
    costly_policy = PortfolioPolicy.model_validate(costly_payload)
    zero = simulate_portfolio(manifest, snapshots, policy)
    costly = simulate_portfolio(manifest, snapshots, costly_policy)
    replay = simulate_portfolio(manifest, snapshots, policy)
    assert zero.final_net_asset_value >= costly.final_net_asset_value
    assert zero.model_dump(mode="json") == replay.model_dump(mode="json")
    assert any(event.event_type.value == "DIVIDEND" for event in zero.events)
    assert any(event.event_type.value == "SPLIT" for event in zero.events)
    assert any(event.event_type.value == "TERMINAL_VALUE" for event in zero.events)
    assert replay_cash_balance(zero.events) == pytest.approx(zero.snapshots[-1].cash)
    fills = [event for event in zero.events if event.event_type.value == "FILL"]
    assert fills and all(event.side in {"BUY", "SELL"} and event.quantity >= 0 for event in fills)
    assert all(
        position.quantity >= 0 for snapshot in zero.snapshots for position in snapshot.positions
    )
    workspace = BacktestWorkspace(tmp_path / "backtest")
    workspace.save_policy(policy)
    workspace.save_portfolio_simulation(zero)
    assert workspace.load_portfolio_simulation(zero.simulation_id) == zero
    started_at_execution = simulate_portfolio(
        manifest,
        [_snapshot("A-SH600001", _session(date(2020, 1, 2), 16, 0))],
        costly_policy,
        start_date=date(2020, 1, 3),
        end_date=date(2020, 1, 6),
    )
    assert any(event.event_type.value == "FILL" for event in started_at_execution.events)
    assert started_at_execution.metrics.coverage_ratio == 1.0


def test_portfolio_requires_fx_and_does_not_fabricate_missing_liquidity():
    manifest = _manifest(include_fx=False)
    h_snapshot = _snapshot("H-HK000001", _session(date(2020, 1, 2), 16, 0))
    policy = PortfolioPolicy(
        policy_id="missing-fx",
        base_currency="CNY",
        initial_cash=100_000.0,
        eligible_states=["PASS"],
    )
    with pytest.raises(PortfolioSimulationError, match="FX"):
        simulate_portfolio(manifest, [h_snapshot], policy)


def test_portfolio_action_without_point_in_time_availability_fails_closed():
    manifest = _manifest()
    payload = manifest.model_dump(mode="python", warnings=False)
    payload["corporate_actions"][0]["available_at"] = None
    payload["content_sha256"] = "0" * 64
    actionless = BacktestDatasetManifest.build(
        dataset_id=payload["dataset_id"],
        dataset_version=payload["dataset_version"],
        start_date=payload["start_date"],
        end_date=payload["end_date"],
        calendar_id=payload["calendar_id"],
        universe_id=payload["universe_id"],
        universe_coverage=payload["universe_coverage"],
        listing_lifecycles=payload["listing_lifecycles"],
        universe_memberships=payload["universe_memberships"],
        market_bars=payload["market_bars"],
        corporate_actions=payload["corporate_actions"],
        fx_observations=payload["fx_observations"],
        benchmarks=payload["benchmarks"],
        limitations=payload["limitations"],
        survivorship_bias_note=payload["survivorship_bias_note"],
    )
    policy = PortfolioPolicy(
        policy_id="missing-action-availability",
        base_currency="CNY",
        initial_cash=100_000.0,
        eligible_states=["PASS"],
    )
    with pytest.raises(PortfolioSimulationError, match="availability is unknown"):
        simulate_portfolio(
            actionless,
            [_snapshot("A-SH600001", _session(date(2020, 1, 2), 16, 0))],
            policy,
        )


def test_calibration_is_chronological_proposal_only_and_holdout_locked():
    observations = [
        CalibrationObservation(
            observation_id=f"cal-{index}",
            observed_at=date(2020, 1, index + 1),
            target_return=float(index - 2),
            feature_values={"quality": float(index)},
            source_hash=SOURCE_HASH,
        )
        for index in range(1, 9)
    ]

    split = ChronologicalSplit(
        train_start=date(2020, 1, 2),
        train_end=date(2020, 1, 4),
        validation_start=date(2020, 1, 5),
        validation_end=date(2020, 1, 6),
        holdout_start=date(2020, 1, 7),
        holdout_end=date(2020, 1, 9),
    )
    search_space = CalibrationSearchSpace(
        space_id="quality-thresholds-v1",
        base_profile_id="strict-v1",
        parameters={"min_quality": [0.0, 4.0]},
        objective="MEAN_RETURN",
    )
    runner = CalibrationRunner(
        manifest_id="frozen-ah-mini-v1",
        base_profile_id="strict-v1",
        base_profile_sha256=SOURCE_HASH,
        search_space=search_space,
        split=split,
    )
    experiment = runner.run(observations)
    holdout_ids = {
        item.observation_id for item in observations if item.observed_at >= split.holdout_start
    }
    assert experiment.holdout_locked is True
    assert not holdout_ids.intersection(
        {observation_id for trial in experiment.trials for observation_id in trial.observation_ids}
    )
    assert experiment.proposal is not None
    assert experiment.proposal.status == "PROPOSAL_ONLY"
    assert experiment.proposal.base_profile_id == "strict-v1"
    holdout = runner.evaluate_holdout(experiment, observations)
    assert holdout.observation_count == 3
    with pytest.raises(CalibrationError, match="outside calibration split"):
        runner.run(
            observations
            + [
                CalibrationObservation(
                    observation_id="cal-outside",
                    observed_at=date(2020, 2, 1),
                    target_return=0.1,
                    source_hash=SOURCE_HASH,
                )
            ]
        )


def test_backtest_orchestration_persists_frozen_inputs_and_explicit_benchmark(tmp_path: Path):
    manifest = _manifest()
    snapshot = _snapshot("A-SH600001", _session(date(2020, 1, 2), 16, 0))
    policy = PortfolioPolicy(
        policy_id="orchestration-policy",
        base_currency="CNY",
        initial_cash=100_000.0,
        eligible_states=["PASS"],
    )
    spec = BacktestRunSpec.build(
        run_id="orchestration-run",
        manifest_id=manifest.dataset_id,
        profile_id=snapshot.profile_id,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 2, 5),
        horizons=["1D", "1M"],
        snapshot_ids=[snapshot.snapshot_id],
        portfolio_policy_id=policy.policy_id,
        benchmark_ids=["CSI-FROZEN"],
        run_portfolio_simulation=True,
    )
    workspace = BacktestWorkspace(tmp_path / "orchestrated")
    result = run_backtest(manifest, spec, [snapshot], policy=policy, workspace=workspace)
    assert result.signal_evaluation is not None
    assert result.portfolio_simulation is not None
    assert result.portfolio_simulation.policy_version == "portfolio-policy-v1"
    assert (
        result.portfolio_simulation.benchmark_results[0].return_type
        is BenchmarkReturnType.PRICE_RETURN
    )
    assert result.metrics is not None
    assert result.metrics.coverage_ratio == 1.0
    assert result.metrics.tracking_error is not None
    assert "market:A" in result.metrics.factor_exposure
    assert workspace.load_manifest(manifest.dataset_id) == manifest
    assert workspace.load_run_spec(spec.run_id) == spec
    assert workspace.load_snapshot(snapshot.snapshot_id) == snapshot
    assert workspace.load_policy(policy.policy_id) == policy
    assert workspace.load_result(spec.run_id) == result


def test_decision_snapshot_projects_existing_analysis_without_changing_strict_v1():
    normalized = load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json")
    analysis = run_analyze(normalized)
    snapshot = build_decision_snapshot(
        analysis,
        normalized_input=normalized,
        decision_time=_session(normalized.as_of, 16, 0),
        input_artifact_id="frozen-input-healthy-cash-cow",
    )
    assert snapshot.analysis_id == analysis.analysis_id
    assert snapshot.profile_id == "strict-v1"
    assert snapshot.listing_id == normalized.company.primary_listing
    strict_bytes = subprocess.check_output(["git", "show", "HEAD:rules/strict-v1.yaml"], cwd=ROOT)
    assert (
        hashlib.sha256((ROOT / "rules" / "strict-v1.yaml").read_bytes()).digest()
        == hashlib.sha256(strict_bytes).digest()
    )


@pytest.mark.parametrize(
    "schema_name",
    [
        "backtest-dataset-manifest.schema.json",
        "decision-snapshot.schema.json",
        "forward-return-observation.schema.json",
        "signal-evaluation-result.schema.json",
        "portfolio-policy.schema.json",
        "portfolio-simulation-result.schema.json",
        "calibration-experiment.schema.json",
    ],
)
def test_phase5_public_schemas_are_validated_by_draft202012(schema_name: str):
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    manifest = _manifest()
    if schema_name == "backtest-dataset-manifest.schema.json":
        value = manifest
    elif schema_name == "decision-snapshot.schema.json":
        value = _snapshot("A-SH600001", _session(date(2020, 1, 2), 16, 0))
    elif schema_name == "forward-return-observation.schema.json":
        value = evaluate_forward_return(
            manifest,
            _snapshot("A-SH600001", _session(date(2020, 1, 2), 16, 0)),
            "1D",
        )
    elif schema_name == "signal-evaluation-result.schema.json":
        value = evaluate_signals(
            manifest,
            [_snapshot("A-SH600001", _session(date(2020, 1, 2), 16, 0))],
            spec=SignalEvaluationSpec(spec_id="schema", horizons=["1D"]),
        )
    elif schema_name == "portfolio-policy.schema.json":
        value = PortfolioPolicy(
            policy_id="schema-policy",
            base_currency="CNY",
            initial_cash=1_000.0,
            eligible_states=["PASS"],
        )
    elif schema_name == "portfolio-simulation-result.schema.json":
        value = simulate_portfolio(
            manifest,
            [_snapshot("A-SH600001", _session(date(2020, 1, 2), 16, 0))],
            PortfolioPolicy(
                policy_id="schema-simulation",
                base_currency="CNY",
                initial_cash=1_000.0,
                eligible_states=["PASS"],
            ),
        )
    else:
        split = ChronologicalSplit(
            train_start=date(2020, 1, 1),
            train_end=date(2020, 1, 2),
            validation_start=date(2020, 1, 3),
            validation_end=date(2020, 1, 4),
            holdout_start=date(2020, 1, 5),
            holdout_end=date(2020, 1, 6),
        )
        space = CalibrationSearchSpace(
            space_id="schema-space", base_profile_id="strict-v1", parameters={"x": [1]}
        )
        value = CalibrationRunner(
            manifest_id="m",
            base_profile_id="strict-v1",
            base_profile_sha256=SOURCE_HASH,
            search_space=space,
            split=split,
        ).run(
            [
                CalibrationObservation(
                    observation_id=f"schema-{index}",
                    observed_at=date(2020, 1, index),
                    target_return=float(index),
                    source_hash=SOURCE_HASH,
                )
                for index in range(1, 7)
            ]
        )
    Draft202012Validator(schema).validate(value.model_dump(mode="json", warnings=False))
