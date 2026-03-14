"""Authored-book ingestion backend and extraction pipeline."""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from asky.config import (
    DEFAULT_MODEL,
    MODELS,
    SUMMARIZATION_MODEL,
)
from asky.core import get_llm_msg
from asky.plugins.manual_persona_creator.book_prompts import (
    BOOK_SUMMARIZATION_PROMPT,
    TOPIC_DISCOVERY_PROMPT,
    VIEWPOINT_EXTRACTION_PROMPT,
)
from asky.plugins.manual_persona_creator.book_types import (
    AuthoredBookReport,
    BookMetadata,
    ExtractionTargets,
    IngestionJobManifest,
    ViewpointEntry,
    ViewpointEvidence,
)
from asky.plugins.manual_persona_creator.knowledge_catalog import (
    rebuild_catalog_from_legacy,
)
from asky.plugins.manual_persona_creator.runtime_index import rebuild_runtime_index
from asky.plugins.manual_persona_creator.storage import (
    AUTHORED_BOOKS_INDEX_FILENAME,
    CHUNKS_FILENAME,
    get_book_key,
    get_book_paths,
    get_job_paths,
    get_persona_paths,
    read_chunks,
    read_job_manifest,
    write_book_metadata,
    write_chunks,
    write_job_manifest,
)
from asky.plugins.persona_manager.knowledge import rebuild_embeddings
from asky.research.adapters import fetch_source_via_adapter
from asky.research.embeddings import get_embedding_client
from asky.research.sections import build_section_index, slice_section_content
from asky.research.vector_store_common import cosine_similarity

logger = logging.getLogger(__name__)


def _validate_topics_payload(payload: Any) -> List[str]:
    """Validate that the topics payload is a list of non-empty strings."""
    if not isinstance(payload, list):
        raise ValueError(f"Expected a list for topics, got {type(payload).__name__}")

    valid_topics = []
    for topic in payload:
        if isinstance(topic, str) and topic.strip():
            valid_topics.append(topic.strip())

    if not valid_topics:
        raise ValueError("No valid topics found in payload")
    return valid_topics


def _validate_viewpoint_payload(payload: Any, topic: str) -> Dict[str, Any]:
    """Validate the viewpoint JSON structure strictly."""
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a dict for viewpoint, got {type(payload).__name__}")

    claim = payload.get("claim")
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("Missing or invalid 'claim'")

    stance = payload.get("stance_label")
    allowed_stances = {"supports", "opposes", "mixed", "descriptive", "unclear"}
    if stance not in allowed_stances:
        raise ValueError(f"Invalid 'stance_label': {stance}. Must be one of {allowed_stances}")

    confidence = payload.get("confidence")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid 'confidence': {confidence}")

    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"Confidence out of range: {confidence}")

    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("Missing or invalid 'evidence' list")

    valid_evidence = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        excerpt = item.get("excerpt")
        ref = item.get("section_ref")
        if isinstance(excerpt, str) and excerpt.strip() and isinstance(ref, str) and ref.strip():
            valid_evidence.append({"excerpt": excerpt.strip(), "section_ref": ref.strip()})

    if not valid_evidence:
        raise ValueError("No valid evidence items found in 'evidence' list")

    return {
        "topic": topic,
        "claim": claim.strip(),
        "stance_label": stance,
        "confidence": confidence,
        "evidence": valid_evidence,
    }


class BookIngestionJob:
    """Orchestrates the multi-pass authored-book ingestion process."""

    def __init__(
        self,
        *,
        data_dir: Path,
        persona_name: str,
        job_id: str,
    ):
        self.data_dir = data_dir
        self.persona_name = persona_name
        self.job_id = job_id
        self.paths = get_persona_paths(data_dir, persona_name)
        self.job_paths = get_job_paths(self.paths.root_dir, job_id)
        self.manifest: Optional[IngestionJobManifest] = None

    def load_manifest(self) -> IngestionJobManifest:
        """Load manifest from disk."""
        data = read_job_manifest(self.job_paths.manifest_path)
        # Convert metadata and targets from dict to dataclass
        metadata = BookMetadata(**data["metadata"])
        targets = ExtractionTargets(**data["targets"])
        self.manifest = IngestionJobManifest(
            job_id=data["job_id"],
            persona_name=data["persona_name"],
            source_path=data["source_path"],
            source_fingerprint=data["source_fingerprint"],
            status=data["status"],
            mode=data.get("mode", "ingest"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            metadata=metadata,
            targets=targets,
            stages_completed=data.get("stages_completed", []),
            stage_timings=data.get("stage_timings", {}),
            warnings=data.get("warnings", []),
            error=data.get("error"),
        )
        return self.manifest

    def save_manifest(self):
        """Save current manifest to disk."""
        if not self.manifest:
            return
        data = {
            "job_id": self.manifest.job_id,
            "persona_name": self.manifest.persona_name,
            "source_path": self.manifest.source_path,
            "source_fingerprint": self.manifest.source_fingerprint,
            "status": self.manifest.status,
            "mode": self.manifest.mode,
            "created_at": self.manifest.created_at,
            "updated_at": self.manifest.updated_at,
            "metadata": asdict(self.manifest.metadata),
            "targets": asdict(self.manifest.targets),
            "stages_completed": self.manifest.stages_completed,
            "stage_timings": self.manifest.stage_timings,
            "warnings": self.manifest.warnings,
            "error": self.manifest.error,
        }
        write_job_manifest(self.job_paths.manifest_path, data)

    def run(self) -> AuthoredBookReport:
        """Execute the ingestion pipeline."""
        if not self.manifest:
            self.load_manifest()

        # Final identity check before running
        book_key = get_book_key(
            title=self.manifest.metadata.title,
            publication_year=self.manifest.metadata.publication_year,
            isbn=self.manifest.metadata.isbn
        )
        book_paths = get_book_paths(self.paths.root_dir, book_key)
        if self.manifest.mode == "ingest" and book_paths.metadata_path.exists():
            raise ValueError(f"Book already exists: {self.manifest.metadata.title}. Use reingest-book to replace.")

        try:
            self._update_status("running")
            
            # 1. Read source
            content = self._run_stage("read_source", self._stage_read_source)
            
            # 2. Summarize sections
            section_summaries = self._run_stage("summarize_sections", self._stage_summarize_sections, content)
            
            # 3. Discover topics
            topics = self._run_stage("discover_topics", self._stage_discover_topics, section_summaries)
            
            # 4. Extract viewpoints
            viewpoints = self._run_stage("extract_viewpoints", self._stage_extract_viewpoints, content, section_summaries, topics)
            
            # 5. Materialize book
            report = self._run_stage("materialize_book", self._stage_materialize_book, viewpoints)
            
            # 6. Project compatibility chunks and rebuild embeddings
            self._run_stage("project_compat_chunks", self._stage_project_compat_chunks, viewpoints)
            
            self._update_status("completed")
            return report
            
        except Exception as e:
            logger.exception("Job %s failed: %s", self.job_id, e)
            self._update_status("failed", error=str(e))
            raise

    def _update_status(self, status: str, error: Optional[str] = None):
        if not self.manifest:
            return
        self.manifest = IngestionJobManifest(
            **{**self.manifest.__dict__, "status": status, "error": error, "updated_at": _utc_now_iso()}
        )
        self.save_manifest()

    def _run_stage(self, stage_name: str, func, *args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start_time
        
        # Accumulate timings
        self.manifest.stage_timings[stage_name] = self.manifest.stage_timings.get(stage_name, 0.0) + duration
        if stage_name not in self.manifest.stages_completed:
            self.manifest.stages_completed.append(stage_name)
        
        self.save_manifest()
        return result

    def _stage_read_source(self) -> str:
        target = f"local://{Path(self.manifest.source_path).resolve().as_posix()}"
        source_data = fetch_source_via_adapter(target, operation="read")
        if not source_data or source_data.get("error"):
            raise ValueError(f"Could not read source: {source_data.get('error') if source_data else 'Unknown'}")
        
        return source_data.get("content", "")

    def _stage_summarize_sections(self, content: str) -> List[Dict[str, str]]:
        summaries_path = self.job_paths.job_dir / "section_summaries.json"
        if summaries_path.exists():
            return json.loads(summaries_path.read_text(encoding="utf-8"))

        section_index = build_section_index(content)
        sections = section_index.get("sections", [])
        if not sections:
            # Fallback to simple chunking if no sections detected
            chunk_size = 10000
            sections = [{"id": f"chunk-{i}", "start_char": i*chunk_size, "end_char": (i+1)*chunk_size} 
                        for i in range(math.ceil(len(content)/chunk_size))]

        summaries = []
        for i, sec in enumerate(sections, 1):
            sec_id = sec.get("id", str(i))
            start = sec.get("start_char", 0)
            end = sec.get("end_char", len(content))
            sec_content = content[start:end].strip()
            if not sec_content:
                continue
                
            prompt = BOOK_SUMMARIZATION_PROMPT.format(
                title=self.manifest.metadata.title,
                authors=", ".join(self.manifest.metadata.authors),
            )
            
            summary = self._call_llm(SUMMARIZATION_MODEL, prompt, sec_content)
            summaries.append({
                "id": sec_id,
                "summary": summary,
                "start_char": start,
                "end_char": end,
            })

        summaries_path.write_text(json.dumps(summaries), encoding="utf-8")
        return summaries

    def _stage_discover_topics(self, summaries: List[Dict[str, str]]) -> List[str]:
        topics_path = self.job_paths.job_dir / "topics.json"
        if topics_path.exists():
            return json.loads(topics_path.read_text(encoding="utf-8"))

        summaries_text = "\n\n".join([f"Section {s['id']}:\n{s['summary']}" for s in summaries])
        prompt = TOPIC_DISCOVERY_PROMPT.format(
            title=self.manifest.metadata.title,
            authors=", ".join(self.manifest.metadata.authors),
            target_count=self.manifest.targets.topic_target,
        )

        response = self._call_llm(DEFAULT_MODEL, prompt, summaries_text)
        try:
            # Extract JSON array
            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON array found in topic discovery response")

            payload = json.loads(json_match.group(0))
            topics = _validate_topics_payload(payload)
        except Exception as e:
            logger.warning("Topic discovery failed for %s: %s", self.manifest.metadata.title, e)
            self.manifest.warnings.append(f"Topic discovery failed: {str(e)}")
            # If discovery fails, we fall back to a generic topic or raise if we must be strict
            # For now, let's keep it strict if discovery fails completely
            raise

        topics = [t for t in topics if t][: self.manifest.targets.topic_target]
        topics_path.write_text(json.dumps(topics), encoding="utf-8")
        return topics

    def _stage_extract_viewpoints(
        self, content: str, summaries: List[Dict[str, str]], topics: List[str]
    ) -> List[ViewpointEntry]:
        viewpoints_path = self.job_paths.job_dir / "viewpoints_scratch.json"
        if viewpoints_path.exists():
            data = json.loads(viewpoints_path.read_text(encoding="utf-8"))
            return [
                ViewpointEntry(**{**v, "evidence": [ViewpointEvidence(**e) for e in v["evidence"]]})
                for v in data
            ]

        client = get_embedding_client()
        summary_vectors = client.embed([s["summary"] for s in summaries])

        all_viewpoints = []
        book_key = get_book_key(
            title=self.manifest.metadata.title,
            publication_year=self.manifest.metadata.publication_year,
            isbn=self.manifest.metadata.isbn,
        )

        for topic in topics:
            topic_vector = client.embed_single(topic)
            scores = []
            for i, vec in enumerate(summary_vectors):
                scores.append((cosine_similarity(topic_vector, vec), i))

            scores.sort(key=lambda x: x[0], reverse=True)
            top_indices = [idx for _, idx in scores[:3]]

            context_parts = []
            for idx in top_indices:
                s = summaries[idx]
                context_parts.append(
                    f"Source Excerpt (Section {s['id']}):\n{content[s['start_char']:s['end_char']]}"
                )

            context = "\n\n---\n\n".join(context_parts)
            prompt = VIEWPOINT_EXTRACTION_PROMPT.format(
                title=self.manifest.metadata.title,
                topic=topic,
            )

            response = self._call_llm(DEFAULT_MODEL, prompt, context)
            try:
                json_match = re.search(r"\{.*\}", response, re.DOTALL)
                if not json_match:
                    raise ValueError(f"No JSON object found in extraction response for topic: {topic}")

                payload = json.loads(json_match.group(0))
                vp_data = _validate_viewpoint_payload(payload, topic)

                entry = ViewpointEntry(
                    entry_id=str(uuid.uuid4()),
                    topic=topic,
                    claim=vp_data["claim"],
                    stance_label=vp_data["stance_label"],
                    confidence=vp_data["confidence"],
                    book_key=book_key,
                    book_title=self.manifest.metadata.title,
                    publication_year=self.manifest.metadata.publication_year,
                    isbn=self.manifest.metadata.isbn,
                    evidence=[ViewpointEvidence(**e) for e in vp_data["evidence"]],
                )
                all_viewpoints.append(entry)
            except Exception as e:
                logger.warning("Failed to parse viewpoint for topic %s: %s", topic, e)
                self.manifest.warnings.append(f"Failed to parse viewpoint for topic {topic}: {str(e)}")

        # Deduplicate and limit to viewpoint_target
        deduped = {}
        for vp in all_viewpoints:
            key = (vp.topic, vp.claim.lower().strip())
            if key not in deduped:
                deduped[key] = vp

        final_viewpoints = list(deduped.values())[: self.manifest.targets.viewpoint_target]

        viewpoints_data = [asdict(v) for v in final_viewpoints]
        viewpoints_path.write_text(json.dumps(viewpoints_data), encoding="utf-8")
        return final_viewpoints

    def _stage_materialize_book(self, viewpoints: List[ViewpointEntry]) -> AuthoredBookReport:
        book_key = get_book_key(
            title=self.manifest.metadata.title,
            publication_year=self.manifest.metadata.publication_year,
            isbn=self.manifest.metadata.isbn
        )
        book_paths = get_book_paths(self.paths.root_dir, book_key)
        book_paths.book_dir.mkdir(parents=True, exist_ok=True)
        
        # Write book.toml
        metadata_dict = asdict(self.manifest.metadata)
        write_book_metadata(book_paths.metadata_path, metadata_dict)
        
        # Write viewpoints.json
        v_data = [asdict(v) for v in viewpoints]
        book_paths.viewpoints_path.write_text(json.dumps(v_data, indent=2), encoding="utf-8")
        
        # Write report.json
        started_at = datetime.fromisoformat(self.manifest.created_at)
        completed_at = datetime.now(UTC).replace(microsecond=0)
        report = AuthoredBookReport(
            book_key=book_key,
            metadata=self.manifest.metadata,
            targets=self.manifest.targets,
            actual_topics=len(set(v.topic for v in viewpoints)),
            actual_viewpoints=len(viewpoints),
            started_at=self.manifest.created_at,
            completed_at=completed_at.isoformat(),
            duration_seconds=(completed_at - started_at.replace(tzinfo=UTC)).total_seconds(),
            warnings=self.manifest.warnings,
            stage_timings=self.manifest.stage_timings,
        )
        book_paths.report_path.write_text(json.dumps(asdict(report), indent=2, default=str), encoding="utf-8")
        
        # Update index.json
        index_path = self.paths.root_dir / "authored_books" / AUTHORED_BOOKS_INDEX_FILENAME
        index = {}
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
        index[book_key] = {
            "title": self.manifest.metadata.title,
            "publication_year": self.manifest.metadata.publication_year,
            "isbn": self.manifest.metadata.isbn,
            "ingested_at": completed_at.isoformat(),
        }
        index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

        return report

    def _stage_project_compat_chunks(self, viewpoints: List[ViewpointEntry]):
        # Read existing chunks.json
        existing_chunks = read_chunks(self.paths.chunks_path)
        
        book_key = get_book_key(
            title=self.manifest.metadata.title,
            publication_year=self.manifest.metadata.publication_year,
            isbn=self.manifest.metadata.isbn
        )
        
        other_chunks = [c for c in existing_chunks if c.get("book_key") != book_key]
        
        new_chunks = []
        for i, vp in enumerate(viewpoints):
            evidence_preview = ""
            if vp.evidence:
                evidence_preview = f"\nEvidence: {vp.evidence[0].excerpt} [{vp.evidence[0].section_ref}]"
            
            chunk_text = f"Topic: {vp.topic}\nClaim: {vp.claim}\nStance: {vp.stance_label}{evidence_preview}"
            new_chunks.append({
                "chunk_id": f"vp-{vp.entry_id}",
                "chunk_index": i,
                "text": chunk_text,
                "source": f"authored-book://{book_key}",
                "title": vp.book_title,
                "book_key": book_key,
            })
            
        final_chunks = other_chunks + new_chunks
        write_chunks(self.paths.chunks_path, final_chunks)
        
        # Rebuild catalog, embeddings and runtime index
        rebuild_catalog_from_legacy(persona_root=self.paths.root_dir)
        rebuild_embeddings(persona_dir=self.paths.root_dir, chunks=final_chunks)
        rebuild_runtime_index(persona_dir=self.paths.root_dir)
        
        # Cleanup job artifacts (except manifest)
        self._cleanup_job_artifacts()

    def _cleanup_job_artifacts(self):
        """Retain manifest but remove temporary extraction files."""
        for path in self.job_paths.job_dir.iterdir():
            if path.name != "job.toml":
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)

    def _call_llm(self, model_key: str, system_prompt: str, user_content: str) -> str:
        model_id = MODELS[model_key]["id"]
        model_alias = MODELS[model_key].get("alias", model_key)
        msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        msg = get_llm_msg(model_id, msgs, use_tools=False, model_alias=model_alias)
        from asky.html import strip_think_tags
        return strip_think_tags(msg.get("content", "")).strip()


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
