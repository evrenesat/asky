"""Source ingestion job for milestone-3 structured extraction."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from asky.config import DEFAULT_MODEL, MODELS
from asky.core import get_llm_msg
from asky.plugins.manual_persona_creator.source_prompts import SOURCE_EXTRACTION_PROMPTS
from asky.plugins.manual_persona_creator.source_types import (
    PersonaReviewStatus,
    PersonaSourceIngestionJobManifest,
    PersonaSourceKind,
    PersonaSourceReportRecord,
)
from asky.plugins.manual_persona_creator.storage import (
    get_persona_paths,
    get_source_bundle_paths,
    get_source_id,
    get_source_job_paths,
    ensure_canonical_source_bundle,
    read_job_manifest,
    write_chunks,
    write_job_manifest,
)
from asky.research.adapters import fetch_source_via_adapter

logger = logging.getLogger(__name__)

AUTO_APPROVE_KINDS = {
    PersonaSourceKind.AUTOBIOGRAPHY,
    PersonaSourceKind.ARTICLE,
    PersonaSourceKind.ESSAY,
    PersonaSourceKind.SPEECH,
    PersonaSourceKind.NOTES,
    PersonaSourceKind.POSTS,
}

class SourceIngestionJob:
    """Orchestrates the milestone-3 structured source ingestion process."""

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
        self.job_paths = get_source_job_paths(self.paths.root_dir, job_id)
        self.manifest: Optional[PersonaSourceIngestionJobManifest] = None

    def load_manifest(self) -> PersonaSourceIngestionJobManifest:
        """Load manifest from disk."""
        data = read_job_manifest(self.job_paths.manifest_path)
        self.manifest = PersonaSourceIngestionJobManifest(**data)
        return self.manifest

    def save_manifest(self):
        """Save current manifest to disk."""
        if not self.manifest:
            return
        data = asdict(self.manifest)
        write_job_manifest(self.job_paths.manifest_path, data)

    def run(self) -> PersonaSourceReportRecord:
        """Execute the ingestion pipeline."""
        if not self.manifest:
            self.load_manifest()

        try:
            self._update_status("running")
            
            # 1. Read source
            content = self._run_stage("read_source", self._stage_read_source)
            
            # 2. Extract structured knowledge
            extracted_data = self._run_stage("extract_knowledge", self._stage_extract_knowledge, content)
            
            # 3. Materialize source bundle
            report = self._run_stage("materialize_bundle", self._stage_materialize_bundle, content, extracted_data)
            
            # 4. Auto-approval and projection if applicable
            if self.manifest.kind in AUTO_APPROVE_KINDS:
                self._run_stage("auto_approve", self._stage_auto_approve, report)
            
            self._update_status("completed")
            return report
            
        except Exception as e:
            logger.exception("Job %s failed: %s", self.job_id, e)
            self._update_status("failed")
            # In a real implementation we might store the error in metadata
            raise

    def _update_status(self, status: str):
        if not self.manifest:
            return
        self.manifest = PersonaSourceIngestionJobManifest(
            **{**asdict(self.manifest), "status": status, "updated_at": _utc_now_iso()}
        )
        self.save_manifest()

    def _run_stage(self, stage_name: str, func, *args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start_time
        
        # Accumulate timings in metadata
        timings = self.manifest.metadata.setdefault("stage_timings", {})
        timings[stage_name] = timings.get(stage_name, 0.0) + duration
        
        self.manifest.stages.append({
            "name": stage_name,
            "completed_at": _utc_now_iso(),
            "duration": duration
        })
        
        self.save_manifest()
        return result

    def _stage_read_source(self) -> str:
        source_path = Path(self.manifest.source_path)
        kind = self.manifest.kind
        
        members: List[Path] = []
        if source_path.is_dir():
            if kind not in {PersonaSourceKind.NOTES, PersonaSourceKind.POSTS}:
                raise ValueError(f"Directory input only allowed for notes/posts, not {kind}")
            members = sorted([p for p in source_path.iterdir() if p.is_file()])
        else:
            # Check if it's a manifest for notes/posts
            is_manifest = False
            if kind in {PersonaSourceKind.NOTES, PersonaSourceKind.POSTS}:
                try:
                    text = source_path.read_text(encoding="utf-8")
                    lines = [line.strip() for line in text.splitlines()]
                    # Filter comments and blanks
                    path_lines = [line for line in lines if line and not line.startswith("#")]
                    
                    if path_lines:
                        # Heuristic: if all non-comment lines are existing files, it's a manifest
                        # Or if it's notes/posts and the user provided a list of files, treat as manifest
                        potential_members = []
                        all_exist = True
                        for line in path_lines:
                            p = Path(line)
                            if not p.is_absolute():
                                p = source_path.parent / p
                            if p.exists() and p.is_file():
                                potential_members.append(p)
                            else:
                                all_exist = False
                                break
                        
                        if all_exist:
                            members = sorted(potential_members)
                            is_manifest = True
                        elif len(path_lines) > 0 and (path_lines[0].startswith("/") or path_lines[0].startswith("./") or path_lines[0].startswith("../")):
                            # Looks like a manifest but a file is missing
                            raise ValueError(f"Manifest bundle error: Referenced file missing or not a file: {path_lines[0]}")
                except ValueError:
                    raise
                except Exception:
                    pass
            
            if not is_manifest:
                members = [source_path]

        # Read and join content
        contents = []
        for p in members:
            target = f"local://{p.resolve().as_posix()}"
            source_data = fetch_source_via_adapter(target, operation="read")
            if not source_data or source_data.get("error"):
                raise ValueError(f"Could not read source member {p}: {source_data.get('error') if source_data else 'Unknown'}")
            contents.append(source_data.get("content", ""))
        
        # Use deterministic separator
        return "\n\n---\n\n".join(contents)

    def _stage_extract_knowledge(self, content: str) -> Dict[str, Any]:
        # Use kind-specific prompt
        prompt_template = SOURCE_EXTRACTION_PROMPTS.get(self.manifest.kind)
        if not prompt_template:
            raise ValueError(f"No extraction prompt for kind: {self.manifest.kind}")
            
        prompt = prompt_template.format(persona_name=self.persona_name)
        
        # Call LLM
        response = self._call_llm(DEFAULT_MODEL, prompt, content)
        
        try:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON object found in extraction response")
            return json.loads(json_match.group(0))
        except Exception as e:
            logger.warning("Failed to parse extracted knowledge: %s", e)
            raise

    def _stage_materialize_bundle(self, content: str, extracted_data: Dict[str, Any]) -> PersonaSourceReportRecord:
        source_id = get_source_id(self.manifest.kind, content)
        bundle_paths = ensure_canonical_source_bundle(self.paths.root_dir, source_id)
        bundle_paths.source_dir.mkdir(parents=True, exist_ok=True)
        
        # Write extracted files
        bundle_paths.viewpoints_path.write_text(json.dumps(extracted_data.get("viewpoints", []), indent=2), encoding="utf-8")
        bundle_paths.facts_path.write_text(json.dumps(extracted_data.get("facts", []), indent=2), encoding="utf-8")
        bundle_paths.timeline_path.write_text(json.dumps(extracted_data.get("timeline", []), indent=2), encoding="utf-8")
        bundle_paths.conflicts_path.write_text(json.dumps(extracted_data.get("conflicts", []), indent=2), encoding="utf-8")
        
        # Determine initial review status
        review_status = PersonaReviewStatus.APPROVED if self.manifest.kind in AUTO_APPROVE_KINDS else PersonaReviewStatus.PENDING
        
        # Write source.toml
        source_metadata = {
            "source_id": source_id,
            "kind": self.manifest.kind,
            "label": Path(self.manifest.source_path).name,
            "review_status": review_status,
            "created_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "source_class": self.manifest.metadata.get("source_class", "manual_source"),
            "trust_class": self.manifest.metadata.get("trust_class", "authored_primary"),
            "metadata": self.manifest.metadata,
        }
        from asky.plugins.manual_persona_creator.storage import write_source_metadata
        write_source_metadata(bundle_paths.metadata_path, source_metadata)
        
        # Write report.json
        report = PersonaSourceReportRecord(
            source_id=source_id,
            kind=self.manifest.kind,
            status="success",
            extracted_counts={
                "viewpoints": len(extracted_data.get("viewpoints", [])),
                "facts": len(extracted_data.get("facts", [])),
                "timeline": len(extracted_data.get("timeline", [])),
                "conflicts": len(extracted_data.get("conflicts", [])),
            },
            stage_timings=self.manifest.metadata.get("stage_timings", {}),
        )
        bundle_paths.report_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        
        return report

    def _stage_auto_approve(self, report: PersonaSourceReportRecord):
        # In a real implementation, this would call source_service.approve_source_bundle
        # which performs the canonical projection.
        from asky.plugins.manual_persona_creator.source_service import approve_source_bundle
        approve_source_bundle(self.data_dir, self.persona_name, report.source_id)

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
