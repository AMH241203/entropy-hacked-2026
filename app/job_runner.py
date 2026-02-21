from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Job:
    job_id: str
    payload: Dict[str, Any]
    attempts: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)


@dataclass
class JobResult:
    job_id: str
    success: bool
    attempts: int
    result: Optional[Any] = None
    error: Optional[str] = None


class BackgroundJobRunner:
    def __init__(self, worker_fn: Callable[[Dict[str, Any]], Any], *, workers: int = 2):
        if workers <= 0:
            raise ValueError("workers must be > 0")

        self.worker_fn = worker_fn
        self._job_queue: "queue.Queue[Job]" = queue.Queue()
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self.completed: Dict[str, JobResult] = {}
        self.failed: Dict[str, JobResult] = {}
        self._failed_jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._workers = workers

    def start(self) -> None:
        if self._threads:
            return
        for idx in range(self._workers):
            thread = threading.Thread(target=self._worker_loop, name=f"job-worker-{idx}", daemon=True)
            self._threads.append(thread)
            thread.start()

    def submit(self, job: Job) -> None:
        self._job_queue.put(job)

    def join(self, timeout: Optional[float] = None) -> bool:
        start = time.time()
        while True:
            if self._job_queue.unfinished_tasks == 0:
                return True
            if timeout is not None and (time.time() - start) > timeout:
                return False
            time.sleep(0.01)

    def shutdown(self) -> None:
        self._stop_event.set()
        for _ in self._threads:
            self._job_queue.put(Job(job_id="__shutdown__", payload={}, max_retries=0))
        for thread in self._threads:
            thread.join(timeout=1)
        self._threads.clear()

    def retry_failed(self, job_id: Optional[str] = None) -> int:
        retried = 0
        with self._lock:
            candidates = [job_id] if job_id else list(self.failed.keys())
            for failed_id in candidates:
                result = self.failed.get(failed_id)
                if result is None:
                    continue
                prior_job = self._failed_jobs.get(failed_id)
                if prior_job is None:
                    continue
                job = Job(
                    job_id=prior_job.job_id,
                    payload=prior_job.payload,
                    max_retries=prior_job.max_retries,
                )
                self._job_queue.put(job)
                del self.failed[failed_id]
                del self._failed_jobs[failed_id]
                retried += 1
        return retried

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._job_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            try:
                if job.job_id == "__shutdown__":
                    return

                self._run_job(job)
            finally:
                self._job_queue.task_done()

    def _run_job(self, job: Job) -> None:
        while True:
            job.attempts += 1
            try:
                value = self.worker_fn(job.payload)
            except Exception as exc:  # noqa: BLE001
                if job.attempts <= job.max_retries:
                    continue
                result = JobResult(
                    job_id=job.job_id,
                    success=False,
                    attempts=job.attempts,
                    error=str(exc),
                )
                with self._lock:
                    self.failed[job.job_id] = result
                    self._failed_jobs[job.job_id] = Job(
                        job_id=job.job_id, payload=job.payload, max_retries=job.max_retries
                    )
                return

            result = JobResult(job_id=job.job_id, success=True, attempts=job.attempts, result=value)
            with self._lock:
                self.completed[job.job_id] = result
            return