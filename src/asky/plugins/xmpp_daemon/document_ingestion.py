"""Document URL ingestion for XMPP session-scoped research corpus loading."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import requests
import tomlkit

import asky.config as asky_config
from asky.cli.local_ingestion_flow import preload_local_research_sources
from asky.config.loader import _get_config_dir
from asky.research.adapters import LOCAL_SUPPORTED_EXTENSIONS
from asky.storage import (
    get_session_by_id,
    get_uploaded_document_by_hash,
    get_uploaded_document_by_url,
    link_session_uploaded_document,
    list_session_uploaded_documents,
    save_uploaded_document_url,
    update_session_research_profile,
    upsert_uploaded_document,
)

DOCUMENT_DOWNLOAD_TIMEOUT_SECONDS = 30
DOCUMENT_MAX_FILES_PER_MESSAGE = 10
DOCUMENT_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
DEFAULT_BOOTSTRAP_ROOT = Path("~/.config/asky/research-corpus").expanduser()
UPLOADS_DIRNAME = "uploads"
URL_FILENAME_QUERY_KEYS = ("filename", "file", "name")
SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    extension.lower() for extension in LOCAL_SUPPORTED_EXTENSIONS
)
TEXT_LIKE_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".html",
        ".htm",
        ".json",
        ".csv",
    }
)
STRICT_MIME_BY_EXTENSION = {
    ".pdf": frozenset({"application/pdf"}),
    ".epub": frozenset({"application/epub+zip"}),
}
GENERIC_MIME_TYPES = frozenset(
    {"", "application/octet-stream", "binary/octet-stream"}
)
SLUG_STRIP_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")
URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")


def _normalize_document_url(url: str) -> str:
    return str(url or "").strip()


def _extract_url_filename(url: str) -> str:
    parsed = urlparse(url)
    basename = Path(parsed.path or "").name
    if basename and "." in basename:
        return basename
    query_params = parse_qs(str(parsed.query or ""))
    for key in URL_FILENAME_QUERY_KEYS:
        for value in query_params.get(key, []):
            candidate = Path(str(value or "")).name
            if candidate and "." in candidate:
                return candidate
    return ""


def extract_document_extension(url: str) -> str:
    filename = _extract_url_filename(url)
    if not filename:
        return ""
    return Path(filename).suffix.lower()


def split_document_urls(urls: list[str]) -> list[str]:
    """Return unique supported-document URLs from arbitrary URL list."""
    selected: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        url = _normalize_document_url(raw)
        if not url or url in seen:
            continue
        seen.add(url)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        extension = extract_document_extension(url)
        if extension in SUPPORTED_DOCUMENT_EXTENSIONS:
            selected.append(url)
    return selected


def redact_document_urls(text: str, urls: list[str]) -> str:
    """Redact specific URLs from query text while preserving non-URL text."""
    if not text:
        return ""
    blocked = {str(url).strip() for url in urls if str(url).strip()}
    if not blocked:
        return str(text).strip()

    def _replace(match: re.Match[str]) -> str:
        raw = str(match.group(0) or "")
        candidate = raw.strip().rstrip(".,;:!?)]}\"'")
        if candidate in blocked:
            return " "
        return raw

    normalized = URL_PATTERN.sub(_replace, str(text or ""))
    return " ".join(normalized.split()).strip()


def _slugify_filename(filename: str, fallback_extension: str) -> str:
    candidate = str(filename or "").strip()
    if not candidate:
        candidate = f"document{fallback_extension}"
    cleaned = SLUG_STRIP_PATTERN.sub("_", candidate).strip("._-")
    if not cleaned:
        cleaned = f"document{fallback_extension}"
    extension = Path(cleaned).suffix.lower()
    if not extension and fallback_extension:
        cleaned = f"{cleaned}{fallback_extension}"
    return cleaned


def _resolve_upload_root_entry() -> tuple[Path, bool]:
    """Return upload directory and whether config roots were bootstrapped."""
    roots = [Path(raw).expanduser() for raw in asky_config.RESEARCH_LOCAL_DOCUMENT_ROOTS]
    if not roots:
        root = DEFAULT_BOOTSTRAP_ROOT.resolve()
        upload_dir = (root / UPLOADS_DIRNAME).resolve()
        _persist_research_roots([str(root)])
        return upload_dir, True

    uploads_root = next(
        (root for root in roots if "uploads" in str(root).lower().split("/")),
        None,
    )
    if uploads_root is not None:
        return uploads_root.resolve(), False
    return (roots[0].resolve() / UPLOADS_DIRNAME).resolve(), False


def _persist_research_roots(roots: list[str]) -> None:
    config_dir = _get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    research_path = config_dir / "research.toml"
    if research_path.exists():
        document = tomlkit.parse(research_path.read_text(encoding="utf-8"))
    else:
        document = tomlkit.document()
    research_table = document.get("research")
    if research_table is None or not isinstance(research_table, dict):
        research_table = tomlkit.table()
        document["research"] = research_table
    research_table["local_document_roots"] = list(roots)
    research_path.write_text(tomlkit.dumps(document), encoding="utf-8")
    asky_config.RESEARCH_LOCAL_DOCUMENT_ROOTS[:] = list(roots)


def _safe_content_type(response: requests.Response) -> str:
    raw = str(response.headers.get("Content-Type", "") or "").strip().lower()
    return raw.split(";", 1)[0].strip()


def _validate_extension_and_mime(extension: str, mime_type: str) -> tuple[bool, Optional[str]]:
    if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
        return False, f"Unsupported file type '{extension or '(none)'}'."
    if mime_type in GENERIC_MIME_TYPES:
        return True, "MIME type is missing/generic; accepted via extension check."

    if extension in STRICT_MIME_BY_EXTENSION:
        allowed = STRICT_MIME_BY_EXTENSION[extension]
        if mime_type not in allowed:
            return False, f"MIME type '{mime_type}' is invalid for extension '{extension}'."
        return True, None

    if extension in TEXT_LIKE_EXTENSIONS:
        if mime_type.startswith("text/") or mime_type in {
            "application/json",
            "application/csv",
            "text/csv",
        }:
            return True, None
        return False, f"MIME type '{mime_type}' is invalid for text-like extension '{extension}'."

    return True, None


def _download_document(url: str) -> tuple[bytes, str]:
    with requests.get(
        url,
        stream=True,
        timeout=DOCUMENT_DOWNLOAD_TIMEOUT_SECONDS,
    ) as response:
        response.raise_for_status()
        mime_type = _safe_content_type(response)
        data = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            data.extend(chunk)
            if len(data) > DOCUMENT_MAX_FILE_SIZE_BYTES:
                raise RuntimeError(
                    f"File exceeds size limit ({len(data)} > {DOCUMENT_MAX_FILE_SIZE_BYTES} bytes)."
                )
    return bytes(data), mime_type


def _resolve_write_path(upload_dir: Path, original_name: str, extension: str) -> Path:
    upload_dir.mkdir(parents=True, exist_ok=True)
    base = _slugify_filename(original_name, extension)
    candidate = upload_dir / base
    if not candidate.exists():
        return candidate

    stem = Path(base).stem or "document"
    suffix = Path(base).suffix
    index = 2
    while True:
        rotated = upload_dir / f"{stem}_{index}{suffix}"
        if not rotated.exists():
            return rotated
        index += 1


class DocumentIngestionService:
    """Ingest XMPP-uploaded document URLs into session research corpus."""

    def ingest_for_session(
        self,
        *,
        session_id: int,
        urls: list[str],
    ) -> dict[str, Any]:
        deduped_urls = split_document_urls(urls)
        report: dict[str, Any] = {
            "processed_count": 0,
            "ingested_count": 0,
            "linked_count": 0,
            "skipped_count": 0,
            "failed": [],
            "warnings": [],
            "source_handles": [],
            "linked_paths": [],
            "bootstrapped_roots": False,
        }
        if not deduped_urls:
            return report

        selected_urls = deduped_urls[:DOCUMENT_MAX_FILES_PER_MESSAGE]
        if len(deduped_urls) > len(selected_urls):
            report["warnings"].append(
                f"Only the first {DOCUMENT_MAX_FILES_PER_MESSAGE} document URLs were processed."
            )

        upload_dir, bootstrapped = _resolve_upload_root_entry()
        report["bootstrapped_roots"] = bootstrapped
        existing_links = {
            int(item.id) for item in list_session_uploaded_documents(session_id=session_id)
        }
        paths_for_linking: list[str] = []

        for url in selected_urls:
            report["processed_count"] += 1
            try:
                if urlparse(url).scheme != "https":
                    raise RuntimeError("Only HTTPS document URLs are supported.")

                extension = extract_document_extension(url)
                if extension not in SUPPORTED_DOCUMENT_EXTENSIONS:
                    raise RuntimeError(
                        f"Unsupported document extension '{extension or '(none)'}'."
                    )

                cached_doc = get_uploaded_document_by_url(url=url)
                if cached_doc is not None and Path(cached_doc.file_path).exists():
                    link_session_uploaded_document(
                        session_id=session_id,
                        document_id=int(cached_doc.id),
                    )
                    save_uploaded_document_url(url=url, document_id=int(cached_doc.id))
                    if int(cached_doc.id) in existing_links:
                        report["skipped_count"] += 1
                    else:
                        existing_links.add(int(cached_doc.id))
                        paths_for_linking.append(cached_doc.file_path)
                        report["linked_count"] += 1
                    continue

                payload, mime_type = _download_document(url)
                is_valid, warning_or_error = _validate_extension_and_mime(
                    extension, mime_type
                )
                if not is_valid:
                    raise RuntimeError(str(warning_or_error))
                if warning_or_error:
                    report["warnings"].append(f"{url}: {warning_or_error}")

                content_hash = hashlib.sha256(payload).hexdigest()
                existing_doc = get_uploaded_document_by_hash(content_hash=content_hash)
                if existing_doc is not None and Path(existing_doc.file_path).exists():
                    doc = existing_doc
                    report["skipped_count"] += 1
                else:
                    filename = _extract_url_filename(url) or f"document{extension}"
                    write_path = _resolve_write_path(upload_dir, filename, extension)
                    write_path.write_bytes(payload)
                    doc = upsert_uploaded_document(
                        content_hash=content_hash,
                        file_path=str(write_path.resolve()),
                        original_filename=filename,
                        file_extension=extension,
                        mime_type=mime_type,
                        file_size=len(payload),
                    )
                    report["ingested_count"] += 1

                save_uploaded_document_url(url=url, document_id=int(doc.id))
                link_session_uploaded_document(
                    session_id=session_id,
                    document_id=int(doc.id),
                )
                if int(doc.id) not in existing_links:
                    existing_links.add(int(doc.id))
                    paths_for_linking.append(doc.file_path)
                    report["linked_count"] += 1
            except Exception as exc:
                report["failed"].append({"url": url, "error": str(exc)})

        if paths_for_linking:
            session = get_session_by_id(int(session_id))
            existing_paths = (
                list(getattr(session, "research_local_corpus_paths", []) or [])
                if session
                else []
            )
            merged_paths = _dedupe_preserve_order(existing_paths + paths_for_linking)
            update_session_research_profile(
                int(session_id),
                research_mode=True,
                research_source_mode="local_only",
                research_local_corpus_paths=merged_paths,
            )
            local_payload = preload_local_research_sources(
                user_prompt="",
                explicit_targets=paths_for_linking,
            )
            handles = [
                str(item.get("source_handle", "")).strip()
                for item in local_payload.get("ingested", []) or []
                if str(item.get("source_handle", "")).strip()
            ]
            report["source_handles"] = handles
            report["linked_paths"] = paths_for_linking
        return report

    def format_ack(self, report: dict[str, Any]) -> str:
        failed = list(report.get("failed", []) or [])
        warnings = list(report.get("warnings", []) or [])
        handles = list(report.get("source_handles", []) or [])
        lines = [
            "Document corpus ingestion completed.",
            (
                f"Processed={int(report.get('processed_count', 0))}, "
                f"Ingested={int(report.get('ingested_count', 0))}, "
                f"Linked={int(report.get('linked_count', 0))}, "
                f"Skipped={int(report.get('skipped_count', 0))}, "
                f"Failed={len(failed)}"
            ),
        ]
        if handles:
            lines.append("Corpus handles: " + ", ".join(handles[:6]))
        if warnings:
            lines.append("Warning: " + str(warnings[0]))
        if failed:
            sample = failed[0]
            lines.append(
                f"Error sample: {sample.get('url', '(unknown)')} -> {sample.get('error', 'unknown error')}"
            )
        if report.get("bootstrapped_roots"):
            lines.append("Initialized research.local_document_roots for uploads.")
        return "\n".join(lines)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for raw in values:
        normalized = str(raw or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped
