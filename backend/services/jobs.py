"""
后台任务（内存中）：视频分析这类要跑一两分钟的请求，前端提交后轮询进度，而不是一直挂着一个请求。
进程重启后任务会丢失；任务结果保留 30 分钟。
"""

from __future__ import annotations

import secrets
import threading
import time

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_TTL = 30 * 60


def _gc() -> None:
    now = time.time()
    for k in [k for k, j in _JOBS.items() if now - j["updated"] > _TTL]:
        _JOBS.pop(k, None)


def create(owner, items: list[dict]) -> str:
    job_id = secrets.token_urlsafe(12)
    with _LOCK:
        _gc()
        _JOBS[job_id] = {"id": job_id, "owner": owner, "status": "running", "items": items, "result": None, "error": "", "created": time.time(), "updated": time.time()}
    return job_id


def update_item(job_id: str, index: int, stage: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job and 0 <= index < len(job["items"]):
            job["items"][index]["stage"] = stage
            job["updated"] = time.time()


def finish(job_id: str, result: dict) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(status="done", result=result, updated=time.time())


def fail(job_id: str, error: str) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(status="error", error=error, updated=time.time())


def get(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        return {**job, "items": [dict(i) for i in job["items"]], "elapsed": round(time.time() - job["created"])}
