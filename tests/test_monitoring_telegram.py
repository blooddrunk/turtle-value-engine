"""Focused offline proofs for the optional Telegram delivery preset."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import turtle_value_engine.cli as cli
import turtle_value_engine.monitoring_delivery.telegram as telegram
from turtle_value_engine.cli import _run_watch_telegram_chats
from turtle_value_engine.config.project import ProjectConfig
from turtle_value_engine.monitoring_delivery import (
    DeliveryNetworkDeniedError,
    DeliverySettingsV1,
    DeliveryStatus,
    MonitoringDeliveryIntentV1,
    MonitoringTelegramPayloadV1,
    MonitoringWebhookAlertV1,
    TelegramBotTransport,
    WebhookHttpTransport,
    WebhookRequest,
    classify_telegram_response,
    render_telegram_text,
    telegram_destination_id,
)


def _telegram_payload(alert_count: int = 1) -> MonitoringTelegramPayloadV1:
    return MonitoringTelegramPayloadV1(
        delivery_id="a" * 64,
        destination_id="owner-telegram",
        runner_id="owner-runner",
        activation_id="b" * 64,
        cycle_id="c" * 64,
        watchlist_id="owner-watchlist",
        as_of=datetime(2026, 9, 28, tzinfo=UTC),
        d1_status="COMPLETED",
        alert_batch_id="d" * 64,
        alert_batch_content_sha256="e" * 64,
        alert_count=alert_count,
        alerts=[
            MonitoringWebhookAlertV1(
                alert_id=f"{index:064x}",
                kind="FILING",
                listing_id="SH600519",
                reason_code="DISCLOSURE",
                message="发现一则新披露，请查看监控面板。" * 15,
            )
            for index in range(alert_count)
        ],
    )


def test_telegram_preset_has_distinct_durable_identity_and_rejects_idempotency_claim() -> None:
    base = dict(
        runner_id="owner-runner",
        activation_id="b" * 64,
        cycle_id="c" * 64,
        d1_status="COMPLETED",
        result_content_sha256="f" * 64,
        alert_batch_id="d" * 64,
        alert_batch_content_sha256="e" * 64,
        destination_id="owner-primary",
        payload_sha256="1" * 64,
        payload_bytes=100,
        empty_outbox=False,
        max_attempts=5,
        timeout_seconds=10.0,
        backoff_base_seconds=60,
        backoff_cap_seconds=3600,
        receiver_idempotency_declared=False,
        created_at=datetime(2026, 9, 28, tzinfo=UTC),
    )
    webhook = MonitoringDeliveryIntentV1.build(**base)
    telegram_intent = MonitoringDeliveryIntentV1.build(
        **base,
        transport="telegram-v1",
        payload_contract="monitoring_delivery_telegram_payload_v1",
    )
    assert webhook.delivery_id != telegram_intent.delivery_id
    with pytest.raises(ValidationError, match="transport and payload contract"):
        MonitoringDeliveryIntentV1.build(**base, transport="telegram-v1")
    with pytest.raises(ValidationError, match="receiver idempotency"):
        DeliverySettingsV1(
            destination_id="owner-telegram",
            transport="telegram-v1",
            receiver_idempotency_declared=True,
        )
    first = telegram_destination_id("owner", "123:abc_DEF", "123456789")
    assert first == telegram_destination_id("owner", "123:rotated_TOKEN", "123456789")
    assert first != telegram_destination_id("owner", "123:abc_DEF", "987654321")
    assert first != telegram_destination_id("owner", "456:abc_DEF", "123456789")


def test_telegram_response_requires_bot_receipt_and_matching_message() -> None:
    message = "Turtle 监控提醒"
    accepted = json.dumps(
        {"ok": True, "result": {"message_id": 1, "chat": {"id": 123}, "text": message}}
    ).encode()
    assert classify_telegram_response(
        200, accepted, expected_chat_id="123", expected_text=message
    ).classification == DeliveryStatus.DELIVERED
    assert classify_telegram_response(
        200, accepted, expected_chat_id="456", expected_text=message
    ).classification == DeliveryStatus.AMBIGUOUS
    assert classify_telegram_response(200, b"{}", expected_chat_id="123").classification == (
        DeliveryStatus.AMBIGUOUS
    )
    assert classify_telegram_response(200, b'{"ok":false,"error_code":400}').classification == (
        DeliveryStatus.PERMANENT_FAILURE
    )
    assert classify_telegram_response(429, b"").classification == (
        DeliveryStatus.RETRYABLE_FAILURE
    )


def test_http_transport_does_not_treat_telegram_ok_false_as_delivered() -> None:
    response_body = b'{"ok":false,"error_code":400}'

    class FakeResponse:
        status = 200

        def __init__(self):
            self.unread = response_body

        def getheader(self, _name):
            return str(len(response_body))

        def read(self, _size):
            chunk, self.unread = self.unread, b""
            return chunk

    class FakeSocket:
        def settimeout(self, _remaining):
            return None

    class FakeConnection:
        sock = FakeSocket()

        def connect(self):
            return None

        def request(self, *_args, **_kwargs):
            return None

        def getresponse(self):
            return FakeResponse()

        def close(self):
            return None

    transport = WebhookHttpTransport(
        monotonic_clock=lambda: 0.0,
        connection_factory=lambda **_kwargs: FakeConnection(),
        response_classifier=classify_telegram_response,
    )
    outcome = transport.send(
        endpoint="https://api.telegram.org/bot123:abc/sendMessage",
        auth_bearer=None,
        request=WebhookRequest(
            body=b"{}",
            idempotency_key="a" * 64,
            timeout_seconds=10.0,
            max_response_bytes=1024,
        ),
    )
    assert outcome.classification == DeliveryStatus.PERMANENT_FAILURE
    assert outcome.response_body_sha256 is not None


def test_telegram_transport_posts_bounded_plain_text_once(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _telegram_payload(30)
    text = render_telegram_text(payload)
    assert len(text) <= 4096
    assert "另有" in text
    assert payload.delivery_id in text
    sent: list[dict[str, object]] = []

    class FakeHttp:
        def __init__(self, *, response_classifier):
            self.classifier = response_classifier

        def send(self, *, endpoint, auth_bearer, request):
            sent.append(
                {
                    "endpoint": endpoint,
                    "auth_bearer": auth_bearer,
                    "body": json.loads(request.body),
                    "key": request.idempotency_key,
                }
            )
            return self.classifier(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "message_id": 1,
                            "chat": {"id": 123},
                            "text": json.loads(request.body)["text"],
                        },
                    }
                ).encode(),
            )

    monkeypatch.setattr(telegram, "WebhookHttpTransport", FakeHttp)
    result = TelegramBotTransport(chat_id="123").send(
        endpoint="https://api.telegram.org/bot123:abc/sendMessage",
        auth_bearer=None,
        request=WebhookRequest(
            body=payload.canonical_bytes(),
            idempotency_key=payload.delivery_id,
            timeout_seconds=10.0,
            max_response_bytes=65536,
        ),
    )
    assert result.classification == DeliveryStatus.DELIVERED
    assert len(sent) == 1
    assert sent[0]["auth_bearer"] is None
    assert sent[0]["body"] == {"chat_id": "123", "text": text}
    assert sent[0]["key"] == payload.delivery_id


def test_config_and_chat_discovery_are_opt_in_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ProjectConfig.model_validate(
        {
            "monitoring": {
                "delivery": {
                    "enabled": True,
                    "transport": "telegram-v1",
                    "destination_id": "owner",
                    "telegram_bot_token_ref": {
                        "env": "TVE_MONITORING_TELEGRAM_BOT_TOKEN"
                    },
                    "telegram_chat_id": "123",
                }
            }
        }
    )
    assert config.safe_summary()["monitoring"]["delivery"]["telegram_bot_token_ref"] == (
        "TVE_MONITORING_TELEGRAM_BOT_TOKEN"
    )
    with pytest.raises(ValidationError, match="Telegram does not provide"):
        ProjectConfig.model_validate(
            {
                "monitoring": {
                    "delivery": {
                        "enabled": True,
                        "transport": "telegram-v1",
                        "telegram_bot_token_ref": {"env": "TVE_TOKEN"},
                        "telegram_chat_id": "123",
                        "receiver_idempotency_declared": True,
                    }
                }
            }
        )
    called = False

    def fake_discovery(_token: str):
        nonlocal called
        called = True
        return [{"chat_id": "123", "type": "private"}]

    monkeypatch.setattr("turtle_value_engine.cli.discover_telegram_chats", fake_discovery)
    monkeypatch.setenv("TVE_MONITORING_TELEGRAM_BOT_TOKEN", "123:secret")
    with pytest.raises(DeliveryNetworkDeniedError):
        _run_watch_telegram_chats(
            SimpleNamespace(network="deny", bot_token_env="TVE_MONITORING_TELEGRAM_BOT_TOKEN")
        )
    assert called is False
    result = _run_watch_telegram_chats(
        SimpleNamespace(network="allow", bot_token_env="TVE_MONITORING_TELEGRAM_BOT_TOKEN")
    )
    assert result["suggested_chat_id"] == "123"
    assert "123:secret" not in json.dumps(result)


def test_unattended_notify_composes_one_terminal_activation_without_early_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ProjectConfig.model_validate(
        {
            "monitoring": {
                "delivery": {
                    "enabled": True,
                    "transport": "telegram-v1",
                    "telegram_bot_token_ref": {"env": "TVE_TOKEN"},
                    "telegram_chat_id": "123",
                }
            }
        }
    )
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(cli, "load_project_config", lambda _path: config)

    def fake_runner(_args):
        calls.append(("runner", None))
        return {"activation_id": "a" * 64, "classification": "COMPLETED_REUSED"}

    def fake_deliver(args):
        calls.append(("deliver", args.activation_id))
        return {"classification": "DELIVERED", "http_requests": 0}

    monkeypatch.setattr(cli, "_run_watch_unattended_run", fake_runner)
    monkeypatch.setattr(cli, "_run_watch_deliver", fake_deliver)
    args = SimpleNamespace(
        runner_config="runner.json", project_config="project.toml", network="deny", output=None
    )
    with pytest.raises(DeliveryNetworkDeniedError):
        cli._run_watch_unattended_notify(args)
    assert calls == []
    args.network = "allow"
    result = cli._run_watch_unattended_notify(args)
    assert calls == [("runner", None), ("deliver", "a" * 64)]
    assert result["delivery"]["classification"] == "DELIVERED"


def test_telegram_schema_is_checked_in() -> None:
    from pathlib import Path

    schema = (
        Path(__file__).resolve().parents[1]
        / "schemas/monitoring-delivery-telegram-payload.schema.json"
    )
    checked_in = json.loads(schema.read_text(encoding="utf-8"))
    assert checked_in == MonitoringTelegramPayloadV1.model_json_schema()
