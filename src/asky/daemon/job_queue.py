"""
Daemon-core SQLite job queue.

Minimal subset of ideas vendored with attribution from Pinion:
https://github.com/Nouman64-cat/Pinion
"""

from __future__ import annotations

import enum
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class JobStatus(enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass
class Job:
    """One background job record."""
    func_name: str
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.PENDING
    attempts: int = 0
    created_at: float = field(default_factory=time.time)
    error: Optional[str] = None
    heartbeat_at: Optional[float] = None


class JobQueue:
    """SQLite-backed job queue with a single worker thread."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._cv = threading.Condition()
        self._handlers: Dict[str, Callable[..., None]] = {}
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id           TEXT PRIMARY KEY,
                    func_name    TEXT NOT NULL,
                    args         TEXT NOT NULL,
                    kwargs       TEXT NOT NULL,
                    status       TEXT NOT NULL,
                    attempts     INTEGER NOT NULL,
                    created_at   REAL NOT NULL,
                    error        TEXT,
                    heartbeat_at REAL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);")
            conn.close()

    def register_handler(self, func_name: str, handler: Callable[..., None]) -> None:
        """Register a function to handle jobs with func_name."""
        self._handlers[func_name.lower()] = handler

    def enqueue(self, func_name: str, *args: Any, **kwargs: Any) -> str:
        """Add a job to the queue and return its ID."""
        job = Job(func_name=func_name.lower(), args=args, kwargs=kwargs)
        with self._lock:
            conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
            conn.execute(
                "INSERT INTO jobs (id, func_name, args, kwargs, status, attempts, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.func_name,
                    json.dumps(list(job.args)),
                    json.dumps(job.kwargs),
                    job.status.value,
                    job.attempts,
                    job.created_at,
                ),
            )
            conn.close()
            with self._cv:
                self._cv.notify_all()
        return job.id

    def list_jobs(self, limit: int = 50) -> List[Job]:
        """Return recent jobs."""
        with self._lock:
            conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
            cursor = conn.execute(
                "SELECT id, func_name, args, kwargs, status, attempts, created_at, error, heartbeat_at "
                "FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            conn.close()
            
            jobs = []
            for row in rows:
                jobs.append(Job(
                    id=row[0],
                    func_name=row[1],
                    args=tuple(json.loads(row[2])),
                    kwargs=json.loads(row[3]),
                    status=JobStatus(row[4]),
                    attempts=row[5],
                    created_at=row[6],
                    error=row[7],
                    heartbeat_at=row[8],
                ))
            return jobs

    def get_job(self, job_id: str) -> Optional[Job]:
        """Return a specific job by ID."""
        with self._lock:
            conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
            row = conn.execute(
                "SELECT id, func_name, args, kwargs, status, attempts, created_at, error, heartbeat_at "
                "FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            conn.close()
            if not row:
                return None
            return Job(
                id=row[0],
                func_name=row[1],
                args=tuple(json.loads(row[2])),
                kwargs=json.loads(row[3]),
                status=JobStatus(row[4]),
                attempts=row[5],
                created_at=row[6],
                error=row[7],
                heartbeat_at=row[8],
            )

    def start(self) -> None:
        """Start the background worker thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker_thread = threading.Thread(target=self._worker_loop, name="asky-job-worker", daemon=True)
            self._worker_thread.start()

    def stop(self) -> None:
        """Stop the background worker thread."""
        with self._lock:
            self._running = False
            with self._cv:
                self._cv.notify_all()
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)

    def _worker_loop(self) -> None:
        while self._running:
            job = self._dequeue()
            if job is None:
                with self._cv:
                    self._cv.wait(timeout=1.0)
                continue

            handler = self._handlers.get(job.func_name)
            if not handler:
                logger.error("No handler registered for job type: %s", job.func_name)
                self._mark_failed(job.id, f"No handler registered for {job.func_name}")
                continue

            logger.info("Starting job %s (%s)", job.id, job.func_name)
            try:
                handler(*job.args, **job.kwargs)
                self._mark_success(job.id)
                logger.info("Job %s succeeded", job.id)
            except Exception as exc:
                logger.exception("Job %s failed", job.id)
                self._mark_failed(job.id, str(exc))

    def _dequeue(self) -> Optional[Job]:
        with self._lock:
            conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
            try:
                conn.execute("BEGIN IMMEDIATE;")
                row = conn.execute(
                    "SELECT id, func_name, args, kwargs, status, attempts, created_at FROM jobs "
                    "WHERE status='PENDING' ORDER BY created_at LIMIT 1"
                ).fetchone()
                
                if row:
                    job_id = row[0]
                    conn.execute(
                        "UPDATE jobs SET status='RUNNING', attempts=attempts+1, heartbeat_at=? WHERE id=?",
                        (time.time(), job_id),
                    )
                    conn.execute("COMMIT;")
                    return Job(
                        id=row[0],
                        func_name=row[1],
                        args=tuple(json.loads(row[2])),
                        kwargs=json.loads(row[3]),
                        status=JobStatus.RUNNING,
                        attempts=row[5] + 1,
                        created_at=row[6],
                        heartbeat_at=time.time(),
                    )
                else:
                    conn.execute("COMMIT;")
                    return None
            except Exception:
                conn.execute("ROLLBACK;")
                logger.exception("Failed to dequeue job")
                return None
            finally:
                conn.close()

    def _mark_success(self, job_id: str) -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
            conn.execute("UPDATE jobs SET status='SUCCESS', error=NULL WHERE id=?", (job_id,))
            conn.close()

    def _mark_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
            conn.execute("UPDATE jobs SET status='FAILED', error=? WHERE id=?", (error, job_id))
            conn.close()
