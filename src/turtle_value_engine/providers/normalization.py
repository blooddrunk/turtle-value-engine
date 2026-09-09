"""Provider-neutral helpers for stable normalized-record identities."""

import re
from hashlib import sha256

from .models import JSONValue, canonical_json_bytes


def deterministic_id(namespace: str, *components: JSONValue) -> str:
    """Create a stable opaque ID from canonical JSON components.

    IDs should be based on semantic identity (for example entity, field,
    period and source request identity), not on a retrieval timestamp or the
    order in which a provider returned rows.
    """

    if not re.fullmatch(r"[a-z][a-z0-9_-]*", namespace):
        raise ValueError("namespace must contain lowercase letters, digits, '_' or '-'")
    digest = sha256(
        canonical_json_bytes({"namespace": namespace, "components": list(components)})
    ).hexdigest()[:24]
    return f"{namespace}-{digest}"
