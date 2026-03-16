"""Service layer for holistic persona creation from scratch."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from asky.plugins.manual_persona_creator import book_service, source_service, storage
from asky.plugins.manual_persona_creator.book_types import (
    BookMetadata,
    ExtractionTargets,
)
from asky.plugins.manual_persona_creator.source_types import PersonaSourceKind


@dataclass(frozen=True)
class StagedSourceSpec:
    """Specification for an initial source to be ingested during persona creation."""

    kind: PersonaSourceKind | str  # "authored_book" or PersonaSourceKind
    path: str
    metadata: Optional[BookMetadata] = None
    targets: Optional[ExtractionTargets] = None
    resumable_job_id: Optional[str] = None


@dataclass(frozen=True)
class PersonaCreationSpecs:
    """Holistic specification for creating a persona with initial sources."""

    name: str
    description: str
    behavior_prompt: str
    initial_sources: List[StagedSourceSpec]


@dataclass(frozen=True)
class CreatedJobInfo:
    """Info about an enqueued ingestion job."""

    job_id: str
    kind: str  # "authored_book_ingest" or "source_ingest"


def create_persona_from_scratch(
    data_dir: Path,
    specs: PersonaCreationSpecs,
) -> tuple[str, List[CreatedJobInfo]]:
    """
    Validate, create persona storage, and enqueue initial source ingestion jobs.

    This function implements a simplified transactional 'all-or-nothing' shell creation.
    If shell creation or any job enqueueing fails, it attempts to clean up the persona directory.
    """
    # 1. Validation
    name = storage.validate_persona_name(specs.name)
    if not str(specs.behavior_prompt or "").strip():
        raise ValueError("Behavior prompt cannot be empty.")

    if not specs.initial_sources:
        raise ValueError("At least one initial source must be provided.")

    if storage.persona_exists(data_dir, name):
        raise ValueError(f"Persona '{name}' already exists.")

    # Validate source paths and specs before doing any disk writes
    for i, source in enumerate(specs.initial_sources):
        source_path = Path(source.path).expanduser()
        if not source_path.exists():
            raise FileNotFoundError(f"Initial source path not found: {source.path}")

        if source.kind == "authored_book":
            if not source.metadata or not source.targets:
                raise ValueError(
                    f"Initial source #{i+1} (authored_book) missing metadata or targets."
                )
        else:
            try:
                # Ensure it's a valid kind string
                PersonaSourceKind(str(source.kind))
            except ValueError:
                raise ValueError(f"Initial source #{i+1} has invalid kind: {source.kind}")

    # 2. Atomic creation of the persona shell
    paths = storage.create_persona(
        data_dir=data_dir,
        persona_name=name,
        description=specs.description,
        behavior_prompt=specs.behavior_prompt,
    )

    # 3. Enqueue jobs
    created_jobs = []
    try:
        for source in specs.initial_sources:
            source_path = Path(source.path).expanduser()

            if source.kind == "authored_book":
                # Authored book preflight to get fingerprint
                preflight = book_service.prepare_ingestion_preflight(
                    data_dir=data_dir,
                    persona_name=name,
                    source_path=str(source_path),
                )

                # Create or update job
                if source.resumable_job_id:
                    book_service.update_ingestion_job_inputs(
                        data_dir=data_dir,
                        persona_name=name,
                        job_id=source.resumable_job_id,
                        metadata=source.metadata,  # type: ignore
                        targets=source.targets,  # type: ignore
                        mode="ingest",
                    )
                    job_id = source.resumable_job_id
                else:
                    job_id = book_service.create_ingestion_job(
                        data_dir=data_dir,
                        persona_name=name,
                        source_path=str(source_path),
                        source_fingerprint=preflight.source_fingerprint,
                        # metadata and targets are guaranteed present by validation above
                        metadata=source.metadata,  # type: ignore
                        targets=source.targets,  # type: ignore
                        mode="ingest",
                    )
                created_jobs.append(CreatedJobInfo(job_id=job_id, kind="authored_book_ingest"))
            else:
                # Manual source
                kind = PersonaSourceKind(str(source.kind))
                job_id = source_service.create_source_ingestion_job(
                    data_dir=data_dir,
                    persona_name=name,
                    kind=kind,
                    source_path=source_path,
                )
                created_jobs.append(CreatedJobInfo(job_id=job_id, kind="source_ingest"))
    except Exception as e:
        # 4. Rollback on any failure after shell creation
        shutil.rmtree(paths.root_dir, ignore_errors=True)
        raise e

    return name, created_jobs
