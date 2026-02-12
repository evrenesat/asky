"""Adapter helpers for routing research targets to custom user tools."""

import json
import logging
from pathlib import Path, PurePosixPath
import shlex
from urllib.parse import unquote, urlsplit
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from asky.config import RESEARCH_LOCAL_DOCUMENT_ROOTS, RESEARCH_SOURCE_ADAPTERS
from asky.html import strip_tags
from asky.tools import _execute_custom_tool

logger = logging.getLogger(__name__)

DEFAULT_ADAPTER_MAX_LINKS = 50
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

LINK_HREF_FIELDS = ("href", "url", "target", "id", "path")
LINK_TEXT_FIELDS = ("text", "title", "name", "label")


@dataclass(frozen=True)
class ResearchSourceAdapter:
    """Configuration for a research source adapter."""

    name: str
    prefix: str
    discover_tool: str
    read_tool: str


def _get_enabled_adapters() -> List[ResearchSourceAdapter]:
    """Build enabled adapter definitions from configuration."""
    adapters: List[ResearchSourceAdapter] = []

    for name, cfg in RESEARCH_SOURCE_ADAPTERS.items():
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", True):
            continue

        default_tool = str(cfg.get("tool", "")).strip()
        discover_tool = str(
            cfg.get("discover_tool") or cfg.get("list_tool") or default_tool
        ).strip()
        read_tool = str(cfg.get("read_tool") or default_tool).strip()

        if not discover_tool and not read_tool:
            logger.warning(
                f"Research source adapter '{name}' has no tool configured."
            )
            continue
        if not discover_tool:
            discover_tool = read_tool
        if not read_tool:
            read_tool = discover_tool

        prefix = str(cfg.get("prefix", f"{name}://")).strip()
        if not prefix:
            logger.warning(f"Research source adapter '{name}' has an empty prefix.")
            continue

        adapters.append(
            ResearchSourceAdapter(
                name=name,
                prefix=prefix,
                discover_tool=discover_tool,
                read_tool=read_tool,
            )
        )

    adapters.sort(key=lambda adapter: len(adapter.prefix), reverse=True)
    return adapters


def get_source_adapter(target: str) -> Optional[ResearchSourceAdapter]:
    """Resolve adapter for a target identifier."""
    if not target:
        return None

    for adapter in _get_enabled_adapters():
        if target.startswith(adapter.prefix):
            return adapter
    return None


def has_source_adapter(target: str) -> bool:
    """Check whether a target is handled by a configured source adapter."""
    return get_source_adapter(target) is not None or _is_builtin_local_target(target)


def _is_builtin_local_target(target: str) -> bool:
    """Return True when a target should be handled by local file reader fallback."""
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
    """Remove local-source target tokens from free-form user text."""
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


def _coerce_text(value: Any, fallback: str = "") -> str:
    """Coerce any adapter payload value to text."""
    if value is None:
        return fallback
    return str(value)


def _normalize_link(item: Any) -> Optional[Dict[str, str]]:
    """Normalize a single link-like item to {text, href} format."""
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {"text": text, "href": text}

    if not isinstance(item, dict):
        return None

    href = ""
    for field in LINK_HREF_FIELDS:
        if item.get(field):
            href = _coerce_text(item.get(field)).strip()
            if href:
                break

    if not href:
        return None

    text = ""
    for field in LINK_TEXT_FIELDS:
        if item.get(field):
            text = _coerce_text(item.get(field)).strip()
            if text:
                break

    if not text:
        text = href

    return {"text": text, "href": href}


def _normalize_links(raw_links: Any, max_links: int) -> List[Dict[str, str]]:
    """Normalize links from adapter payload."""
    if not isinstance(raw_links, list):
        return []

    links: List[Dict[str, str]] = []
    for item in raw_links:
        normalized = _normalize_link(item)
        if normalized:
            links.append(normalized)
        if len(links) >= max_links:
            break
    return links


def _parse_adapter_stdout(stdout: str) -> Dict[str, Any]:
    """Parse adapter stdout as JSON object."""
    if not stdout.strip():
        return {"error": "Adapter tool returned empty stdout."}

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"Adapter tool returned invalid JSON: {exc}"}

    if not isinstance(data, dict):
        return {"error": "Adapter tool JSON output must be an object."}

    return data


def _normalize_adapter_payload(
    payload: Dict[str, Any],
    target: str,
    max_links: int,
) -> Dict[str, Any]:
    """Normalize adapter payload into research fetch contract."""
    if payload.get("error"):
        return {
            "content": "",
            "title": target,
            "links": [],
            "error": _coerce_text(payload.get("error")),
        }

    title = _coerce_text(payload.get("title") or payload.get("name"), fallback=target)
    content = _coerce_text(payload.get("content"), fallback="")
    raw_links = payload.get("links", payload.get("items", []))
    links = _normalize_links(raw_links, max_links=max_links)

    return {
        "content": content,
        "title": title,
        "links": links,
        "error": None,
    }


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


def _normalize_relative_local_target_path(target: str) -> Optional[Path]:
    """Normalize a local target into a corpus-relative path."""
    path_candidate = _extract_local_target_path_candidate(target)
    if not path_candidate:
        return None

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
    """Resolve a local target by searching configured corpus roots."""
    roots = _configured_local_document_roots()
    if not roots:
        return [], None, LOCAL_ROOTS_DISABLED_ERROR

    relative_target = _normalize_relative_local_target_path(target)
    if relative_target is None:
        return [], None, f"Invalid local source target: {target}"

    resolved_matches: List[Path] = []
    for root in roots:
        candidate = (root / relative_target).resolve()
        if not _path_is_within_root(candidate, root):
            continue
        if candidate.exists():
            resolved_matches.append(candidate)

    if resolved_matches:
        return resolved_matches, relative_target, None

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
    for candidate in iterator:
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() not in LOCAL_SUPPORTED_EXTENSIONS:
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


def _fetch_builtin_local_source(
    target: str,
    max_links: int,
    operation: str,
) -> Optional[Dict[str, Any]]:
    """Handle local/file targets without requiring user-configured custom adapters."""
    if not _is_builtin_local_target(target):
        return None

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
            resolved_path, max_links=max_links
        )
        for link in discovered_links:
            href = str(link.get("href", "")).strip()
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            links.append(link)
            if len(links) >= max_links:
                break
        if len(links) >= max_links:
            break

    if operation == "read":
        return {
            "content": "",
            "title": relative_label,
            "links": links,
            "error": "Directory targets support discovery only; select file links to read content.",
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
    }


def fetch_source_via_adapter(
    target: str,
    query: Optional[str] = None,
    max_links: Optional[int] = None,
    operation: str = "discover",
) -> Optional[Dict[str, Any]]:
    """Fetch source metadata/content via matching custom tool adapter.

    Returns None when no adapter matches the target.
    """
    adapter = get_source_adapter(target)
    if not adapter:
        return _fetch_builtin_local_source(
            target=target,
            max_links=(
                max_links
                if isinstance(max_links, int) and max_links > 0
                else DEFAULT_ADAPTER_MAX_LINKS
            ),
            operation=operation,
        )

    link_limit = (
        max_links
        if isinstance(max_links, int) and max_links > 0
        else DEFAULT_ADAPTER_MAX_LINKS
    )
    tool_name = adapter.read_tool if operation == "read" else adapter.discover_tool

    tool_args: Dict[str, Any] = {
        "target": target,
        "max_links": link_limit,
        "operation": operation,
    }
    if query:
        tool_args["query"] = query

    result = _execute_custom_tool(tool_name, tool_args)
    if result.get("error"):
        return {
            "content": "",
            "title": target,
            "links": [],
            "error": _coerce_text(result.get("error")),
        }

    payload = _parse_adapter_stdout(_coerce_text(result.get("stdout"), fallback=""))
    return _normalize_adapter_payload(payload, target=target, max_links=link_limit)
