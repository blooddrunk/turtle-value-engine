"""Phase 6-F persistent owner production-operations harness.

Turns the already-proven Phase 6-E single-host acceptance chain into an
explicitly owner-authorized, restart-resilient long-lived monitoring
deployment.  This is operational hardening of the closed chain

```text
Phase 6-B bounded acquisition
  -> Phase 6-A planning/cursor commit
  -> Phase 6-C re-analysis boundary
  -> D1 cycle/outbox
  -> D2A/R1 unattended runner + authoritative lease
  -> optional D2B/R1/R2 delivery
  -> D3/R1 read-only operations projection
```

with no change to any of its semantics.  The Phase 6-E acceptance workspace
and this production lifecycle stay strictly separate: the harness refuses to
reuse or promote acceptance roots, runner ids or unit names.

Every mode is explicit and fail-closed:

- ``gate``          run the mandatory deterministic repository gate and bind
                    a green artifact to the current HEAD SHA;
- ``preflight``     non-mutating host/topology/config/secret/linger/lock
                    classification, including native-Linux vs WSL2 detection
                    and the honest Windows-bootstrap capability boundary;
- ``plan``          deterministic, redacted, mutation-free convergence plan
                    stating per resource create/modify/unchanged/enable/
                    linger-enable plus desired hashes and identities;
- ``render``        deterministic owner-specific unit material, production
                    runner/project configuration and ``systemd-analyze
                    verify`` under the private production root only;
- ``apply``/``converge`` install, daemon-reload, enable (never start) the
                    timer, converge linger for user scope and verify the
                    effective state; idempotent;
- ``activate``      the explicit production activation (start the timer);
- ``verify``        inspect the *effective* deployment through ``systemctl
                    show`` / bounded redacted journal slices, never the
                    templates;
- ``live-proof``    one bounded immediate production firing, replay/no-
                    duplicate proof, D3 read-only/non-interference proof,
                    acceptance-root immutability and a secret scan;
- ``recover-proof`` the strongest safe manager refresh (daemon-reload +
                    daemon-reexec), timer stop/start, durable resume with no
                    duplicate activation/cycle/delivery and unchanged
                    configuration identity;
- ``deactivate``    safe, idempotent stop+disable of the production timer;
- ``report``        assemble/validate the secret-free machine-readable
                    production operations report.

Secret discipline: no credential value is ever accepted, printed or
persisted by this script.  Notification is optional; when enabled, the only
typed local credential source is a systemd ``EnvironmentFile`` under the
ignored private root whose *path* (never its content) appears in the unit.
The file must satisfy the canonical subset (one physical ``NAME=VALUE``
line per referenced secret, no quoting/escaping/continuation/whitespace,
no unrelated keys, no systemd-invalid Unicode anywhere in the file) so every
accepted value is byte-identical under this harness and systemd, and the
render step refuses to continue before any artifact is written unless the
file is readable, complete and canonical.

Phase 6-F-R3 keeps that contract continuously true instead of only at
render time: apply/converge and activate revalidate the *current* private
credential file before any system mutation, verify and report fail closed
on current credential drift (safe deactivation never depends on it), and
every delivery-enabled service unit renders an ``ExecStartPre=`` credential
gate (``scripts/monitoring_credential_gate.py``) that re-reads the file,
reuses the one current-credential validation primitive and compares the
referenced values with the environment systemd actually injected
byte-for-byte — value-free — before the unchanged ``unattended-notify``
``ExecStart=`` may run.  No secret value or secret-derived digest or
fingerprint is ever persisted for drift detection; the private file is
re-read and compared in memory.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import stat as stat_module
import subprocess
import sys
import time
import tomllib
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote as _url_quote

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(ROOT), str(ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import scripts.monitoring_live_acceptance as acceptance  # noqa: E402
from scripts.monitoring_live_acceptance import (  # noqa: E402
    DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN,
    EXIT_FAIL_CLOSED,
    EXIT_MARKER,
    EXIT_OK,
    MANUAL_SECRET_REFERENCE_REQUIRED,
    MANUAL_SUDO_INSTALL_REQUIRED,
    AcceptanceError,
    CheckLog,
    CommandOutcome,
    CommandRunner,
    ManualBoundary,
    _atomic_write,
    _bounded,
    _default_runner,
    _outcome_public,
    _sha256_bytes,
    _systemctl_show,
    _systemd_analyze_verify,
    _systemd_privilege_available,
    _tracked_files_without_secrets,
    content_tree_hash,
    gate_commands,
    load_gate_artifact,
    probe_lock_visibility,
    redact_text,
    run_command,
    scan_bytes_for_secrets,
    systemctl_prefix,
    systemd_unit_destination_dir,
)
from turtle_value_engine.config import load_project_config  # noqa: E402
from turtle_value_engine.monitoring.canonical import canonical_json_bytes  # noqa: E402
from turtle_value_engine.monitoring.models import WatchlistSpecV1  # noqa: E402
from turtle_value_engine.monitoring_runner.contracts import RunnerConfigV1  # noqa: E402

# ---------------------------------------------------------------------------
# Markers and contracts
# ---------------------------------------------------------------------------

MANUAL_ENABLE_LINGER_REQUIRED = "MANUAL_ENABLE_LINGER_REQUIRED"
WINDOWS_HOST_BOOTSTRAP_UNPROVEN = "WINDOWS_HOST_BOOTSTRAP_UNPROVEN"

CONFIG_CONTRACT = "monitoring_production_config_v1"
REPORT_CONTRACT = "monitoring_production_report_v1"

PROBE_RUNNER_ID = "phase6f-lock-visibility"

# The Phase 6-E acceptance assets this production lifecycle must never
# silently reuse or promote (goal section 4: acceptance != production).
PHASE6E_UNIT_BASENAMES: frozenset[str] = frozenset(
    {"tve-phase6e-acceptance", "turtle-value-monitor"}
)
PHASE6E_ROOT_MARKER = "phase6e"
PHASE6E_ROOT_HINT = str(ROOT / ".tve-private" / "monitoring" / "phase6e")

_LISTING_PATTERN = re.compile(r"^(SH|SZ|BJ)\d{6}$|^(HK)\d{5}$")
_UNIT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SECRET_ENV_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Phase 6-F-R2 canonical private EnvironmentFile contract.  The accepted
# grammar is a deliberately unambiguous subset of systemd ``EnvironmentFile=``
# semantics (one physical ``NAME=VALUE`` line per referenced secret name, no
# quoting/escaping/continuations/whitespace) so every accepted value is
# byte-identical under the harness reader and the service manager.  Values
# may legitimately contain ``=``, ``#``, ``;``, ``?``, ``&`` and ``%``: they
# are data, never inline comments.
_ENV_FILE_MAX_BYTES = 65536
_ENV_FILE_VALUE_FORBIDDEN_CHARS = ('"', "'", "\\")

# Phase 6-F-R3 service-execution credential gate.  The dedicated gate CLI is
# rendered into delivery-enabled units ahead of ``unattended-notify``; it
# reuses this module's validation primitive and prints status/category/
# reference names only — never a value.
CREDENTIAL_GATE_SCRIPT = Path(__file__).resolve().parent / "monitoring_credential_gate.py"
CREDENTIAL_GATE_OK = "CREDENTIAL_GATE_OK"
CREDENTIAL_GATE_REJECTED = "CREDENTIAL_GATE_REJECTED"


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(ch) == "Cc" for ch in value)


def _systemd_invalid_unicode(text: str) -> tuple[int, str] | None:
    """The first systemd-invalid Unicode scalar in a decoded EnvironmentFile.

    systemd's ``EnvironmentFile=`` contract excludes ``U+0000``, ``U+FEFF``,
    the Unicode noncharacters ``U+FDD0..U+FDEF`` and every code point whose
    low 16 bits are ``FFFE``/``FFFF`` from the *whole* file, comments
    included.  Strict UTF-8 decoding (which already rejects non-scalar
    surrogate encodings) stays in front of this check.  The returned
    category is deliberately content-free.
    """

    for index, ch in enumerate(text):
        code = ord(ch)
        if code == 0x0000:
            return index, "U+0000 (NUL)"
        if code == 0xFEFF:
            return index, "U+FEFF (byte order mark)"
        if 0xFDD0 <= code <= 0xFDEF:
            return index, "Unicode noncharacter U+FDD0..U+FDEF"
        if (code & 0xFFFF) in (0xFFFE, 0xFFFF):
            return index, "plane-ending Unicode noncharacter"
    return None


# ---------------------------------------------------------------------------
# Phase 6-F-R4 systemd-native / TOML-safe serialization boundary
#
# The invariant every helper here serves is exact semantic parity:
#
#     typed owner input -> rendered unit/TOML bytes -> systemd manager or
#     tomllib -> effective value == typed value
#
# The grammar facts below were verified against a real systemd 259 user
# manager during R4 development (load-time busctl argv, runtime argv dumps
# and EnvironmentFile/WorkingDirectory effective properties):
#
# * Exec command lines are tokenized by the systemd.syntax(7) quoting rules:
#   double or single quotes may wrap a whole item, C-style escapes apply
#   (``\\``, ``\"``, ``\'``, ``\s``, ...), and an argument solely consisting
#   of ``;`` is special.  Quoting protects token boundaries only — it does
#   NOT disable expansion.
# * ``$`` sequences in Exec lines expand (at execution time) against the
#   service environment; a literal dollar sign must be written ``$$``.
# * ``%`` specifiers expand (at load time) in Exec lines and in path/text
#   directives such as ``EnvironmentFile=``, ``WorkingDirectory=``,
#   ``Description=`` and ``Documentation=``; a literal percent must be
#   written ``%%``.
# * ``EnvironmentFile=`` / ``WorkingDirectory=`` values do NOT support
#   quoting (quotes become literal path bytes); raw spaces are preserved
#   and ``$``, ``;``, ``#`` are ordinary data in them.  A backslash is
#   ordinary data in ``WorkingDirectory=`` but the ``EnvironmentFile=``
#   exec-time loader treats it as an escape, so it is rejected at parse
#   time for the credential path (unrepresentable either way).
# * Control characters cannot appear in Exec command lines or unit
# *assignment* values at all; they are rejected fail-closed at parse time.
#
# shlex.join() is a POSIX-shell serializer and stays reserved for the
# human-facing resume commands (a separate, explicit boundary).
# ---------------------------------------------------------------------------

# Characters that force whole-item double quoting in an Exec line (whitespace
# splits tokens; quotes open quoting modes; ; and # are kept wrapped because
# a standalone form is parser-special).
_SYSTEMD_EXEC_WRAP_PATTERN = re.compile(r"""[\s'`;#]""")

# The escape table subset this serializer emits and its mirror parser
# accepts (systemd.syntax(7) "Supported escapes").
_SYSTEMD_ESCAPE_TABLE: dict[str, str] = {
    "\\": "\\",
    '"': '"',
    "'": "'",
    "s": " ",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}


class SerializationError(AcceptanceError):
    """A typed owner input cannot be represented in the target grammar."""


def _require_unit_line_serializable(field_name: str, value: str) -> None:
    if _contains_control_character(value):
        raise SerializationError(
            f"{field_name} must not contain control characters or newlines: "
            "systemd unit syntax cannot represent them in assignment values "
            "or Exec command lines, so the value would be corrupted"
        )


def systemd_exec_argument(value: str) -> str:
    """One argv element as literal systemd Exec-line data.

    Backslashes are doubled, a double quote is escaped, and every literal
    ``$``/``%`` is doubled because both expansions stay active inside
    quotes.  Items containing tokenizer-active characters are wrapped in
    whole-item double quotes (single-quote data stays literal inside them).
    Values without any of these characters serialize to themselves, keeping
    ordinary rendering byte-compatible.
    """

    _require_unit_line_serializable("exec argument", value)
    serialized = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "$$")
        .replace("%", "%%")
    )
    if _SYSTEMD_EXEC_WRAP_PATTERN.search(serialized):
        serialized = f'"{serialized}"'
    return serialized


def systemd_exec_command(argv: Sequence[str]) -> str:
    """A full ``ExecStartPre=``/``ExecStart=`` command line from argv."""

    return " ".join(systemd_exec_argument(element) for element in argv)


def parse_systemd_exec_command(
    line: str, environ: Mapping[str, str] | None = None
) -> list[str]:
    """The bounded inverse of :func:`systemd_exec_command`.

    Restores the manager-effective argv for any command line produced by
    the serializer above: systemd.syntax(7) tokenization with whole-item
    quoting and C-style escapes, load-time ``%%`` collapse, then the
    execution-time ``$$`` collapse and ``$NAME``/``${NAME}`` expansion
    against ``environ`` (empty for unset names, matching systemd).  The
    render boundary uses this mirror to prove parity before writing any
    unit bytes; the deterministic tests additionally prove it against the
    real manager.
    """

    environment = os.environ if environ is None else environ
    tokens: list[str] = []
    index, length = 0, len(line)
    while index < length:
        while index < length and line[index].isspace():
            index += 1
        if index >= length:
            break
        parts: list[str] = []
        while index < length and not line[index].isspace():
            ch = line[index]
            if ch == "'":
                index += 1
                while index < length and line[index] != "'":
                    parts.append(line[index])
                    index += 1
                index += 1
            elif ch == '"':
                index += 1
                while index < length and line[index] != '"':
                    if line[index] == "\\" and index + 1 < length:
                        index += 1
                        parts.append(_SYSTEMD_ESCAPE_TABLE.get(line[index], "\\" + line[index]))
                        index += 1
                    else:
                        parts.append(line[index])
                        index += 1
                index += 1
            elif ch == "\\" and index + 1 < length:
                index += 1
                parts.append(_SYSTEMD_ESCAPE_TABLE.get(line[index], "\\" + line[index]))
                index += 1
            else:
                parts.append(ch)
                index += 1
        tokens.append("".join(parts))

    def _expand_percent(token: str) -> str:
        out: list[str] = []
        i = 0
        while i < len(token):
            ch = token[i]
            if ch == "%" and i + 1 < len(token) and token[i + 1] == "%":
                out.append("%")
                i += 2
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    def _expand_dollar(token: str) -> str:
        out: list[str] = []
        i = 0
        while i < len(token):
            ch = token[i]
            if ch != "$":
                out.append(ch)
                i += 1
                continue
            if i + 1 < len(token) and token[i + 1] == "$":
                out.append("$")
                i += 2
                continue
            if i + 1 < len(token) and token[i + 1] == "{":
                end = token.find("}", i + 2)
                if end != -1:
                    out.append(environment.get(token[i + 2 : end], ""))
                    i = end + 1
                    continue
            j = i + 1
            while j < len(token) and (token[j].isalnum() or token[j] == "_"):
                j += 1
            if j > i + 1:
                out.append(environment.get(token[i + 1 : j], ""))
                i = j
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    return [_expand_dollar(_expand_percent(token)) for token in tokens]


def systemd_unit_path_value(value: str) -> str:
    """An ``EnvironmentFile=``/``WorkingDirectory=`` path as literal data.

    These directives do not support quoting (quotes would become literal
    path bytes) and take the whole rest of the line, so spaces, backslashes,
    dollars, semicolons and hashes stay raw; only the percent specifier
    expansion is active and is neutralized by doubling.
    """

    _require_unit_line_serializable("unit path value", value)
    return value.replace("%", "%%")


def effective_unit_path_value(value: str) -> str:
    """The manager-effective value of a rendered path directive (``%%`` collapse)."""

    out: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "%" and i + 1 < len(value) and value[i + 1] == "%":
            out.append("%")
            i += 2
            continue
        out.append(value[i])
        i += 1
    return "".join(out)


def systemd_unit_text_value(value: str) -> str:
    """Owner-derived free text (``Description=``) with percent doubling only."""

    _require_unit_line_serializable("unit text value", value)
    return value.replace("%", "%%")


def toml_basic_string(value: str) -> str:
    """A TOML basic string that parses back to the exact typed value.

    TOML basic strings escape ``\\"`` and ``\\\\``, the five short control
    escapes and any other control character as ``\\uXXXX``; everything else
    (including ordinary and non-BMP Unicode) stays raw UTF-8, which tomllib
    decodes back byte-exactly.
    """

    short_escapes = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}
    parts: list[str] = ['"']
    for ch in value:
        if ch == '"':
            parts.append('\\"')
        elif ch == "\\":
            parts.append("\\\\")
        elif ch in short_escapes:
            parts.append(short_escapes[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            parts.append(f"\\u{ord(ch):04x}")
        else:
            parts.append(ch)
    parts.append('"')
    return "".join(parts)


# ---------------------------------------------------------------------------
# Typed production configuration (owner inputs; non-secret by construction)
# ---------------------------------------------------------------------------


class ProductionConfigV1(BaseModel):
    """Explicit, non-secret owner inputs for one long-lived production run.

    Every path, identity and policy here is a production fact.  The Phase 6-E
    acceptance workspace is never a valid value: roots, runner ids and unit
    names that would collide with acceptance assets are rejected at parse
    time.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: StrictStr = CONFIG_CONTRACT
    schema_version: StrictStr = "1.0.0"

    # Deployment shape.
    scope: StrictStr = Field(pattern=r"^(user|system)$")
    service_user: StrictStr | None = None
    python_executable: StrictStr = Field(min_length=1, max_length=4096)
    working_directory: StrictStr = Field(min_length=1, max_length=4096)
    unit_base_name: StrictStr = Field(min_length=1, max_length=120)
    on_calendar: StrictStr = Field(min_length=1, max_length=200)
    randomized_delay_sec: StrictInt = Field(ge=0, le=3600)
    timer_accuracy_sec: StrictInt = Field(default=1, ge=1, le=60)

    # Private operations root (reports, rendered material, gate artifacts).
    production_root: StrictStr = Field(min_length=1, max_length=4096)

    # Production identities and typed roots (explicit; no silent defaults).
    runner_id: StrictStr = Field(min_length=1, max_length=128)
    watchlist_path: StrictStr = Field(min_length=1, max_length=4096)
    monitoring_workspace_root: StrictStr = Field(min_length=1, max_length=512)
    reanalysis_job_root: StrictStr = Field(min_length=1, max_length=512)
    cycle_store_root: StrictStr = Field(min_length=1, max_length=512)
    runner_root: StrictStr = Field(min_length=1, max_length=512)
    cache_dir: StrictStr = Field(min_length=1, max_length=512)
    delivery_root: StrictStr = Field(min_length=1, max_length=512)

    # Network/acquisition policy (Phase 6-B stays opt-in and bounded).
    network_allowed: StrictBool = False
    window_days: StrictInt = Field(ge=1, le=366)
    as_of: datetime | None = None
    acquisition_limit: StrictInt = Field(default=30, ge=1, le=30)
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    max_response_bytes: StrictInt = Field(default=524288, ge=1024, le=8388608)
    lease_ttl_seconds: StrictInt = Field(default=900, ge=1, le=604800)

    # Optional notification (disabled by default; references only).
    delivery_enabled: StrictBool = False
    delivery_transport: StrictStr = Field(
        default="webhook-v1", pattern=r"^(webhook-v1|telegram-v1)$"
    )
    delivery_destination_id: StrictStr = Field(
        default="production-primary", min_length=1, max_length=128
    )
    delivery_endpoint_env: StrictStr = Field(
        default="TVE_MONITORING_WEBHOOK_URL", min_length=1, max_length=256
    )
    delivery_auth_env: StrictStr | None = Field(
        default="TVE_MONITORING_WEBHOOK_TOKEN", min_length=1, max_length=256
    )
    delivery_telegram_bot_token_env: StrictStr = Field(
        default="TVE_MONITORING_TELEGRAM_BOT_TOKEN", min_length=1, max_length=256
    )
    delivery_telegram_chat_id: StrictStr | None = None
    # The one typed local credential source: a private systemd
    # ``EnvironmentFile`` holding the referenced secret values.  Only its
    # path is ever rendered; its content never enters Git, units, argv,
    # configs, ledgers, reports or API payloads.
    delivery_environment_file: StrictStr | None = Field(
        default=None, min_length=1, max_length=4096
    )

    # Read-only D3 projection check inputs.
    snapshot_path: StrictStr | None = Field(default=None, min_length=1, max_length=4096)
    surface_port: StrictInt = Field(default=8899, ge=1024, le=65535)

    require_repo_gate: StrictBool = True

    @field_validator("as_of")
    @classmethod
    def _normalize_as_of(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("as_of must carry an explicit timezone")
        return value.astimezone(UTC)

    @field_validator(
        "delivery_endpoint_env",
        "delivery_auth_env",
        "delivery_telegram_bot_token_env",
    )
    @classmethod
    def _validate_secret_env_name(cls, value: str | None) -> str | None:
        if value is not None and not _SECRET_ENV_PATTERN.fullmatch(value):
            raise ValueError("delivery secret reference must be an environment variable name")
        return value

    def _refuse_phase6e(self, value: str, field_name: str) -> None:
        parts = Path(value).parts
        if PHASE6E_ROOT_MARKER in parts:
            raise ValueError(
                f"{field_name} must not touch the Phase 6-E acceptance tree "
                f"({PHASE6E_ROOT_MARKER} path segment); production and acceptance "
                "workspaces are strictly separate"
            )

    @model_validator(mode="after")
    def _validate_config(self) -> ProductionConfigV1:
        if not _UNIT_NAME_PATTERN.match(self.unit_base_name):
            raise ValueError("unit_base_name is not a valid systemd unit name fragment")
        if self.unit_base_name in PHASE6E_UNIT_BASENAMES or self.unit_base_name.startswith(
            "tve-phase6e"
        ):
            raise ValueError(
                "unit_base_name must not reuse the Phase 6-E acceptance unit namespace"
            )
        if self.runner_id.startswith("phase6e"):
            raise ValueError("runner_id must not reuse the Phase 6-E acceptance namespace")
        if self.scope == "system" and self.service_user is None:
            raise ValueError("scope=system requires an explicit service_user")
        if self.scope == "user" and self.service_user is not None:
            raise ValueError("scope=user must not pin a service_user (it runs as the owner)")
        # R4: these owner strings are serialized verbatim into systemd unit
        # Exec command lines and path directives, where control characters
        # cannot be represented; they are refused fail-closed instead of
        # being silently corrupted by the unit parser.  (Values that are not
        # encodable UTF-8 text, such as lone surrogates, are already refused
        # by the StrictStr field validation itself.)
        for name in (
            "python_executable",
            "working_directory",
            "production_root",
            "runner_id",
            "unit_base_name",
        ):
            if _contains_control_character(getattr(self, name)):
                raise ValueError(
                    f"{name} must not contain control characters or newlines; systemd "
                    "unit Exec lines and path directives cannot represent them, so "
                    "the value would be corrupted by the manager parser"
                )
        # R4: the first Exec token is the executable path, where systemd
        # refuses quote characters and backslashes outright ("Executable
        # path contains special characters" is a fatal load error, verified
        # against systemd 259) and a dollar sequence cannot be proven
        # literal under the real unit parser.  python_executable is the
        # only owner-controlled argv[0]; every other path is an argument or
        # path directive where the full serializer applies.
        forbidden_exe_chars = {"'", '"', "\\", "$"}
        found = sorted(set(self.python_executable) & forbidden_exe_chars)
        if found:
            raise ValueError(
                "python_executable is serialized as the systemd Exec executable "
                f"path, which cannot represent {found}; choose an interpreter "
                "path without quotes, backslashes or dollar characters"
            )
        for name in (
            "python_executable",
            "working_directory",
            "production_root",
            "watchlist_path",
            "monitoring_workspace_root",
            "reanalysis_job_root",
            "cycle_store_root",
            "runner_root",
            "cache_dir",
            "delivery_root",
        ):
            if not Path(getattr(self, name)).is_absolute():
                raise ValueError(f"{name} must be an absolute path")
        for name in (
            "production_root",
            "watchlist_path",
            "monitoring_workspace_root",
            "reanalysis_job_root",
            "cycle_store_root",
            "runner_root",
            "cache_dir",
            "delivery_root",
        ):
            self._refuse_phase6e(getattr(self, name), name)
        if self.delivery_enabled:
            if self.delivery_environment_file is None:
                raise ValueError(
                    "delivery_enabled=true requires delivery_environment_file (the typed "
                    "local credential source; its path is rendered, never its content)"
                )
            if not Path(self.delivery_environment_file).is_absolute():
                raise ValueError("delivery_environment_file must be an absolute path")
            if _contains_control_character(self.delivery_environment_file):
                raise ValueError(
                    "delivery_environment_file must not contain control characters "
                    "or newlines (the path is serialized verbatim into the unit's "
                    "EnvironmentFile= line)"
                )
            # R4: a backslash in the EnvironmentFile path cannot be
            # represented — the manager's exec-time environment-file loader
            # interprets backslash escapes in the path (verified against
            # systemd 259: the literal file is never found either raw or
            # doubled).  Every other supported character (spaces, quotes,
            # dollar, non-ASCII) round-trips through percent doubling.
            if "\\" in self.delivery_environment_file:
                raise ValueError(
                    "delivery_environment_file must not contain backslashes: the "
                    "systemd environment-file loader treats them as escapes at "
                    "execution time, so the typed path cannot be represented"
                )
            env_file = Path(os.path.normpath(self.delivery_environment_file))
            private_root = Path(os.path.normpath(self.production_root))
            if not env_file.is_relative_to(private_root):
                raise ValueError(
                    "delivery_environment_file must stay inside the production private "
                    f"root {self.production_root} (got {self.delivery_environment_file}); "
                    "the typed credential source cannot live outside the ignored "
                    "private operations tree"
                )
            if self.delivery_transport == "telegram-v1":
                if self.delivery_telegram_chat_id is None or not re.fullmatch(
                    r"-?[0-9]+", self.delivery_telegram_chat_id
                ):
                    raise ValueError(
                        "telegram-v1 delivery requires a numeric delivery_telegram_chat_id"
                    )
            elif self.delivery_endpoint_env is None:
                raise ValueError("webhook-v1 delivery requires delivery_endpoint_env")
        else:
            if self.delivery_environment_file is not None:
                raise ValueError(
                    "delivery_environment_file is only meaningful with delivery_enabled=true"
                )
        return self

    # -- derived paths ------------------------------------------------------

    @property
    def systemd_output_dir(self) -> Path:
        return Path(self.production_root) / "systemd"

    @property
    def runner_config_path(self) -> Path:
        return Path(self.production_root) / "runner.json"

    @property
    def project_config_path(self) -> Path:
        return Path(self.production_root) / "project.toml"

    @property
    def service_unit_name(self) -> str:
        return f"{self.unit_base_name}.service"

    @property
    def timer_unit_name(self) -> str:
        return f"{self.unit_base_name}.timer"

    @property
    def report_path(self) -> Path:
        return Path(self.production_root) / "production-report.json"

    @property
    def gate_artifact_path(self) -> Path:
        return Path(self.production_root) / "gate.json"

    @property
    def service_identity(self) -> str:
        return self.service_user if self.scope == "system" else "owner-user-manager"


def load_production_config(path: str | Path) -> ProductionConfigV1:
    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"cannot read production config {config_path}: {exc}") from exc
    try:
        config = ProductionConfigV1.model_validate(payload)
    except Exception as exc:
        raise AcceptanceError(f"invalid production config {config_path}: {exc}") from exc
    if config.contract != CONFIG_CONTRACT:
        raise AcceptanceError(f"production config {config_path} has the wrong contract")
    return config


def build_runner_config(config: ProductionConfigV1) -> RunnerConfigV1:
    """The production runner configuration from the typed owner inputs."""

    return RunnerConfigV1(
        runner_id=config.runner_id,
        watchlist_path=config.watchlist_path,
        monitoring_workspace_root=config.monitoring_workspace_root,
        reanalysis_job_root=config.reanalysis_job_root,
        cycle_store_root=config.cycle_store_root,
        runner_root=config.runner_root,
        cache_dir=config.cache_dir,
        network_allowed=config.network_allowed,
        offline_replay=not config.network_allowed,
        window_days=config.window_days,
        as_of=config.as_of,
        acquisition_limit=config.acquisition_limit,
        timeout_seconds=config.timeout_seconds,
        max_response_bytes=config.max_response_bytes,
        lease_ttl_seconds=config.lease_ttl_seconds,
    )


def render_project_config(config: ProductionConfigV1) -> str:
    """The production project TOML (non-secret; secret references only).

    Every owner-provided string is emitted through :func:`toml_basic_string`
    so the generated document parses back into the exact typed values; the
    round-trip is proven with ``tomllib`` before the text leaves this
    function (R4 goal section 5).
    """

    text = f"""# Phase 6-F production project configuration (non-secret).
# Generated by scripts/monitoring_production_ops.py; isolated production ledger.
schema_version = 1

[project]
id = "turtle-value-engine"
environment = "private"
timezone = "Asia/Taipei"

[monitoring]
watchlist_path = {toml_basic_string(config.watchlist_path)}
workspace_root = {toml_basic_string(config.monitoring_workspace_root)}

[monitoring.delivery]
enabled = {"true" if config.delivery_enabled else "false"}
transport = {toml_basic_string(config.delivery_transport)}
destination_id = {toml_basic_string(config.delivery_destination_id)}
delivery_root = {toml_basic_string(config.delivery_root)}
receiver_idempotency_declared = false
max_attempts = 5
timeout_seconds = 10.0
backoff_base_seconds = 60
backoff_cap_seconds = 3600
max_response_bytes = 65536
"""
    if config.delivery_enabled and config.delivery_transport == "telegram-v1":
        text += (
            "telegram_bot_token_ref = "
            f'{{ env = {toml_basic_string(config.delivery_telegram_bot_token_env)} }}\n'
            f"telegram_chat_id = {toml_basic_string(config.delivery_telegram_chat_id or '')}\n"
        )
    elif config.delivery_enabled:
        text += f"endpoint_ref = {{ env = {toml_basic_string(config.delivery_endpoint_env)} }}\n"
        if config.delivery_auth_env is not None:
            text += f"auth_token_ref = {{ env = {toml_basic_string(config.delivery_auth_env)} }}\n"

    # Self-check: the generated bytes must parse and every owner-provided
    # string must survive the round-trip exactly (fail closed, never emit
    # a document whose parsed values differ from the typed inputs).
    parsed = tomllib.loads(text)
    monitoring = parsed["monitoring"]
    delivery = monitoring.get("delivery", {})
    expected: dict[tuple[str, str], str] = {
        ("monitoring", "watchlist_path"): config.watchlist_path,
        ("monitoring", "workspace_root"): config.monitoring_workspace_root,
        ("delivery", "transport"): config.delivery_transport,
        ("delivery", "destination_id"): config.delivery_destination_id,
        ("delivery", "delivery_root"): config.delivery_root,
    }
    sections = {"monitoring": monitoring, "delivery": delivery}
    for (section_name, key), expected_value in expected.items():
        actual = sections[section_name].get(key)
        if actual != expected_value:
            raise SerializationError(
                f"generated project TOML does not round-trip {section_name}.{key} "
                "to the exact typed owner input"
            )
    if config.delivery_enabled and config.delivery_transport == "telegram-v1":
        if delivery.get("telegram_bot_token_ref") != {
            "env": config.delivery_telegram_bot_token_env
        } or delivery.get("telegram_chat_id") != config.delivery_telegram_chat_id:
            raise SerializationError(
                "generated project TOML does not round-trip the telegram "
                "delivery reference strings to the exact typed owner input"
            )
    elif config.delivery_enabled:
        if delivery.get("endpoint_ref") != {"env": config.delivery_endpoint_env} or (
            config.delivery_auth_env is not None
            and delivery.get("auth_token_ref") != {"env": config.delivery_auth_env}
        ):
            raise SerializationError(
                "generated project TOML does not round-trip the webhook "
                "delivery reference strings to the exact typed owner input"
            )
    return text


# ---------------------------------------------------------------------------
# Systemd rendering (production units)
# ---------------------------------------------------------------------------


def main_exec_argv(config: ProductionConfigV1, runner_config_path: Path) -> tuple[str, ...]:
    """The one intended main ``ExecStart`` argv for the configured mode.

    Delivery-enabled units run the unchanged ``unattended-notify`` command;
    monitoring-only units keep ``unattended-run``.  Both the renderer and
    the structural manager-effective verification derive their expectation
    from this single definition (R4 goal section 6).
    """

    argv: list[str] = [
        config.python_executable,
        "-m",
        "turtle_value_engine",
        "watch",
        "unattended-notify" if config.delivery_enabled else "unattended-run",
        "--runner-config",
        str(runner_config_path),
    ]
    if config.delivery_enabled:
        argv.extend(
            ("--project-config", str(config.project_config_path.resolve()), "--network", "allow")
        )
    return tuple(argv)


def render_service_unit(config: ProductionConfigV1, runner_config_path: Path) -> str:
    """Deterministic production oneshot service unit (no secret values).

    R4: every Exec command line and execution-critical path directive is
    serialized through the systemd-native boundary, and the rendered lines
    are mirror-parsed back before the text is returned so no owner input
    can leave this function without proven semantic parity.
    """

    environment_value = (
        systemd_unit_path_value(config.delivery_environment_file)
        if config.delivery_enabled
        else None
    )
    environment_line = (
        f"EnvironmentFile={environment_value}\n" if environment_value is not None else ""
    )
    main_argv = main_exec_argv(config, runner_config_path)
    if config.delivery_enabled:
        # R3: the runtime credential gate runs before unattended-notify.  It
        # re-reads the private credential file, reuses the one current-
        # credential validation primitive and compares the referenced values
        # with the environment systemd injected byte-for-byte; its argv
        # carries only non-secret paths and reference names, and any failure
        # (missing/mismatch/noncanonical/metadata) leaves ExecStart unrun.
        gate_argv = credential_gate_argv(config)
        prestart_lines = (
            f"ExecStartPre={systemd_exec_command(gate_argv)}\n"
            "# The ExecStartPre gate above prints only status/category/\n"
            "# reference names and never a credential value; systemd executes\n"
            "# it with the service environment, so a drifted or noncanonical\n"
            "# private file blocks notification execution entirely.\n"
        )
    else:
        gate_argv = None
        prestart_lines = ""
    run_line = f"ExecStart={systemd_exec_command(main_argv)}\n"
    user_line = f"User={config.service_user}\n" if config.scope == "system" else ""
    description = (
        "turtle-value-engine production monitoring cycle "
        f"({systemd_unit_text_value(config.runner_id)}, "
        "Phase 6-F persistent owner operations)"
    )
    # R4: Documentation= is a space-separated URL list — a raw owner path
    # with spaces would be split into invalid URLs.  URL-encode the path
    # (ordinary paths stay unchanged) and double the introduced percent
    # signs so the specifier expansion cannot reinterpret them.
    documentation_url = (
        f"file://{_url_quote(config.working_directory, safe='/')}"
        "/docs/goals/phase-6-f-persistent-owner-operations.md"
    ).replace("%", "%%")
    unit_text = (
        "[Unit]\n"
        f"Description={description}\n"
        f"Documentation={documentation_url}\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "# Rendered by scripts/monitoring_production_ops.py from explicit non-secret\n"
        "# owner inputs.  No credential value ever appears in this unit; the\n"
        "# optional EnvironmentFile path is the only credential-related fact and\n"
        "# its content stays in the ignored private root with 0600 permissions.\n"
        f"WorkingDirectory={systemd_unit_path_value(config.working_directory)}\n"
        f"{user_line}"
        f"{environment_line}"
        f"{prestart_lines}"
        f"{run_line}"
        "TimeoutStartSec=30min\n"
        "# Exit code 3 (LEASE_BUSY) means another live invocation owns the runner\n"
        "# lease and this invocation intentionally performed no work.\n"
        "SuccessExitStatus=3\n"
        "Nice=10\n"
    )

    # Render-boundary parity self-check (R4 goal section 3): mirror-parse
    # every serialized line and require the effective values to equal the
    # intended argv/paths exactly before any bytes are handed downstream.
    if gate_argv is not None and parse_systemd_exec_command(
        systemd_exec_command(gate_argv)
    ) != list(gate_argv):
        raise SerializationError(
            "rendered ExecStartPre does not round-trip to the intended gate argv"
        )
    if parse_systemd_exec_command(systemd_exec_command(main_argv)) != list(main_argv):
        raise SerializationError(
            "rendered ExecStart does not round-trip to the intended main argv"
        )
    if environment_value is not None and effective_unit_path_value(
        environment_value
    ) != str(config.delivery_environment_file):
        raise SerializationError(
            "rendered EnvironmentFile does not round-trip to the typed credential path"
        )
    if effective_unit_path_value(
        systemd_unit_path_value(config.working_directory)
    ) != config.working_directory:
        raise SerializationError(
            "rendered WorkingDirectory does not round-trip to the typed path"
        )
    return unit_text


def render_timer_unit(config: ProductionConfigV1) -> str:
    return (
        "[Unit]\n"
        "Description=Schedule the turtle-value-engine production monitoring cycle\n"
        "\n"
        "[Timer]\n"
        f"OnCalendar={config.on_calendar}\n"
        "Persistent=true\n"
        f"Unit={config.service_unit_name}\n"
        f"RandomizedDelaySec={config.randomized_delay_sec}s\n"
        f"AccuracySec={config.timer_accuracy_sec}s\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def desired_unit_bytes(config: ProductionConfigV1) -> dict[str, bytes]:
    runner_config_path = config.runner_config_path.resolve()
    return {
        config.service_unit_name: render_service_unit(config, runner_config_path).encode("utf-8"),
        config.timer_unit_name: render_timer_unit(config).encode("utf-8"),
    }


def desired_runner_config_bytes(config: ProductionConfigV1) -> bytes:
    return (
        build_runner_config(config).model_dump_json(indent=2, warnings=False).encode("utf-8")
        + b"\n"
    )


def desired_project_config_bytes(config: ProductionConfigV1) -> bytes:
    return render_project_config(config).encode("utf-8")


# ---------------------------------------------------------------------------
# Host topology classification (native Linux vs WSL2, Windows bootstrap)
# ---------------------------------------------------------------------------


def classify_topology_from_facts(
    *,
    sys_platform: str,
    kernel_release: str,
    proc_version: str,
    pid1_comm: str,
    wsl_conf_text: str | None,
    interop_available: bool,
) -> dict[str, object]:
    """Pure topology classification from injectable host facts."""

    is_wsl = "microsoft" in (kernel_release + " " + proc_version).lower()
    wsl_systemd_boot: bool | None = None
    if wsl_conf_text is not None:
        in_boot = False
        for raw_line in wsl_conf_text.splitlines():
            line = raw_line.strip()
            if line.startswith("["):
                in_boot = line.lower().startswith("[boot]")
                continue
            if in_boot and "=" in line:
                key, _, value = line.partition("=")
                if key.strip().lower() == "systemd":
                    wsl_systemd_boot = value.strip().lower() == "true"
    # Linux-side evidence (systemd as PID 1, [boot] systemd=true in
    # /etc/wsl.conf) proves the distro user manager starts whenever the
    # distro runs.  Nothing readable from inside the distro proves the
    # Windows host auto-starts this distro after a Windows reboot, so the
    # bootstrap capability boundary stays explicit rather than inferred.
    windows_bootstrap_proven = False
    persistence_claim = (
        "persistent while the WSL distro/user manager is running "
        "(Linux systemd PID 1 with linger; Windows-reboot distro autostart "
        "not claimed)"
        if is_wsl
        else "persistent through host reboots via the native Linux system manager"
    )
    if not is_wsl:
        windows_bootstrap_proven = True  # not applicable on native Linux
    return {
        "sys_platform": sys_platform,
        "kernel_release": kernel_release,
        "wsl2": is_wsl,
        "pid1": pid1_comm,
        "wsl_conf_systemd_boot": wsl_systemd_boot,
        "windows_interop_available": interop_available if is_wsl else None,
        "windows_host_bootstrap_proven": windows_bootstrap_proven,
        "persistence_claim": persistence_claim,
    }


def classify_host_topology(runner: CommandRunner = _default_runner) -> dict[str, object]:
    proc_version = ""
    try:
        proc_version = Path("/proc/version").read_text(encoding="utf-8")
    except OSError:
        proc_version = ""
    try:
        pid1_comm = Path("/proc/1/comm").read_text(encoding="utf-8").strip()
    except OSError:
        pid1_comm = "unknown"
    wsl_conf_text: str | None = None
    try:
        wsl_conf_text = Path("/etc/wsl.conf").read_text(encoding="utf-8")
    except OSError:
        wsl_conf_text = None
    interop = bool(os.environ.get("WSL_INTEROP")) and Path("/run/WSL").is_dir()
    facts = classify_topology_from_facts(
        sys_platform=sys.platform,
        kernel_release=platform.release(),
        proc_version=proc_version,
        pid1_comm=pid1_comm,
        wsl_conf_text=wsl_conf_text,
        interop_available=interop,
    )
    version_outcome = run_command(("systemctl", "--version"), runner=runner)
    facts["systemd_version"] = _bounded(
        (version_outcome.stdout.splitlines() or ["unavailable"])[0], 120
    )
    return facts


def windows_bootstrap_marker_payload(
    config: ProductionConfigV1, production_config_path: str | Path
) -> dict[str, object]:
    """The precise WSL capability boundary (six disclosure items)."""

    marker = ManualBoundary(
        WINDOWS_HOST_BOOTSTRAP_UNPROVEN,
        stopped_after=(
            "preflight/verify topology classification on the real deployment host: "
            "Linux-side evidence (systemd PID 1, /etc/wsl.conf) cannot prove that "
            "the Windows host auto-starts this WSL distro after a Windows reboot"
        ),
        human_action=(
            "optional: register a Windows-side logon/startup task that starts this "
            "distro (e.g. an owner-created scheduled task running "
            "`wsl.exe -d <DistroName>`) if unattended Windows-reboot autostart is "
            "wanted; this is a Windows-owner action, not a Linux-side edit"
        ),
        secret_boundary="no secret is involved in the bootstrap registration",
        resume_command=_resume_command(production_config_path, "verify"),
        machine_verifiable_success=(
            "a future topology probe that can read a Windows-side autostart "
            "registration for this distro through interop flips "
            "windows_host_bootstrap_proven to true; run the resume command after "
            "the Windows-side registration exists (the topology classifier records "
            "the interop probe result in every report)"
        ),
        remaining_unverified=(
            "Windows-reboot autostart of the WSL distro itself; everything on the "
            "Linux side (linger, timer, units, runner durability) remains proven"
        ),
    )
    return marker.payload


# ---------------------------------------------------------------------------
# Linger (user-scope persistence)
# ---------------------------------------------------------------------------


def linger_state(user: str, runner: CommandRunner = _default_runner) -> str | None:
    outcome = run_command(("loginctl", "show-user", user, "-p", "Linger"), runner=runner)
    if not outcome.ok:
        return None
    for line in outcome.stdout.splitlines():
        if line.startswith("Linger="):
            return line.partition("=")[2].strip()
    return None


def enable_linger(user: str, runner: CommandRunner = _default_runner) -> CommandOutcome:
    # The explicit username matters: the argument-less form resolves the
    # calling session and fails on hosts without a controlling TTY (WSL2).
    return run_command(("loginctl", "enable-linger", user), runner=runner)


def ensure_linger(
    config: ProductionConfigV1,
    *,
    current_user: str | None = None,
    runner: CommandRunner = _default_runner,
    production_config_path: str | Path,
) -> dict[str, object]:
    """Verify linger for user scope, enabling it automatically when allowed."""

    if config.scope != "user":
        return {"applicable": False, "scope": config.scope}
    user = current_user or config.service_user or getpass_user()
    before = linger_state(user, runner)
    if before == "yes":
        return {"applicable": True, "user": user, "state_before": before, "action": "unchanged"}
    outcome = enable_linger(user, runner=runner)
    after = linger_state(user, runner)
    if outcome.ok and after == "yes":
        return {
            "applicable": True,
            "user": user,
            "state_before": before,
            "action": "enabled",
            "state_after": after,
        }
    raise ManualBoundary(
        MANUAL_ENABLE_LINGER_REQUIRED,
        stopped_after=(
            f"apply: user-scope production persistence requires Linger=yes for "
            f"{user}, but `loginctl enable-linger {user}` did not establish it "
            f"(rc={outcome.returncode}, Linger={after})"
        ),
        human_action=(
            f"run `sudo loginctl enable-linger {user}` (or ask an administrator to) "
            "so the user systemd manager keeps running after the last login session"
        ),
        secret_boundary="no secret is involved; this is a systemd user-manager property",
        resume_command=_resume_command(production_config_path, "apply"),
        machine_verifiable_success=(
            f"`loginctl show-user {user} -p Linger` reports Linger=yes and the "
            "resumed apply exits 0"
        ),
        remaining_unverified=(
            "unattended production persistence outside an interactive login "
            "(the timer only runs while the user manager is alive)"
        ),
    )


def getpass_user() -> str:
    import pwd

    return pwd.getpwuid(os.getuid()).pw_name


def _resume_command(production_config_path: str | Path, mode: str) -> str:
    """A directly runnable resume command using the actual input config."""

    return shlex.join(
        (
            sys.executable,
            str(Path(__file__).resolve()),
            "--production-config",
            str(Path(production_config_path).expanduser().resolve()),
            mode,
        )
    )


# ---------------------------------------------------------------------------
# Deterministic plan (mutation-free convergence projection)
# ---------------------------------------------------------------------------

_ACTION_CREATE = "create"
_ACTION_MODIFY = "modify"
_ACTION_UNCHANGED = "unchanged"


def _file_action(existing: Path, desired: bytes) -> tuple[str, str | None]:
    if not existing.is_file():
        return _ACTION_CREATE, None
    installed_sha = _sha256_bytes(existing.read_bytes())
    if existing.read_bytes() == desired:
        return _ACTION_UNCHANGED, installed_sha
    return _ACTION_MODIFY, installed_sha


def compute_plan(
    config: ProductionConfigV1, runner: CommandRunner = _default_runner
) -> dict[str, object]:
    """Deterministic, redacted, mutation-free convergence plan."""

    desired_units = desired_unit_bytes(config)
    destination = systemd_unit_destination_dir(config)
    resources: list[dict[str, object]] = []
    for name, desired in desired_units.items():
        action, installed_sha = _file_action(destination / name, desired)
        resources.append(
            {
                "resource": f"unit-file:{name}",
                "action": action,
                "path": str(destination / name),
                "desired_sha256": _sha256_bytes(desired),
                "installed_sha256": installed_sha,
                "desired_bytes": len(desired),
            }
        )
    for label, path, desired in (
        ("runner-config", config.runner_config_path, desired_runner_config_bytes(config)),
        ("project-config", config.project_config_path, desired_project_config_bytes(config)),
    ):
        action, installed_sha = _file_action(path, desired)
        resources.append(
            {
                "resource": label,
                "action": action,
                "path": str(path),
                "desired_sha256": _sha256_bytes(desired),
                "installed_sha256": installed_sha,
                "desired_bytes": len(desired),
            }
        )

    timer_props = _systemctl_show(
        config,
        config.timer_unit_name,
        ("UnitFileState", "ActiveState"),
        runner,
    )
    unit_file_state = timer_props.get("UnitFileState", "")
    resources.append(
        {
            "resource": "timer-enable",
            "action": "enable" if unit_file_state != "enabled" else "unchanged",
            "unit": config.timer_unit_name,
            "effective_unit_file_state": unit_file_state or "absent",
        }
    )
    # Activation is deliberately excluded from apply: the timer is enabled,
    # never started, by configuration installation.
    resources.append(
        {
            "resource": "timer-start",
            "action": "explicit-activation-required",
            "unit": config.timer_unit_name,
            "effective_active_state": timer_props.get("ActiveState", "") or "unknown",
            "note": "apply never starts the timer; run the activate mode explicitly",
        }
    )
    if config.scope == "user":
        user = config.service_user or getpass_user()
        state = linger_state(user, runner)
        resources.append(
            {
                "resource": "linger",
                "action": "enable" if state != "yes" else "unchanged",
                "user": user,
                "effective_linger": state or "unknown",
            }
        )
    service_props = _systemctl_show(
        config,
        config.service_unit_name,
        ("ExecStart", "WorkingDirectory", "User"),
        runner,
    )
    return {
        "contract": "monitoring_production_plan_v1",
        "generated_for_head": acceptance._git_head(ROOT, runner),
        "scope": config.scope,
        "service_user": config.service_user,
        "service_identity": config.service_identity,
        "on_calendar": config.on_calendar,
        "randomized_delay_sec": config.randomized_delay_sec,
        "network_policy": "explicit-opt-in" if config.network_allowed else "offline-replay",
        "window_days": config.window_days,
        "delivery": {
            "enabled": config.delivery_enabled,
            "transport": config.delivery_transport if config.delivery_enabled else None,
            "environment_file": config.delivery_environment_file
            if config.delivery_enabled
            else None,
        },
        "runner_id": config.runner_id,
        "watchlist_path": config.watchlist_path,
        "runner_config_path": str(config.runner_config_path),
        "effective_service_properties": service_props,
        "resources": resources,
        "mutation_performed": False,
        "contains_secrets": False,
    }


def cmd_plan(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    plan = compute_plan(config, runner=runner)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return EXIT_OK


# ---------------------------------------------------------------------------
# Preflight (non-mutating)
# ---------------------------------------------------------------------------


def _production_secret_reference_names(config: ProductionConfigV1) -> list[str]:
    if not config.delivery_enabled:
        return []
    names = [config.delivery_endpoint_env, config.delivery_auth_env]
    if config.delivery_transport == "telegram-v1":
        names = [config.delivery_telegram_bot_token_env]
    return [name for name in names if name is not None]


def resolvable_secret_values(
    config: ProductionConfigV1, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Currently resolvable secret values by reference (scans/redaction only)."""

    environment = os.environ if environ is None else environ
    values: dict[str, str] = {}
    for name in _production_secret_reference_names(config):
        raw = environment.get(name, "")
        if raw.strip():
            values[name] = raw
    return values


def effective_secret_values(
    config: ProductionConfigV1, environ: Mapping[str, str] | None = None
) -> dict[str, list[str]]:
    """Every value currently usable by the production service, by reference.

    The production service resolves a referenced secret from its private
    systemd ``EnvironmentFile``; an operator harness run may additionally
    hold a value for the same reference in its own process environment.
    Both sources are merged in memory: when they carry different values for
    one reference, both are returned so leak scans and redaction cover
    either value instead of silently dropping one.

    File values come only from the canonical parser
    (``environment_file_values``): a file that is unreadable or outside the
    canonical subset contributes no values here, because its bytes cannot be
    proven identical to what systemd would inject.  The precise
    missing/unreadable/insecure/non-canonical boundary is raised by the
    gating paths (preflight/render/live-proof delivery), never by
    fabricating a value.
    """

    names = _production_secret_reference_names(config)
    environment_values = resolvable_secret_values(config, environ)
    file_values: dict[str, str] = {}
    if config.delivery_enabled and config.delivery_environment_file is not None:
        file_values, _error = environment_file_values(config)
    collected: dict[str, list[str]] = {}
    for name in names:
        candidates: list[str] = []
        for source_value in (environment_values.get(name, ""), file_values.get(name, "")):
            if source_value.strip() and source_value not in candidates:
                candidates.append(source_value)
        if candidates:
            collected[name] = candidates
    return collected


def _effective_secret_scan_map(values: Mapping[str, list[str]]) -> dict[str, str]:
    """Flatten effective values into one name/value scan/redaction map.

    A second distinct value for the same reference gets a derived key
    (``NAME~2``) so both values are scanned and redacted while hit reports
    stay value-free; the derived key is scan bookkeeping, not a public
    reference name.
    """

    flat: dict[str, str] = {}
    for name in sorted(values):
        for index, value in enumerate(values[name]):
            flat[name if index == 0 else f"{name}~{index + 1}"] = value
    return flat


def environment_file_values(
    config: ProductionConfigV1,
) -> tuple[dict[str, str], str | None]:
    """Read the private credential file under the canonical subset (memory only).

    This is the one canonical parser/validator for every production-operations
    credential path (render gating, preflight, effective secret scanning and
    redaction, D3 payload scans, the R3 current-credential primitive and the
    service pre-start gate).  The accepted grammar is a deliberately
    unambiguous subset of systemd's ``EnvironmentFile=`` semantics so that
    every accepted value is byte-identical to what the service manager
    injects:

    - UTF-8 text; blank lines and whole-line ``#``/``;`` comments are ignored;
    - the *whole decoded file* — comments included — must be free of the
      Unicode scalars systemd itself rejects (``U+0000``, ``U+FEFF``,
      ``U+FDD0..U+FDEF`` and every plane-ending ``FFFE``/``FFFF`` code
      point), so every file called canonical is valid under systemd;
    - every assignment is exactly one physical ``NAME=VALUE`` line starting at
      column 0; ``NAME`` must be one of the currently referenced secret names
      (``_production_secret_reference_names``), each present exactly once;
    - duplicates, unknown/unrelated environment keys and ``export NAME=...``
      forms are rejected, so the file cannot inject unrelated process
      environment;
    - ``VALUE`` is non-empty, carries no leading/trailing/embedded whitespace,
      no control character, no quote and no backslash, and is used
      byte-for-byte after UTF-8 decoding and line-ending removal (``=``, ``#``,
      ``;``, ``?``, ``&``, ``%`` and other URL punctuation stay literal data).

    Any syntax-level violation (unreadable, non-UTF-8, systemd-invalid
    Unicode, malformed line, duplicate, unknown key, ``export`` form, empty
    value) returns ``({}, reason)``: no value from a file whose
    interpretation is not provably identical under systemd is ever released.
    A file whose present lines are all canonical but which is missing a
    referenced name returns its partial values together with the reason:
    those bytes are still exactly what systemd would inject for them, so the
    fail-safe scan and redaction set keeps its Phase 6-F-R1 coverage, while
    every gating path (preflight/render/live-proof delivery, the R3
    lifecycle drift gates and the pre-start gate) fails closed on the
    non-``None`` error.  Reasons name only the line number/category of the
    problem and referenced (public) names — never file content.  Values
    never leave the caller's process memory except inside absence
    scans/redaction.
    """

    assert config.delivery_environment_file is not None
    return _parse_canonical_environment_file(
        Path(config.delivery_environment_file),
        _production_secret_reference_names(config),
    )


def _parse_canonical_environment_file(
    path: Path, required: Sequence[str]
) -> tuple[dict[str, str], str | None]:
    """The canonical EnvironmentFile parser core (see ``environment_file_values``)."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {}, f"cannot read {path}: {type(exc).__name__}"
    if len(raw) > _ENV_FILE_MAX_BYTES:
        return {}, (
            f"{path} is larger than the {_ENV_FILE_MAX_BYTES}-byte "
            "credential-file bound"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {}, f"{path} is not valid UTF-8"
    invalid_unicode = _systemd_invalid_unicode(text)
    if invalid_unicode is not None:
        offset, category = invalid_unicode
        lineno = text.count("\n", 0, offset) + 1
        return {}, (
            f"line {lineno}: systemd-invalid Unicode in the file ({category}); "
            "systemd itself would reject this EnvironmentFile"
        )
    values: dict[str, str] = {}
    for lineno, raw_line in enumerate(text.split("\n"), start=1):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        if not line or not line.strip(" \t"):
            continue
        if line[0] in "#;":
            continue
        if line.startswith("export") and len(line) > 6 and line[6] in " \t":
            return {}, (
                f"line {lineno}: 'export NAME=VALUE' is not the canonical "
                "EnvironmentFile form"
            )
        if line[0] in " \t":
            return {}, (
                f"line {lineno}: assignment must start at column 0 (no leading "
                "whitespace)"
            )
        if "=" not in line:
            return {}, (
                f"line {lineno}: neither a blank line, a comment nor a "
                "NAME=VALUE assignment (unsupported syntax)"
            )
        name, _, value = line.partition("=")
        if not name:
            return {}, f"line {lineno}: missing NAME before '='"
        if name != name.strip(" \t"):
            return {}, (
                f"line {lineno}: whitespace in or around the name of a "
                "referenced assignment"
            )
        if name not in required:
            return {}, (
                f"line {lineno}: assigns an environment name that is not one of "
                f"the referenced secret names ({', '.join(required)}); the "
                "credential file cannot inject unrelated process environment"
            )
        if name in values:
            return {}, f"line {lineno}: duplicate assignment for referenced name {name}"
        if not value:
            return {}, f"line {lineno}: empty value for {name}"
        violation = _canonical_value_violation(value)
        if violation is not None:
            return {}, f"line {lineno}: {violation} for {name}"
        values[name] = value
    missing = [name for name in required if name not in values]
    if missing:
        # Present canonical lines keep their unambiguous bytes in the
        # fail-safe scan/redaction set (R1 coverage), but the non-None error
        # fails every gating path closed.
        return values, (
            f"{path} does not define every referenced secret: missing "
            f"{', '.join(missing)}"
        )
    return values, None


def _canonical_value_violation(value: str) -> str | None:
    """Categorize why a ``VALUE`` is outside the canonical subset (leak-free)."""

    for ch in value:
        if ch in _ENV_FILE_VALUE_FORBIDDEN_CHARS:
            return "quote or backslash in value (quoting/escaping is not canonical)"
        if ch.isspace():
            return "whitespace in value"
        if unicodedata.category(ch) == "Cc":
            return "control character in value"
    return None


def validate_delivery_environment_file(
    config: ProductionConfigV1,
) -> tuple[dict[str, object], str | None]:
    """Machine-check the private ``EnvironmentFile`` contract (metadata only).

    When delivery is enabled the configured credential file must be a
    regular file whose resolved path stays inside the production private
    root (no symlink/``..`` escape) and whose permissions are owner-only
    (``0600`` is the documented normal form; any group/world bit is
    rejected).  Returns ``(metadata, None)`` when the boundary holds and
    ``(metadata, reason)`` when it is violated.  Only path/permission
    metadata is reported; content is never read here and the owner's file
    is never rewritten or chmod'ed by this harness.
    """

    assert config.delivery_environment_file is not None
    return _validate_environment_file_facts(
        Path(config.delivery_environment_file), Path(config.production_root)
    )


def _validate_environment_file_facts(
    configured: Path, private_root: Path
) -> tuple[dict[str, object], str | None]:
    """The R1 metadata/path/type/mode boundary core (facts-based)."""

    metadata: dict[str, object] = {
        "path": str(configured),
        "private_root": str(private_root),
    }
    if _contains_control_character(str(configured)):
        return metadata, (
            "the configured environment file path contains control characters "
            "or newlines (it is serialized into the unit's EnvironmentFile= line)"
        )
    if not configured.exists() and not configured.is_symlink():
        return metadata, f"{configured} does not exist"
    try:
        resolved = configured.resolve(strict=True)
        resolved_stat = resolved.stat()
    except OSError as exc:
        return metadata, f"cannot resolve {configured}: {type(exc).__name__}"
    metadata["resolved"] = str(resolved)
    mode = stat_module.S_IMODE(resolved_stat.st_mode)
    metadata["mode"] = format(mode, "04o")
    if not resolved.is_relative_to(private_root.resolve()):
        return metadata, (
            f"{configured} resolves to {resolved}, outside the production "
            f"private root {private_root}"
        )
    if not stat_module.S_ISREG(resolved_stat.st_mode):
        return metadata, f"{resolved} is not a regular file"
    if mode & 0o077:
        return metadata, (
            f"{resolved} is group/world-accessible (mode {format(mode, '04o')}); "
            "owner-only access is required (chmod 0600 by the owner; this "
            "harness never changes the file)"
        )
    return metadata, None


# ---------------------------------------------------------------------------
# Phase 6-F-R3: one current-credential validation primitive
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurrentCredentialState:
    """The combined current-credential validation result (secret-free shell).

    ``values`` holds the canonical parsed referenced values **in process
    memory only**; it must never be persisted, printed or projected.  Every
    public field and both summary helpers are value-free by construction.
    """

    environment_file: str
    production_root: str
    referenced_names: tuple[str, ...]
    metadata: dict[str, object] = field(default_factory=dict)
    metadata_error: str | None = None
    values: dict[str, str] = field(default_factory=dict)
    canonical_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.metadata_error is None and self.canonical_error is None

    def public_reason(self) -> str:
        """A value-free reason string for logs, markers and reports."""

        if self.metadata_error is not None:
            return self.metadata_error
        if self.canonical_error is not None:
            return self.canonical_error
        return (
            "the current private credential file satisfies the R1 metadata "
            "boundary, the canonical grammar and referenced-name completeness, "
            "and carries no systemd-invalid Unicode (values not shown)"
        )

    def public_summary(self) -> dict[str, object]:
        """A value-free machine-readable summary for reports."""

        return {
            "enabled": True,
            "ok": self.ok,
            "environment_file": self.environment_file,
            "referenced_names": list(self.referenced_names),
            "metadata": self.metadata,
            "metadata_error": self.metadata_error,
            "canonical_error": self.canonical_error,
        }


def validate_current_credential(
    *,
    environment_file: str | Path,
    production_root: str | Path,
    referenced_names: Sequence[str],
) -> CurrentCredentialState:
    """The one current-credential validation primitive (R3 goal section 4).

    Combines, against the file as it exists *right now*:

    - the R1 metadata/path/type/mode boundary;
    - the R2 canonical parsing and referenced-name completeness;
    - the R3 whole-file systemd-valid Unicode validation.

    Lifecycle checks (render, apply/converge, activate, verify, report,
    preflight, the live-proof delivery boundary and the recover-proof
    restart probe) and the service ``ExecStartPre=`` gate must reuse this
    operation instead of implementing separate parsing rules.  No raw value
    or digest/HMAC/fingerprint derived from credential content is ever
    persisted; drift detection always re-reads the private file here.
    """

    configured = Path(environment_file)
    root = Path(production_root)
    metadata, metadata_error = _validate_environment_file_facts(configured, root)
    values: dict[str, str] = {}
    canonical_error: str | None = None
    if metadata_error is None:
        # Only read content once the metadata boundary (containment, type,
        # owner-only permissions) is proven; a boundary failure is reported
        # without probing the file's bytes.
        values, canonical_error = _parse_canonical_environment_file(
            configured, tuple(referenced_names)
        )
    return CurrentCredentialState(
        environment_file=str(configured),
        production_root=str(root),
        referenced_names=tuple(referenced_names),
        metadata=metadata,
        metadata_error=metadata_error,
        values=values,
        canonical_error=canonical_error,
    )


def current_credential_state(
    config: ProductionConfigV1,
) -> CurrentCredentialState | None:
    """The current-credential state for one production config (None if disabled)."""

    if not config.delivery_enabled:
        return None
    assert config.delivery_environment_file is not None
    return validate_current_credential(
        environment_file=config.delivery_environment_file,
        production_root=config.production_root,
        referenced_names=_production_secret_reference_names(config),
    )


def _environment_value_bytes(value: str) -> bytes:
    """Round-trip a process-environment string to its raw bytes.

    ``os.environ`` decodes values with ``surrogateescape``; re-encoding the
    same way recovers the exact injected bytes, so comparing them with the
    canonical parser's UTF-8 bytes is a byte-for-byte comparison that also
    fails closed on invalid-UTF-8 environment content.
    """

    return value.encode("utf-8", "surrogateescape")


def run_credential_gate(
    *,
    environment_file: str | Path,
    production_root: str | Path,
    referenced_names: Sequence[str],
    environ: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    """The service-execution credential gate (R3 goal section 6).

    Reuses :func:`validate_current_credential` against the current private
    file, then compares every referenced value with the environment the
    service manager actually injected (``os.environ`` inside the
    ``ExecStartPre=`` context, or the injected ``environ`` mapping) byte
    for byte in memory.  Success requires metadata, canonicality,
    completeness and byte equality to all hold.  The returned payload
    carries only status/category/reference names — never a value, a digest
    or a fingerprint.
    """

    state = validate_current_credential(
        environment_file=environment_file,
        production_root=production_root,
        referenced_names=referenced_names,
    )
    if state.metadata_error is not None:
        return EXIT_FAIL_CLOSED, {
            "status": CREDENTIAL_GATE_REJECTED,
            "category": "METADATA",
            "reason": state.metadata_error,
        }
    if state.canonical_error is not None:
        return EXIT_FAIL_CLOSED, {
            "status": CREDENTIAL_GATE_REJECTED,
            "category": "NONCANONICAL_OR_INCOMPLETE",
            "reason": state.canonical_error,
        }
    environment = os.environ if environ is None else environ
    for name in state.referenced_names:
        inherited = environment.get(name)
        if inherited is None:
            return EXIT_FAIL_CLOSED, {
                "status": CREDENTIAL_GATE_REJECTED,
                "category": "ENV_MISSING",
                "reference": name,
                "reason": (
                    f"the inherited service environment does not define the "
                    f"referenced secret {name}"
                ),
            }
        if _environment_value_bytes(inherited) != state.values[name].encode("utf-8"):
            return EXIT_FAIL_CLOSED, {
                "status": CREDENTIAL_GATE_REJECTED,
                "category": "ENV_MISMATCH",
                "reference": name,
                "reason": (
                    f"the inherited service environment value for {name} does "
                    "not byte-match the current canonical credential file"
                ),
            }
    return EXIT_OK, {
        "status": CREDENTIAL_GATE_OK,
        "references": list(state.referenced_names),
        "compared": "metadata+canonical+complete+inherited-byte-equality",
    }


def credential_gate_argv(config: ProductionConfigV1) -> tuple[str, ...]:
    """The exact non-secret gate argv rendered into the delivery unit."""

    assert config.delivery_environment_file is not None
    argv: list[str] = [
        config.python_executable,
        str(CREDENTIAL_GATE_SCRIPT),
        "--environment-file",
        config.delivery_environment_file,
        "--production-root",
        config.production_root,
    ]
    for name in _production_secret_reference_names(config):
        argv.extend(("--reference", name))
    return tuple(argv)


def credential_gate_command(config: ProductionConfigV1) -> str:
    """The unit-serialized gate command (paths and reference names only).

    R4: serialized through the systemd-native Exec-line boundary —
    ``shlex.join`` is a POSIX-shell serializer and left literal ``$``/``%``
    sequences to the systemd expansions.  shlex remains in use only for the
    human-facing shell resume commands.
    """

    return systemd_exec_command(credential_gate_argv(config))


def cmd_preflight(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    log = CheckLog()

    log.add("host.linux", sys.platform.startswith("linux"), f"sys.platform={sys.platform}")
    log.add(
        "host.python",
        sys.version_info >= (3, 11),
        f"interpreter={sys.executable} version={sys.version.split()[0]}",
    )
    systemd_version = run_command(("systemctl", "--version"), runner=runner)
    log.add(
        "host.systemd-present",
        systemd_version.ok,
        _bounded(systemd_version.stdout.splitlines()[0] if systemd_version.stdout else "", 120),
    )
    systemd_state = run_command(("systemctl", "is-system-running"), runner=runner)
    log.add(
        "host.systemd-running",
        systemd_state.ok or systemd_state.stdout.strip() == "degraded",
        f"is-system-running={systemd_state.stdout.strip() or systemd_state.stderr.strip()}",
    )
    log.add("host.proc-locks-readable", os.access("/proc/locks", os.R_OK), "/proc/locks")

    head_sha = acceptance._git_head(ROOT, runner)
    tree_clean = acceptance._git_clean(ROOT, runner)
    log.add("repo.head", bool(re.fullmatch(r"[0-9a-f]{40}", head_sha)), head_sha)
    log.add(
        "repo.working-tree",
        tree_clean or not args.require_clean_tree,
        "clean" if tree_clean else "dirty (pass --require-clean-tree to enforce)",
    )
    if config.require_repo_gate and not args.skip_gate:
        try:
            artifact = load_gate_artifact(config, head_sha=head_sha)
            log.add("repo.gate-artifact", True, f"green at {artifact['head_sha']}")
        except AcceptanceError as exc:
            log.add("repo.gate-artifact", False, str(exc))
    else:
        log.add_marker(
            "repo.gate-artifact",
            acceptance.MANUAL_OWNER_INPUT_REQUIRED,
            "repo gate check skipped by explicit flag",
        )

    # Typed inputs: the production watchlist is an existing owner file.
    watchlist_path = Path(config.watchlist_path)
    if watchlist_path.is_file():
        try:
            watchlist = WatchlistSpecV1.build(
                **json.loads(watchlist_path.read_text(encoding="utf-8"))
            )
            entries = [entry.listing_id for entry in watchlist.entries]
            bad_entries = [item for item in entries if not _LISTING_PATTERN.match(item)]
            log.add(
                "config.watchlist",
                not bad_entries,
                f"watchlist_id={watchlist.watchlist_id} entries={entries}",
            )
        except Exception as exc:
            log.add("config.watchlist", False, f"invalid watchlist: {exc}")
    else:
        log.add("config.watchlist", False, f"missing production watchlist: {watchlist_path}")

    try:
        runner_config = build_runner_config(config)
        log.add(
            "config.runner",
            True,
            f"runner_id={runner_config.runner_id} network_allowed="
            f"{runner_config.network_allowed} window_days={runner_config.window_days}",
        )
    except Exception as exc:
        log.add("config.runner", False, f"cannot build runner config: {exc}")

    # Roots are private (never a tracked-worktree path outside .tve-private).
    inside_worktree = False
    try:
        Path(config.production_root).relative_to(ROOT)
        inside_worktree = True
    except ValueError:
        inside_worktree = False
    private = (not inside_worktree) or ".tve-private" in Path(config.production_root).parts
    probe_dir = Path(config.production_root)
    while not probe_dir.exists():
        probe_dir = probe_dir.parent
    log.add(
        "config.roots-private-writable",
        private and os.access(probe_dir, os.W_OK | os.X_OK),
        f"production_root={config.production_root} writable_probe={probe_dir} "
        f"inside_worktree={inside_worktree}",
    )

    # Topology classification (native vs WSL2, PID 1, Windows bootstrap).
    topology = classify_host_topology(runner)
    topology_ok = (
        topology["pid1"] == "systemd"
        and (not topology["wsl2"] or topology["wsl_conf_systemd_boot"] is True)
    )
    log.add(
        "host.topology",
        bool(topology_ok),
        json.dumps(topology, ensure_ascii=False),
    )
    if topology["wsl2"] and not topology["windows_host_bootstrap_proven"]:
        # Capability boundary, not a deployment blocker: the persistence claim
        # is narrowed, and the exact marker travels into every report.
        log.add_marker(
            "host.windows-bootstrap",
            WINDOWS_HOST_BOOTSTRAP_UNPROVEN,
            "Linux-side evidence cannot prove Windows-reboot distro autostart; the "
            "persistence claim stays narrowed to the running distro/user manager",
        )

    # Linger classification (user scope): state now + what apply would do.
    if config.scope == "user":
        user = config.service_user or getpass_user()
        state = linger_state(user, runner)
        log.add(
            "host.linger",
            state == "yes",
            f"Linger={state or 'unknown'} for {user}; "
            + (
                "already persistent"
                if state == "yes"
                else "apply will attempt `loginctl enable-linger` automatically"
            ),
        )

    # Delivery: optional; references and the typed environment file only.
    credential = current_credential_state(config)
    if config.delivery_enabled:
        env_file = Path(config.delivery_environment_file or "")
        assert credential is not None
        if credential.metadata_error is not None:
            log.add_marker(
                "delivery.environment-file",
                MANUAL_SECRET_REFERENCE_REQUIRED,
                f"{credential.metadata_error}; required: a regular owner-private "
                f"(0600) file inside {config.production_root} defining "
                f"{', '.join(credential.referenced_names)}",
            )
            log.add_marker(
                "delivery.secret-reference",
                MANUAL_SECRET_REFERENCE_REQUIRED,
                "credential source not accepted (see delivery.environment-file); "
                "fix the private-file boundary first",
            )
        elif not credential.ok:
            log.add(
                "delivery.environment-file",
                True,
                json.dumps(credential.metadata, ensure_ascii=False)
                + " (content never read into any artifact)",
            )
            log.add_marker(
                "delivery.secret-reference",
                MANUAL_SECRET_REFERENCE_REQUIRED,
                f"the private credential file does not satisfy the canonical "
                f"EnvironmentFile contract: {credential.canonical_error}; fix "
                f"{env_file} by hand so each referenced value is one physical "
                "NAME=VALUE line (non-empty, no quoting/escaping/continuation/"
                "whitespace, no systemd-invalid Unicode anywhere in the file; "
                "URL characters like = # ; ? & % stay literal)",
            )
        else:
            log.add(
                "delivery.environment-file",
                True,
                json.dumps(credential.metadata, ensure_ascii=False)
                + " (content never read into any artifact)",
            )
            log.add(
                "delivery.secret-reference",
                True,
                "every referenced secret resolves from the typed environment file "
                "in canonical form, byte-identical to the service manager's "
                "injection (values not shown)",
            )
    else:
        log.add(
            "delivery",
            True,
            "notification disabled (monitoring-only production deployment)",
        )

    effective = effective_secret_values(config)
    tracked = _tracked_files_without_secrets(
        runner, _effective_secret_scan_map(effective)
    )
    log.add(
        "secrets.tracked-files-clean",
        bool(tracked["clean"]),
        json.dumps(tracked, ensure_ascii=False),
    )

    reference_verify = _systemd_analyze_verify(
        (
            ROOT / "deploy/monitoring/turtle-value-monitor.service",
            ROOT / "deploy/monitoring/turtle-value-monitor.timer",
        ),
        runner=runner,
    )
    log.add(
        "systemd.reference-units-verify",
        reference_verify.ok,
        _bounded(reference_verify.stderr or "ok", 400),
    )

    if config.snapshot_path is None:
        log.add_marker(
            "surface.snapshot",
            acceptance.MANUAL_OWNER_INPUT_REQUIRED,
            "no snapshot_path configured; the D3 read-only check will be skipped",
        )
    elif Path(config.snapshot_path).is_file():
        log.add("surface.snapshot", True, config.snapshot_path)
    else:
        log.add("surface.snapshot", False, f"snapshot missing: {config.snapshot_path}")

    lock = probe_lock_visibility(config, Path(config.runner_root), runner=runner)
    if lock["proven"] is True:
        log.add("lock.visibility", True, json.dumps(lock["steps"], ensure_ascii=False))
    else:
        log.add(
            "lock.visibility",
            False,
            json.dumps(lock, ensure_ascii=False),
            marker=DEPLOYMENT_LOCK_VISIBILITY_UNPROVEN,
        )

    payload = {
        "head_sha": head_sha,
        "topology": topology,
        "checks": log.checks,
        "green": not log.failed,
        "markers": [item["marker"] for item in log.checks if item["marker"] is not None],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK if not log.failed else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Gate (same mandatory deterministic gate, bound to the production root)
# ---------------------------------------------------------------------------


def cmd_gate(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    records: list[dict[str, object]] = []
    green = True
    for name, argv, extra_env in gate_commands(args.python):
        env = dict(os.environ)
        env.update(extra_env)
        outcome = run_command(argv, runner=runner, cwd=ROOT, env=env, timeout=args.timeout)
        record: dict[str, object] = {
            "name": name,
            "argv": list(argv),
            "returncode": outcome.returncode,
            "timed_out": outcome.timed_out,
            "stdout_tail": _bounded(outcome.stdout, 2000),
            "stderr_tail": _bounded(outcome.stderr, 2000),
        }
        records.append(record)
        if not outcome.ok:
            green = False
            if args.fail_fast:
                break
    artifact = {
        "head_sha": acceptance._git_head(ROOT, runner),
        "working_tree_clean": acceptance._git_clean(ROOT, runner),
        "green": green,
        "commands": records,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(config.gate_artifact_path, canonical_json_bytes(artifact) + b"\n")
    print(
        json.dumps(
            {
                "gate": "GREEN" if green else "RED",
                "head_sha": artifact["head_sha"],
                "working_tree_clean": artifact["working_tree_clean"],
                "artifact": str(config.gate_artifact_path),
                "failures": [
                    record["name"]
                    for record in records
                    if int(record["returncode"]) != 0 or record["timed_out"]
                ],
            },
            indent=2,
        )
    )
    return EXIT_OK if green else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Render (deterministic material under the private production root)
# ---------------------------------------------------------------------------


def cmd_render(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)

    if config.delivery_enabled:
        # R2/R3: prove the whole canonical credential contract through the one
        # current-credential validation primitive BEFORE any unit/config/
        # render-plan artifact byte is written: R1 metadata boundary, actual
        # readability, R2 canonical syntax subset, referenced-name completeness
        # and the R3 whole-file systemd-valid Unicode boundary in a single
        # place.
        credential = current_credential_state(config)
        if credential is None or not credential.ok:
            reason = credential.public_reason() if credential is not None else "unknown"
            raise ManualBoundary(
                MANUAL_SECRET_REFERENCE_REQUIRED,
                stopped_after=(
                    "render: delivery is enabled but the typed local credential "
                    f"source is not acceptable: {reason}; no unit, runner-config "
                    "or render-plan artifact was written"
                ),
                human_action=(
                    f"fix {config.delivery_environment_file} by hand: a regular "
                    "owner-private file (mode 0600) inside the production private "
                    f"root {config.production_root} defining each referenced "
                    "value exactly once in canonical form — one physical "
                    "NAME=VALUE line per name "
                    f"({', '.join(_production_secret_reference_names(config))}), "
                    "value non-empty without quoting, backslash escaping, line "
                    "continuation or whitespace, and no systemd-invalid Unicode "
                    "(U+0000, U+FEFF or noncharacters) anywhere in the file, "
                    "comments included (URL characters like = # ; ? & % stay "
                    "literal). This harness never chmods or rewrites the "
                    "owner's credential file. Do not paste any value into chat, "
                    "Git or documents"
                ),
                secret_boundary=(
                    "the environment file lives only in the ignored private root; "
                    "its values are never rendered, committed, logged or projected"
                ),
                resume_command=_resume_command(args.production_config, "render"),
                machine_verifiable_success=(
                    "render exits 0, the unit carries exactly the EnvironmentFile "
                    "path and the ExecStartPre credential gate ahead of the "
                    "unchanged unattended-notify ExecStart, and the file is an "
                    "in-root owner-private regular file whose canonical "
                    "NAME=VALUE content defines every referenced name exactly "
                    "once (values never printed)"
                ),
                remaining_unverified=(
                    "production notification delivery and post-restart credential "
                    "resolvability for the service identity"
                ),
            )
        if not CREDENTIAL_GATE_SCRIPT.is_file():
            raise AcceptanceError(
                "the delivery pre-start credential gate script is missing from "
                f"this checkout ({CREDENTIAL_GATE_SCRIPT}); the rendered unit "
                "could not enforce the runtime credential contract"
            )

    output_dir = config.systemd_output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    runner_config_bytes = desired_runner_config_bytes(config)
    project_config_bytes = desired_project_config_bytes(config)
    _atomic_write(config.runner_config_path, runner_config_bytes)
    _atomic_write(config.project_config_path, project_config_bytes)
    RunnerConfigV1.model_validate(json.loads(runner_config_bytes.decode("utf-8")))
    load_project_config(config.project_config_path)

    desired_units = desired_unit_bytes(config)
    written: list[dict[str, object]] = []
    for name, content in desired_units.items():
        path = output_dir / name
        _atomic_write(path, content)
        written.append(
            {"path": str(path), "sha256": _sha256_bytes(content), "bytes": len(content)}
        )
    verify = _systemd_analyze_verify(
        (output_dir / config.service_unit_name, output_dir / config.timer_unit_name),
        runner=runner,
    )
    destination = systemd_unit_destination_dir(config)
    install_commands = (
        [
            [
                "sudo",
                "install",
                "-o",
                "root",
                "-g",
                "root",
                "-m",
                "0644",
                str(output_dir / config.service_unit_name),
                str(destination / config.service_unit_name),
            ],
            [
                "sudo",
                "install",
                "-o",
                "root",
                "-g",
                "root",
                "-m",
                "0644",
                str(output_dir / config.timer_unit_name),
                str(destination / config.timer_unit_name),
            ],
            ["sudo", "systemctl", "daemon-reload"],
            ["sudo", "systemctl", "enable", config.timer_unit_name],
        ]
        if config.scope == "system"
        else [
            [
                "install",
                "-m",
                "0644",
                str(output_dir / config.service_unit_name),
                str(destination / config.service_unit_name),
            ],
            [
                "install",
                "-m",
                "0644",
                str(output_dir / config.timer_unit_name),
                str(destination / config.timer_unit_name),
            ],
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", config.timer_unit_name],
        ]
    )
    plan = {
        "scope": config.scope,
        "service_user": config.service_user,
        "on_calendar": config.on_calendar,
        "unit_files": written,
        "runner_config": {
            "path": str(config.runner_config_path),
            "sha256": _sha256_bytes(runner_config_bytes),
        },
        "project_config": {
            "path": str(config.project_config_path),
            "sha256": _sha256_bytes(project_config_bytes),
        },
        "destinations": [
            str(destination / config.service_unit_name),
            str(destination / config.timer_unit_name),
        ],
        "delivery_environment_file": config.delivery_environment_file
        if config.delivery_enabled
        else None,
        "verify": _outcome_public(verify),
        "install_commands": install_commands,
        "activation_note": "apply enables the timer without starting it; activation is explicit",
        "contains_secrets": False,
        "system_mutation_performed": False,
    }
    _atomic_write(output_dir / "render-plan.json", canonical_json_bytes(plan) + b"\n")
    print(json.dumps(plan, indent=2))
    if not verify.ok:
        print("systemd-analyze verify failed on the rendered units", file=sys.stderr)
        return EXIT_FAIL_CLOSED
    return EXIT_OK


# ---------------------------------------------------------------------------
# Apply / converge (idempotent; never starts recurring work)
# ---------------------------------------------------------------------------


def _install_argv(config: ProductionConfigV1, source: Path, target: Path) -> tuple[str, ...]:
    if config.scope == "user":
        return ("install", "-m", "0644", str(source), str(target))
    return (
        "sudo",
        "install",
        "-o",
        "root",
        "-g",
        "root",
        "-m",
        "0644",
        str(source),
        str(target),
    )


def cmd_apply(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    output_dir = config.systemd_output_dir
    desired_units = desired_unit_bytes(config)
    for name in desired_units:
        if not (output_dir / name).is_file():
            raise AcceptanceError(f"rendered unit missing: {output_dir / name}; run render first")
    # The rendered bytes must equal the desired bytes for this configuration.
    for name, desired in desired_units.items():
        rendered = (output_dir / name).read_bytes()
        if rendered != desired:
            raise AcceptanceError(
                f"rendered unit {name} does not match the current configuration; rerun render"
            )

    # R3 lifecycle drift gate: systemd reads EnvironmentFile= at service
    # start, so a file that drifted after render must block *here*, before
    # any install, daemon-reload, timer-enable or linger mutation.
    credential = current_credential_state(config)
    if credential is not None and not credential.ok:
        raise ManualBoundary(
            MANUAL_SECRET_REFERENCE_REQUIRED,
            stopped_after=(
                "apply: delivery is enabled and the current private credential "
                "file drifted out of the canonical contract since render "
                f"({credential.public_reason()}); zero install, daemon-reload, "
                "timer-enable or linger mutations were performed"
            ),
            human_action=(
                f"fix {config.delivery_environment_file} by hand back to the "
                "canonical form (one physical NAME=VALUE line per referenced "
                f"name ({', '.join(credential.referenced_names)}), non-empty, "
                "no quoting/escaping/continuation/whitespace and no "
                "systemd-invalid Unicode anywhere in the file), then rerun the "
                "resume command; never paste values into chat or Git"
            ),
            secret_boundary=(
                "values stay in the ignored private environment file and in "
                "process memory only"
            ),
            resume_command=_resume_command(args.production_config, "apply"),
            machine_verifiable_success=(
                f"`{_resume_command(args.production_config, 'verify')}` exits 0 "
                "with the credential.current-contract check green (the file "
                "revalidated as canonical, complete and systemd-Unicode-valid; "
                "values never printed)"
            ),
            remaining_unverified=(
                "notification delivery until the credential is canonical again"
            ),
        )

    destination = systemd_unit_destination_dir(config)
    if not _systemd_privilege_available(config, runner=runner):
        raise ManualBoundary(
            MANUAL_SUDO_INSTALL_REQUIRED,
            stopped_after=(
                f"rendered and verified units exist at {output_dir}; "
                "non-interactive installation privilege for scope=system is "
                "unavailable (this process is not root and `sudo -n true` fails)"
            ),
            human_action=(
                "run the exact install/enable commands from "
                f"{output_dir / 'render-plan.json'} field install_commands as the "
                "owner (four commands: two `sudo install`, `sudo systemctl "
                f"daemon-reload`, `sudo systemctl enable {config.timer_unit_name}`)"
            ),
            secret_boundary=(
                "none of the unit files or commands carries a credential; do not "
                "add environment files with secrets to the units"
            ),
            resume_command=_resume_command(args.production_config, "apply"),
            machine_verifiable_success=(
                f"`{_resume_command(args.production_config, 'verify')}` "
                "exits 0: installed file hashes equal "
                "the rendered hashes, `systemctl show` reports the timer "
                "UnitFileState=enabled, and the effective ExecStart equals the "
                "rendered command"
            ),
            remaining_unverified=(
                "systemd-scheduled unattended production execution at the "
                "configured cadence on the system bus"
            ),
        )

    actions: list[dict[str, object]] = []
    for name, desired in desired_units.items():
        source = output_dir / name
        target = destination / name
        current = target.read_bytes() if target.is_file() else None
        if current == desired:
            actions.append({"resource": f"unit-file:{name}", "action": "unchanged"})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        outcome = run_command(_install_argv(config, source, target), runner=runner)
        if not outcome.ok:
            print(json.dumps({"applied": False, "actions": actions}, indent=2))
            return EXIT_FAIL_CLOSED
        if not target.is_file() or target.read_bytes() != desired:
            raise AcceptanceError(
                f"install reported success but {target} is missing or diverged"
            )
        actions.append(
            {
                "resource": f"unit-file:{name}",
                "action": "modified" if current is not None else "installed",
            }
        )
    reload = run_command((*systemctl_prefix(config), "daemon-reload"), runner=runner)
    if not reload.ok:
        print(json.dumps({"applied": False, "actions": actions}, indent=2))
        return EXIT_FAIL_CLOSED
    actions.append({"resource": "daemon-reload", "action": "performed"})

    timer_state = _systemctl_show(
        config, config.timer_unit_name, ("UnitFileState",), runner
    ).get("UnitFileState", "")
    if timer_state != "enabled":
        # Enable only; activation (start) stays a separate explicit command.
        enable = run_command(
            (*systemctl_prefix(config), "enable", config.timer_unit_name), runner=runner
        )
        if not enable.ok:
            print(json.dumps({"applied": False, "actions": actions}, indent=2))
            return EXIT_FAIL_CLOSED
        actions.append({"resource": "timer-enable", "action": "enabled"})
    else:
        actions.append({"resource": "timer-enable", "action": "unchanged"})

    linger = ensure_linger(
        config, runner=runner, production_config_path=args.production_config
    )
    actions.append({"resource": "linger", "action": linger.get("action", "not-applicable")})

    effective = _effective_state(config, runner)
    converged = effective["units_match"] is True and effective["timer_enabled"] is True
    record = {
        "applied": bool(converged),
        "scope": config.scope,
        "destination": str(destination),
        "actions": actions,
        "linger": linger,
        "effective": effective,
        "applied_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(output_dir / "apply-record.json", canonical_json_bytes(record) + b"\n")
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return EXIT_OK if converged else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Effective-state inspection
# ---------------------------------------------------------------------------


def _dbus_unit_object_path(unit: str) -> str:
    """The manager D-Bus object path for a unit name.

    systemd's ``bus_path_encode`` escaping: ``[A-Za-z0-9_]`` stay literal,
    every other character becomes ``_`` plus its two-digit lowercase hex
    code (unit names here can only contribute ``.`` and ``-``).
    """

    escaped = "".join(
        ch if re.fullmatch(r"[A-Za-z0-9_]", ch) else f"_{ord(ch):02x}" for ch in unit
    )
    return f"/org/freedesktop/systemd1/unit/{escaped}"


def manager_service_exec_property(
    config: ProductionConfigV1, property_name: str, runner: CommandRunner
) -> list[list[object]]:
    """The manager-effective service Exec property rows via D-Bus.

    ``busctl --json=short get-property ... Service ExecStart/ExecStartPre``
    returns one row per command whose second element is the exact argv
    array the manager loaded (after load-time percent processing) — the
    structural representation the R4 verification compares element by
    element.  A failed query raises :class:`AcceptanceError` so callers
    fail closed instead of guessing.
    """

    argv = (
        "busctl",
        *(("--user",) if config.scope == "user" else ()),
        "--json=short",
        "get-property",
        "org.freedesktop.systemd1",
        _dbus_unit_object_path(config.service_unit_name),
        "org.freedesktop.systemd1.Service",
        property_name,
    )
    outcome = run_command(argv, runner=runner)
    if not outcome.ok:
        raise AcceptanceError(
            f"cannot query manager-effective {property_name} for "
            f"{config.service_unit_name}: {_bounded(outcome.stderr, 300)}"
        )
    try:
        payload = json.loads(outcome.stdout)
        data = payload["data"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AcceptanceError(
            f"manager-effective {property_name} payload is not readable: {exc}"
        ) from exc
    if not isinstance(data, list):
        raise AcceptanceError(f"manager-effective {property_name} payload is not a list")
    return data


def _effective_state(
    config: ProductionConfigV1, runner: CommandRunner = _default_runner
) -> dict[str, object]:
    destination = systemd_unit_destination_dir(config)
    desired_units = desired_unit_bytes(config)
    units: dict[str, object] = {}
    units_match = True
    for name, desired in desired_units.items():
        installed = destination / name
        if not installed.is_file():
            units[name] = {"installed": False, "sha256": None, "matches_desired": False}
            units_match = False
            continue
        content = installed.read_bytes()
        matches = content == desired
        units_match = units_match and matches
        units[name] = {
            "installed": True,
            "sha256": _sha256_bytes(content),
            "desired_sha256": _sha256_bytes(desired),
            "matches_desired": matches,
        }
    timer_props = _systemctl_show(
        config,
        config.timer_unit_name,
        (
            "ActiveState",
            "UnitFileState",
            "Persistent",
            "LastTriggerUSec",
            "NextElapseUSecRealtime",
        ),
        runner,
    )
    service_props = _systemctl_show(
        config,
        config.service_unit_name,
        (
            "ExecStart",
            "ExecStartPre",
            "WorkingDirectory",
            "User",
            "Result",
            "ExecMainStatus",
        ),
        runner,
    )
    # R4: the manager-effective Exec/EnvironmentFile structures come from
    # the D-Bus property (exact argv arrays), not from the lossy textual
    # "argv[]=" rendering that cannot represent spaces inside arguments.
    exec_structures: dict[str, object] = {}
    for property_name in ("ExecStart", "ExecStartPre", "EnvironmentFiles"):
        try:
            exec_structures[property_name] = manager_service_exec_property(
                config, property_name, runner
            )
        except AcceptanceError as exc:
            exec_structures[property_name] = {"error": str(exc)}
    return {
        "units": units,
        "units_match": units_match,
        "timer_properties": timer_props,
        "timer_enabled": timer_props.get("UnitFileState") == "enabled",
        "timer_active": timer_props.get("ActiveState") == "active",
        "service_properties": service_props,
        "service_exec_structures": exec_structures,
    }


def cmd_verify(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    checks = CheckLog()
    state = _effective_state(config, runner)
    for name, unit_state in state["units"].items():  # type: ignore[union-attr]
        checks.add(
            f"install.{name}",
            bool(unit_state.get("matches_desired")),  # type: ignore[union-attr]
            json.dumps(unit_state, ensure_ascii=False),
        )
    # R4: the ExecStart/ExecStartPre/EnvironmentFile contracts are proven
    # structurally — the manager-effective D-Bus argv arrays must equal the
    # intended argv element by element.  A textual substring such as the
    # expected command inside the lossy "argv[]=" rendering is not proof:
    # it cannot represent argument boundaries at all.
    exec_structures: dict[str, object] = state["service_exec_structures"]  # type: ignore[assignment]
    intended_main = list(main_exec_argv(config, config.runner_config_path.resolve()))

    def _exec_rows(property_name: str) -> list[list[object]]:
        raw = exec_structures.get(property_name)
        if not isinstance(raw, list):
            raise AcceptanceError(str(raw))
        return raw

    try:
        exec_start_rows = _exec_rows("ExecStart")
        manager_main = [row[1] for row in exec_start_rows]
        checks.add(
            "service.effective-execstart",
            manager_main == [intended_main],
            f"intended={intended_main} effective={manager_main}",
        )
    except (AcceptanceError, IndexError, TypeError) as exc:
        checks.add("service.effective-execstart", False, f"unreadable ExecStart: {exc}")
    # R3: a delivery-enabled deployment must carry the runtime credential
    # gate ahead of the notification ExecStart, and the *current* private
    # credential file must still satisfy the whole canonical contract —
    # green historical records cannot substitute for a live revalidation.
    credential = current_credential_state(config)
    if config.delivery_enabled:
        intended_gate = list(credential_gate_argv(config))
        try:
            exec_start_pre_rows = _exec_rows("ExecStartPre")
            manager_gate = [row[1] for row in exec_start_pre_rows]
            checks.add(
                "service.prestart-gate",
                manager_gate == [intended_gate],
                f"intended={intended_gate} effective={manager_gate}",
            )
        except (AcceptanceError, IndexError, TypeError) as exc:
            checks.add("service.prestart-gate", False, f"unreadable ExecStartPre: {exc}")
        try:
            env_rows = _exec_rows("EnvironmentFiles")
            manager_env_paths = [row[0] for row in env_rows]
            intended_env = [str(config.delivery_environment_file)]
            checks.add(
                "service.effective-environmentfile",
                manager_env_paths == intended_env,
                f"intended={intended_env} effective={manager_env_paths}",
            )
        except (AcceptanceError, IndexError, TypeError) as exc:
            checks.add(
                "service.effective-environmentfile",
                False,
                f"unreadable EnvironmentFiles: {exc}",
            )
    else:
        try:
            exec_start_pre_rows = _exec_rows("ExecStartPre")
            checks.add(
                "service.prestart-gate",
                exec_start_pre_rows == [],
                f"delivery-disabled unit must load zero pre-start commands: "
                f"{exec_start_pre_rows}",
            )
        except (AcceptanceError, IndexError, TypeError) as exc:
            checks.add("service.prestart-gate", False, f"unreadable ExecStartPre: {exc}")
    if credential is not None:
        checks.add(
            "credential.current-contract",
            credential.ok,
            credential.public_reason(),
        )
    working_directory = str(
        state["service_properties"].get("WorkingDirectory", "")  # type: ignore[union-attr]
    )
    checks.add(
        "service.effective-workingdirectory",
        working_directory == config.working_directory,
        working_directory,
    )
    timer_props: dict[str, str] = state["timer_properties"]  # type: ignore[assignment]
    checks.add(
        "timer.enabled", timer_props.get("UnitFileState") == "enabled", str(timer_props)
    )
    checks.add(
        "timer.persistent",
        timer_props.get("Persistent", "").lower() == "yes",
        f"Persistent={timer_props.get('Persistent', '')}",
    )
    if args.expect_active:
        checks.add(
            "timer.active", timer_props.get("ActiveState") == "active", str(timer_props)
        )
        checks.add(
            "timer.next-trigger",
            bool(timer_props.get("NextElapseUSecRealtime", "").strip()),
            f"NextElapseUSecRealtime={timer_props.get('NextElapseUSecRealtime', '')}",
        )
    if config.scope == "user":
        user = config.service_user or getpass_user()
        linger = linger_state(user, runner)
        checks.add("linger", linger == "yes", f"Linger={linger or 'unknown'} for {user}")

    status = run_command(
        (
            config.python_executable,
            "-m",
            "turtle_value_engine",
            "watch",
            "unattended-status",
            "--runner-root",
            config.runner_root,
            "--runner-id",
            config.runner_id,
        ),
        runner=runner,
        cwd=ROOT,
        timeout=60,
    )
    runner_state: dict[str, object] | None = None
    if status.ok:
        try:
            runner_state = json.loads(status.stdout)
        except json.JSONDecodeError:
            runner_state = None
    if isinstance(runner_state, dict):
        latest = None
        for item in runner_state.get("runners", []):  # type: ignore[union-attr]
            if item.get("runner_id") == config.runner_id and item.get("latest") is not None:
                latest = item["latest"]
        checks.add(
            "runner.latest-receipt",
            latest is not None,
            "none" if latest is None else f"activation_id={latest.get('activation_id')}",
        )
    else:
        checks.add("runner.latest-receipt", False, _bounded(status.stderr, 400))

    journal_argv = (
        (
            "journalctl",
            "--user",
            "-u",
            config.service_unit_name,
            "-n",
            "40",
            "--no-pager",
            "-o",
            "cat",
        )
        if config.scope == "user"
        else (
            "journalctl",
            "-u",
            config.service_unit_name,
            "-n",
            "40",
            "--no-pager",
            "-o",
            "cat",
        )
    )
    journal = run_command(journal_argv, runner=runner)
    redacted_journal = redact_text(
        _bounded(journal.stdout, 6000),
        _effective_secret_scan_map(effective_secret_values(config)),
    )
    checks.add("service.journal", journal.returncode in (0, 1), redacted_journal)

    payload = {
        "checks": checks.checks,
        "green": not checks.failed,
        "effective_state": state,
        "runner_state": runner_state,
        "journal_redacted": redacted_journal,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(
        config.systemd_output_dir / "verify-record.json", canonical_json_bytes(payload) + b"\n"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK if not checks.failed else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Explicit activation / safe deactivation
# ---------------------------------------------------------------------------


def _require_applied(config: ProductionConfigV1) -> dict[str, object]:
    path = config.systemd_output_dir / "apply-record.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"no readable apply record ({path}); run apply first: {exc}")
    if record.get("applied") is not True:
        raise AcceptanceError("apply record does not record a converged apply; run apply first")
    return record


def cmd_activate(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    _require_applied(config)
    # R3 lifecycle drift gate: revalidate the current credential contract
    # before any timer enable/start action is authorized.  Deactivation stays
    # credential-independent by design; activation does not.
    credential = current_credential_state(config)
    if credential is not None and not credential.ok:
        raise ManualBoundary(
            MANUAL_SECRET_REFERENCE_REQUIRED,
            stopped_after=(
                "activate: delivery is enabled and the current private "
                "credential file drifted out of the canonical contract "
                f"({credential.public_reason()}); zero timer-enable and zero "
                "timer-start actions were authorized"
            ),
            human_action=(
                f"fix {config.delivery_environment_file} by hand back to the "
                "canonical form (one physical NAME=VALUE line per referenced "
                f"name ({', '.join(credential.referenced_names)}), non-empty, "
                "no quoting/escaping/continuation/whitespace and no "
                "systemd-invalid Unicode anywhere in the file), then rerun the "
                "resume command; never paste values into chat or Git"
            ),
            secret_boundary=(
                "values stay in the ignored private environment file and in "
                "process memory only"
            ),
            resume_command=_resume_command(args.production_config, "activate"),
            machine_verifiable_success=(
                "the resumed activate exits 0, `systemctl show` reports the "
                "timer UnitFileState=enabled and ActiveState=active, and "
                "`"
                + _resume_command(args.production_config, "verify")
                + "` is green including credential.current-contract"
            ),
            remaining_unverified=(
                "scheduled notification delivery until the credential is "
                "canonical again"
            ),
        )
    state = _systemctl_show(
        config, config.timer_unit_name, ("ActiveState", "UnitFileState"), runner
    )
    enabled_by_activate = False
    if state.get("UnitFileState") != "enabled":
        # A prior deactivation leaves the unit disabled; activation converges
        # both the enable symlink and the running timer, never only one.
        enable = run_command(
            (*systemctl_prefix(config), "enable", config.timer_unit_name), runner=runner
        )
        if not enable.ok:
            print(
                json.dumps({"activated": False, "enable": _outcome_public(enable)}, indent=2)
            )
            return EXIT_FAIL_CLOSED
        enabled_by_activate = True
    started = False
    if state.get("ActiveState") != "active":
        start = run_command(
            (*systemctl_prefix(config), "start", config.timer_unit_name), runner=runner
        )
        if not start.ok:
            print(
                json.dumps({"activated": False, "start": _outcome_public(start)}, indent=2)
            )
            return EXIT_FAIL_CLOSED
        started = True
    props = _systemctl_show(
        config,
        config.timer_unit_name,
        ("ActiveState", "UnitFileState", "NextElapseUSecRealtime"),
        runner,
    )
    activated = (
        props.get("ActiveState") == "active"
        and props.get("UnitFileState") == "enabled"
        and bool(props.get("NextElapseUSecRealtime", "").strip())
    )
    record = {
        "activated": bool(activated),
        "started_by_activate": started,
        "enabled_by_activate": enabled_by_activate,
        "timer_properties": props,
        "activated_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(
        config.systemd_output_dir / "activation-record.json", canonical_json_bytes(record) + b"\n"
    )
    print(json.dumps(record, indent=2))
    return EXIT_OK if activated else EXIT_FAIL_CLOSED


def cmd_deactivate(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    if not _systemd_privilege_available(config, runner=runner):
        raise AcceptanceError("insufficient privilege to disable the production timer")
    props_before = _systemctl_show(
        config, config.timer_unit_name, ("ActiveState", "UnitFileState"), runner
    )
    disable = run_command(
        (*systemctl_prefix(config), "disable", "--now", config.timer_unit_name), runner=runner
    )
    props_after = _systemctl_show(
        config, config.timer_unit_name, ("ActiveState", "UnitFileState"), runner
    )
    record = {
        "deactivated": bool(
            disable.ok
            and props_after.get("ActiveState") != "active"
            and props_after.get("UnitFileState") == "disabled"
        ),
        "idempotent_rerun_ok": True,
        "before": props_before,
        "records": _outcome_public(disable),
        "after": props_after,
        "units_left_installed": not args.remove_units,
        "deactivated_at": datetime.now(UTC).isoformat(),
    }
    if args.remove_units:
        destination = systemd_unit_destination_dir(config)
        removals: list[str] = []
        for name in (config.service_unit_name, config.timer_unit_name):
            target = destination / name
            if target.is_file():
                target.unlink()
                removals.append(str(target))
        run_command((*systemctl_prefix(config), "daemon-reload"), runner=runner)
        record["removed_unit_files"] = removals
    _atomic_write(
        config.systemd_output_dir / "deactivation-record.json",
        canonical_json_bytes(record) + b"\n",
    )
    print(json.dumps(record, indent=2))
    return EXIT_OK if record["deactivated"] else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Bounded live production proof
# ---------------------------------------------------------------------------


def _unattended_latest(
    config: ProductionConfigV1, runner: CommandRunner
) -> dict[str, object] | None:
    outcome = run_command(
        (
            config.python_executable,
            "-m",
            "turtle_value_engine",
            "watch",
            "unattended-status",
            "--runner-root",
            config.runner_root,
            "--runner-id",
            config.runner_id,
        ),
        runner=runner,
        cwd=ROOT,
        timeout=60,
    )
    if not outcome.ok:
        return None
    try:
        payload = json.loads(outcome.stdout)
    except json.JSONDecodeError:
        return None
    for item in payload.get("runners", []):
        if item.get("runner_id") == config.runner_id:
            return item
    return None


def _latest_receipt(
    config: ProductionConfigV1, runner: CommandRunner
) -> dict[str, object] | None:
    """Latest durable receipt identity (pointer + persisted receipt content).

    The status pointer carries identity hashes only; the terminality
    classification and D1 status live in the immutable receipt file.
    """

    item = _unattended_latest(config, runner)
    if item is None or item.get("latest") is None:
        return None
    pointer = item["latest"]
    activation_id = pointer.get("activation_id")
    if not activation_id:
        return None
    receipt_path = Path(config.runner_root) / "receipts" / f"{activation_id}.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "activation_id": activation_id,
        "cycle_id": pointer.get("cycle_id"),
        "receipt_content_sha256": pointer.get("receipt_content_sha256"),
        "classification": receipt.get("classification"),
        "d1_status": receipt.get("d1_status"),
    }


def _reanalysis_names(config: ProductionConfigV1) -> list[str]:
    root = Path(config.reanalysis_job_root)
    if not root.is_dir():
        return []
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def _watch_state_identity(
    config: ProductionConfigV1, runner: CommandRunner
) -> dict[str, object] | None:
    """The committed monitoring-state identity (None while NOT_AVAILABLE)."""

    try:
        watchlist = WatchlistSpecV1.build(
            **json.loads(Path(config.watchlist_path).read_text(encoding="utf-8"))
        )
    except Exception:
        return None
    outcome = run_command(
        (
            config.python_executable,
            "-m",
            "turtle_value_engine",
            "watch",
            "status",
            "--workspace",
            config.monitoring_workspace_root,
            "--watchlist-id",
            watchlist.watchlist_id,
        ),
        runner=runner,
        cwd=ROOT,
        timeout=60,
    )
    if not outcome.ok:
        return None
    try:
        status = json.loads(outcome.stdout)
    except json.JSONDecodeError:
        return None
    if status.get("availability") != "AVAILABLE":
        return None
    return {
        "state_id": status.get("state_id"),
        "last_committed_run_id": status.get("last_committed_run_id"),
    }


def _service_wake(
    config: ProductionConfigV1, runner: CommandRunner, *, wait_seconds: float
) -> dict[str, object]:
    """One bounded immediate service firing through the real unit."""

    initial = _systemctl_show(
        config, config.service_unit_name, ("ExecMainStartTimestamp",), runner
    ).get("ExecMainStartTimestamp", "")
    start = run_command(
        (*systemctl_prefix(config), "start", config.service_unit_name), runner=runner
    )
    if not start.ok:
        return {"ok": False, "stage": "systemctl-start", "outcome": _outcome_public(start)}
    deadline = time.monotonic() + wait_seconds
    final_start = initial
    completed = False
    while time.monotonic() < deadline:
        props = _systemctl_show(
            config,
            config.service_unit_name,
            ("ExecMainStartTimestamp", "ActiveState", "Result", "ExecMainStatus"),
            runner,
        )
        if props.get("ExecMainStartTimestamp", "") != initial and initial != "":
            final_start = props.get("ExecMainStartTimestamp", "")
        if initial == "" and props.get("ExecMainStartTimestamp", ""):
            final_start = props.get("ExecMainStartTimestamp", "")
        if props.get("ActiveState") == "inactive" and props.get("Result", ""):
            completed = True
            result = props
            break
        time.sleep(0.5)
    else:
        result = _systemctl_show(
            config, config.service_unit_name, ("Result", "ExecMainStatus"), runner
        )
    journal_argv = (
        (
            "journalctl",
            "--user",
            "-u",
            config.service_unit_name,
            "-n",
            "20",
            "--no-pager",
            "-o",
            "cat",
        )
        if config.scope == "user"
        else ("journalctl", "-u", config.service_unit_name, "-n", "20", "--no-pager", "-o", "cat")
    )
    journal = redact_text(
        _bounded(run_command(journal_argv, runner=runner).stdout, 4000),
        _effective_secret_scan_map(effective_secret_values(config)),
    )
    return {
        "ok": bool(
            completed
            and final_start
            and result.get("Result") == "success"
            and result.get("ExecMainStatus") in {"0", "3"}
        ),
        "exec_main_start_timestamp": final_start,
        "service_result": dict(result),
        "journal_redacted": journal,
        "classification_seen": "COMPLETED_" in journal,
    }


def _acceptance_roots_immutability(
    before: Mapping[str, tuple[str, int]]
) -> dict[str, object]:
    roots = {
        "phase6e": Path(ROOT / ".tve-private" / "monitoring" / "phase6e"),
    }
    after = {
        name: content_tree_hash(path) if path.exists() else ("absent", 0)
        for name, path in roots.items()
    }
    unchanged = all(name in before and after[name] == before[name] for name in roots)
    return {
        "roots": {
            name: {"before": list(before.get(name, ())), "after": list(after[name])}
            for name in roots
        },
        "ok": unchanged,
        "unchanged": unchanged,
    }


def _d3_forbidden_strings(config: ProductionConfigV1) -> list[str]:
    """Strings that must never appear in a public D3 payload (paths/tokens)."""

    return [
        str(config.production_root),
        str(config.project_config_path),
        str(config.runner_config_path),
        "holder_token",
    ]


def _d3_readonly_section(
    config: ProductionConfigV1,
    runner: CommandRunner,
    *,
    monitored_tree_before: tuple[str, int],
    expected_activation_id: str | None = None,
) -> dict[str, object]:
    if config.snapshot_path is None or not Path(config.snapshot_path).is_file():
        return {
            "ok": False,
            "skipped": True,
            "reason": f"validated surface snapshot missing ({config.snapshot_path})",
        }
    import urllib.error
    import urllib.request

    server = subprocess.Popen(
        [
            config.python_executable,
            "-m",
            "turtle_value_engine",
            "surface",
            "serve",
            "--snapshot",
            str(Path(config.snapshot_path).resolve()),
            "--port",
            str(config.surface_port),
            "--monitoring-runner-config",
            str(config.runner_config_path.resolve()),
            "--monitoring-project-config",
            str(config.project_config_path.resolve()),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
    )

    def request(method: str, data: bytes | None = None) -> tuple[int, bytes]:
        url = f"http://127.0.0.1:{config.surface_port}/v1/monitoring/operations"
        req = urllib.request.Request(url, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    try:
        deadline = time.monotonic() + 30
        ready = False
        import socket as socket_module

        while time.monotonic() < deadline:
            try:
                with socket_module.create_connection(
                    ("127.0.0.1", config.surface_port), timeout=1
                ):
                    ready = True
                    break
            except OSError:
                time.sleep(0.2)
        if not ready:
            return {"ok": False, "reason": "surface server did not listen"}
        status_code, body = request("GET")
        for _ in range(3):
            request("GET")
        mutations = {
            method: request(method, b"{}")[0]
            for method in ("POST", "PUT", "PATCH", "DELETE")
        }
        monitored_tree_after = content_tree_hash(_monitored_root(config))
        effective = effective_secret_values(config)
        payload_text = body.decode("utf-8", errors="replace")
        secret_hits = scan_bytes_for_secrets(
            body, _effective_secret_scan_map(effective)
        )
        path_leaks = [
            item for item in _d3_forbidden_strings(config) if item and item in payload_text
        ]
        projected_activation = None
        activation_matches = True
        if status_code == 200:
            try:
                projected = json.loads(body)
                activation = projected.get("activation") or {}
                projected_activation = activation.get("activation_id")
                activation_matches = (
                    expected_activation_id is None
                    or projected_activation == expected_activation_id
                )
            except json.JSONDecodeError:
                activation_matches = False
        ok = (
            status_code == 200
            and all(code == 405 for code in mutations.values())
            and monitored_tree_after == monitored_tree_before
            and not secret_hits
            and not path_leaks
            and activation_matches
        )
        return {
            "ok": bool(ok),
            "http_status": status_code,
            "mutation_methods": mutations,
            "mutations_rejected": all(code == 405 for code in mutations.values()),
            "monitored_tree_unchanged": monitored_tree_after == monitored_tree_before,
            "activation_matches_latest_receipt": bool(activation_matches),
            "projected_activation_id": projected_activation,
            "secret_scan_hits": secret_hits,
            "path_leaks": path_leaks,
        }
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)


def _monitored_root(config: ProductionConfigV1) -> Path:
    """One parent covering every production runtime root (for tree hashing)."""

    roots = [
        Path(config.monitoring_workspace_root),
        Path(config.reanalysis_job_root),
        Path(config.cycle_store_root),
        Path(config.runner_root),
        Path(config.cache_dir),
        Path(config.delivery_root),
    ]
    common = roots[0]
    for path in roots[1:]:
        common = Path(os.path.commonpath((str(common), str(path))))
    return common


def _delivery_section(
    config: ProductionConfigV1,
    runner: CommandRunner,
    activation_id: str,
    *,
    production_config_path: str | Path,
) -> dict[str, object]:
    """Optional production delivery proof (enabled configurations only)."""

    credential = current_credential_state(config)
    if credential is None or not credential.ok:
        needed = (
            list(credential.referenced_names) if credential is not None else []
        ) or _production_secret_reference_names(config)
        detail = credential.public_reason() if credential is not None else "unknown"
        marker = ManualBoundary(
            MANUAL_SECRET_REFERENCE_REQUIRED,
            stopped_after=(
                "live-proof delivery step: delivery is enabled but the typed "
                "environment file does not satisfy the private canonical "
                f"credential source contract ({detail})"
            ),
            human_action=(
                f"fix {config.delivery_environment_file} by hand: each referenced "
                f"value ({', '.join(needed)}) on one physical NAME=VALUE line, "
                "non-empty, without quoting/escaping/continuation/whitespace and "
                "without systemd-invalid Unicode anywhere in the file; "
                "never paste values into chat or Git"
            ),
            secret_boundary=(
                "values stay in the ignored private environment file and in "
                "process memory only"
            ),
            resume_command=_resume_command(production_config_path, "live-proof"),
            machine_verifiable_success=(
                "`tve watch deliver ... --network allow` returns DELIVERED (or NOOP "
                "with no alert outbox), delivery-status reports pointer CURRENT, and "
                "repeating the identity authorizes zero additional dispatch slots"
            ),
            remaining_unverified=(
                "production notification delivery to the owner destination and its "
                "durable accounting"
            ),
        )
        return {"ok": False, "skipped": True, "marker_payload": marker.payload}

    def deliver() -> tuple[CommandOutcome, dict[str, object] | None]:
        outcome = run_command(
            (
                config.python_executable,
                "-m",
                "turtle_value_engine",
                "watch",
                "deliver",
                "--runner-config",
                str(config.runner_config_path),
                "--project-config",
                str(config.project_config_path),
                "--activation-id",
                activation_id,
                "--network",
                "allow",
            ),
            runner=runner,
            cwd=ROOT,
            timeout=180,
        )
        try:
            payload = json.loads(outcome.stdout) if outcome.stdout.strip() else None
        except json.JSONDecodeError:
            payload = None
        return outcome, payload

    first_outcome, first = deliver()
    if first_outcome.returncode != 0 or first is None or first.get("classification") not in {
        "DELIVERED",
        "NOOP",
    }:
        return {"ok": False, "first": _outcome_public(first_outcome), "payload": first}
    if first.get("classification") == "NOOP":
        return {
            "ok": True,
            "classification": "NOOP",
            "note": "terminal activation carries no alert outbox; zero requests",
        }
    delivery_id = str(first.get("delivery_id"))
    second_outcome, second = deliver()
    duplicate_free = (
        second is not None
        and second.get("reused") is True
        and second.get("http_requests") == 0
    )
    return {
        "ok": bool(duplicate_free),
        "delivery_id": delivery_id,
        "first_classification": first.get("classification"),
        "repeat": {
            "reused": None if second is None else second.get("reused"),
            "http_requests": None if second is None else second.get("http_requests"),
        },
    }


def cmd_live_proof(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    _require_applied(config)
    activation_record_path = config.systemd_output_dir / "activation-record.json"
    if not activation_record_path.is_file():
        raise AcceptanceError("timer was never activated; run activate first")
    report: dict[str, object] = {"contract": REPORT_CONTRACT + ".live-proof"}

    # Acceptance/production separation: the Phase 6-E tree must not change.
    phase6e_root = ROOT / ".tve-private" / "monitoring" / "phase6e"
    acceptance_before = {
        "phase6e": content_tree_hash(phase6e_root) if phase6e_root.exists() else ("absent", 0)
    }

    monitored_before = content_tree_hash(_monitored_root(config))
    activations_before = _count_activation_files(config)

    # Production wakes resolve a fresh PIT per invocation, so every wake is
    # legitimately one new durable activation; "no duplicate work" is proven
    # on the D1/cursor level, not by freezing one activation id.
    wake = _service_wake(config, runner, wait_seconds=args.wake_wait_seconds)
    report["bounded_firing"] = wake
    first_exactly_one = _count_activation_files(config) == activations_before + 1
    report["first_firing_effects"] = {
        "activation_files_before": activations_before,
        "activation_files_after": _count_activation_files(config),
        "exactly_one_new_activation": first_exactly_one,
        "monitored_tree_changed_by_firing": content_tree_hash(_monitored_root(config))
        != monitored_before,
    }
    receipt_first = _latest_receipt(config, runner)
    receipt_ok = (
        receipt_first is not None
        and receipt_first.get("classification") == "CYCLE_TERMINAL"
        and bool(receipt_first.get("activation_id"))
        and bool(receipt_first.get("cycle_id"))
    )
    receipt_identity: dict[str, object] = receipt_first or {}
    report["runner_receipt"] = {"ok": bool(receipt_ok), **receipt_identity}

    runner_config_sha = _sha256_bytes(config.runner_config_path.read_bytes())
    desired_runner_sha = _sha256_bytes(desired_runner_config_bytes(config))
    report["configuration_identity"] = {
        "ok": runner_config_sha == desired_runner_sha,
        "runner_config_sha256": runner_config_sha,
        "desired_runner_config_sha256": desired_runner_sha,
    }

    activations_after_first = _count_activation_files(config)
    reanalysis_after_first = _reanalysis_names(config)
    state_after_first = _watch_state_identity(config, runner)

    replay = _service_wake(config, runner, wait_seconds=args.wake_wait_seconds)
    receipt_after_replay = _latest_receipt(config, runner)
    replay_terminal = (
        receipt_after_replay is not None
        and receipt_after_replay.get("classification") == "CYCLE_TERMINAL"
        and receipt_after_replay.get("activation_id") != receipt_identity.get("activation_id")
    )
    # A repeated wake must manufacture no duplicate D1 work: exactly one new
    # activation (this wake), a NO_CHANGE D1 cycle, an unchanged re-analysis
    # set and a byte-stable committed watch state.
    no_duplicate_work = (
        replay_terminal
        and receipt_after_replay is not None
        and receipt_after_replay.get("d1_status") == "NO_CHANGE"
        and _reanalysis_names(config) == reanalysis_after_first
        and _watch_state_identity(config, runner) == state_after_first
        and _count_activation_files(config) == activations_after_first + 1
    )
    report["replay"] = {
        "ok": bool(replay.get("ok") and no_duplicate_work),
        "receipt_after_replay": receipt_after_replay,
        "exactly_one_new_activation": _count_activation_files(config)
        == activations_after_first + 1,
        "d1_status_no_change": None
        if receipt_after_replay is None
        else receipt_after_replay.get("d1_status") == "NO_CHANGE",
        "reanalysis_unchanged": _reanalysis_names(config) == reanalysis_after_first,
        "committed_state_stable": _watch_state_identity(config, runner) == state_after_first,
        "committed_state": state_after_first,
        "monitored_tree_sha256_after_replay": content_tree_hash(_monitored_root(config))[0],
    }

    d3 = _d3_readonly_section(
        config,
        runner,
        monitored_tree_before=content_tree_hash(_monitored_root(config)),
        expected_activation_id=None
        if receipt_after_replay is None
        else str(receipt_after_replay.get("activation_id")),
    )
    report["d3_readonly"] = d3

    # The lock probe mutates its own probe slot under the runner root, so it
    # runs after the D3 immutability window, never inside it.
    lock = probe_lock_visibility(config, Path(config.runner_root), runner=runner)
    report["lock_visibility"] = {"ok": lock.get("proven") is True, "proven": lock.get("proven")}

    if config.delivery_enabled:
        assert receipt_identity.get("activation_id") is not None
        report["delivery"] = _delivery_section(
            config,
            runner,
            str(receipt_identity["activation_id"]),
            production_config_path=args.production_config,
        )
    else:
        report["delivery"] = {
            "ok": True,
            "enabled": False,
            "note": "monitoring-only production deployment (notification disabled)",
        }

    immutability = _acceptance_roots_immutability(acceptance_before)
    report["acceptance_roots_unchanged"] = immutability

    effective = effective_secret_values(config)
    secrets = _effective_secret_scan_map(effective)
    scanned: list[str] = []
    hits: list[str] = []
    for path in sorted(Path(config.production_root).rglob("*")):
        if path.is_file() and path.suffix in {".json", ".toml", ".py", ".service", ".timer"}:
            scanned.append(str(path))
            found = scan_bytes_for_secrets(path.read_bytes(), secrets)
            hits.extend(f"{path.name}:{name}" for name in found)
    report["secret_scan"] = {
        "scanned_files": scanned,
        "secret_references_checked": sorted(effective),
        "hits": hits,
    }

    failures = [
        name
        for name, section in report.items()
        if isinstance(section, Mapping) and section.get("ok") is False
    ]
    report["failures"] = failures
    report["proved_at"] = datetime.now(UTC).isoformat()
    serialized = canonical_json_bytes(report)
    if scan_bytes_for_secrets(serialized, secrets):
        raise AcceptanceError("live-proof report would contain secret values; refusing")
    _atomic_write(config.systemd_output_dir / "live-proof-record.json", serialized + b"\n")
    print(
        json.dumps(
            {
                "failures": failures,
                "record": str(config.systemd_output_dir / "live-proof-record.json"),
            },
            indent=2,
        )
    )
    return EXIT_OK if not failures else EXIT_FAIL_CLOSED


def _count_activation_files(config: ProductionConfigV1) -> int:
    activations = Path(config.runner_root) / "activations"
    return len(list(activations.glob("*.json"))) if activations.is_dir() else 0


def _cycle_store_names(config: ProductionConfigV1) -> list[str]:
    root = Path(config.cycle_store_root)
    if not root.is_dir():
        return []
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


# ---------------------------------------------------------------------------
# Restart / recovery proof
# ---------------------------------------------------------------------------


def _credential_resolution_probe(
    config: ProductionConfigV1, runner: CommandRunner
) -> dict[str, object]:
    """Service-context credential proof after a manager refresh (R3 goal 8).

    Runs the *actual* rendered pre-start gate command inside one bounded
    transient service context carrying the same ``EnvironmentFile=`` the
    production unit declares.  The gate re-reads the current private file
    and compares the manager-injected referenced values with the canonical
    parser's in-memory values byte-for-byte, so this proves equality — not
    only non-empty presence — while emitting no value.  This probe is extra
    evidence; the standing runtime guard is the rendered ``ExecStartPre=``
    gate on every delivery service start.
    """

    assert config.delivery_environment_file is not None
    probe = run_command(
        (
            "systemd-run",
            *(("--user",) if config.scope == "user" else ()),
            "--wait",
            "--pipe",
            "--collect",
            "-p",
            f"EnvironmentFile={config.delivery_environment_file}",
            *credential_gate_argv(config),
        ),
        runner=runner,
        timeout=180,
    )
    return {
        "ok": bool(probe.ok and CREDENTIAL_GATE_OK in probe.stdout),
        "stdout_tail": _bounded(probe.stdout, 200),
        "returncode": probe.returncode,
    }


def cmd_recover_proof(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    _require_applied(config)
    report: dict[str, object] = {"contract": REPORT_CONTRACT + ".recover-proof"}

    identity_before = {
        "runner_config_sha256": _sha256_bytes(config.runner_config_path.read_bytes()),
        "service_unit_sha256": _sha256_bytes(
            (systemd_unit_destination_dir(config) / config.service_unit_name).read_bytes()
        ),
        "timer_unit_sha256": _sha256_bytes(
            (systemd_unit_destination_dir(config) / config.timer_unit_name).read_bytes()
        ),
    }
    activations_before = _count_activation_files(config)
    cycle_names_before = _cycle_store_names(config)
    reanalysis_before = _reanalysis_names(config)

    # Strongest safe manager refresh: daemon-reload then daemon-reexec.
    reload = run_command((*systemctl_prefix(config), "daemon-reload"), runner=runner)
    reexec = run_command((*systemctl_prefix(config), "daemon-reexec"), runner=runner)
    report["manager_refresh"] = {
        "daemon-reload": _outcome_public(reload),
        "daemon-reexec": _outcome_public(reexec),
        "ok": reload.ok and reexec.ok,
    }

    stop = run_command((*systemctl_prefix(config), "stop", config.timer_unit_name), runner=runner)
    stopped_state = _systemctl_show(
        config, config.timer_unit_name, ("ActiveState",), runner
    )
    start = run_command((*systemctl_prefix(config), "start", config.timer_unit_name), runner=runner)
    final_timer = _systemctl_show(
        config,
        config.timer_unit_name,
        ("ActiveState", "UnitFileState", "NextElapseUSecRealtime"),
        runner,
    )
    report["timer_stop_start"] = {
        "stop": _outcome_public(stop),
        "stopped_state": stopped_state,
        "start": _outcome_public(start),
        "final_properties": final_timer,
        "ok": bool(
            stop.ok
            and stopped_state.get("ActiveState") == "inactive"
            and start.ok
            and final_timer.get("ActiveState") == "active"
            and final_timer.get("UnitFileState") == "enabled"
        ),
    }

    wake = _service_wake(config, runner, wait_seconds=args.wake_wait_seconds)
    receipt_after = _latest_receipt(config, runner)
    resumed_terminal = (
        receipt_after is not None
        and receipt_after.get("classification") == "CYCLE_TERMINAL"
        and bool(receipt_after.get("activation_id"))
    )
    # One wake must manufacture exactly one new durable activation and no
    # duplicate re-analysis work; the manager refresh must not resurrect or
    # replay anything on its own.
    exactly_one_new = _count_activation_files(config) == activations_before + 1
    reanalysis_stable = _reanalysis_names(config) == reanalysis_before
    report["durable_resume"] = {
        "wake": {key: wake.get(key) for key in ("ok", "service_result")},
        "receipt_after_recovery": receipt_after,
        "ok": bool(wake.get("ok") and resumed_terminal and exactly_one_new and reanalysis_stable),
        "exactly_one_new_activation": exactly_one_new,
        "reanalysis_unchanged": reanalysis_stable,
        "cycle_store_names_delta": len(_cycle_store_names(config)) - len(cycle_names_before),
        "monitored_tree_sha256_after": content_tree_hash(_monitored_root(config))[0],
    }

    identity_after = {
        "runner_config_sha256": _sha256_bytes(config.runner_config_path.read_bytes()),
        "service_unit_sha256": _sha256_bytes(
            (systemd_unit_destination_dir(config) / config.service_unit_name).read_bytes()
        ),
        "timer_unit_sha256": _sha256_bytes(
            (systemd_unit_destination_dir(config) / config.timer_unit_name).read_bytes()
        ),
    }
    report["configuration_identity_unchanged"] = identity_before == identity_after
    report["configuration_identity"] = identity_after

    if config.scope == "user":
        user = config.service_user or getpass_user()
        report["linger_after_recovery"] = linger_state(user, runner)

    if config.delivery_enabled:
        report["credential_resolution_after_restart"] = _credential_resolution_probe(
            config, runner
        )
    else:
        report["credential_resolution_after_restart"] = {
            "ok": True,
            "enabled": False,
            "note": "notification disabled; no credential to resolve",
        }

    failures = [
        name
        for name, section in report.items()
        if isinstance(section, Mapping) and section.get("ok") is False
    ]
    if report.get("configuration_identity_unchanged") is not True:
        failures.append("configuration_identity")
    report["failures"] = failures
    report["proved_at"] = datetime.now(UTC).isoformat()
    serialized = canonical_json_bytes(report)
    if scan_bytes_for_secrets(
        serialized, _effective_secret_scan_map(effective_secret_values(config))
    ):
        raise AcceptanceError("recover-proof report would contain secret values; refusing")
    _atomic_write(config.systemd_output_dir / "recover-proof-record.json", serialized + b"\n")
    print(
        json.dumps(
            {
                "failures": failures,
                "record": str(config.systemd_output_dir / "recover-proof-record.json"),
            },
            indent=2,
        )
    )
    return EXIT_OK if not failures else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# Secret-free production operations report
# ---------------------------------------------------------------------------


def cmd_report(args: argparse.Namespace, runner: CommandRunner = _default_runner) -> int:
    config = load_production_config(args.production_config)
    head_sha = acceptance._git_head(ROOT, runner)
    topology = classify_host_topology(runner)
    effective_secrets = effective_secret_values(config)
    secrets = _effective_secret_scan_map(effective_secrets)

    def _load_record(name: str) -> dict[str, object] | None:
        path = config.systemd_output_dir / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    gate_summary: dict[str, object] | None = None
    if config.require_repo_gate:
        try:
            artifact = load_gate_artifact(config, head_sha=head_sha)
            gate_summary = {"head_sha": artifact["head_sha"], "green": artifact["green"]}
        except AcceptanceError as exc:
            gate_summary = {"green": False, "error": str(exc)}

    effective = _effective_state(config, runner)
    linger_facts: dict[str, object] | None = None
    if config.scope == "user":
        user = config.service_user or getpass_user()
        linger_facts = {"user": user, "linger": linger_state(user, runner)}

    # R3: the current credential contract is revalidated live, value-free.
    # Historical green apply/activation/verify records cannot substitute for
    # it, and an invalid current credential must keep the report away from
    # PRODUCTION_DEPLOYED even when every record is green.
    credential = current_credential_state(config)
    credential_summary: dict[str, object] = (
        credential.public_summary()
        if credential is not None
        else {
            "enabled": False,
            "ok": True,
            "note": "notification disabled (monitoring-only production)",
        }
    )

    markers: list[dict[str, object]] = []
    if topology["wsl2"] and not topology["windows_host_bootstrap_proven"]:
        markers.append(
            windows_bootstrap_marker_payload(config, args.production_config)
        )

    report = {
        "contract": REPORT_CONTRACT,
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "implementation": {
            "head_sha": head_sha,
            "working_tree_clean": acceptance._git_clean(ROOT, runner),
            "gate": gate_summary,
        },
        "host": topology,
        "deployment": {
            "scope": config.scope,
            "service_identity": config.service_identity,
            "unit_base_name": config.unit_base_name,
            "on_calendar": config.on_calendar,
            "randomized_delay_sec": config.randomized_delay_sec,
            "network_policy": "explicit-opt-in" if config.network_allowed else "offline-replay",
            "window_days": config.window_days,
        },
        "configuration": {
            "runner_id": config.runner_id,
            "watchlist_path": config.watchlist_path,
            "runner_config_sha256": _sha256_bytes(config.runner_config_path.read_bytes())
            if config.runner_config_path.is_file()
            else None,
            "desired_runner_config_sha256": _sha256_bytes(desired_runner_config_bytes(config)),
            "delivery_enabled": config.delivery_enabled,
            "delivery_transport": config.delivery_transport if config.delivery_enabled else None,
        },
        "desired_effective_units": effective,
        "linger": linger_facts,
        "credential": credential_summary,
        "records": {
            "apply": _load_record("apply-record.json"),
            "activation": _load_record("activation-record.json"),
            "verify": _load_record("verify-record.json"),
            "live_proof": _load_record("live-proof-record.json"),
            "recover_proof": _load_record("recover-proof-record.json"),
            "deactivation": _load_record("deactivation-record.json"),
        },
        "markers": markers,
    }

    failures: list[str] = []
    if gate_summary is not None and gate_summary.get("green") is not True:
        failures.append("gate")
    for record_name in ("apply", "activation", "verify", "live_proof", "recover_proof"):
        record = report["records"][record_name]  # type: ignore[index]
        if not isinstance(record, Mapping):
            failures.append(f"missing-record:{record_name}")
        elif record_name == "apply" and record.get("applied") is not True:
            failures.append("apply")
        elif record_name == "activation" and record.get("activated") is not True:
            failures.append("activation")
        elif record_name == "verify" and record.get("green") is not True:
            failures.append("verify")
        elif isinstance(record, Mapping) and record.get("failures"):
            failures.append(record_name)
    if effective.get("units_match") is not True:
        failures.append("effective-units")
    if effective.get("timer_enabled") is not True:
        failures.append("timer-enabled")
    if linger_facts is not None and linger_facts.get("linger") != "yes":
        failures.append("linger")
    if credential is not None and not credential.ok:
        failures.append("current-credential")

    # Final secret scan across every persisted production artifact.
    scanned: list[str] = []
    hits: list[str] = []
    for path in sorted(Path(config.production_root).rglob("*")):
        if path.is_file() and path.suffix in {".json", ".toml", ".service", ".timer"}:
            scanned.append(str(path))
            found = scan_bytes_for_secrets(path.read_bytes(), secrets)
            hits.extend(f"{path.name}:{name}" for name in found)
    report["secret_scan"] = {
        "scanned_files": scanned,
        "secret_references_checked": sorted(effective_secrets),
        "hits": hits,
    }
    if hits:
        failures.append("secret-scan")

    marker_names = [item.get("marker") for item in markers]
    blocking_markers = [name for name in marker_names if name != WINDOWS_HOST_BOOTSTRAP_UNPROVEN]
    report["failures"] = sorted(set(failures))
    report["phase_state"] = (
        "PRODUCTION_DEPLOYED"
        if not failures and not blocking_markers
        else "READY_FOR_OWNER_AUTHORIZED_PHASE_6F"
    )
    # WINDOWS_HOST_BOOTSTRAP_UNPROVEN narrows the persistence claim but does
    # not block production closure on a WSL host (goal section 11).

    serialized = canonical_json_bytes(report)
    if scan_bytes_for_secrets(serialized, secrets):
        raise AcceptanceError("production report would contain secret values; refusing")
    _atomic_write(config.report_path, serialized + b"\n")
    print(
        json.dumps(
            {
                "phase_state": report["phase_state"],
                "failures": report["failures"],
                "markers": marker_names,
                "report": str(config.report_path),
            },
            indent=2,
        )
    )
    return EXIT_OK if not failures and not blocking_markers else EXIT_FAIL_CLOSED


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monitoring_production_ops.py",
        description="Phase 6-F persistent owner production-operations harness",
    )
    parser.add_argument(
        "--production-config", required=True, type=Path, help="non-secret production config JSON"
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    gate = subparsers.add_parser("gate", help="run the mandatory deterministic repository gate")
    gate.add_argument("--python", default=sys.executable)
    gate.add_argument("--fail-fast", action="store_true")
    gate.add_argument("--timeout", type=float, default=1800)

    preflight = subparsers.add_parser("preflight", help="non-mutating classification/checks")
    preflight.add_argument("--skip-gate", action="store_true")
    preflight.add_argument("--require-clean-tree", action="store_true")

    subparsers.add_parser("plan", help="deterministic mutation-free convergence plan")
    subparsers.add_parser("render", help="render production units/config (private root only)")
    subparsers.add_parser("apply", help="install/enable/converge (never starts)")
    subparsers.add_parser("converge", help="alias of apply")
    subparsers.add_parser("activate", help="explicit production activation (start the timer)")
    verify = subparsers.add_parser("verify", help="verify the effective installed state")
    verify.add_argument("--expect-active", action="store_true")
    live_proof = subparsers.add_parser(
        "live-proof", help="bounded production firing/replay/D3 proof"
    )
    live_proof.add_argument("--wake-wait-seconds", type=float, default=120)
    recover = subparsers.add_parser(
        "recover-proof", help="manager refresh + durable resume proof"
    )
    recover.add_argument("--wake-wait-seconds", type=float, default=120)
    deactivate = subparsers.add_parser("deactivate", help="stop+disable the production timer")
    deactivate.add_argument(
        "--remove-units", action="store_true", help="also uninstall the unit files"
    )
    subparsers.add_parser("report", help="assemble/validate the production operations report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers: dict[str, Callable[[argparse.Namespace], int]] = {
        "gate": cmd_gate,
        "preflight": cmd_preflight,
        "plan": cmd_plan,
        "render": cmd_render,
        "apply": cmd_apply,
        "converge": cmd_apply,
        "activate": cmd_activate,
        "verify": cmd_verify,
        "live-proof": cmd_live_proof,
        "recover-proof": cmd_recover_proof,
        "deactivate": cmd_deactivate,
        "report": cmd_report,
    }
    try:
        return handlers[args.mode](args)
    except ManualBoundary as exc:
        print(json.dumps(exc.payload, indent=2))
        return EXIT_MARKER
    except AcceptanceError as exc:
        print(f"monitoring_production_ops: {exc}", file=sys.stderr)
        return EXIT_FAIL_CLOSED


if __name__ == "__main__":
    raise SystemExit(main())
