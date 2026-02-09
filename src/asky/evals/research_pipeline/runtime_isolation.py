"""Runtime isolation helpers for evaluation runs."""

from __future__ import annotations

import importlib
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

ASKY_DB_PATH_ENV_VAR = "ASKY_DB_PATH"
RUNTIME_DB_FILENAME = "history.db"
RUNTIME_CHROMA_DIRNAME = "chromadb"

_MISSING = object()


@dataclass(frozen=True)
class RuntimePaths:
    """Filesystem paths used for one isolated run."""

    run_dir: Path
    runtime_dir: Path
    artifacts_dir: Path
    db_path: Path
    chroma_dir: Path


def build_runtime_paths(run_dir: Path) -> RuntimePaths:
    """Create directory layout used for one run profile execution."""
    resolved_run_dir = run_dir.resolve()
    runtime_dir = resolved_run_dir / "runtime"
    artifacts_dir = resolved_run_dir / "artifacts"
    db_path = runtime_dir / RUNTIME_DB_FILENAME
    chroma_dir = runtime_dir / RUNTIME_CHROMA_DIRNAME

    runtime_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    chroma_dir.mkdir(parents=True, exist_ok=True)

    return RuntimePaths(
        run_dir=resolved_run_dir,
        runtime_dir=runtime_dir,
        artifacts_dir=artifacts_dir,
        db_path=db_path,
        chroma_dir=chroma_dir,
    )


def reset_runtime_singletons() -> None:
    """Reset singleton state so runs do not leak cached objects across profiles."""
    try:
        from asky.research.cache import ResearchCache

        cache_instance = getattr(ResearchCache, "_instance", None)
        if cache_instance is not None:
            executor = getattr(cache_instance, "_executor", None)
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
        ResearchCache._instance = None
    except Exception:
        pass

    try:
        from asky.research.vector_store import VectorStore

        VectorStore._instance = None
    except Exception:
        pass

    try:
        from asky.research.embeddings import EmbeddingClient

        EmbeddingClient._instance = None
    except Exception:
        pass


def _patch_module_attr(
    module_name: str,
    attr_name: str,
    value: Any,
    patched: List[Tuple[Any, str, Any]],
) -> None:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return

    previous = getattr(module, attr_name, _MISSING)
    patched.append((module, attr_name, previous))
    setattr(module, attr_name, value)


@contextmanager
def isolated_asky_runtime(paths: RuntimePaths) -> Iterator[None]:
    """Patch runtime globals and environment to isolate one evaluation run."""
    patched_attrs: List[Tuple[Any, str, Any]] = []
    previous_repo_db_path: Any = _MISSING

    previous_env = os.environ.get(ASKY_DB_PATH_ENV_VAR)
    os.environ[ASKY_DB_PATH_ENV_VAR] = str(paths.db_path)

    try:
        _patch_module_attr("asky.config", "DB_PATH", paths.db_path, patched_attrs)
        _patch_module_attr(
            "asky.config",
            "RESEARCH_CHROMA_PERSIST_DIRECTORY",
            paths.chroma_dir,
            patched_attrs,
        )
        _patch_module_attr("asky.storage", "DB_PATH", paths.db_path, patched_attrs)
        _patch_module_attr("asky.storage.sqlite", "DB_PATH", paths.db_path, patched_attrs)
        _patch_module_attr("asky.research.cache", "DB_PATH", paths.db_path, patched_attrs)
        _patch_module_attr("asky.research.vector_store", "DB_PATH", paths.db_path, patched_attrs)
        _patch_module_attr(
            "asky.research.vector_store",
            "RESEARCH_CHROMA_PERSIST_DIRECTORY",
            paths.chroma_dir,
            patched_attrs,
        )

        try:
            storage_module = importlib.import_module("asky.storage")
            repo = getattr(storage_module, "_repo", None)
            if repo is not None:
                previous_repo_db_path = getattr(repo, "db_path", _MISSING)
                repo.db_path = paths.db_path
        except Exception:
            pass

        reset_runtime_singletons()
        yield
    finally:
        reset_runtime_singletons()

        for module, attr_name, previous in reversed(patched_attrs):
            if previous is _MISSING:
                try:
                    delattr(module, attr_name)
                except Exception:
                    pass
            else:
                setattr(module, attr_name, previous)

        if previous_env is None:
            os.environ.pop(ASKY_DB_PATH_ENV_VAR, None)
        else:
            os.environ[ASKY_DB_PATH_ENV_VAR] = previous_env

        if previous_repo_db_path is not _MISSING:
            try:
                storage_module = importlib.import_module("asky.storage")
                repo = getattr(storage_module, "_repo", None)
                if repo is not None:
                    repo.db_path = previous_repo_db_path
            except Exception:
                pass
