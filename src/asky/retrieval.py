"""Shared URL retrieval and main-content extraction helpers."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

import requests

from asky.config import FETCH_TIMEOUT, MAX_URL_DETAIL_LINKS, USER_AGENT
from asky.html import HTMLStripper, strip_tags
from asky.url_utils import sanitize_url

logger = logging.getLogger(__name__)

try:
    import trafilatura
except ImportError:
    trafilatura = None  # type: ignore[assignment]

SUPPORTED_OUTPUT_FORMATS = {"markdown", "txt"}
MAX_TITLE_CHARS = 220
TraceCallback = Callable[[Dict[str, Any]], None]

# Portal detection: if extracted content is less than this fraction of total
# visible text, the page is classified as a listing/portal page.
PORTAL_DETECTION_CONTENT_RATIO = 0.15
# Minimum visible text for portal detection to fire (avoids false positives on
# tiny pages like error pages or single-widget apps).
PORTAL_DETECTION_MIN_VISIBLE_CHARS = 2000
# Maximum links to include in portal-mode content.
PORTAL_MAX_LINKS = 150


def _emit_trace_event(
    trace_callback: Optional[TraceCallback],
    event: Dict[str, Any],
) -> None:
    """Best-effort metadata trace emission for retrieval transport calls."""
    if trace_callback is None:
        return
    try:
        trace_callback(event)
    except Exception:
        logger.debug("Retrieval trace callback failed for event kind=%s", event.get("kind"))


def _infer_response_type(content_type: str) -> str:
    """Infer high-level response type from HTTP content-type."""
    normalized = content_type.lower()
    if "json" in normalized:
        return "json"
    if "html" in normalized:
        return "html"
    if "text/" in normalized:
        return "text"
    if normalized:
        return "binary"
    return "unknown"


def fetch_url_document(
    url: str,
    output_format: str = "markdown",
    include_links: bool = False,
    max_links: Optional[int] = None,
    trace_callback: Optional[TraceCallback] = None,
    trace_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fetch URL and extract structured main content.

    Returns a payload with common fields shared by standard, research, and shortlist flows.
    """
    requested_url = sanitize_url(url)
    if not requested_url:
        return {
            "error": "URL is empty.",
            "content": "",
            "text": "",
            "title": "",
            "date": None,
            "links": [],
        }

    _plugin_override = _try_fetch_url_plugin_override(
        url=requested_url,
        output_format=output_format,
        include_links=include_links,
        max_links=max_links,
        trace_callback=trace_callback,
        trace_context=trace_context,
    )
    if _plugin_override is not None:
        return _plugin_override

    started = time.perf_counter()
    normalized_format = (
        output_format if output_format in SUPPORTED_OUTPUT_FORMATS else "markdown"
    )
    link_limit = max_links if isinstance(max_links, int) and max_links > 0 else MAX_URL_DETAIL_LINKS

    try:
        request_trace = {
            "kind": "transport_request",
            "transport": "http",
            "source": "retrieval",
            "operation": "fetch_url_document",
            "method": "GET",
            "url": requested_url,
        }
        if trace_context:
            request_trace.update(trace_context)
        _emit_trace_event(trace_callback, request_trace)

        response = requests.get(
            requested_url,
            headers={"User-Agent": USER_AGENT},
            timeout=FETCH_TIMEOUT,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        timeout_trace = {
            "kind": "transport_error",
            "transport": "http",
            "source": "retrieval",
            "operation": "fetch_url_document",
            "method": "GET",
            "url": requested_url,
            "error_type": "timeout",
            "error": f"Request timed out after {FETCH_TIMEOUT}s",
            "elapsed_ms": (time.perf_counter() - started) * 1000,
        }
        if trace_context:
            timeout_trace.update(trace_context)
        _emit_trace_event(trace_callback, timeout_trace)
        return {
            "error": f"Request timed out after {FETCH_TIMEOUT}s",
            "content": "",
            "text": "",
            "title": "",
            "date": None,
            "links": [],
        }
    except requests.exceptions.RequestException as exc:
        error_trace = {
            "kind": "transport_error",
            "transport": "http",
            "source": "retrieval",
            "operation": "fetch_url_document",
            "method": "GET",
            "url": requested_url,
            "error_type": "request_exception",
            "error": str(exc),
            "elapsed_ms": (time.perf_counter() - started) * 1000,
        }
        if trace_context:
            error_trace.update(trace_context)
        if getattr(exc, "response", None) is not None:
            error_trace["status_code"] = exc.response.status_code
        _emit_trace_event(trace_callback, error_trace)
        return {
            "error": str(exc),
            "content": "",
            "text": "",
            "title": "",
            "date": None,
            "links": [],
        }

    html = response.text or ""
    final_url = sanitize_url(response.url) or requested_url

    extracted = _extract_main_content(
        html=html,
        source_url=final_url,
        output_format=normalized_format,
    )

    content = extracted.get("content", "")
    title = extracted.get("title", "") or _derive_title(content, final_url)
    warning = extracted.get("warning")

    links: List[Dict[str, str]] = []
    if include_links:
        links = _extract_links(html, final_url, link_limit)

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.debug(
        "retrieval fetched url=%s final_url=%s status=%s format=%s source=%s content_len=%d links=%d elapsed=%.2fms warning=%s",
        requested_url,
        final_url,
        response.status_code,
        normalized_format,
        extracted.get("source", "unknown"),
        len(content),
        len(links),
        elapsed_ms,
        warning,
    )

    payload: Dict[str, Any] = {
        "error": None,
        "requested_url": requested_url,
        "final_url": final_url,
        "content": content,
        "text": content,
        "title": title[:MAX_TITLE_CHARS],
        "date": extracted.get("date"),
        "links": links,
        "source": extracted.get("source", "unknown"),
        "output_format": normalized_format,
        "page_type": extracted.get("page_type", "article"),
    }
    if warning:
        payload["warning"] = warning

    response_trace = {
        "kind": "transport_response",
        "transport": "http",
        "source": "retrieval",
        "operation": "fetch_url_document",
        "method": "GET",
        "url": requested_url,
        "status_code": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "response_type": _infer_response_type(response.headers.get("Content-Type", "")),
        "response_bytes": len(response.content or b""),
        "response_chars": len(response.text or ""),
        "elapsed_ms": elapsed_ms,
    }
    if trace_context:
        response_trace.update(trace_context)
    _emit_trace_event(trace_callback, response_trace)
    return payload


def _extract_main_content(
    html: str,
    source_url: str,
    output_format: str,
) -> Dict[str, Any]:
    """Extract main content with Trafilatura first, then fallback parser.

    When Trafilatura's output is sparse relative to the page's total visible
    text, the page is classified as a portal/listing page and a structured
    link listing is returned instead.
    """
    trafilatura_result = _extract_with_trafilatura(
        html=html,
        source_url=source_url,
        output_format=output_format,
    )
    extracted_content = trafilatura_result.get("content", "")

    # Fast path: Trafilatura produced substantial content → article, skip detection.
    if len(extracted_content) >= PORTAL_DETECTION_MIN_VISIBLE_CHARS:
        trafilatura_result["page_type"] = "article"
        return trafilatura_result

    visible_chars = len(strip_tags(html).strip())
    page_type = _detect_page_type(extracted_content, visible_chars)

    if page_type == "portal":
        portal_content = _format_portal_content(html, source_url, PORTAL_MAX_LINKS)
        result: Dict[str, Any] = {
            "content": portal_content,
            "title": trafilatura_result.get("title", ""),
            "date": trafilatura_result.get("date"),
            "source": "portal_links",
            "page_type": "portal",
        }
        if trafilatura_result.get("warning"):
            result["warning"] = trafilatura_result["warning"]
        return result

    if extracted_content:
        trafilatura_result["page_type"] = "article"
        return trafilatura_result

    fallback = _extract_with_html_fallback(html=html, output_format=output_format)
    fallback["page_type"] = "article"
    if trafilatura_result.get("warning") and not fallback.get("warning"):
        fallback["warning"] = trafilatura_result["warning"]
    return fallback


def _detect_page_type(extracted_content: str, visible_chars: int) -> str:
    """Classify a page as 'article' or 'portal' based on extraction yield.

    A portal is a listing/aggregation page (news homepage, category index, etc.)
    where Trafilatura finds little content relative to the total visible text.
    """
    if visible_chars < PORTAL_DETECTION_MIN_VISIBLE_CHARS:
        return "article"
    extracted_chars = len(extracted_content.strip())
    if extracted_chars == 0:
        return "portal"
    return "portal" if extracted_chars / visible_chars < PORTAL_DETECTION_CONTENT_RATIO else "article"


def _format_portal_content(html: str, base_url: str, max_links: int) -> str:
    """Extract and format section-grouped links from a portal/listing page.

    Returns a markdown string with a type header and links grouped under
    their structural section (heading text or zone name).
    """
    stripper = HTMLStripper(base_url=base_url)
    stripper.feed(html)
    links = stripper.get_links_with_sections()

    # Group links by section preserving first-appearance order,
    # deduplicating by href and capping at max_links total.
    sections: Dict[str, List[Dict[str, str]]] = {}
    section_order: List[str] = []
    seen_hrefs: Set[str] = set()
    count = 0

    for link in links:
        if count >= max_links:
            break
        href = link["href"]
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        section = link["section"] or "Content"
        if section not in sections:
            sections[section] = []
            section_order.append(section)
        sections[section].append(link)
        count += 1

    lines = ["[Page type: news portal / content listing]", ""]
    for section in section_order:
        lines.append(f"## {section}")
        for link in sections[section]:
            lines.append(f"- [{link['text']}]({link['href']})")
        lines.append("")

    return "\n".join(lines).strip()


def _extract_with_trafilatura(
    html: str,
    source_url: str,
    output_format: str,
) -> Dict[str, Any]:
    """Best-effort Trafilatura extraction with metadata."""
    if trafilatura is None:
        return {
            "content": "",
            "title": "",
            "date": None,
            "source": "none",
            "warning": "trafilatura_unavailable",
        }

    try:
        extraction_kwargs = {
            "output_format": output_format,
            "include_comments": False,
            "include_tables": False,
        }
        try:
            extracted = trafilatura.extract(
                html,
                url=source_url,
                **extraction_kwargs,
            )
        except TypeError:
            extracted = trafilatura.extract(
                html,
                **extraction_kwargs,
            )

        if not extracted:
            return {
                "content": "",
                "title": "",
                "date": None,
                "source": "trafilatura",
                "warning": "trafilatura_empty_extract",
            }

        title = ""
        date = None
        metadata_extractor = getattr(trafilatura, "extract_metadata", None)
        if callable(metadata_extractor):
            try:
                metadata = metadata_extractor(html)
                title = _clean_title(getattr(metadata, "title", ""))
                raw_date = getattr(metadata, "date", None)
                if raw_date:
                    date = str(raw_date)
            except Exception as exc:
                logger.debug(
                    "retrieval metadata extraction failed url=%s error=%s",
                    source_url,
                    exc,
                )

        return {
            "content": str(extracted).strip(),
            "title": title,
            "date": date,
            "source": "trafilatura",
        }
    except Exception as exc:
        logger.debug(
            "retrieval trafilatura extraction failed url=%s error=%s",
            source_url,
            exc,
        )
        return {
            "content": "",
            "title": "",
            "date": None,
            "source": "trafilatura",
            "warning": f"trafilatura_error:{exc}",
        }


def _extract_with_html_fallback(html: str, output_format: str) -> Dict[str, Any]:
    """Fallback extraction when Trafilatura does not produce content."""
    if output_format == "txt":
        content = strip_tags(html).strip()
    else:
        content = strip_tags(html).strip()

    return {
        "content": content,
        "title": "",
        "date": None,
        "source": "html_fallback",
    }


def _extract_and_normalize_links(
    html: str, base_url: str, max_links: Optional[int]
) -> List[Dict[str, str]]:
    """Extract and normalize anchor links from HTML. Package-internal."""
    try:
        stripper = HTMLStripper(base_url=base_url)
        stripper.feed(html)
        links = stripper.get_links()
        if max_links is not None and max_links > 0:
            return links[:max_links]
        return links
    except Exception as exc:
        logger.debug("retrieval link extraction failed url=%s error=%s", base_url, exc)
        return []


def _extract_links(html: str, base_url: str, max_links: int) -> List[Dict[str, str]]:
    """Extract links from raw HTML while preserving anchor text."""
    return _extract_and_normalize_links(html, base_url, max_links)


def _clean_title(value: str) -> str:
    """Normalize extracted titles."""
    if not value:
        return ""
    cleaned = str(value).strip().strip("#").strip()
    return cleaned[:MAX_TITLE_CHARS]


def _try_fetch_url_plugin_override(
    url: str,
    output_format: str,
    include_links: bool,
    max_links: Optional[int],
    trace_callback: Optional[TraceCallback],
    trace_context: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Ask plugins for an override result; returns None to use the default pipeline."""
    try:
        from asky.plugins.hook_types import FETCH_URL_OVERRIDE, FetchURLContext
        from asky.plugins.runtime import get_or_create_plugin_runtime
    except ImportError:
        return None
    runtime = get_or_create_plugin_runtime()
    if runtime is None:
        return None
    ctx = FetchURLContext(
        url=url,
        output_format=output_format,
        include_links=include_links,
        max_links=max_links,
        trace_callback=trace_callback,
        trace_context=trace_context,
    )
    runtime.hooks.invoke(FETCH_URL_OVERRIDE, ctx)
    return ctx.result


def _derive_title(content: str, url: str) -> str:
    """Derive a fallback title from content or URL."""
    if content:
        for line in content.splitlines():
            cleaned = _clean_title(line)
            if cleaned:
                return cleaned
    return url[:MAX_TITLE_CHARS]
