"""Builtin local-source loading helpers for research ingestion."""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

from asky.config import RESEARCH_LOCAL_DOCUMENT_ROOTS
from asky.html import strip_tags

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_MAX_LINKS = 50
LOCAL_DIRECTORY_RECURSIVE = False
LOCAL_SUPPORTED_TEXT_EXTENSIONS = frozenset(
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
LOCAL_SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".epub",
    }
)
LOCAL_SUPPORTED_EXTENSIONS = (
    LOCAL_SUPPORTED_TEXT_EXTENSIONS | LOCAL_SUPPORTED_DOCUMENT_EXTENSIONS
)
WINDOWS_DRIVE_INDICATOR_INDEX = 1
LOCAL_TARGET_TRAILING_PUNCTUATION = ".,;:!?)]}>\"'"
LOCAL_ROOTS_DISABLED_ERROR = (
    "Local source loading is disabled. Set research.local_document_roots to enable it."
)
LOCAL_SOURCE_NOT_FOUND_ERROR = (
    "Local source not found in configured document roots: {relative_target}"
)


@dataclass
class LocalSourcePayload:
    """Normalized payload for a local source file."""

    content: str
    title: str
    links: List[Dict[str, str]] = field(default_factory=list)
    error: Optional[str] = None
    resolved_target: Optional[str] = None
    mime: Optional[str] = None


_PLUGIN_HANDLERS: Optional[List[Any]] = None


def _get_plugin_handlers() -> List[Any]:
    global _PLUGIN_HANDLERS
    if _PLUGIN_HANDLERS is not None:
        return _PLUGIN_HANDLERS

    try:
        from asky.plugins import (
            LOCAL_SOURCE_HANDLER_REGISTER,
            LocalSourceHandlerRegisterContext,
            get_or_create_plugin_runtime,
        )

        runtime = get_or_create_plugin_runtime()
        ctx = LocalSourceHandlerRegisterContext()
        runtime.hooks.invoke(LOCAL_SOURCE_HANDLER_REGISTER, ctx)
        _PLUGIN_HANDLERS = ctx.handlers
    except (ImportError, Exception):
        _PLUGIN_HANDLERS = []

    return _PLUGIN_HANDLERS


def get_all_supported_extensions() -> frozenset[str]:
    """Return all supported local extensions, including plugin-provided ones."""
    extensions = set(LOCAL_SUPPORTED_EXTENSIONS)
    for handler in _get_plugin_handlers():
        for ext in handler.extensions:
            extensions.add(ext.lower())
    return frozenset(extensions)


def _is_builtin_local_target(target: str) -> bool:
    """Return True when a target should be handled by local file reader."""
    if not target:
        return False
    if target.startswith("local://") or target.startswith("file://"):
        return True
    if target.startswith("/") or target.startswith("~/") or target.startswith("./"):
        return True
    return len(target) > WINDOWS_DRIVE_INDICATOR_INDEX and target[
        WINDOWS_DRIVE_INDICATOR_INDEX
    ] == ":"


def extract_local_source_targets(text: str) -> List[str]:
    """Extract potential local source targets from free-form user text."""
    if not text:
        return []

    raw_tokens = _split_query_tokens(text)
    targets: List[str] = []
    seen = set()
    for token in raw_tokens:
        candidate = token.strip().rstrip(LOCAL_TARGET_TRAILING_PUNCTUATION)
        if not candidate:
            continue
        if not _is_builtin_local_target(candidate):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        targets.append(candidate)
    return targets


def redact_local_source_targets(text: str) -> str:
    """Remove local-source target tokens from model-visible user text."""
    if not text:
        return ""

    redacted_tokens: List[str] = []
    for token in _split_query_tokens(text):
        candidate = token.strip().rstrip(LOCAL_TARGET_TRAILING_PUNCTUATION)
        if candidate and _is_builtin_local_target(candidate):
            continue
        redacted_tokens.append(token)
    return " ".join(redacted_tokens).strip()


def _split_query_tokens(text: str) -> List[str]:
    """Split user text into shell-like tokens for local-target parsing."""
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _extract_local_target_path_candidate(target: str) -> Optional[str]:
    """Extract the path-like portion from local/file targets."""
    if not target:
        return None

    path_candidate = target
    if target.startswith("local://"):
        path_candidate = unquote(target[len("local://") :])
    elif target.startswith("file://"):
        parsed = urlsplit(target)
        file_path = unquote(parsed.path or "")
        if parsed.netloc and parsed.netloc not in {"", "localhost"}:
            file_path = f"//{parsed.netloc}{file_path}"
        path_candidate = file_path

    if not path_candidate:
        return None
    return path_candidate


def _safe_relative_path(path_candidate: str) -> Path:
    """Normalize a user path into a safe corpus-root-relative path."""
    normalized = path_candidate.strip().replace("\\", "/")
    if len(normalized) > WINDOWS_DRIVE_INDICATOR_INDEX and normalized[
        WINDOWS_DRIVE_INDICATOR_INDEX
    ] == ":":
        normalized = normalized[WINDOWS_DRIVE_INDICATOR_INDEX + 1 :]

    normalized = normalized.lstrip("/")
    if normalized.startswith("~/"):
        normalized = normalized[2:]
    elif normalized == "~":
        normalized = ""

    safe_parts: List[str] = []
    for part in PurePosixPath(normalized).parts:
        if part in {"", ".", "/"}:
            continue
        if part == "..":
            continue
        safe_parts.append(part)

    if not safe_parts:
        return Path(".")
    return Path(*safe_parts)


def _configured_local_document_roots() -> List[Path]:
    """Return normalized configured corpus roots for local-source loading."""
    roots: List[Path] = []
    for raw_root in RESEARCH_LOCAL_DOCUMENT_ROOTS:
        try:
            roots.append(Path(raw_root).expanduser().resolve())
        except Exception:
            continue
    return roots


def _path_is_within_root(path: Path, root: Path) -> bool:
    """Check if resolved path remains inside its configured corpus root."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_local_target_paths(
    target: str,
) -> Tuple[List[Path], Optional[Path], Optional[str]]:
    """Resolve a local target to existing files/directories under configured roots."""
    roots = _configured_local_document_roots()
    if not roots:
        return [], None, LOCAL_ROOTS_DISABLED_ERROR

    path_candidate = _extract_local_target_path_candidate(target)
    if not path_candidate:
        return [], None, f"Invalid local source target: {target}"

    expanded = Path(path_candidate).expanduser()
    resolved_matches: List[Path] = []

    if expanded.is_absolute():
        try:
            absolute_candidate = expanded.resolve()
            for root in roots:
                if (
                    _path_is_within_root(absolute_candidate, root)
                    and absolute_candidate.exists()
                ):
                    resolved_matches.append(absolute_candidate)
                    break
        except Exception:
            absolute_candidate = None
    else:
        absolute_candidate = None

    relative_target = _safe_relative_path(path_candidate)
    for root in roots:
        candidate = (root / relative_target).resolve()
        if not _path_is_within_root(candidate, root):
            continue
        if candidate.exists():
            resolved_matches.append(candidate)

    if resolved_matches:
        deduped: List[Path] = []
        seen = set()
        for item in resolved_matches:
            key = str(item)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped, relative_target, None

    if absolute_candidate is not None and absolute_candidate.exists():
        return [], relative_target, (
            f"Local source is outside configured document roots: {absolute_candidate}"
        )

    relative_label = relative_target.as_posix()
    return [], relative_target, LOCAL_SOURCE_NOT_FOUND_ERROR.format(
        relative_target=relative_label
    )


def _local_target_from_path(path: Path) -> str:
    """Build canonical local:// target from a filesystem path."""
    return f"local://{path.resolve().as_posix()}"


def _load_pymupdf_module() -> Any:
    """Best-effort PyMuPDF import supporting both modern and legacy module names."""
    try:
        import pymupdf  # type: ignore

        return pymupdf
    except Exception:
        try:
            import fitz  # type: ignore

            return fitz
        except Exception:
            return None


def _read_text_file(path: Path) -> tuple[str, Optional[str]]:
    """Read plain text-like files with UTF-8 fallback handling."""
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8", errors="ignore"), None
        except Exception as exc:
            return "", str(exc)
    except Exception as exc:
        return "", str(exc)


def _read_with_pymupdf(path: Path) -> tuple[str, Optional[str]]:
    """Extract text from PDF/EPUB files via PyMuPDF."""
    pymupdf_module = _load_pymupdf_module()
    if pymupdf_module is None:
        return "", "PyMuPDF is required to read PDF/EPUB local sources."

    try:
        doc = pymupdf_module.open(str(path))
        try:
            page_texts = []
            for page in doc:
                page_texts.append(page.get_text("text"))
        finally:
            doc.close()
        return "\n\n".join(page_texts).strip(), None
    except Exception as exc:
        return "", str(exc)


def _read_local_file_content(path: Path) -> tuple[str, Optional[str]]:
    """Read supported local file types into normalized plain text."""
    extension = path.suffix.lower()

    # Check plugin-provided handlers first
    for handler in _get_plugin_handlers():
        if extension in (ext.lower() for ext in handler.extensions):
            try:
                # The read() callable returns a LocalSourcePayload
                payload = handler.read(str(path))
                if not payload:
                    return "", f"Plugin-provided reader returned empty for '{extension}'."
                if payload.error:
                    return "", payload.error
                return payload.content, None
            except Exception as exc:
                return "", str(exc)

    if extension in {".html", ".htm"}:
        html_text, error = _read_text_file(path)
        if error:
            return "", error
        return strip_tags(html_text).strip(), None
    if extension in LOCAL_SUPPORTED_TEXT_EXTENSIONS:
        return _read_text_file(path)
    if extension in LOCAL_SUPPORTED_DOCUMENT_EXTENSIONS:
        return _read_with_pymupdf(path)
    return "", f"Unsupported local file type: '{extension or '(none)'}'."


def _discover_local_directory_links(path: Path, max_links: int) -> List[Dict[str, str]]:
    """Discover supported local files under a directory."""
    iterator = path.rglob("*") if LOCAL_DIRECTORY_RECURSIVE else path.iterdir()
    links: List[Dict[str, str]] = []
    supported_extensions = get_all_supported_extensions()
    for candidate in iterator:
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() not in supported_extensions:
            continue
        links.append(
            {
                "text": candidate.name,
                "href": _local_target_from_path(candidate),
            }
        )
        if len(links) >= max_links:
            break
    return links


def fetch_source_via_adapter(
    target: str,
    query: Optional[str] = None,
    max_links: Optional[int] = None,
    operation: str = "discover",
) -> Optional[Dict[str, Any]]:
    """Fetch local source metadata/content.

    Returns None when `target` is not local.
    """
    del query  # query is unused by builtin local loader
    if not _is_builtin_local_target(target):
        return None

    link_limit = (
        max_links
        if isinstance(max_links, int) and max_links > 0
        else DEFAULT_LOCAL_MAX_LINKS
    )
    resolved_paths, relative_target, resolve_error = _resolve_local_target_paths(target)
    if relative_target is None:
        return {
            "content": "",
            "title": target,
            "links": [],
            "error": resolve_error or f"Invalid local source target: {target}",
        }

    if not resolved_paths:
        return {
            "content": "",
            "title": relative_target.as_posix(),
            "links": [],
            "error": resolve_error,
        }

    selected_file = next((path for path in resolved_paths if path.is_file()), None)
    if selected_file is not None:
        file_content, content_error = _read_local_file_content(selected_file)
        if content_error:
            return {
                "content": "",
                "title": selected_file.name,
                "links": [],
                "error": content_error,
            }

        return {
            "content": file_content,
            "title": selected_file.name,
            "links": [],
            "error": None,
            "resolved_target": _local_target_from_path(selected_file),
        }

    relative_label = relative_target.as_posix()
    links: List[Dict[str, str]] = []
    seen_hrefs = set()
    for resolved_path in resolved_paths:
        discovered_links = _discover_local_directory_links(
            resolved_path, max_links=link_limit
        )
        for link in discovered_links:
            href = str(link.get("href", "")).strip()
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            links.append(link)
            if len(links) >= link_limit:
                break
        if len(links) >= link_limit:
            break

    if operation == "read":
        return {
            "content": "",
            "title": relative_label,
            "links": links,
            "error": "Directory targets support discovery only; select file links to read content.",
            "is_directory_discovery": True,
        }
    summary = (
        f"Local directory '{relative_label}' with {len(links)} discoverable files."
    )
    return {
        "content": summary,
        "title": relative_label,
        "links": links,
        "error": None,
        "resolved_target": _local_target_from_path(resolved_paths[0]),
        "is_directory_discovery": True,
    }
