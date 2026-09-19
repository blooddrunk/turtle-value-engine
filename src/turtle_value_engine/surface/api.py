"""Optional, thin ASGI adapter for the read-only surface service.

Importing this module does not import FastAPI, Starlette, httpx or uvicorn.
Those dependencies are loaded only when an application is created or a server
is started, so the deterministic engine remains usable without the ``api``
extra.
"""

import ipaddress
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from .contracts import ResearchSurfaceSnapshotV1
from .registry import (
    InvalidSurfaceQueryError,
    SurfaceBindError,
    SurfaceMetadata,
    SurfaceNotFoundError,
    SurfaceReadService,
    SurfaceRegistry,
    SurfaceRegistryError,
)


class SurfaceAPIUnavailableError(ValueError):
    """Raised when the optional HTTP stack is not installed."""


class SurfaceHealthResponse(BaseModel):
    """Local service health; it deliberately says nothing about upstreams."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    contract: StrictStr
    version: StrictStr
    loaded_snapshot_count: StrictInt = Field(ge=1)


class SurfaceListResponse(BaseModel):
    """Deterministically ordered surface metadata response."""

    model_config = ConfigDict(extra="forbid")

    surfaces: list[SurfaceMetadata]


class SurfaceErrorDetail(BaseModel):
    """Stable machine-readable error detail."""

    model_config = ConfigDict(extra="forbid")

    code: StrictStr = Field(min_length=1)
    message: StrictStr = Field(min_length=1)


class SurfaceErrorResponse(BaseModel):
    """Stable error envelope used by the API adapter."""

    model_config = ConfigDict(extra="forbid")

    error: SurfaceErrorDetail


def _error_payload(code: str, message: str) -> dict[str, object]:
    return SurfaceErrorResponse(
        error=SurfaceErrorDetail(code=code, message=message)
    ).model_dump(mode="json", warnings=False)


def _etag(content_sha256: str) -> str:
    return f'"{content_sha256}"'


def _etag_matches(header: str | None, content_sha256: str) -> bool:
    if header is None:
        return False
    for candidate in header.split(","):
        normalized = candidate.strip()
        if normalized == "*":
            return True
        if normalized.startswith("W/"):
            normalized = normalized[2:].strip()
        if normalized.strip('"') == content_sha256:
            return True
    return False


def _validate_bind_host(host: str, *, allow_non_loopback: bool) -> None:
    if not isinstance(host, str) or not host.strip():
        raise SurfaceBindError("host must be a non-empty hostname or IP address")
    normalized = host.strip().lower()
    loopback = normalized in {"localhost", "ip6-localhost"}
    if not loopback:
        try:
            loopback = ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            # Hostnames cannot be safely assumed to resolve to loopback without
            # doing network/environment-dependent resolution.  They therefore
            # require the same explicit opt-in as a non-loopback address.
            loopback = False
    if not loopback and not allow_non_loopback:
        raise SurfaceBindError(
            "non-loopback bind requires explicit allow_non_loopback opt-in"
        )


def create_surface_app(
    registry_or_service: SurfaceRegistry | SurfaceReadService,
) -> Any:
    """Create the optional FastAPI app over an already-built read service."""

    try:
        from fastapi import FastAPI, Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse, Response
        from starlette.exceptions import HTTPException as StarletteHTTPException
    except ImportError as exc:  # pragma: no cover - exercised in minimal installs
        raise SurfaceAPIUnavailableError(
            "the optional API stack is unavailable; install the 'api' extra"
        ) from exc

    if isinstance(registry_or_service, SurfaceRegistry):
        service = SurfaceReadService(registry_or_service)
    elif isinstance(registry_or_service, SurfaceReadService):
        service = registry_or_service
    else:
        raise TypeError("create_surface_app requires a SurfaceRegistry or SurfaceReadService")

    app = FastAPI(
        title="Turtle Value Engine Research Surface API",
        version="1.0.0",
        description="Read-only access to explicitly supplied ResearchSurfaceSnapshotV1 artifacts.",
    )
    app.state.surface_service = service

    @app.exception_handler(SurfaceRegistryError)
    def handle_surface_error(_request: Request, exc: SurfaceRegistryError) -> JSONResponse:
        status_code = 404 if isinstance(exc, SurfaceNotFoundError) else 400
        message = "surface not found" if exc.code == "SURFACE_NOT_FOUND" else str(exc)
        return JSONResponse(
            status_code=status_code,
            content=_error_payload(exc.code, message),
        )

    @app.exception_handler(RequestValidationError)
    def handle_request_validation_error(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=_error_payload(
                InvalidSurfaceQueryError.code,
                "invalid query parameter",
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    def handle_http_error(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse | Response:
        if request.url.path.startswith("/v1/surfaces") and exc.status_code in {404, 405}:
            code = (
                "SURFACE_NOT_FOUND"
                if exc.status_code == 404
                else "READ_ONLY_METHOD_NOT_ALLOWED"
            )
            message = (
                "surface not found"
                if exc.status_code == 404
                else "read-only method not allowed"
            )
            return JSONResponse(
                status_code=exc.status_code,
                content=_error_payload(code, message),
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    def _validate_query_parameters(request: Request) -> None:
        allowed = {"primary_listing", "profile_id", "as_of"}
        for key in request.query_params.keys():
            if key not in allowed:
                raise InvalidSurfaceQueryError(f"unsupported query parameter: {key}")
            if len(request.query_params.getlist(key)) != 1:
                raise InvalidSurfaceQueryError(f"query parameter {key} must occur once")

    @app.get(
        "/healthz",
        response_model=SurfaceHealthResponse,
        operation_id="getHealth",
        tags=["system"],
    )
    def healthz() -> dict[str, object]:
        return service.health()

    @app.get(
        "/v1/surfaces",
        response_model=SurfaceListResponse,
        operation_id="listSurfaces",
        tags=["surfaces"],
    )
    def list_surfaces(
        request: Request,
        primary_listing: str | None = None,
        profile_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, object]:
        _validate_query_parameters(request)
        return {
            "surfaces": service.list_surfaces(
                primary_listing=primary_listing,
                profile_id=profile_id,
                as_of=as_of,
            )
        }

    @app.get(
        "/v1/surfaces/{surface_id}",
        response_model=ResearchSurfaceSnapshotV1,
        operation_id="getSurface",
        tags=["surfaces"],
    )
    def get_surface(request: Request, surface_id: str) -> Response:
        snapshot = service.get_surface(surface_id)
        headers = {"ETag": _etag(snapshot.content_sha256)}
        if _etag_matches(request.headers.get("if-none-match"), snapshot.content_sha256):
            return Response(status_code=304, headers=headers)
        return JSONResponse(
            content=snapshot.model_dump(mode="json", warnings=False),
            headers=headers,
        )

    return app


# Common names for callers that use ``build`` or ``app`` terminology.
build_surface_app = create_surface_app
create_app = create_surface_app


def serve_surface_snapshots(
    snapshot_paths: Iterable[str | Path],
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    allow_non_loopback: bool = False,
) -> None:
    """Load explicit snapshots and run the optional uvicorn server."""

    _validate_bind_host(host, allow_non_loopback=allow_non_loopback)
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    registry = SurfaceRegistry.from_paths(snapshot_paths)
    app = create_surface_app(registry)
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised in minimal installs
        raise SurfaceAPIUnavailableError(
            "uvicorn is unavailable; install the 'api' extra"
        ) from exc
    uvicorn.run(app, host=host, port=port)


run_surface_server = serve_surface_snapshots
validate_bind_host = _validate_bind_host


__all__ = [
    "SurfaceAPIUnavailableError",
    "SurfaceErrorDetail",
    "SurfaceErrorResponse",
    "SurfaceHealthResponse",
    "SurfaceListResponse",
    "build_surface_app",
    "create_app",
    "create_surface_app",
    "run_surface_server",
    "serve_surface_snapshots",
    "validate_bind_host",
]
