"""Generic HTTP webhook transport for Phase 6-D2B.

One bounded POST of the canonical JSON payload with a deterministic
idempotency key.  The transport is provider-neutral: it knows nothing about
Slack/Telegram/email specifics and carries no vendor routing.  Endpoint URL
and bearer token are secret material resolved by the caller in process
memory; this module must never echo either into exceptions, logs or
persisted state — every failure is reported as a stable machine code with a
sanitized message.

Semantics (explicitly not exactly-once for arbitrary receivers):

- any 2xx -> ``DELIVERED``;
- 429 and 5xx -> ``RETRYABLE_FAILURE``;
- redirects are never followed: 3xx -> ``PERMANENT_FAILURE``;
- ordinary non-retryable 4xx -> ``PERMANENT_FAILURE``;
- a connect failure proven to precede request dispatch is retryable;
- a timeout or connection loss after dispatch may have reached the receiver
  and is ``AMBIGUOUS`` — never a false success and never falsely called
  unsent.

Response bodies are capped and persisted only as a SHA-256 digest by the
caller; raw untrusted response content never leaves this transport's read
buffer.
"""

from __future__ import annotations

import hashlib
import http.client
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from .contracts import DeliveryFailureCode, DeliveryStatus

_USER_AGENT = "turtle-value-engine monitoring-delivery webhook-v1"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class WebhookEndpointError(ValueError):
    """Raised when the configured endpoint is missing or invalid.

    The message deliberately never contains the endpoint itself: a webhook
    URL can embed credential material in its path or query string.
    """


class WebhookTransportError(ValueError):
    """Raised when the transport cannot produce a classified outcome."""


@dataclass(frozen=True, slots=True)
class WebhookRequest:
    """In-memory request material; never persisted or logged."""

    body: bytes
    idempotency_key: str
    timeout_seconds: float
    max_response_bytes: int


@dataclass(frozen=True, slots=True)
class TransportOutcome:
    """Classified outcome of exactly one outbound HTTP exchange."""

    classification: DeliveryStatus
    http_status: int | None
    response_body_sha256: str | None
    error_code: DeliveryFailureCode | None


class WebhookTransport(Protocol):
    def send(
        self,
        *,
        endpoint: str,
        auth_bearer: str | None,
        request: WebhookRequest,
    ) -> TransportOutcome:
        """Perform one bounded outbound POST and classify the result."""


def _parse_webhook_endpoint(
    endpoint: str, *, allow_loopback_http: bool
) -> tuple[str, str, int, str]:
    """Validate and split the endpoint without ever echoing it."""

    if not isinstance(endpoint, str) or not endpoint.strip():
        raise WebhookEndpointError("webhook endpoint is missing or empty")
    parts = urlsplit(endpoint.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"https", "http"}:
        raise WebhookEndpointError("webhook endpoint scheme must be https")
    if scheme == "http" and not allow_loopback_http:
        raise WebhookEndpointError(
            "webhook endpoint must use https; plain http is not a live transport"
        )
    host = parts.hostname
    if not host:
        raise WebhookEndpointError("webhook endpoint host is missing")
    if "@" in (parts.netloc or ""):
        raise WebhookEndpointError("webhook endpoint must not embed userinfo credentials")
    try:
        port = parts.port
    except ValueError as exc:
        raise WebhookEndpointError("webhook endpoint port is invalid") from exc
    if scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise WebhookEndpointError("plain http webhook endpoints are loopback-test-only")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return scheme, host, port, path


def _classify_status(status: int) -> TransportOutcome:
    if 200 <= status < 300:
        return TransportOutcome(
            DeliveryStatus.DELIVERED, status, None, None
        )
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
    return TransportOutcome(
        DeliveryStatus.PERMANENT_FAILURE,
        status,
        None,
        DeliveryFailureCode.HTTP_PERMANENT_STATUS,
    )


class WebhookHttpTransport:
    """Real generic HTTP webhook transport over ``http.client``.

    ``allow_loopback_http`` is the explicit test-only injection path for
    plain-http loopback receivers; the live CLI path always constructs this
    transport without it, so a live endpoint must be HTTPS.
    """

    def __init__(self, *, allow_loopback_http: bool = False) -> None:
        self.allow_loopback_http = allow_loopback_http

    def send(
        self,
        *,
        endpoint: str,
        auth_bearer: str | None,
        request: WebhookRequest,
    ) -> TransportOutcome:
        scheme, host, port, path = _parse_webhook_endpoint(
            endpoint, allow_loopback_http=self.allow_loopback_http
        )
        default_port = 443 if scheme == "https" else 80
        connection: http.client.HTTPConnection
        if scheme == "https":
            connection = http.client.HTTPSConnection(
                host, port if port is not None else default_port, timeout=request.timeout_seconds
            )
        else:
            connection = http.client.HTTPConnection(
                host, port if port is not None else default_port, timeout=request.timeout_seconds
            )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
            "Idempotency-Key": request.idempotency_key,
            "X-TVE-Delivery-Id": request.idempotency_key,
            "Content-Length": str(len(request.body)),
        }
        if auth_bearer:
            headers["Authorization"] = f"Bearer {auth_bearer}"
        try:
            try:
                connection.connect()
            except (OSError, socket.gaierror):
                # Proven to precede any request dispatch: honestly retryable.
                return TransportOutcome(
                    DeliveryStatus.RETRYABLE_FAILURE,
                    None,
                    None,
                    DeliveryFailureCode.CONNECT_FAILED_PRE_DISPATCH,
                )
            try:
                connection.request("POST", path, body=request.body, headers=headers)
                response = connection.getresponse()
            except TimeoutError:
                return TransportOutcome(
                    DeliveryStatus.AMBIGUOUS,
                    None,
                    None,
                    DeliveryFailureCode.TIMEOUT_AFTER_DISPATCH,
                )
            except (OSError, http.client.HTTPException):
                return TransportOutcome(
                    DeliveryStatus.AMBIGUOUS,
                    None,
                    None,
                    DeliveryFailureCode.CONNECTION_LOST_AFTER_DISPATCH,
                )
            status = response.status
            body_digest, bytes_exceeded = self._read_bounded(response, request)
            outcome = _classify_status(status)
            if bytes_exceeded:
                return TransportOutcome(
                    outcome.classification,
                    status,
                    None,
                    DeliveryFailureCode.RESPONSE_BYTES_EXCEEDED,
                )
            return TransportOutcome(
                outcome.classification, status, body_digest, outcome.error_code
            )
        finally:
            try:
                connection.close()
            except OSError:
                pass

    @staticmethod
    def _read_bounded(
        response: http.client.HTTPResponse, request: WebhookRequest
    ) -> tuple[str | None, bool]:
        cap = request.max_response_bytes
        try:
            declared = response.getheader("Content-Length")
        except OSError as exc:
            raise WebhookTransportError("cannot read webhook response headers") from exc
        if declared is not None:
            try:
                if int(declared) > cap:
                    response.close()
                    return None, True
            except ValueError as exc:
                raise WebhookTransportError("invalid webhook Content-Length") from exc
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(min(8192, max(1, cap - total)))
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                response.close()
                return None, True
            chunks.append(chunk)
        return hashlib.sha256(b"".join(chunks)).hexdigest(), False


__all__ = [
    "TransportOutcome",
    "WebhookEndpointError",
    "WebhookHttpTransport",
    "WebhookRequest",
    "WebhookTransport",
    "WebhookTransportError",
]
