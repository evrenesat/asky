"""Source-provider strategies for evaluation query construction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol

from asky.evals.research_pipeline.dataset import DatasetDocument
from asky.evals.research_pipeline.matrix import (
    SOURCE_PROVIDER_LIVE_WEB,
    SOURCE_PROVIDER_LOCAL_SNAPSHOT,
    SOURCE_PROVIDER_MOCK_WEB,
)

LOCAL_PROVIDER_LABEL = SOURCE_PROVIDER_LOCAL_SNAPSHOT
LIVE_PROVIDER_LABEL = SOURCE_PROVIDER_LIVE_WEB
MOCK_PROVIDER_LABEL = SOURCE_PROVIDER_MOCK_WEB


@dataclass(frozen=True)
class SourceQueryPayload:
    """Rendered query payload for one test case and source provider."""

    provider_name: str
    query_text: str
    source_identifiers: List[str]


class SourceProvider(Protocol):
    """Contract for source-provider implementations."""

    name: str

    def build_query(
        self,
        *,
        base_query: str,
        docs: List[DatasetDocument],
        snapshot_paths: Optional[Dict[str, Path]] = None,
    ) -> SourceQueryPayload:
        """Render query text with provider-specific source hints."""


def _compose_query(
    *,
    heading: str,
    source_lines: Iterable[str],
    base_query: str,
) -> str:
    lines = [heading]
    lines.extend(source_lines)
    lines.append("")
    lines.append("Question:")
    lines.append(base_query)
    return "\n".join(lines)


@dataclass(frozen=True)
class LocalSnapshotSourceProvider:
    """Build queries that reference pinned local files."""

    name: str = LOCAL_PROVIDER_LABEL

    def build_query(
        self,
        *,
        base_query: str,
        docs: List[DatasetDocument],
        snapshot_paths: Optional[Dict[str, Path]] = None,
    ) -> SourceQueryPayload:
        if snapshot_paths is None:
            raise ValueError("Local snapshot provider requires snapshot_paths.")

        source_identifiers: List[str] = []
        source_lines: List[str] = []
        for doc in docs:
            doc_path = snapshot_paths.get(doc.id)
            if doc_path is None:
                raise ValueError(f"Missing snapshot path for doc_id '{doc.id}'.")
            source_identifiers.append(str(doc_path))
            source_lines.append(f'- {doc.title}: "{doc_path}"')

        query_text = _compose_query(
            heading=(
                "Use the following local research sources (already pinned snapshots). "
                "Treat these as primary references:"
            ),
            source_lines=source_lines,
            base_query=base_query,
        )
        return SourceQueryPayload(
            provider_name=self.name,
            query_text=query_text,
            source_identifiers=source_identifiers,
        )


@dataclass(frozen=True)
class LiveWebSourceProvider:
    """Build queries that seed the model with canonical web URLs."""

    name: str = LIVE_PROVIDER_LABEL

    def build_query(
        self,
        *,
        base_query: str,
        docs: List[DatasetDocument],
        snapshot_paths: Optional[Dict[str, Path]] = None,
    ) -> SourceQueryPayload:
        del snapshot_paths

        source_identifiers = [doc.url for doc in docs]
        source_lines = [f"- {doc.title}: {doc.url}" for doc in docs]
        query_text = _compose_query(
            heading=(
                "Start from these canonical web sources and use web tools/search "
                "as needed for verification:"
            ),
            source_lines=source_lines,
            base_query=base_query,
        )
        return SourceQueryPayload(
            provider_name=self.name,
            query_text=query_text,
            source_identifiers=source_identifiers,
        )


@dataclass(frozen=True)
class MockWebSourceProvider:
    """Placeholder for future mocked web-search/URL-fetch evaluation mode."""

    name: str = MOCK_PROVIDER_LABEL

    def build_query(
        self,
        *,
        base_query: str,
        docs: List[DatasetDocument],
        snapshot_paths: Optional[Dict[str, Path]] = None,
    ) -> SourceQueryPayload:
        del base_query
        del docs
        del snapshot_paths
        raise NotImplementedError(
            "mock_web source provider is reserved for future stubbed network testing."
        )


def get_source_provider(name: str) -> SourceProvider:
    """Return a source provider by identifier."""
    if name == LOCAL_PROVIDER_LABEL:
        return LocalSnapshotSourceProvider()
    if name == LIVE_PROVIDER_LABEL:
        return LiveWebSourceProvider()
    if name == MOCK_PROVIDER_LABEL:
        return MockWebSourceProvider()
    raise ValueError(f"Unknown source provider '{name}'.")
