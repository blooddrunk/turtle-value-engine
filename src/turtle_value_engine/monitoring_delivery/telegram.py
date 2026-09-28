"""Optional Telegram Bot API adapter over the durable D2B delivery ledger.

One delivery identity produces at most one ``sendMessage`` request per durable
dispatch claim. Telegram does not promise receiver-side idempotency, so an
uncertain post-dispatch outcome is never automatically resent.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from turtle_value_engine.monitoring.canonical import canonical_json_bytes

from .contracts import (
    DeliveryFailureCode,
    DeliveryStatus,
    MonitoringTelegramPayloadV1,
)
from .transport import (
    TransportOutcome,
    WebhookEndpointError,
    WebhookHttpTransport,
    WebhookRequest,
)

_BOT_TOKEN = re.compile(r"^[0-9]+:[A-Za-z0-9_-]+$")
_CHAT_ID = re.compile(r"^-?[0-9]+$")
_SEND_PATH = re.compile(r"^/bot[0-9]+:[A-Za-z0-9_-]+/sendMessage$")
_TELEGRAM_TEXT_LIMIT = 4096


def _telegram_text_units(value: str) -> int:
    """Count UTF-16 units conservatively for Bot API text limits."""

    return len(value.encode("utf-16-le")) // 2


def telegram_endpoint_from_token(token: str) -> str:
    """Construct Telegram's fixed HTTPS endpoint without exposing the token."""

    if not isinstance(token, str) or len(token) > 256 or not _BOT_TOKEN.fullmatch(token):
        raise WebhookEndpointError("Telegram bot token is missing or malformed")
    return f"https://api.telegram.org/bot{token}/sendMessage"


def telegram_destination_id(base: str, token: str, chat_id: str) -> str:
    """Bind the durable destination to the non-secret bot and chat identities."""

    import hashlib

    telegram_endpoint_from_token(token)
    if not _CHAT_ID.fullmatch(chat_id):
        raise WebhookEndpointError("Telegram chat ID must be numeric")
    bot_id = token.split(":", 1)[0]
    suffix = "-telegram-" + hashlib.sha256(
        f"{bot_id}:{chat_id}".encode("ascii")
    ).hexdigest()[:12]
    prefix = base[: 128 - len(suffix)].rstrip("-._")
    return f"{prefix or 'owner'}{suffix}"


def discover_telegram_chats(token: str) -> list[dict[str, str]]:
    """Read recent bot chats once, without confirming or consuming updates."""

    endpoint = telegram_endpoint_from_token(token).replace("/sendMessage", "/getUpdates")
    chats: dict[str, str] = {}

    def classify(status: int, body: bytes) -> TransportOutcome:
        if not 200 <= status < 300:
            return classify_telegram_response(status, body)
        try:
            response = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = None
        if not isinstance(response, dict) or response.get("ok") is not True:
            return classify_telegram_response(status, body)
        updates = response.get("result")
        if not isinstance(updates, list) or len(updates) > 100:
            return TransportOutcome(
                DeliveryStatus.AMBIGUOUS,
                status,
                None,
                DeliveryFailureCode.RESPONSE_UNVERIFIED,
            )
        for update in updates:
            message = update.get("message") if isinstance(update, dict) else None
            chat = message.get("chat") if isinstance(message, dict) else None
            chat_id = chat.get("id") if isinstance(chat, dict) else None
            chat_type = chat.get("type") if isinstance(chat, dict) else None
            if type(chat_id) is int and isinstance(chat_type, str):
                chats[str(chat_id)] = chat_type
        return TransportOutcome(DeliveryStatus.DELIVERED, status, None, None)

    body = canonical_json_bytes({"limit": 100, "timeout": 0})
    outcome = WebhookHttpTransport(response_classifier=classify).send(
        endpoint=endpoint,
        auth_bearer=None,
        request=WebhookRequest(
            body=body,
            idempotency_key="telegram-chat-discovery",
            timeout_seconds=10.0,
            max_response_bytes=65536,
        ),
    )
    if outcome.classification != DeliveryStatus.DELIVERED:
        code = "UNKNOWN" if outcome.error_code is None else outcome.error_code.value
        raise WebhookEndpointError(f"Telegram chat discovery failed: {code}")
    return [{"chat_id": chat_id, "type": chats[chat_id]} for chat_id in sorted(chats)]


def render_telegram_text(payload: MonitoringTelegramPayloadV1) -> str:
    """Render one deterministic, bounded Chinese-first notification."""

    header = (
        "Turtle 监控提醒\n"
        f"截至 {payload.as_of.isoformat()}\n"
        f"共 {payload.alert_count} 条提醒"
    )
    footer = f"\n交付编号：{payload.delivery_id}"
    lines: list[str] = []
    for alert in payload.alerts:
        label = alert.listing_id or "监控任务"
        line = f"\n\n{label}：{alert.message}"
        remaining = payload.alert_count - len(lines) - 1
        overflow_note = (
            f"\n另有 {remaining} 条提醒，请在监控面板查看。" if remaining else ""
        )
        if (
            _telegram_text_units(header + "".join(lines) + line + overflow_note + footer)
            > _TELEGRAM_TEXT_LIMIT
        ):
            break
        lines.append(line)
    omitted = payload.alert_count - len(lines)
    note = f"\n另有 {omitted} 条提醒，请在监控面板查看。" if omitted else ""
    text = header + "".join(lines) + note + footer
    if _telegram_text_units(text) > _TELEGRAM_TEXT_LIMIT:
        raise ValueError("Telegram alert summary exceeds its bounded message limit")
    return text


def classify_telegram_response(
    status: int,
    body: bytes,
    *,
    expected_chat_id: str | None = None,
    expected_text: str | None = None,
) -> TransportOutcome:
    """Require Bot API ``ok=true``; HTTP 2xx alone does not prove delivery."""

    if status == 429 or 500 <= status < 600:
        return TransportOutcome(
            DeliveryStatus.RETRYABLE_FAILURE,
            status,
            None,
            DeliveryFailureCode.HTTP_RETRYABLE_STATUS,
        )
    if 300 <= status < 400:
        return TransportOutcome(
            DeliveryStatus.PERMANENT_FAILURE,
            status,
            None,
            DeliveryFailureCode.HTTP_REDIRECT_NOT_FOLLOWED,
        )
    if not 200 <= status < 300:
        return TransportOutcome(
            DeliveryStatus.PERMANENT_FAILURE,
            status,
            None,
            DeliveryFailureCode.HTTP_PERMANENT_STATUS,
        )
    try:
        response = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        response = None
    if not isinstance(response, dict) or type(response.get("ok")) is not bool:
        return TransportOutcome(
            DeliveryStatus.AMBIGUOUS,
            status,
            None,
            DeliveryFailureCode.RESPONSE_UNVERIFIED,
        )
    if response["ok"] is True:
        if expected_chat_id is not None or expected_text is not None:
            result = response.get("result")
            chat = result.get("chat") if isinstance(result, dict) else None
            chat_id = chat.get("id") if isinstance(chat, dict) else None
            if (
                not isinstance(result, dict)
                or type(chat_id) is not int
                or str(chat_id) != expected_chat_id
                or result.get("text") != expected_text
            ):
                return TransportOutcome(
                    DeliveryStatus.AMBIGUOUS,
                    status,
                    None,
                    DeliveryFailureCode.RESPONSE_UNVERIFIED,
                )
        return TransportOutcome(DeliveryStatus.DELIVERED, status, None, None)
    error_code = response.get("error_code")
    if type(error_code) is int and (error_code == 429 or error_code >= 500):
        return TransportOutcome(
            DeliveryStatus.RETRYABLE_FAILURE,
            status,
            None,
            DeliveryFailureCode.TELEGRAM_API_REJECTED,
        )
    return TransportOutcome(
        DeliveryStatus.PERMANENT_FAILURE,
        status,
        None,
        DeliveryFailureCode.TELEGRAM_API_REJECTED,
    )


class TelegramBotTransport:
    """Render a validated alert envelope and send it to one numeric chat."""

    def __init__(self, *, chat_id: str) -> None:
        if not isinstance(chat_id, str) or not _CHAT_ID.fullmatch(chat_id):
            raise WebhookEndpointError("Telegram chat ID must be numeric")
        self.chat_id = chat_id

    def send(
        self,
        *,
        endpoint: str,
        auth_bearer: str | None,
        request: WebhookRequest,
    ) -> TransportOutcome:
        try:
            parts = urlsplit(endpoint)
            port = parts.port
        except ValueError:
            raise WebhookEndpointError("Telegram endpoint is malformed") from None
        if (
            parts.scheme != "https"
            or parts.hostname != "api.telegram.org"
            or port is not None
            or parts.query
            or parts.fragment
            or parts.username is not None
            or not _SEND_PATH.fullmatch(parts.path)
        ):
            raise WebhookEndpointError(
                "Telegram endpoint must be the fixed Bot API sendMessage URL"
            )
        if auth_bearer is not None:
            raise WebhookEndpointError("Telegram transport does not accept a bearer token")
        try:
            payload = MonitoringTelegramPayloadV1.model_validate_json(request.body)
            if payload.canonical_bytes() != request.body:
                raise ValueError("non-canonical payload")
            message = render_telegram_text(payload)
        except (ValueError, UnicodeError):
            raise WebhookEndpointError("Telegram alert payload is invalid") from None
        body = canonical_json_bytes({"chat_id": self.chat_id, "text": message})
        http = WebhookHttpTransport(
            response_classifier=lambda status, response: classify_telegram_response(
                status,
                response,
                expected_chat_id=self.chat_id,
                expected_text=message,
            )
        )
        return http.send(
            endpoint=endpoint,
            auth_bearer=None,
            request=WebhookRequest(
                body=body,
                idempotency_key=request.idempotency_key,
                timeout_seconds=request.timeout_seconds,
                max_response_bytes=request.max_response_bytes,
            ),
        )


__all__ = [
    "TelegramBotTransport",
    "classify_telegram_response",
    "discover_telegram_chats",
    "render_telegram_text",
    "telegram_destination_id",
    "telegram_endpoint_from_token",
]
