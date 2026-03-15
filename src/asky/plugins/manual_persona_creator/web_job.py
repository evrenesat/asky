from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Sequence, Callable
from urllib.parse import urlparse, urlunparse

from asky.retrieval import fetch_url_document
from asky.url_utils import normalize_url
from asky.plugins.manual_persona_creator.storage import (
    WebCollectionPaths,
    WebPagePaths,
    get_web_page_id,
    get_web_page_paths,
    read_web_frontier,
    write_web_frontier,
    read_web_page_manifest,
    write_web_page_manifest,
    read_web_page_report,
    write_web_page_report,
    read_web_collection_manifest,
    write_web_collection_manifest,
)
from asky.plugins.manual_persona_creator.web_types import (
    WebCollectionManifest,
    WebCollectionMode,
    WebCollectionStatus,
    WebPageManifest,
    WebPageStatus,
    WebPageClassification,
    WebPagePreview,
    WebFrontierState,
    WebPageReport,
    RetrievalProvenance,
    DuplicateMetadata,
)
from asky.plugins.manual_persona_creator.web_prompts import WEB_PAGE_CLASSIFICATION_AND_PREVIEW_PROMPT

logger = logging.getLogger(__name__)


class WebCollectionJob:
    """Background job for fetching and processing web pages for a persona review batch."""

    def __init__(
        self,
        persona_name: str,
        persona_description: str,
        paths: WebCollectionPaths,
        target_results: int,
        mode: WebCollectionMode,
        embedding_client: Optional[Any] = None,
        llm_client: Optional[Any] = None,
        search_executor: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.persona_name = persona_name
        self.persona_description = persona_description
        self.paths = paths
        self.target_results = target_results
        self.mode = mode
        self.embedding_client = embedding_client
        self.llm_client = llm_client
        self._search_executor = search_executor
        self.seed_hosts: Set[str] = set()
        self.processed_fingerprints: Set[str] = set()

    def run(self, manifest: WebCollectionManifest):
        """Execute the collection job."""
        logger.info("Starting web collection job for %s, target=%d", self.persona_name, self.target_results)
        
        from asky.plugins.manual_persona_creator.web_types import WebCollectionInputMode
        import math

        # Initialize seed hosts if in SEED_DOMAIN mode
        if self.mode == WebCollectionMode.SEED_DOMAIN:
            self.seed_hosts = self._get_seed_host_allowlist(manifest.seed_inputs)

        # Load frontier state
        frontier_data = read_web_frontier(self.paths.frontier_path)
        state = WebFrontierState(
            queue=frontier_data.get("queue", []),
            seen_candidate_urls=frontier_data.get("seen_candidate_urls", []),
            fetched_candidate_urls=frontier_data.get("fetched_candidate_urls", []),
            raw_unique_fetch_count=frontier_data.get("raw_unique_fetch_count", 0),
            overcollect_cap=frontier_data.get("overcollect_cap", 0),
        )

        if self.mode == WebCollectionMode.BROAD_EXPAND and state.overcollect_cap == 0:
            state.overcollect_cap = math.ceil(self.target_results * 1.3)

        if not state.queue and not state.seen_candidate_urls:
            if manifest.input_mode == WebCollectionInputMode.SEARCH_QUERY:
                # Perform search to populate initial frontier
                for query in manifest.seed_inputs:
                    logger.info("Performing initial search for query: %s", query)
                    search_results = self._execute_search(query)
                    for res in search_results:
                        url = res.get("url")
                        if url:
                            normalized = normalize_url(url)
                            if normalized not in state.seen_candidate_urls:
                                state.queue.append(url)
                                state.seen_candidate_urls.append(normalized)
            else:
                for url in manifest.seed_inputs:
                    normalized = normalize_url(url)
                    state.queue.append(url)
                    state.seen_candidate_urls.append(normalized)

        processed_urls: Set[str] = self._get_processed_urls()
        # Ensure seen URLs also count as processed if they are already terminal
        processed_urls.update(state.fetched_candidate_urls)
        
        while state.queue:
            # Check termination criteria
            if self.mode == WebCollectionMode.BROAD_EXPAND:
                if state.raw_unique_fetch_count >= state.overcollect_cap:
                    logger.info("Broad overcollection cap reached: %d", state.overcollect_cap)
                    break
            else:
                if self._count_review_ready() >= self.target_results:
                    break

            url = state.queue.pop(0)
            normalized_url = normalize_url(url)
            
            if normalized_url in state.fetched_candidate_urls:
                continue
                
            # Stay within seed domains in SEED_DOMAIN mode
            if self.mode == WebCollectionMode.SEED_DOMAIN:
                if not self._is_in_seed_hosts(url):
                    logger.debug("Skipping cross-domain URL: %s", url)
                    continue

            self._process_page(url, state, processed_urls)
            
            # Save frontier state periodically
            write_web_frontier(self.paths.frontier_path, dataclasses.asdict(state))

        # Update status
        new_status = WebCollectionStatus.REVIEW_READY
        if self._count_review_ready() < self.target_results and not state.queue:
            new_status = WebCollectionStatus.EXHAUSTED
            
        self._update_manifest_status(manifest, new_status)

    def _execute_search(self, query: str) -> List[Dict[str, Any]]:
        """Execute a web search."""
        if self._search_executor:
            executor = self._search_executor
        else:
            from asky.tools import execute_web_search
            executor = execute_web_search
            
        try:
            # BROAD_EXPAND mode uses overcollect_cap for search count
            count = self.target_results * 2
            if self.mode == WebCollectionMode.BROAD_EXPAND:
                import math
                count = math.ceil(self.target_results * 1.3)

            results = executor({"query": query, "count": count})
            return results.get("results", [])
        except Exception as e:
            logger.warning("Search failed: %s", e)
            return []

    def _process_page(self, url: str, state: WebFrontierState, processed_urls: Set[str]):
        """Fetch and process a single page."""
        logger.info("Fetching page: %s", url)
        
        normalized_requested_url = normalize_url(url)
        if normalized_requested_url in state.fetched_candidate_urls:
            return
            
        trace_context = {
            "persona": self.persona_name,
            "collection_id": self.paths.collection_dir.name,
            "milestone": 4,
        }
        
        trace_events: List[Dict[str, Any]] = []

        def trace_callback(event: Dict[str, Any]):
            trace_events.append(event)

        payload = fetch_url_document(
            url=url,
            include_links=True,
            trace_callback=trace_callback,
            trace_context=trace_context,
        )
        
        state.fetched_candidate_urls.append(normalized_requested_url)
        state.raw_unique_fetch_count = len(set(state.fetched_candidate_urls))
        
        # Build retrieval provenance from trace events
        retrieval_provider = "default"
        retrieval_source = payload.get("source", "unknown")
        fallback_reason = None
        
        for ev in trace_events:
            if ev.get("kind") == "playwright_success":
                retrieval_provider = "playwright"
            elif ev.get("kind") == "playwright_failed":
                fallback_reason = ev.get("error")

        retrieval_info = RetrievalProvenance(
            provider=retrieval_provider,
            source=retrieval_source,
            page_type=payload.get("page_type", "html"),
            warning=payload.get("warning"),
            error=payload.get("error"),
            fallback_reason=fallback_reason,
            trace_events=trace_events
        )
        
        if payload.get("error"):
            logger.warning("Failed to fetch %s: %s", url, payload["error"])
            self._save_failed_page(url, payload, retrieval_info=retrieval_info)
            return

        final_url = payload.get("final_url", url)
        normalized_final_url = normalize_url(final_url)
        
        # If redirected, we might have already fetched this final URL
        if normalized_final_url != normalized_requested_url:
            if normalized_final_url in state.fetched_candidate_urls:
                # We already have this content. Mark as duplicate if needed, 
                # but since it's the same URL we can just skip or record it.
                self._save_duplicate_page(url, payload, reason="redirect_to_fetched", retrieval_info=retrieval_info)
                return
            state.fetched_candidate_urls.append(normalized_final_url)

        content = payload.get("content", "")
        if not content:
            logger.warning("Empty content for %s", url)
            self._save_failed_page(url, {"error": "Empty content"}, retrieval_info=retrieval_info)
            return

        page_id = get_web_page_id(normalized_final_url)
        p_paths = get_web_page_paths(self.paths.collection_dir, page_id)
        
        if p_paths.page_dir.exists():
            # Already processed (e.g. from another URL redirecting here)
            self._save_duplicate_page(url, payload, reason="already_exists", matched_page_id=page_id, retrieval_info=retrieval_info)
            return

        # Duplicate filtering by fingerprint
        fingerprint = self._calculate_fingerprint(content)
        if self._is_duplicate_by_fingerprint(fingerprint):
            self._save_duplicate_page(url, payload, reason="content_fingerprint", fingerprint=fingerprint, retrieval_info=retrieval_info)
            return

        # Near-duplicate filtering by embedding similarity
        embedding = None
        if self.embedding_client:
            try:
                embedding = self.embedding_client.embed_text(content)
            except Exception as e:
                logger.warning("Embedding failed for %s: %s", url, e)
        
        near_dup = self._is_near_duplicate(page_id, content, embedding)
        if near_dup:
            self._save_duplicate_page(
                url, 
                payload, 
                reason=near_dup["reason"], 
                matched_page_id=near_dup["matched_page_id"],
                fingerprint=fingerprint,
                similarity_score=near_dup.get("similarity_score"),
                retrieval_info=retrieval_info
            )
            return

        # Extract links for frontier
        for link in payload.get("links", []):
            href = link.get("href")
            if not href:
                continue
            normalized_href = normalize_url(href)
            if normalized_href in state.seen_candidate_urls:
                continue
                
            if self.mode == WebCollectionMode.SEED_DOMAIN:
                if self._is_in_seed_hosts(href):
                    state.queue.append(href)
                    state.seen_candidate_urls.append(normalized_href)
            else:
                # BROAD_EXPAND mode (milestone 4) allows cross-domain link extraction
                state.queue.append(href)
                state.seen_candidate_urls.append(normalized_href)

        # Classify and extract preview
        preview = self._extract_preview(payload)
        
        # Persist artifacts
        p_paths.page_dir.mkdir(parents=True, exist_ok=True)
        p_paths.content_path.write_text(content, encoding="utf-8")
        p_paths.links_path.write_text(json.dumps(payload.get("links", []), indent=2), encoding="utf-8")
        
        manifest = WebPageManifest(
            page_id=page_id,
            status=WebPageStatus.REVIEW_READY,
            requested_url=url,
            final_url=final_url,
            normalized_final_url=normalized_final_url,
            title=payload.get("title", ""),
            content_fingerprint=fingerprint,
            classification=preview.recommended_classification if preview else WebPageClassification.UNCERTAIN,
            similarity_metadata={"embedding": embedding} if embedding else {},
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
        write_web_page_manifest(p_paths.manifest_path, dataclasses.asdict(manifest))
        
        if preview:
            self._write_page_preview(p_paths.preview_path, preview)
            
        # Create initial report
        report = WebPageReport(
            page_id=page_id,
            status=WebPageStatus.REVIEW_READY,
            requested_url=url,
            final_url=final_url,
            normalized_final_url=normalized_final_url,
            title=payload.get("title", ""),
            content_fingerprint=fingerprint,
            retrieval=retrieval_info,
            created_at=datetime.now(UTC).isoformat(),
        )
        write_web_page_report(p_paths.report_path, dataclasses.asdict(report))

    def _extract_preview(self, payload: Dict[str, Any]) -> Optional[WebPagePreview]:
        """Call LLM to extract page classification and preview metadata."""
        if not self.llm_client:
            return None
            
        prompt = WEB_PAGE_CLASSIFICATION_AND_PREVIEW_PROMPT.format(
            persona_name=self.persona_name,
            persona_description=self.persona_description,
            page_title=payload.get("title", ""),
            page_url=payload.get("final_url", ""),
            page_content=payload.get("content", "")[:10000], # Limit content for prompt
        )
        
        try:
            response = self.llm_client.generate_json(prompt)
            return WebPagePreview(
                short_summary=response.get("short_summary", ""),
                candidate_viewpoints=response.get("viewpoints", []),
                candidate_facts=response.get("facts", []),
                candidate_timeline_events=response.get("timeline_events", []),
                conflict_candidates=response.get("conflicts", []),
                recommended_classification=WebPageClassification(response.get("classification", "uncertain")),
                recommended_trust=response.get("recommended_trust", "uncertain"),
            )
        except Exception as e:
            logger.warning("LLM preview extraction failed: %s", e)
            return None

    def _is_duplicate_by_fingerprint(self, fingerprint: str) -> bool:
        """Check for exact duplicates by content fingerprint."""
        if fingerprint in self.processed_fingerprints:
            return True
            
        # Check existing pages in collection
        for page_id in self._list_processed_page_ids():
            p_paths = get_web_page_paths(self.paths.collection_dir, page_id)
            if p_paths.manifest_path.exists():
                try:
                    m = read_web_page_manifest(p_paths.manifest_path)
                    if m.get("content_fingerprint") == fingerprint:
                        self.processed_fingerprints.add(fingerprint)
                        return True
                except Exception:
                    continue
        
        self.processed_fingerprints.add(fingerprint)
        return False

    def _is_near_duplicate(self, page_id: str, content: str, embedding: Optional[List[float]]) -> Optional[Dict[str, Any]]:
        """Check for near-duplicates using embedding similarity."""
        if not embedding or not self.embedding_client:
            return None

        for other_id in self._list_processed_page_ids():
            if other_id == page_id:
                continue
                
            p_paths = get_web_page_paths(self.paths.collection_dir, other_id)
            if not p_paths.manifest_path.exists():
                continue
                
            try:
                m = read_web_page_manifest(p_paths.manifest_path)
                other_similarity = m.get("similarity_metadata", {})
                other_embedding = other_similarity.get("embedding")
                
                if other_embedding:
                    from asky.research.vector_store_common import cosine_similarity
                    similarity = cosine_similarity(embedding, other_embedding)
                    if similarity >= 0.92:
                        return {
                            "reason": "embedding_similarity",
                            "matched_page_id": other_id,
                            "similarity_score": similarity
                        }
            except Exception:
                continue
        return None

    def _get_normalized_host(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower().rstrip(".")
            return host
        except Exception:
            return ""

    def _get_seed_host_allowlist(self, seed_urls: Sequence[str]) -> Set[str]:
        allowlist = set()
        for url in seed_urls:
            host = self._get_normalized_host(url)
            if not host:
                continue
            allowlist.add(host)
            # www alias rule: if example.com is seeded, allow www.example.com and vice versa
            if host.startswith("www."):
                allowlist.add(host[4:])
            elif host.count(".") == 1: # Basic apex detection
                allowlist.add(f"www.{host}")
        return allowlist

    def _is_in_seed_hosts(self, url: str) -> bool:
        host = self._get_normalized_host(url)
        return host in self.seed_hosts if host else False

    def _get_processed_urls(self) -> Set[str]:
        urls = set()
        for page_id in self._list_processed_page_ids():
            p_paths = get_web_page_paths(self.paths.collection_dir, page_id)
            if p_paths.manifest_path.exists():
                try:
                    m = read_web_page_manifest(p_paths.manifest_path)
                    if m.get("normalized_final_url"):
                        urls.add(m["normalized_final_url"])
                    if m.get("requested_url"):
                        urls.add(normalize_url(m["requested_url"]))
                except Exception:
                    continue
        return urls

    def _list_processed_page_ids(self) -> List[str]:
        pages_root = self.paths.collection_dir / "pages"
        if not pages_root.exists():
            return []
        return [p.name for p in pages_root.iterdir() if p.is_dir()]

    def _count_review_ready(self) -> int:
        count = 0
        for page_id in self._list_processed_page_ids():
            p_paths = get_web_page_paths(self.paths.collection_dir, page_id)
            if p_paths.manifest_path.exists():
                try:
                    m = read_web_page_manifest(p_paths.manifest_path)
                    if m.get("status") == WebPageStatus.REVIEW_READY:
                        count += 1
                except Exception:
                    continue
        return count

    def _calculate_fingerprint(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _save_failed_page(self, url: str, payload: Dict[str, Any], retrieval_info: Optional[RetrievalProvenance] = None):
        error = payload.get("error", "Unknown error")
        normalized_url = normalize_url(url)
        # Use a hash of the URL for failed pages to avoid ID collisions with valid pages
        page_id = f"failed:{hashlib.sha256(normalized_url.encode('utf-8')).hexdigest()[:16]}"
        p_paths = get_web_page_paths(self.paths.collection_dir, page_id)
        p_paths.page_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = WebPageManifest(
            page_id=page_id,
            status=WebPageStatus.FETCH_FAILED,
            requested_url=url,
            final_url=payload.get("final_url", url),
            normalized_final_url=normalize_url(payload.get("final_url", url)),
            title="",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
        write_web_page_manifest(p_paths.manifest_path, dataclasses.asdict(manifest))
        
        report = WebPageReport(
            page_id=page_id,
            status=WebPageStatus.FETCH_FAILED,
            requested_url=url,
            final_url=payload.get("final_url", url),
            normalized_final_url=normalize_url(payload.get("final_url", url)),
            title="",
            failure_reason=error,
            retrieval=retrieval_info,
            created_at=datetime.now(UTC).isoformat(),
        )
        write_web_page_report(p_paths.report_path, dataclasses.asdict(report))

    def _save_duplicate_page(
        self, 
        url: str, 
        payload: Dict[str, Any], 
        reason: str, 
        matched_page_id: Optional[str] = None,
        fingerprint: Optional[str] = None,
        similarity_score: Optional[float] = None,
        retrieval_info: Optional[RetrievalProvenance] = None,
    ):
        normalized_url = normalize_url(url)
        page_id = f"dup:{hashlib.sha256(normalized_url.encode('utf-8')).hexdigest()[:16]}"
        p_paths = get_web_page_paths(self.paths.collection_dir, page_id)
        p_paths.page_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = WebPageManifest(
            page_id=page_id,
            status=WebPageStatus.DUPLICATE_FILTERED,
            requested_url=url,
            final_url=payload.get("final_url", url),
            normalized_final_url=normalize_url(payload.get("final_url", url)),
            title=payload.get("title", ""),
            content_fingerprint=fingerprint or "",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
        write_web_page_manifest(p_paths.manifest_path, dataclasses.asdict(manifest))
        
        report = WebPageReport(
            page_id=page_id,
            status=WebPageStatus.DUPLICATE_FILTERED,
            requested_url=url,
            final_url=payload.get("final_url", url),
            normalized_final_url=normalize_url(payload.get("final_url", url)),
            title=payload.get("title", ""),
            duplicate_info=DuplicateMetadata(
                reason=reason,
                matched_page_id=matched_page_id,
                similarity_score=similarity_score,
            ),
            content_fingerprint=fingerprint or "",
            retrieval=retrieval_info,
            created_at=datetime.now(UTC).isoformat(),
        )
        write_web_page_report(p_paths.report_path, dataclasses.asdict(report))

    def _update_manifest_status(self, manifest: WebCollectionManifest, status: WebCollectionStatus):
        manifest_data = read_web_collection_manifest(self.paths.manifest_path)
        manifest_data["status"] = status.value
        manifest_data["updated_at"] = datetime.now(UTC).isoformat()
        write_web_collection_manifest(self.paths.manifest_path, manifest_data)

    def _write_page_preview(self, path: Path, preview: WebPagePreview):
        payload = dataclasses.asdict(preview)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
