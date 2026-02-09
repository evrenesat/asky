"""Shared URL sanitization and normalization helpers."""

from __future__ import annotations

import re
from typing import FrozenSet, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REPEATED_SLASHES_PATTERN = re.compile(r"/{2,}")
WINDOWS_DRIVE_INDICATOR_INDEX = 1
LOCAL_URL_SCHEMES: FrozenSet[str] = frozenset({"local", "file"})
HTTP_URL_SCHEMES: FrozenSet[str] = frozenset({"http", "https"})
DEFAULT_TRACKING_QUERY_KEYS: FrozenSet[str] = frozenset(
    {
        "gclid",
        "fbclid",
        "yclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "igshid",
        "intcmp",
        "abcmp",
        "componenteventparams",
        "acquisitiondata",
        "reftype",
    }
)


def sanitize_url(url: str) -> str:
    """Remove shell-escaping artifacts and surrounding whitespace."""
    if not url:
        return ""
    return str(url).replace("\\", "").strip()


def is_http_url(url: str) -> bool:
    """Return True when a target is a valid HTTP(S) URL."""
    sanitized = sanitize_url(url)
    if not sanitized:
        return False
    parsed = urlsplit(sanitized)
    return parsed.scheme.lower() in HTTP_URL_SCHEMES and bool(parsed.netloc)


def is_local_filesystem_target(target: str) -> bool:
    """Return True when input appears to reference local filesystem content."""
    sanitized = sanitize_url(target)
    if not sanitized:
        return False

    parsed = urlsplit(sanitized)
    if parsed.scheme.lower() in LOCAL_URL_SCHEMES:
        return True

    if sanitized.startswith(("/", "~/", "./", "../")):
        return True

    return (
        len(sanitized) > WINDOWS_DRIVE_INDICATOR_INDEX
        and sanitized[WINDOWS_DRIVE_INDICATOR_INDEX] == ":"
    )


def normalize_url(
    url: str,
    *,
    tracking_query_keys: Optional[set[str] | FrozenSet[str]] = None,
) -> str:
    """Normalize URL for deduplication and canonical matching."""
    sanitized = sanitize_url(url)
    if not sanitized:
        return ""

    parsed = urlsplit(sanitized)
    if not parsed.scheme or not parsed.netloc:
        return ""

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return ""

    port = parsed.port
    include_port = port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    )
    netloc = f"{hostname}:{port}" if include_port else hostname

    normalized_path = REPEATED_SLASHES_PATTERN.sub("/", parsed.path or "/")
    if normalized_path != "/" and normalized_path.endswith("/"):
        normalized_path = normalized_path.rstrip("/")

    filtered_pairs = []
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    blocked_keys = tracking_query_keys or DEFAULT_TRACKING_QUERY_KEYS
    for key, value in query_pairs:
        lowered = key.lower()
        if lowered.startswith("utm_"):
            continue
        if lowered in blocked_keys:
            continue
        filtered_pairs.append((key, value))

    filtered_pairs.sort(key=lambda pair: pair[0])
    normalized_query = urlencode(filtered_pairs, doseq=True)
    return urlunsplit((scheme, netloc, normalized_path, normalized_query, ""))
