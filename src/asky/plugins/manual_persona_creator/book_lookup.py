"""Metadata lookup and preflight services for authored books."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from asky.plugins.manual_persona_creator.book_types import (
    BookMetadata,
    ExtractionTargets,
    MetadataCandidate,
    PreflightResult,
    IngestionJobManifest,
)
from asky.plugins.manual_persona_creator.storage import (
    get_book_key,
    get_book_paths,
    get_job_paths,
    get_persona_paths,
    list_books,
    list_jobs,
    read_book_metadata,
    read_job_manifest,
)
from asky.research.adapters import fetch_source_via_adapter

ISBN_PATTERN = re.compile(r"(?:ISBN(?:-1[03])?:?\s*)?((?:97[89][-\s]?)?[0-9]{1,5}[-\s]?[0-9]+[-\s]?[0-9]+[-\s]?[0-9X])")
OPEN_LIBRARY_BASE_URL = "https://openlibrary.org"


def extract_isbn(text: str) -> Optional[str]:
    """Extract first ISBN-10 or ISBN-13 candidate from text."""
    for match in ISBN_PATTERN.finditer(text):
        raw = match.group(1)
        normalized = re.sub(r"[^0-9X]", "", raw.upper())
        if len(normalized) in {10, 13}:
            return normalized
    return None


def lookup_open_library_metadata(
    *,
    isbn: Optional[str] = None,
    title: Optional[str] = None,
    author: Optional[str] = None,
) -> List[MetadataCandidate]:
    """Lookup book metadata from OpenLibrary API."""
    candidates: List[MetadataCandidate] = []
    
    if isbn:
        try:
            resp = requests.get(
                f"{OPEN_LIBRARY_BASE_URL}/api/books",
                params={"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            book_data = data.get(f"ISBN:{isbn}")
            if book_data:
                candidates.append(MetadataCandidate(
                    metadata=_map_ol_book_to_metadata(book_data, isbn),
                    confidence=1.0,
                    is_ambiguous=False
                ))
        except Exception:
            pass

    if not candidates and title:
        try:
            query = title
            if author:
                query += f" {author}"
            resp = requests.get(
                f"{OPEN_LIBRARY_BASE_URL}/search.json",
                params={"q": query, "limit": 3},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            docs = data.get("docs", [])
            for i, doc in enumerate(docs):
                confidence = 0.9 - (i * 0.1)
                candidates.append(MetadataCandidate(
                    metadata=_map_ol_search_doc_to_metadata(doc),
                    confidence=max(0.1, confidence),
                    is_ambiguous=len(docs) > 1
                ))
        except Exception:
            pass
            
    return candidates


def _map_ol_book_to_metadata(data: Dict[str, Any], isbn: str) -> BookMetadata:
    title = data.get("title", "Unknown Title")
    authors = [a.get("name") for a in data.get("authors", []) if a.get("name")]
    
    pub_date = data.get("publish_date", "")
    pub_year = None
    year_match = re.search(r"\b(19|20)\d{2}\b", pub_date)
    if year_match:
        pub_year = int(year_match.group(0))
        
    return BookMetadata(
        title=title,
        authors=authors,
        publication_year=pub_year,
        isbn=isbn,
        publisher=data.get("publishers", [{}])[0].get("name"),
    )


def _map_ol_search_doc_to_metadata(doc: Dict[str, Any]) -> BookMetadata:
    title = doc.get("title", "Unknown Title")
    authors = doc.get("author_name", [])
    
    pub_year = doc.get("first_publish_year")
    isbn_list = doc.get("isbn", [])
    isbn = isbn_list[0] if isbn_list else None
    
    return BookMetadata(
        title=title,
        authors=authors,
        publication_year=pub_year,
        isbn=isbn,
        publisher=doc.get("publisher", [None])[0],
    )


def compute_extraction_targets(word_count: int) -> ExtractionTargets:
    """Compute proposed extraction targets from word count."""
    topic_target = max(8, min(24, math.ceil(word_count / 7500)))
    viewpoint_target = topic_target * 3
    return ExtractionTargets(topic_target=topic_target, viewpoint_target=viewpoint_target)


def get_source_fingerprint(content: str) -> str:
    """Compute a deterministic fingerprint for source content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def run_preflight(
    *,
    persona_name: str,
    source_path: str,
    data_dir: Path,
) -> PreflightResult:
    """Read source, lookup metadata, and compute targets."""
    path = Path(source_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")
        
    # Use adapter to read content
    target = f"local://{path.resolve().as_posix()}"
    source_data = fetch_source_via_adapter(target, operation="read")
    if not source_data or source_data.get("error"):
        error = source_data.get("error") if source_data else "Failed to read source"
        raise ValueError(f"Could not read source {source_path}: {error}")
        
    content = source_data.get("content", "")
    title_from_filename = path.stem.replace("_", " ").replace("-", " ").title()
    
    # Extract ISBN from first 2000 chars
    front_matter = content[:2000]
    isbn = extract_isbn(front_matter) or extract_isbn(path.name)
    
    candidates = lookup_open_library_metadata(
        isbn=isbn,
        title=title_from_filename,
        author=persona_name,
    )
    
    word_count = len(content.split())
    char_count = len(content)
    # Estimate section count (placeholder for now)
    section_count = content.count("\n\n") // 2
    
    targets = compute_extraction_targets(word_count)
    fingerprint = get_source_fingerprint(content)
    
    stats = {
        "word_count": word_count,
        "char_count": char_count,
        "section_count": section_count,
    }
    
    # Duplicate and resumable job checks
    paths = get_persona_paths(data_dir, persona_name)
    is_duplicate = False
    existing_book_key = None
    resumable_job_id = None
    resumable_manifest = None

    # 1. Check if any candidate metadata matches an existing book key
    for cand in candidates:
        m = cand.metadata
        book_key = get_book_key(title=m.title, publication_year=m.publication_year, isbn=m.isbn)
        book_paths = get_book_paths(paths.root_dir, book_key)
        if book_paths.metadata_path.exists():
            is_duplicate = True
            existing_book_key = book_key
            break

    # 2. Check for resumable jobs with the same source fingerprint
    if not is_duplicate:
        for job_id in list_jobs(paths.root_dir):
            job_paths = get_job_paths(paths.root_dir, job_id)
            try:
                manifest_data = read_job_manifest(job_paths.manifest_path)
                if (manifest_data.get("source_fingerprint") == fingerprint and 
                    manifest_data.get("status") not in {"completed", "cancelled"}):
                    resumable_job_id = job_id
                    resumable_manifest = IngestionJobManifest(
                        job_id=manifest_data["job_id"],
                        persona_name=manifest_data["persona_name"],
                        source_path=manifest_data["source_path"],
                        source_fingerprint=manifest_data["source_fingerprint"],
                        status=manifest_data["status"],
                        mode=manifest_data.get("mode", "ingest"),
                        created_at=manifest_data["created_at"],
                        updated_at=manifest_data["updated_at"],
                        metadata=BookMetadata(**manifest_data["metadata"]),
                        targets=ExtractionTargets(**manifest_data["targets"]),
                        stages_completed=manifest_data.get("stages_completed", []),
                        stage_timings=manifest_data.get("stage_timings", {}),
                        warnings=manifest_data.get("warnings", []),
                        error=manifest_data.get("error"),
                    )
                    break
            except Exception:
                continue

    return PreflightResult(
        source_path=str(path.resolve()),
        source_fingerprint=fingerprint,
        candidates=candidates,
        proposed_targets=targets,
        stats=stats,
        is_duplicate=is_duplicate,
        existing_book_key=existing_book_key,
        resumable_job_id=resumable_job_id,
        resumable_manifest=resumable_manifest,
    )
