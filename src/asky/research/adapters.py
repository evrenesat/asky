"""Adapter helpers for routing research targets to custom user tools."""

import json
import logging
from pathlib import Path
import shlex
from urllib.parse import unquote, urlsplit
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from asky.config import RESEARCH_SOURCE_ADAPTERS
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

    try:
        raw_tokens = shlex.split(text)
    except ValueError:
        raw_tokens = text.split()

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


def _resolve_local_target_path(target: str) -> Optional[Path]:
    """Resolve local/file-scheme targets to local filesystem paths."""
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

    return Path(path_candidate).expanduser()


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

    resolved_path = _resolve_local_target_path(target)
    if resolved_path is None:
        return {
            "content": "",
            "title": target,
            "links": [],
            "error": f"Invalid local source target: {target}",
        }

    if not resolved_path.exists():
        return {
            "content": "",
            "title": str(resolved_path),
            "links": [],
            "error": f"Local source does not exist: {resolved_path}",
        }

    if resolved_path.is_dir():
        links = _discover_local_directory_links(resolved_path, max_links=max_links)
        if operation == "read":
            return {
                "content": "",
                "title": resolved_path.name or str(resolved_path),
                "links": links,
                "error": "Directory targets support discovery only; select file links to read content.",
            }
        summary = (
            f"Local directory {resolved_path} with {len(links)} discoverable files."
        )
        return {
            "content": summary,
            "title": resolved_path.name or str(resolved_path),
            "links": links,
            "error": None,
        }

    file_content, content_error = _read_local_file_content(resolved_path)
    if content_error:
        return {
            "content": "",
            "title": resolved_path.name,
            "links": [],
            "error": content_error,
        }

    return {
        "content": file_content,
        "title": resolved_path.name,
        "links": [],
        "error": None,
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
