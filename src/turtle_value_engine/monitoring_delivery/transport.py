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

Phase 6-D2B-R1: the configured ``timeout_seconds`` is one injectable
monotonic **overall deadline** for the entire exchange.  Connect/TLS
establishment, request write / response-header wait and every bounded
response-body read consume the same remaining budget; expiry after dispatch
may have started is ``AMBIGUOUS`` and expiry proven before any request byte
is honestly retryable.
"""

from __future__ import annotations

import hashlib
import http.client
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from .contracts import DeliveryFailureCode, DeliveryStatus

_USER_AGENT = "turtle-value-engine monitoring-delivery webhook-v1"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

MonotonicClock = Callable[[], float]
ConnectionFactory = Callable[..., object]


class _DeadlineExpired(Exception):
    """The overall monotonic deadline is exhausted (never surfaces raw)."""

    def __init__(self, *, dispatch_started: bool) -> None:
        super().__init__("overall webhook deadline exhausted")
        self.dispatch_started = dispatch_started


class _BodyReadOutcome(Exception):
    """A terminal transport outcome raised from the bounded body-read loop."""

    def __init__(self, outcome: TransportOutcome) -> None:
        super().__init__("webhook response body read produced a terminal outcome")
        self.outcome = outcome


class WebhookEndpointError(ValueError):
    """Raised when the configured endpoint is missing or invalid.

    The message deliberately never contains the endpoint itself: a webhook
    URL can embed credential material in its path or query string.
    """


class WebhookTransportError(ValueError):
    """Raised when the transport cannot produce a classified outcome."""


@dataclass(frozen=True, slots=True)
class WebhookRequest:
    """In-memory request material; never persisted or logged.

    ``timeout_seconds`` is the **overall** monotonic budget for the whole
    HTTP exchange (connect/TLS, request write, response-header wait and every
    bounded response-body read), not a per-socket-operation timeout.
    """

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


def _default_connection_factory(*, scheme: str, host: str, port: int, timeout: float):
    if scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=timeout)
    return http.client.HTTPConnection(host, port, timeout=timeout)


class WebhookHttpTransport:
    """Real generic HTTP webhook transport over ``http.client``.

    ``allow_loopback_http`` is the explicit test-only injection path for
    plain-http loopback receivers; the live CLI path always constructs this
    transport without it, so a live endpoint must be HTTPS.

    ``timeout_seconds`` is enforced as one monotonic **overall deadline**.
    Every potentially blocking phase — connect/TLS establishment, request
    write / response-header wait and each bounded response-body read — is
    bounded by the *remaining* budget from an injectable monotonic clock, so
    a peer that keeps making progress inside individual socket timeouts can
    no longer stretch the exchange past the configured budget.  Deadline
    expiry after dispatch may have started is ``AMBIGUOUS``; expiry proven to
    precede any request byte is honestly retryable.
    """

    def __init__(
        self,
        *,
        allow_loopback_http: bool = False,
        monotonic_clock: MonotonicClock | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.allow_loopback_http = allow_loopback_http
        self._monotonic_clock: MonotonicClock = monotonic_clock or time.monotonic
        self._connection_factory: ConnectionFactory = (
            connection_factory or _default_connection_factory
        )

    def _remaining(self, deadline: float, *, dispatch_started: bool) -> float:
        remaining = deadline - self._monotonic_clock()
        if remaining <= 0:
            raise _DeadlineExpired(dispatch_started=dispatch_started)
        return remaining

    def _apply_socket_deadline(
        self, connection, deadline: float, *, dispatch_started: bool
    ) -> float:
        """Bind the next blocking socket phase to the remaining budget."""

        remaining = self._remaining(deadline, dispatch_started=dispatch_started)
        sock = getattr(connection, "sock", None)
        if sock is not None:
            sock.settimeout(remaining)
        return remaining

    @staticmethod
    def _deadline_outcome(exc: _DeadlineExpired) -> TransportOutcome:
        if exc.dispatch_started:
            return TransportOutcome(
                DeliveryStatus.AMBIGUOUS,
                None,
                None,
                DeliveryFailureCode.TIMEOUT_AFTER_DISPATCH,
            )
        return TransportOutcome(
            DeliveryStatus.RETRYABLE_FAILURE,
            None,
            None,
            DeliveryFailureCode.DEADLINE_EXHAUSTED_PRE_DISPATCH,
        )

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
        deadline = self._monotonic_clock() + request.timeout_seconds
        connection = None
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
                connect_budget = self._remaining(deadline, dispatch_started=False)
                connection = self._connection_factory(
                    scheme=scheme,
                    host=host,
                    port=port if port is not None else default_port,
                    timeout=connect_budget,
                )
                connection.connect()
            except _DeadlineExpired as exc:
                return self._deadline_outcome(exc)
            except (OSError, socket.gaierror):
                # Proven to precede any request dispatch: honestly retryable.
                return TransportOutcome(
                    DeliveryStatus.RETRYABLE_FAILURE,
                    None,
                    None,
                    DeliveryFailureCode.CONNECT_FAILED_PRE_DISPATCH,
                )
            try:
                self._apply_socket_deadline(connection, deadline, dispatch_started=False)
                connection.request("POST", path, body=request.body, headers=headers)
                response = connection.getresponse()
            except _DeadlineExpired as exc:
                return self._deadline_outcome(exc)
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
            try:
                body_digest, bytes_exceeded = self._read_bounded(
                    response, request, connection, deadline
                )
            except _BodyReadOutcome as exc:
                return exc.outcome
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
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass

    def _read_bounded(
        self,
        response,
        request: WebhookRequest,
        connection,
        deadline: float,
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
            try:
                # Every bounded body read shares the same remaining budget;
                # the request has already been dispatched by construction.
                self._apply_socket_deadline(connection, deadline, dispatch_started=True)
                chunk = response.read(min(8192, max(1, cap - total)))
            except _DeadlineExpired as exc:
                raise _BodyReadOutcome(self._deadline_outcome(exc)) from exc
            except TimeoutError as exc:
                raise _BodyReadOutcome(
                    TransportOutcome(
                        DeliveryStatus.AMBIGUOUS,
                        None,
                        None,
                        DeliveryFailureCode.TIMEOUT_AFTER_DISPATCH,
                    )
                ) from exc
            except OSError as exc:
                raise _BodyReadOutcome(
                    TransportOutcome(
                        DeliveryStatus.AMBIGUOUS,
                        None,
                        None,
                        DeliveryFailureCode.CONNECTION_LOST_AFTER_DISPATCH,
                    )
                ) from exc
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                response.close()
                return None, True
            chunks.append(chunk)
        return hashlib.sha256(b"".join(chunks)).hexdigest(), False


__all__ = [
    "ConnectionFactory",
    "MonotonicClock",
    "TransportOutcome",
    "WebhookEndpointError",
    "WebhookHttpTransport",
    "WebhookRequest",
    "WebhookTransport",
    "WebhookTransportError",
]
