"""Phase 6-C controlled re-analysis executor acceptance matrix."""

from __future__ import annotations

import json
import socket
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.test_phase_4_agentic_analysis import (
    _clients,
    _strong_input,
    run_business_quality_research,
)
from turtle_value_engine.cli import main
from turtle_value_engine.config import load_profile
from turtle_value_engine.input_loader import load_normalized_input
from turtle_value_engine.models import Adjustment, NormalizedCompanyInput
from turtle_value_engine.models.common import AdjustmentStatus, AdjustmentType
from turtle_value_engine.monitoring import (
    MonitoringWorkspace,
    WatchlistSpecV1,
    build_event_batch,
    run_monitoring,
)
from turtle_value_engine.monitoring_execution import (
    ReanalysisExecutionError,
    ReanalysisExecutor,
    ReanalysisFailureCode,
    ReanalysisJobStatus,
    ReanalysisJobStore,
    ReanalysisJobStoreError,
)
from turtle_value_engine.pipeline import run_analyze

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "monitoring"
AS_OF = "2026-09-08T00:00:00Z"
AS_OF_DATE = date(2026, 9, 8)


class CountingPreparation:
    """Small preparation double that records the executor boundary exactly."""

    def __init__(self, normalized: NormalizedCompanyInput, *, error: Exception | None = None):
        self.normalized = normalized
        self.error = error
        self.calls: list[tuple[object, bool]] = []

    def prepare(self, request, *, offline=False, **_kwargs):
        self.calls.append((request, offline))
        if self.error is not None:
            raise self.error
        return object(), self.normalized


class FailingResearch:
    def research(self, *_args, **_kwargs):
        raise RuntimeError("secret-model-token-should-not-escape")


def _watchlist(listing: str = "SH600001") -> WatchlistSpecV1:
    return WatchlistSpecV1.build(
        watchlist_id="phase6c-test",
        profile_id="strict-v1",
        entries=[{"listing_id": listing, "company_display_name": "fixture"}],
    )


def _normalized(
    listing: str = "SH600001",
    *,
    strong: bool = False,
    keep_adjustments: bool = False,
) -> NormalizedCompanyInput:
    source = (
        _strong_input()
        if strong
        else load_normalized_input(ROOT / "fixtures" / "healthy_cash_cow.json")
    )
    payload = source.model_dump(mode="python", warnings=False)
    payload["as_of"] = AS_OF_DATE
    payload["company"]["primary_listing"] = listing
    if not keep_adjustments:
        payload["adjustments"] = []
    return NormalizedCompanyInput.model_validate(payload)


def _committed(
    tmp_path: Path,
    event_type: str,
    *,
    event_id: str = "event-1",
    listing: str = "SH600001",
):
    watchlist = _watchlist(listing)
    batch = build_event_batch(
        [
            {
                "event_id": event_id,
                "listing_id": listing,
                "event_type": event_type,
                "source_id": "fixture-source",
                "source_event_id": f"fixture:{event_id}",
                "available_at": "2026-06-01T00:00:00Z",
            }
        ]
    )
    run = run_monitoring(watchlist, batch, None, AS_OF)
    workspace = MonitoringWorkspace(tmp_path / "monitoring")
    workspace.commit_run(run, watchlist=watchlist, batch=batch)
    return workspace, watchlist, batch, run


def _executor(
    workspace: MonitoringWorkspace,
    tmp_path: Path,
    *,
    preparation=None,
    clients=None,
    model_allowed: bool | None = None,
    failure_injector=None,
) -> ReanalysisExecutor:
    return ReanalysisExecutor(
        workspace,
        ReanalysisJobStore(tmp_path / "jobs", failure_injector=failure_injector),
        preparation=preparation,
        analyst_clients=clients,
        model_allowed=model_allowed,
    )


def _json_files(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*.json"))
    }


class TestCommittedRunEligibility:
    def test_arbitrary_orphan_run_is_rejected(self, tmp_path):
        watchlist = _watchlist()
        batch = build_event_batch(
            [
                {
                    "event_id": "orphan",
                    "listing_id": "SH600001",
                    "event_type": "INFORMATIONAL_DISCLOSURE",
                    "source_id": "fixture-source",
                    "source_event_id": "fixture:orphan",
                    "available_at": "2026-06-01T00:00:00Z",
                }
            ]
        )
        run = run_monitoring(watchlist, batch, None, AS_OF)
        workspace = MonitoringWorkspace(tmp_path / "monitoring")
        workspace.root.mkdir(parents=True)
        workspace.run_path(run.run_id).parent.mkdir(parents=True, exist_ok=True)
        workspace.run_path(run.run_id).write_bytes(run.canonical_bytes() + b"\n")
        with pytest.raises(ReanalysisExecutionError, match="fully proven committed"):
            _executor(workspace, tmp_path).execute(run.run_id)

    def test_commit_proof_success_binds_all_artifacts(self, tmp_path):
        workspace, watchlist, batch, run = _committed(
            tmp_path, "INFORMATIONAL_DISCLOSURE"
        )
        proof, loaded_watchlist, loaded_batch, loaded_run, state = workspace.load_committed_run(
            run.run_id
        )
        assert proof.commit_id == proof.content_sha256
        assert loaded_watchlist.content_sha256 == watchlist.content_sha256
        assert loaded_batch.content_sha256 == batch.content_sha256
        assert loaded_run.run_id == run.run_id
        assert state.state_id == run.next_state.state_id

    @pytest.mark.parametrize("which", ["proof", "pointer", "batch"])
    def test_missing_commit_boundary_artifact_fails_closed(self, tmp_path, which):
        workspace, _watchlist_value, batch, run = _committed(
            tmp_path, "INFORMATIONAL_DISCLOSURE"
        )
        paths = {
            "proof": workspace.commit_proof_path(run.run_id),
            "pointer": workspace.pointer_path("phase6c-test"),
            "batch": workspace.event_batch_path(batch.batch_id),
        }
        paths[which].unlink()
        with pytest.raises(ReanalysisExecutionError, match="fully proven committed"):
            _executor(workspace, tmp_path).execute(run.run_id)

    def test_corrupt_commit_proof_fails_closed(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(
            tmp_path, "INFORMATIONAL_DISCLOSURE"
        )
        workspace.commit_proof_path(run.run_id).write_bytes(b"{}")
        with pytest.raises(ReanalysisExecutionError, match="fully proven committed"):
            _executor(workspace, tmp_path).execute(run.run_id)

    @pytest.mark.parametrize("field", ["as_of", "plan"])
    def test_tampered_run_or_plan_identity_fails_closed(self, tmp_path, field):
        workspace, _watchlist_value, _batch, run = _committed(
            tmp_path, "INFORMATIONAL_DISCLOSURE"
        )
        payload = json.loads(workspace.run_path(run.run_id).read_text(encoding="utf-8"))
        if field == "as_of":
            payload["as_of"] = "2030-01-01T00:00:00Z"
        else:
            payload["plan"]["run_id"] = "0" * 64
        workspace.run_path(run.run_id).write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ReanalysisExecutionError, match="fully proven committed"):
            _executor(workspace, tmp_path).execute(run.run_id)

    def test_execution_uses_committed_as_of_and_rejects_missing_event(self, tmp_path):
        workspace, _watchlist_value, batch, run = _committed(
            tmp_path, "INTERIM_REPORT"
        )
        batch_path = workspace.event_batch_path(batch.batch_id)
        batch_path.unlink()
        with pytest.raises(ReanalysisExecutionError, match="fully proven committed"):
            _executor(workspace, tmp_path).execute(run.run_id)


class TestImpactPolicyExecution:
    def test_no_reanalysis_is_zero_call_and_does_not_mutate_monitoring(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(
            tmp_path, "INFORMATIONAL_DISCLOSURE"
        )
        before = _json_files(workspace.root)
        preparation = CountingPreparation(_normalized())
        clients = _clients()
        result = _executor(
            workspace, tmp_path, preparation=preparation, clients=clients, model_allowed=True
        ).execute(run.run_id)[0]
        assert result.job.status is ReanalysisJobStatus.NO_ACTION
        assert result.job.evidence_codes == ["NO_REANALYSIS"]
        assert not preparation.calls
        assert not any(client.calls for client in clients)
        assert _json_files(workspace.root) == before

    def test_urgent_manual_review_is_zero_call_and_preserves_event_proof(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(
            tmp_path, "REGULATORY_PENALTY"
        )
        before = _json_files(workspace.root)
        preparation = CountingPreparation(_normalized())
        clients = _clients()
        result = _executor(
            workspace, tmp_path, preparation=preparation, clients=clients, model_allowed=True
        ).execute(run.run_id)[0]
        assert result.job.status is ReanalysisJobStatus.MANUAL_REVIEW_REQUIRED
        assert result.job.event_types == ["REGULATORY_PENALTY"]
        assert not preparation.calls
        assert not any(client.calls for client in clients)
        assert _json_files(workspace.root) == before

    def test_partial_happy_path_is_fresh_and_point_in_time_bound(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized()
        preparation = CountingPreparation(normalized)
        result = _executor(workspace, tmp_path, preparation=preparation).execute(run.run_id)[0]
        assert result.job.status is ReanalysisJobStatus.SUCCEEDED
        assert result.job.evidence_codes == ["BUSINESS_QUALITY_NOT_REFRESHED"]
        assert preparation.calls[0][0].as_of == AS_OF_DATE
        assert preparation.calls[0][1] is True
        assert result.artifacts is not None
        assert result.artifacts.analysis.business_quality is None
        assert result.artifacts.surface.analysis_id == result.artifacts.analysis.analysis_id

    def test_partial_reuses_only_explicit_prior_business_quality(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized(strong=True)
        research = run_business_quality_research(normalized, *_clients())
        prior = run_analyze(
            normalized,
            load_profile("strict-v1"),
            business_quality=research.business_quality,
        )
        result = _executor(
            workspace,
            tmp_path,
            preparation=CountingPreparation(normalized),
        ).execute(run.run_id, prior_analysis=prior)[0]
        assert result.job.status is ReanalysisJobStatus.SUCCEEDED
        assert result.job.evidence_codes == ["REUSED_PRIOR_BQ"]
        assert result.job.prior_analysis_id == prior.analysis_id
        assert result.artifacts is not None
        assert result.artifacts.analysis.business_quality is not None

    @pytest.mark.parametrize("mutation", ["listing", "profile", "future"])
    def test_invalid_prior_analysis_is_rejected_without_implicit_reuse(self, tmp_path, mutation):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized(strong=True)
        prior = run_analyze(normalized, load_profile("strict-v1"))
        if mutation == "listing":
            company = prior.company.model_copy(update={"primary_listing": "OTHER"})
            prior = prior.model_copy(update={"company": company})
        elif mutation == "profile":
            prior = prior.model_copy(update={"profile_id": "other-profile"})
        else:
            prior = prior.model_copy(update={"as_of": date(2030, 1, 1)})
        result = _executor(
            workspace, tmp_path, preparation=CountingPreparation(normalized)
        ).execute(run.run_id, prior_analysis=prior)[0]
        assert result.job.status is ReanalysisJobStatus.FAILED
        assert result.job.failure_code is ReanalysisFailureCode.INVALID_PRIOR_ANALYSIS
        assert not result.job.prior_analysis_id

    def test_full_without_research_runtime_is_blocked_before_preparation(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "ANNUAL_REPORT")
        preparation = CountingPreparation(_normalized(strong=True))
        result = _executor(workspace, tmp_path, preparation=preparation).execute(run.run_id)[0]
        assert result.job.status is ReanalysisJobStatus.BLOCKED
        assert result.job.failure_code is ReanalysisFailureCode.BLOCKED_RESEARCH_RUNTIME
        assert not preparation.calls

    def test_full_scripted_research_persists_all_outputs_and_is_idempotent(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "ANNUAL_REPORT")
        normalized = _normalized(strong=True)
        clients = _clients()
        executor = _executor(
            workspace,
            tmp_path,
            preparation=CountingPreparation(normalized),
            clients=clients,
            model_allowed=True,
        )
        first = executor.execute(run.run_id)[0]
        assert first.job.status is ReanalysisJobStatus.SUCCEEDED
        assert first.job.research_session_id
        assert first.job.report_id
        assert first.artifacts is not None
        assert first.artifacts.research_session is not None
        assert first.artifacts.report is not None
        counts = [len(client.calls) for client in clients]
        second = executor.execute(run.run_id, prepared_input=normalized)[0]
        assert second.reused is True
        assert [len(client.calls) for client in clients] == counts
        restored = ReanalysisJobStore(tmp_path / "jobs").load_success_artifacts(first.job)
        assert restored.surface.analysis_id == restored.analysis.analysis_id

    def test_network_deny_is_passed_as_offline_and_never_implies_model_access(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized()
        preparation = CountingPreparation(normalized)
        result = _executor(workspace, tmp_path, preparation=preparation).execute(
            run.run_id, network_allowed=False
        )[0]
        assert result.job.status is ReanalysisJobStatus.SUCCEEDED
        assert result.job.capabilities.network_allowed is False
        assert preparation.calls[0][1] is True

    def test_offline_path_remains_safe_when_socket_transport_is_blocked(
        self, tmp_path, monkeypatch
    ):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized()
        calls: list[bool] = []

        def blocked_socket(*_args, **_kwargs):
            raise AssertionError("offline preparation attempted socket transport")

        monkeypatch.setattr(socket, "create_connection", blocked_socket)

        class OfflinePreparation(CountingPreparation):
            def prepare(self, request, *, offline=False, **kwargs):
                calls.append(offline)
                return super().prepare(request, offline=offline, **kwargs)

        result = _executor(
            workspace, tmp_path, preparation=OfflinePreparation(normalized)
        ).execute(run.run_id, network_allowed=False)[0]
        assert result.job.status is ReanalysisJobStatus.SUCCEEDED
        assert calls == [True]


class TestAdjustmentAndFailureBoundaries:
    def test_fresh_input_drops_implicit_prior_adjustments(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized(keep_adjustments=True)
        result = _executor(
            workspace, tmp_path, preparation=CountingPreparation(normalized)
        ).execute(run.run_id)[0]
        assert result.job.status is ReanalysisJobStatus.SUCCEEDED
        assert result.artifacts is not None
        assert result.artifacts.normalized_input.adjustments == []
        assert result.artifacts.analysis.adjustments == []

    def test_only_explicitly_accepted_adjustment_uses_materialization_boundary(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized()
        adjustment = Adjustment(
            id="explicit-human-adjustment",
            target_field="ordinary_dividend_cash",
            target_period="FY2021",
            adjustment_type=AdjustmentType.NORMALIZE,
            input_value=28.0,
            proposed_adjusted_value=30.0,
            status=AdjustmentStatus.ACCEPTED,
            reason="Explicit deterministic test approval.",
            source_evidence_ids=[normalized.evidence_index[0].id],
            proposed_by="HUMAN",
            approved_by="HUMAN",
            confidence=1.0,
        )
        result = _executor(
            workspace, tmp_path, preparation=CountingPreparation(normalized)
        ).execute(run.run_id, accepted_adjustments=[adjustment])[0]
        assert result.job.status is ReanalysisJobStatus.SUCCEEDED
        assert result.job.capabilities.accepted_adjustments_supplied is True
        assert result.artifacts is not None
        assert any(item.id == adjustment.id for item in result.artifacts.analysis.adjustments)

    def test_proposed_adjustment_is_not_auto_approved(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized()
        proposal = Adjustment(
            id="explicit-proposal-only",
            target_field="ordinary_dividend_cash",
            target_period="FY2021",
            adjustment_type=AdjustmentType.NORMALIZE,
            input_value=28.0,
            proposed_adjusted_value=30.0,
            status=AdjustmentStatus.PROPOSED,
            reason="Proposal must remain ineffective.",
            source_evidence_ids=[normalized.evidence_index[0].id],
            proposed_by="LLM",
            approved_by=None,
            confidence=0.8,
        )
        result = _executor(
            workspace, tmp_path, preparation=CountingPreparation(normalized)
        ).execute(run.run_id, accepted_adjustments=[proposal])[0]
        assert result.job.status is ReanalysisJobStatus.SUCCEEDED
        assert result.artifacts is not None
        effective = [
            fact
            for fact in result.artifacts.normalized_input.facts
            if fact.field == "ordinary_dividend_cash"
        ]
        assert effective and effective[0].value == 28.0
        assert not any(fact.applied_adjustment_ids for fact in effective)

    def test_preparation_exception_is_stable_and_bounded(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        result = _executor(
            workspace,
            tmp_path,
            preparation=CountingPreparation(
                _normalized(), error=RuntimeError("provider-secret-token")
            ),
        ).execute(run.run_id)[0]
        assert result.job.status is ReanalysisJobStatus.FAILED
        assert result.job.failure_code is ReanalysisFailureCode.PREPARATION_FAILED
        assert "provider-secret-token" not in (result.job.message or "")
        assert len(result.job.message or "") <= 512

    def test_research_exception_is_stable_and_does_not_persist_outputs(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "ANNUAL_REPORT")
        result = ReanalysisExecutor(
            workspace,
            ReanalysisJobStore(tmp_path / "jobs"),
            preparation=CountingPreparation(_normalized(strong=True)),
            research_orchestrator=FailingResearch(),
            model_allowed=True,
        ).execute(run.run_id)[0]
        assert result.job.failure_code is ReanalysisFailureCode.RESEARCH_FAILED
        assert "secret-model-token" not in (result.job.message or "")
        assert result.job.analysis_id is None

    def test_analysis_exception_is_stable(self, tmp_path, monkeypatch):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        import turtle_value_engine.monitoring_execution.executor as executor_module

        def fail(*_args, **_kwargs):
            raise RuntimeError("analysis-secret")

        monkeypatch.setattr(executor_module, "run_analyze", fail)
        result = _executor(
            workspace, tmp_path, preparation=CountingPreparation(_normalized())
        ).execute(run.run_id)[0]
        assert result.job.failure_code is ReanalysisFailureCode.ANALYSIS_FAILED

    def test_surface_exception_is_stable(self, tmp_path, monkeypatch):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        import turtle_value_engine.monitoring_execution.executor as executor_module

        monkeypatch.setattr(
            executor_module,
            "build_research_surface_snapshot",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("surface-secret")),
        )
        result = _executor(
            workspace, tmp_path, preparation=CountingPreparation(_normalized())
        ).execute(run.run_id)[0]
        assert result.job.failure_code is ReanalysisFailureCode.SURFACE_FAILED


class TestDurabilityAndSurface:
    def test_job_identity_is_stable_and_includes_committed_as_of(self, tmp_path):
        first = _committed(tmp_path / "first", "INTERIM_REPORT")
        second = _committed(tmp_path / "second", "INTERIM_REPORT")
        normalized = _normalized()
        first_result = _executor(
            first[0], tmp_path / "first", preparation=CountingPreparation(normalized)
        ).execute(first[3].run_id)[0]
        second_result = _executor(
            second[0], tmp_path / "second", preparation=CountingPreparation(normalized)
        ).execute(second[3].run_id)[0]
        assert first_result.job.job_id == second_result.job.job_id
        assert first_result.job.execution_as_of.isoformat().startswith("2026-09-08")

    def test_repeated_success_has_no_duplicate_preparation_or_model_calls(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "ANNUAL_REPORT")
        normalized = _normalized(strong=True)
        preparation = CountingPreparation(normalized)
        clients = _clients()
        executor = _executor(
            workspace,
            tmp_path,
            preparation=preparation,
            clients=clients,
            model_allowed=True,
        )
        executor.execute(run.run_id)
        executor.execute(run.run_id)
        assert len(preparation.calls) == 1
        assert [len(client.calls) for client in clients] == [8, 8, 8]

    def test_conflicting_content_under_successful_identity_fails_closed(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized()
        result = _executor(
            workspace, tmp_path, preparation=CountingPreparation(normalized)
        ).execute(run.run_id)[0]
        payload = result.job.model_dump(mode="python", warnings=False)
        payload.pop("job_id")
        payload.pop("content_sha256")
        payload["capabilities"]["network_allowed"] = True
        from turtle_value_engine.monitoring_execution import ReanalysisJobV1

        conflicting = ReanalysisJobV1.build(**payload)
        with pytest.raises(ReanalysisJobStoreError, match="conflicting terminal content"):
            ReanalysisJobStore(tmp_path / "jobs").save(conflicting)

    def test_pointer_write_failure_recovers_without_repeating_calls(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized()
        preparation = CountingPreparation(normalized)
        failed_once = True

        def fail_pointer(_path, kind):
            nonlocal failed_once
            if kind == "pointer" and failed_once:
                failed_once = False
                raise OSError("pointer crash")

        with pytest.raises(ReanalysisJobStoreError):
            _executor(
                workspace,
                tmp_path,
                preparation=preparation,
                failure_injector=fail_pointer,
            ).execute(run.run_id)
        recovered = _executor(
            workspace,
            tmp_path,
            preparation=preparation,
        ).execute(run.run_id)[0]
        assert recovered.reused is True
        assert len(preparation.calls) == 1
        assert (tmp_path / "jobs" / "jobs" / "latest").is_dir()

    def test_immutable_artifact_failure_can_retry(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        normalized = _normalized()
        failed_once = True

        def fail_artifact(_path, kind):
            nonlocal failed_once
            if kind == "artifact" and failed_once:
                failed_once = False
                raise OSError("artifact crash")

        with pytest.raises(ReanalysisJobStoreError):
            _executor(
                workspace,
                tmp_path,
                preparation=CountingPreparation(normalized),
                failure_injector=fail_artifact,
            ).execute(run.run_id)
        retry = _executor(
            workspace, tmp_path, preparation=CountingPreparation(normalized)
        ).execute(run.run_id)[0]
        assert retry.job.status is ReanalysisJobStatus.SUCCEEDED

    def test_no_nonterminal_state_is_persisted(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "INTERIM_REPORT")
        result = _executor(
            workspace, tmp_path, preparation=CountingPreparation(_normalized())
        ).execute(run.run_id)[0]
        payload = json.loads(
            ReanalysisJobStore(tmp_path / "jobs")
            .attempt_path(result.attempt.attempt_id)
            .read_text(encoding="utf-8")
        )
        assert payload["job"]["status"] not in {"PENDING", "RUNNING"}

    def test_surface_artifact_validates_against_analysis_trace_and_report(self, tmp_path):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "ANNUAL_REPORT")
        normalized = _normalized(strong=True)
        result = _executor(
            workspace,
            tmp_path,
            preparation=CountingPreparation(normalized),
            clients=_clients(),
            model_allowed=True,
        ).execute(run.run_id)[0]
        assert result.artifacts is not None
        store = ReanalysisJobStore(tmp_path / "jobs")
        restored = store.load_success_artifacts(result.job)
        assert restored.surface.analysis_id == restored.analysis.analysis_id
        assert restored.surface.decision_trace_reference is not None
        assert restored.surface.research_report_reference is not None


class TestSchemaAndCli:
    @pytest.mark.parametrize(
        ("filename", "model_name"),
        [
            ("monitoring-commit-proof.schema.json", "MonitoringCommitProofV1"),
            ("reanalysis-capability-summary.schema.json", "ReanalysisCapabilitySummaryV1"),
            ("reanalysis-job.schema.json", "ReanalysisJobV1"),
            ("reanalysis-job-attempt.schema.json", "ReanalysisJobAttemptV1"),
            ("reanalysis-job-pointer.schema.json", "ReanalysisJobPointerV1"),
        ],
    )
    def test_new_checked_in_schemas_are_draft_2020_12_and_current(self, filename, model_name):
        import turtle_value_engine.monitoring as monitoring
        import turtle_value_engine.monitoring_execution as execution

        model = getattr(monitoring, model_name, None) or getattr(execution, model_name)
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert model.model_json_schema() == schema

    def test_cli_output_is_bounded_and_secret_free(self, tmp_path, capsys):
        workspace, _watchlist_value, _batch, run = _committed(tmp_path, "ANNUAL_REPORT")
        code = main(
            [
                "watch",
                "execute-reanalysis",
                "--workspace",
                str(workspace.root),
                "--run-id",
                run.run_id,
                "--job-root",
                str(tmp_path / "cli-jobs"),
                "--listing",
                "SH600001",
            ]
        )
        assert code == 0
        output = capsys.readouterr().out
        assert len(output) < 20_000
        assert "token" not in output.lower()
        payload = json.loads(output)
        assert payload["jobs"][0]["status"] == "BLOCKED"

    def test_cli_reanalysis_status_returns_bounded_job_projection(self, tmp_path, capsys):
        workspace, _watchlist_value, _batch, run = _committed(
            tmp_path, "INFORMATIONAL_DISCLOSURE"
        )
        code = main(
            [
                "watch",
                "execute-reanalysis",
                "--workspace",
                str(workspace.root),
                "--run-id",
                run.run_id,
                "--job-root",
                str(tmp_path / "cli-jobs"),
                "--listing",
                "SH600001",
            ]
        )
        assert code == 0
        output = json.loads(capsys.readouterr().out)
        job_id = output["jobs"][0]["job_id"]
        assert (
            main(
                [
                    "watch",
                    "reanalysis-status",
                    "--job-root",
                    str(tmp_path / "cli-jobs"),
                    "--job-id",
                    job_id,
                ]
            )
            == 0
        )
        status = json.loads(capsys.readouterr().out)
        assert status["job"]["job_id"] == job_id
