from __future__ import annotations

import logging
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import tomlkit
import tomllib

from asky.plugins.manual_persona_creator.storage import (
    get_persona_paths,
    get_web_collection_id,
    get_web_collection_paths,
    get_web_page_paths,
    list_web_collections,
    list_web_pages,
)
from asky.plugins.manual_persona_creator.web_job import WebCollectionJob
from asky.plugins.manual_persona_creator.web_types import (
    WebCollectionManifest,
    WebCollectionMode,
    WebCollectionInputMode,
    WebCollectionStatus,
)

logger = logging.getLogger(__name__)


def start_seed_domain_collection(
    *,
    data_dir: Path,
    persona_name: str,
    target_results: int,
    urls: List[str],
    url_file: Optional[Path] = None,
    embedding_client: Optional[Any] = None,
    llm_client: Optional[Any] = None,
) -> str:
    """Start a new bounded seed-domain web collection."""
    paths = get_persona_paths(data_dir, persona_name)
    if not paths.metadata_path.exists():
        raise ValueError(f"Persona '{persona_name}' not found.")

    with paths.metadata_path.open("rb") as f:
        meta = tomllib.load(f)
    persona_description = meta.get("persona", {}).get("description", "")

    seed_inputs = list(urls)
    input_mode = WebCollectionInputMode.SEED_URLS
    
    if url_file:
        input_mode = WebCollectionInputMode.SEED_URLS # Actually same mode but different source
        if not url_file.exists():
            raise FileNotFoundError(f"URL file not found: {url_file}")
        content = url_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                seed_inputs.append(line)

    # Normalize bare domains
    normalized_seeds = []
    for s in seed_inputs:
        if not s.startswith(("http://", "https://")):
            normalized_seeds.append(f"https://{s}")
        else:
            normalized_seeds.append(s)

    collection_id = get_web_collection_id()
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True, exist_ok=True)

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.SEED_DOMAIN,
        input_mode=input_mode,
        status=WebCollectionStatus.COLLECTING,
        target_results=target_results,
        seed_inputs=normalized_seeds,
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )

    _write_collection_manifest(c_paths.manifest_path, manifest)

    # In a real system, we'd spawn a background job.
    # For now, we'll run it synchronously or rely on the caller to call run().
    job = WebCollectionJob(
        persona_name=persona_name,
        persona_description=persona_description,
        paths=c_paths,
        target_results=target_results,
        mode=WebCollectionMode.SEED_DOMAIN,
        embedding_client=embedding_client,
        llm_client=llm_client,
    )
    job.run(manifest)

    return collection_id


def start_broad_web_expansion(
    *,
    data_dir: Path,
    persona_name: str,
    target_results: int,
    query: Optional[str] = None,
    urls: Optional[List[str]] = None,
    url_file: Optional[Path] = None,
    embedding_client: Optional[Any] = None,
    llm_client: Optional[Any] = None,
) -> str:
    """Start a broad public-web expansion."""
    paths = get_persona_paths(data_dir, persona_name)
    if not paths.metadata_path.exists():
        raise ValueError(f"Persona '{persona_name}' not found.")

    with paths.metadata_path.open("rb") as f:
        meta = tomllib.load(f)
    persona_description = meta.get("persona", {}).get("description", "")

    seed_inputs = list(urls or [])
    input_mode = WebCollectionInputMode.SEED_URLS
    
    if query:
        input_mode = WebCollectionInputMode.SEARCH_QUERY
        seed_inputs = [query]
    elif url_file:
        if not url_file.exists():
            raise FileNotFoundError(f"URL file not found: {url_file}")
        content = url_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                seed_inputs.append(line)

    # Normalize bare domains
    normalized_seeds = []
    for s in seed_inputs:
        if input_mode == WebCollectionInputMode.SEED_URLS and not s.startswith(("http://", "https://")):
            normalized_seeds.append(f"https://{s}")
        else:
            normalized_seeds.append(s)

    collection_id = get_web_collection_id()
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    c_paths.collection_dir.mkdir(parents=True, exist_ok=True)

    manifest = WebCollectionManifest(
        collection_id=collection_id,
        persona_name=persona_name,
        mode=WebCollectionMode.BROAD_EXPAND,
        input_mode=input_mode,
        status=WebCollectionStatus.COLLECTING,
        target_results=target_results,
        seed_inputs=normalized_seeds,
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )

    _write_collection_manifest(c_paths.manifest_path, manifest)

    job = WebCollectionJob(
        persona_name=persona_name,
        persona_description=persona_description,
        paths=c_paths,
        target_results=target_results,
        mode=WebCollectionMode.BROAD_EXPAND,
        embedding_client=embedding_client,
        llm_client=llm_client,
    )
    job.run(manifest)

    return collection_id


def continue_collection(
    *,
    data_dir: Path,
    persona_name: str,
    collection_id: str,
    embedding_client: Optional[Any] = None,
    llm_client: Optional[Any] = None,
) -> None:
    """Resume an existing collection."""
    paths = get_persona_paths(data_dir, persona_name)
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    
    if not c_paths.manifest_path.exists():
        raise ValueError(f"Collection '{collection_id}' not found.")

    with paths.metadata_path.open("rb") as f:
        meta = tomllib.load(f)
    persona_description = meta.get("persona", {}).get("description", "")

    with c_paths.manifest_path.open("rb") as f:
        m_data = tomllib.load(f)
    
    manifest = WebCollectionManifest(
        collection_id=m_data["collection_id"],
        persona_name=m_data["persona_name"],
        mode=WebCollectionMode(m_data["mode"]),
        input_mode=WebCollectionInputMode(m_data["input_mode"]),
        status=WebCollectionStatus(m_data["status"]),
        target_results=m_data["target_results"],
        seed_inputs=m_data.get("seed_inputs", []),
        created_at=m_data.get("created_at", ""),
        updated_at=m_data.get("updated_at", ""),
    )

    job = WebCollectionJob(
        persona_name=persona_name,
        persona_description=persona_description,
        paths=c_paths,
        target_results=manifest.target_results,
        mode=manifest.mode,
        embedding_client=embedding_client,
        llm_client=llm_client,
    )
    job.run(manifest)


def get_collection_review_pages(
    *,
    data_dir: Path,
    persona_name: str,
    collection_id: str,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List review-ready pages for a collection."""
    paths = get_persona_paths(data_dir, persona_name)
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    
    pages = []
    for page_id in list_web_pages(c_paths.collection_dir):
        p_paths = get_web_page_paths(c_paths.collection_dir, page_id)
        if p_paths.manifest_path.exists():
            with p_paths.manifest_path.open("rb") as f:
                m = tomllib.load(f)
                if status and m.get("status") != status:
                    continue
                pages.append(m)
    return pages


def approve_web_page(
    *,
    data_dir: Path,
    persona_name: str,
    collection_id: str,
    page_id: str,
    trust_as: Optional[str] = None,
) -> None:
    """Approve a scraped page and project into persona knowledge."""
    from asky.plugins.manual_persona_creator.knowledge_types import (
        PersonaSourceClass,
        PersonaTrustClass,
    )
    from asky.plugins.manual_persona_creator.web_types import (
        WebPageStatus,
        WebPageClassification,
    )
    from asky.plugins.manual_persona_creator.storage import (
        get_promoted_web_source_id,
    )
    from asky.plugins.manual_persona_creator.source_service import project_source_knowledge

    paths = get_persona_paths(data_dir, persona_name)
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)

    if not p_paths.manifest_path.exists():
        raise ValueError(f"Page '{page_id}' not found in collection '{collection_id}'.")

    with p_paths.manifest_path.open("rb") as f:
        m = tomllib.load(f)
    
    classification = WebPageClassification(m.get("classification", "uncertain"))
    
    # Apply trust/classification rules
    if trust_as == "authored":
        trust_class = PersonaTrustClass.AUTHORED_PRIMARY
    elif trust_as == "about":
        trust_class = PersonaTrustClass.THIRD_PARTY_SECONDARY
    elif classification == WebPageClassification.AUTHORED_BY_PERSONA:
        trust_class = PersonaTrustClass.AUTHORED_PRIMARY
    elif classification == WebPageClassification.ABOUT_PERSONA:
        trust_class = PersonaTrustClass.THIRD_PARTY_SECONDARY
    elif classification == WebPageClassification.UNCERTAIN:
        raise ValueError("Cannot approve 'uncertain' page without --as authored|about.")
    else:
        raise ValueError(f"Cannot approve page with classification '{classification}'.")

    source_id = get_promoted_web_source_id(m["normalized_final_url"])

    # Materialize Milestone-3 Source Bundle
    from asky.plugins.manual_persona_creator.storage import (
        ensure_canonical_source_bundle,
        write_source_metadata,
        read_web_page_report,
        write_web_page_report,
    )
    from asky.plugins.manual_persona_creator.source_types import (
        PersonaSourceKind,
        PersonaReviewStatus,
    )
    import shutil

    bundle_paths = ensure_canonical_source_bundle(paths.root_dir, source_id)
    bundle_paths.source_dir.mkdir(parents=True, exist_ok=True)

    # Copy content
    if p_paths.content_path.exists():
        shutil.copy2(p_paths.content_path, bundle_paths.content_path)

    # Write source.toml
    source_metadata = {
        "source_id": source_id,
        "source_class": PersonaSourceClass.SCRAPED_WEB.value,
        "trust_class": trust_class.value,
        "label": m.get("title", m["final_url"]),
        "kind": PersonaSourceKind.WEB_PAGE.value,
        "review_status": PersonaReviewStatus.APPROVED.value,
        "updated_at": datetime.now(UTC).isoformat(),
        "metadata": {
            "requested_url": m.get("requested_url"),
            "final_url": m.get("final_url"),
            "normalized_final_url": m.get("normalized_final_url"),
            "content_fingerprint": m.get("content_fingerprint"),
            "collection_id": collection_id,
            "page_id": page_id,
            "classification": classification.value,
        },
    }
    # Add retrieval provenance to source metadata if available
    report_data = read_web_page_report(p_paths.report_path)
    if report_data.get("retrieval"):
        source_metadata["metadata"]["retrieval"] = report_data["retrieval"]

    write_source_metadata(bundle_paths.metadata_path, source_metadata)

    # Read preview for knowledge extraction
    preview = {}
    if p_paths.preview_path.exists():
        preview = json.loads(p_paths.preview_path.read_text(encoding="utf-8"))

    # Project extracted knowledge into bundle-local files for durability
    extracted_counts = {
        "viewpoints": 0,
        "facts": 0,
        "timeline": 0,
        "conflicts": 0,
    }
    if preview.get("candidate_viewpoints"):
        extracted_counts["viewpoints"] = len(preview["candidate_viewpoints"])
        bundle_paths.viewpoints_path.write_text(
            json.dumps(preview["candidate_viewpoints"], indent=2), encoding="utf-8"
        )
    if preview.get("candidate_facts"):
        extracted_counts["facts"] = len(preview["candidate_facts"])
        bundle_paths.facts_path.write_text(
            json.dumps(preview["candidate_facts"], indent=2), encoding="utf-8"
        )
    if preview.get("candidate_timeline_events"):
        extracted_counts["timeline"] = len(preview["candidate_timeline_events"])
        bundle_paths.timeline_path.write_text(
            json.dumps(preview["candidate_timeline_events"], indent=2), encoding="utf-8"
        )
    if preview.get("conflict_candidates"):
        extracted_counts["conflicts"] = len(preview["conflict_candidates"])
        bundle_paths.conflicts_path.write_text(
            json.dumps(preview["conflict_candidates"], indent=2), encoding="utf-8"
        )

    # Write source bundle report.json for generic source-report compatibility
    from asky.plugins.manual_persona_creator.source_types import PersonaSourceReportRecord
    from dataclasses import asdict
    
    bundle_report = PersonaSourceReportRecord(
        source_id=source_id,
        kind=PersonaSourceKind.WEB_PAGE,
        status="success",
        extracted_counts=extracted_counts,
        review_timestamp=datetime.now(UTC).isoformat(),
        metadata={
            "final_url": m.get("final_url"),
            "collection_id": collection_id,
            "page_id": page_id,
            "retrieval": report_data.get("retrieval"),
            "discovery_provenance": report_data.get("discovery_provenance"),
        }
    )
    bundle_paths.report_path.write_text(
        json.dumps(asdict(bundle_report), indent=2), encoding="utf-8"
    )

    # Project into canonical knowledge
    project_source_knowledge(
        persona_root=paths.root_dir,
        source_id=source_id,
        source_class=PersonaSourceClass.SCRAPED_WEB,
        trust_class=trust_class,
        label=m.get("title", m["final_url"]),
        source_kind="web_page",
        content_path=bundle_paths.content_path,
        viewpoints_path=bundle_paths.viewpoints_path if bundle_paths.viewpoints_path.exists() else None,
        facts_path=bundle_paths.facts_path if bundle_paths.facts_path.exists() else None,
        timeline_path=bundle_paths.timeline_path if bundle_paths.timeline_path.exists() else None,
        conflicts_path=bundle_paths.conflicts_path if bundle_paths.conflicts_path.exists() else None,
        metadata=source_metadata["metadata"],
    )

    # Update page status
    import tomlkit
    with p_paths.manifest_path.open("r", encoding="utf-8") as f:
        doc = tomlkit.load(f)
    doc["status"] = WebPageStatus.APPROVED.value
    doc["approved_as_trust"] = trust_class.value
    doc["promoted_source_id"] = source_id
    doc["updated_at"] = datetime.now(UTC).isoformat()
    p_paths.manifest_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    # Update report with promoted_source_id
    report_data = read_web_page_report(p_paths.report_path)
    report_data["status"] = WebPageStatus.APPROVED.value
    report_data["promoted_source_id"] = source_id
    write_web_page_report(p_paths.report_path, report_data)


def retract_web_page(
    *,
    data_dir: Path,
    persona_name: str,
    collection_id: str,
    page_id: str,
) -> None:
    """Retract an approved scraped page back to review_ready."""
    from asky.plugins.manual_persona_creator.web_types import WebPageStatus
    from asky.plugins.manual_persona_creator.source_service import retract_source_bundle
    
    paths = get_persona_paths(data_dir, persona_name)
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)

    if not p_paths.manifest_path.exists():
        raise ValueError(f"Page '{page_id}' not found in collection '{collection_id}'.")

    with p_paths.manifest_path.open("rb") as f:
        m = tomllib.load(f)
    
    if m.get("status") != WebPageStatus.APPROVED.value:
        return # Only approved pages can be retracted

    source_id = m.get("promoted_source_id")
    if source_id:
        retract_source_bundle(data_dir=data_dir, persona_name=persona_name, source_id=source_id)

    # Update page status back to review_ready
    import tomlkit
    with p_paths.manifest_path.open("r", encoding="utf-8") as f:
        doc = tomlkit.load(f)
    doc["status"] = WebPageStatus.REVIEW_READY.value
    if "approved_as_trust" in doc:
        del doc["approved_as_trust"]
    doc["updated_at"] = datetime.now(UTC).isoformat()
    p_paths.manifest_path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    # Update report
    from asky.plugins.manual_persona_creator.storage import read_web_page_report, write_web_page_report
    report_data = read_web_page_report(p_paths.report_path)
    report_data["status"] = WebPageStatus.REVIEW_READY.value
    write_web_page_report(p_paths.report_path, report_data)


def reject_web_page(
    *,
    data_dir: Path,
    persona_name: str,
    collection_id: str,
    page_id: str,
) -> None:
    """Reject a scraped page."""
    from asky.plugins.manual_persona_creator.web_types import WebPageStatus
    from asky.plugins.manual_persona_creator.source_service import unproject_source_knowledge
    from asky.plugins.manual_persona_creator.storage import (
        get_promoted_web_source_id,
        get_source_bundle_paths,
    )
    import shutil
    
    paths = get_persona_paths(data_dir, persona_name)
    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)

    if not p_paths.manifest_path.exists():
        raise ValueError(f"Page '{page_id}' not found in collection '{collection_id}'.")

    with p_paths.manifest_path.open("rb") as f:
        m = tomllib.load(f)
    
    # If previously approved, remove from knowledge and delete source bundle
    if m.get("status") == WebPageStatus.APPROVED.value:
        source_id = get_promoted_web_source_id(m["normalized_final_url"])
        unproject_source_knowledge(persona_root=paths.root_dir, source_id=source_id)
        
        bundle_paths = get_source_bundle_paths(paths.root_dir, source_id)
        if bundle_paths.source_dir.exists():
            shutil.rmtree(bundle_paths.source_dir)

    # Update page status
    import tomlkit
    with p_paths.manifest_path.open("r", encoding="utf-8") as f:
        doc = tomlkit.load(f)
    doc["status"] = WebPageStatus.REJECTED.value
    doc["updated_at"] = datetime.now(UTC).isoformat()
    p_paths.manifest_path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _write_collection_manifest(path: Path, manifest: WebCollectionManifest):
    doc = tomlkit.document()
    for k, v in manifest.__dict__.items():
        if v is not None:
            if hasattr(v, "value"): # Enum
                doc[k] = v.value
            else:
                doc[k] = v
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
