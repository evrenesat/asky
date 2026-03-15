from __future__ import annotations

import json
from pathlib import Path
import dataclasses

import pytest
from asky.plugins.manual_persona_creator.storage import (
    get_promoted_web_source_id,
    get_source_bundle_paths,
    get_web_page_paths,
    get_web_collection_paths,
)
from asky.plugins.manual_persona_creator.web_types import (
    WebFrontierState,
    WebPageReport,
    WebPageStatus,
    RetrievalProvenance,
    DuplicateMetadata,
)

def test_stable_web_source_id():
    """Verify web source IDs stay stable when content fingerprint changes."""
    url = "https://example.com/page"
    normalized_url = "example.com/page"
    
    id1 = get_promoted_web_source_id(normalized_url)
    id2 = get_promoted_web_source_id(normalized_url)
    
    assert id1 == id2
    assert id1.startswith("source:web:")
    assert len(id1.split(":")[-1]) == 16
    
    # Different URL -> different ID
    assert get_promoted_web_source_id("example.com/other") != id1

def test_source_bundle_paths_includes_content():
    """Verify source bundle paths now include content.md."""
    persona_root = Path("/tmp/arendt")
    source_id = "source:web:abc123def4567890"
    paths = get_source_bundle_paths(persona_root, source_id)
    
    assert paths.content_path == paths.source_dir / "content.md"

def test_frontier_state_dataclass():
    """Verify frontier state fields."""
    state = WebFrontierState(
        queue=["url1", "url2"],
        seen_candidate_urls=["url1", "url2", "url3"],
        fetched_candidate_urls=["url1"],
        raw_unique_fetch_count=1,
        overcollect_cap=13
    )
    assert state.queue == ["url1", "url2"]
    assert state.raw_unique_fetch_count == 1
    assert state.overcollect_cap == 13

def test_page_report_round_trip():
    """Verify page report can be represented as dict and back (simulating JSON storage)."""
    report = WebPageReport(
        page_id="page:123",
        status=WebPageStatus.REVIEW_READY,
        requested_url="https://example.com",
        final_url="https://example.com/",
        normalized_final_url="example.com/",
        title="Example",
        retrieval=RetrievalProvenance(
            provider="playwright",
            source="chromium",
            page_type="html",
            trace_events=[{"event": "fetch"}]
        ),
        duplicate_info=DuplicateMetadata(
            reason="embedding_similarity",
            matched_page_id="page:456",
            similarity_score=0.95
        ),
        discovery_provenance="extracted_link",
        content_fingerprint="sha256:abc",
        created_at="2026-03-14T12:00:00Z"
    )
    
    # Simple asdict check
    data = dataclasses.asdict(report)
    assert data["page_id"] == "page:123"
    assert data["retrieval"]["provider"] == "playwright"
    assert data["duplicate_info"]["reason"] == "embedding_similarity"
    assert data["duplicate_info"]["similarity_score"] == 0.95

def test_storage_helpers_round_trip(tmp_path: Path):
    """Verify frontier and report helpers work."""
    from asky.plugins.manual_persona_creator.storage import (
        read_web_frontier,
        write_web_frontier,
        read_web_page_report,
        write_web_page_report,
    )
    
    # Frontier
    frontier_path = tmp_path / "frontier.json"
    state = {
        "queue": ["a"],
        "seen_candidate_urls": ["a", "b"],
        "fetched_candidate_urls": ["a"],
        "raw_unique_fetch_count": 1,
        "overcollect_cap": 13
    }
    write_web_frontier(frontier_path, state)
    assert read_web_frontier(frontier_path) == state
    
    # Legacy Frontier fallback
    frontier_path.write_text(json.dumps(["url1", "url2"]), encoding="utf-8")
    assert read_web_frontier(frontier_path) == {"queue": ["url1", "url2"]}
    
    # Report
    report_path = tmp_path / "report.json"
    report_data = {"page_id": "p1", "status": "review_ready"}
    write_web_page_report(report_path, report_data)
    assert read_web_page_report(report_path) == report_data

def test_legacy_source_bundle_resolution_and_migration(tmp_path: Path):
    """Verify get_source_bundle_paths resolves legacy slugged directories and ensure_canonical migrates them."""
    from asky.plugins.manual_persona_creator.storage import (
        get_source_bundle_paths,
        ensure_canonical_source_bundle,
        INGESTED_SOURCES_DIR_NAME,
    )
    
    persona_root = tmp_path / "arendt"
    persona_root.mkdir(parents=True)
    
    source_id = "source:web:73d986e009065f18"
    slugged_id = "source_web_73d986e009065f18"
    
    ingested_root = persona_root / INGESTED_SOURCES_DIR_NAME
    ingested_root.mkdir()
    
    slugged_dir = ingested_root / slugged_id
    slugged_dir.mkdir()
    (slugged_dir / "source.toml").write_text("test = true", encoding="utf-8")
    
    # 1. Test get_source_bundle_paths resolution (read-only)
    paths = get_source_bundle_paths(persona_root, source_id)
    assert paths.source_dir == slugged_dir
    assert paths.metadata_path.exists()
    
    # 2. Test ensure_canonical_source_bundle migration (write)
    canonical_paths = ensure_canonical_source_bundle(persona_root, source_id)
    canonical_dir = ingested_root / source_id
    
    assert canonical_dir.exists()
    assert not slugged_dir.exists()
    assert canonical_paths.source_dir == canonical_dir
    assert (canonical_dir / "source.toml").read_text(encoding="utf-8") == "test = true"
    
    # 3. Test idempotence
    paths_again = ensure_canonical_source_bundle(persona_root, source_id)
    assert paths_again.source_dir == canonical_dir
    assert canonical_dir.exists()
