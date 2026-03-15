"""Tests for daemon job queue."""

from __future__ import annotations

import time
from pathlib import Path

from asky.daemon.job_queue import JobQueue, JobStatus


def test_job_queue_lifecycle(tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    queue = JobQueue(db_path)
    
    handled = []
    def my_handler(arg1, name=""):
        handled.append((arg1, name))

    queue.register_handler("test_job", my_handler)
    queue.start()
    
    try:
        job_id = queue.enqueue("test_job", 123, name="foo")
        
        # Wait for job to be processed
        for _ in range(20):
            job = queue.get_job(job_id)
            if job and job.status == JobStatus.SUCCESS:
                break
            time.sleep(0.1)
        
        assert len(handled) == 1
        assert handled[0] == (123, "foo")
        
        job = queue.get_job(job_id)
        assert job.status == JobStatus.SUCCESS
        assert job.attempts == 1
    finally:
        queue.stop()


def test_job_queue_failure(tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    queue = JobQueue(db_path)
    
    def failing_handler():
        raise ValueError("boom")

    queue.register_handler("fail_job", failing_handler)
    queue.start()
    
    try:
        job_id = queue.enqueue("fail_job")
        
        # Wait for job to be processed
        for _ in range(20):
            job = queue.get_job(job_id)
            if job and job.status == JobStatus.FAILED:
                break
            time.sleep(0.1)
        
        job = queue.get_job(job_id)
        assert job.status == JobStatus.FAILED
        assert "boom" in job.error
    finally:
        queue.stop()


def test_job_queue_list_jobs(tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    queue = JobQueue(db_path)
    
    queue.enqueue("job1")
    queue.enqueue("job2")
    
    jobs = queue.list_jobs()
    assert len(jobs) == 2
    assert jobs[0].func_name == "job2"
    assert jobs[1].func_name == "job1"
