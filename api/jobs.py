from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from typing import Any, Callable, Literal


JobState = Literal["queued", "running", "success", "failed"]

PIPELINE_STAGES = [
    "discover",
    "score",
    "select-projects",
    "research-selected",
    "angles",
    "plan-content",
    "write-articles",
    "review-articles",
    "package-articles",
]

TERMINAL_EVENTS = {"run_succeeded", "run_failed"}
MAX_JOBS = 20
MAX_LOGS = 300


def format_utc() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def initial_stages(stage_names: list[str] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "name": stage,
            "status": "pending",
            "message": "",
            "error": None,
            "started_at": None,
            "finished_at": None,
        }
        for stage in (stage_names or PIPELINE_STAGES)
    ]


class JobManager:
    """Small in-memory background job manager for local API runs."""

    def __init__(self, max_jobs: int = MAX_JOBS, max_logs: int = MAX_LOGS) -> None:
        self.max_jobs = max_jobs
        self.max_logs = max_logs
        self._jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="daily-job")

    def create_job(self, params: dict[str, Any], stages: list[str] | None = None) -> str:
        job_id = uuid.uuid4().hex
        now = format_utc()
        with self._condition:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "created_at": now,
                "started_at": None,
                "finished_at": None,
                "current_stage": None,
                "stages": initial_stages(stages),
                "logs": [],
                "params": dict(params),
                "result": None,
                "error": None,
            }
            self._events[job_id] = []
            self._trim_jobs_locked()
            self._condition.notify_all()
        return job_id

    def start_job(self, job_id: str, callable_: Callable[[], Any]) -> None:
        def runner() -> None:
            self._mark_running(job_id)
            try:
                result = callable_()
            except Exception as exc:
                self._mark_failed(job_id, f"{type(exc).__name__}: {exc}")
                return
            self._mark_success(job_id, self._serialize_result(result))

        self._executor.submit(runner)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(job) for job in reversed(self._jobs.values())]

    def add_event(self, job_id: str, event: dict[str, Any]) -> None:
        safe_event = self._sanitize_event(event)
        with self._condition:
            job = self._jobs.get(job_id)
            if not job:
                return
            self._events.setdefault(job_id, []).append(safe_event)
            self._apply_event_locked(job, safe_event)
            job["logs"].append(self._event_to_log(safe_event))
            job["logs"] = job["logs"][-self.max_logs :]
            self._condition.notify_all()

    def get_events(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._events.get(job_id, []))

    def wait_for_events(
        self,
        job_id: str,
        after_index: int,
        timeout: float = 15.0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        with self._condition:
            self._condition.wait_for(
                lambda: job_id not in self._jobs or len(self._events.get(job_id, [])) > after_index,
                timeout=timeout,
            )
            job = self._jobs.get(job_id)
            events = self._events.get(job_id, [])
            return deepcopy(events[after_index:]), deepcopy(job) if job else None

    def _mark_running(self, job_id: str) -> None:
        with self._condition:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["started_at"] = format_utc()
            self._condition.notify_all()

    def _mark_success(self, job_id: str, result: dict[str, Any] | None) -> None:
        with self._condition:
            job = self._jobs.get(job_id)
            if not job:
                return
            if job["status"] != "failed":
                job["status"] = "success"
                job["finished_at"] = job["finished_at"] or format_utc()
                job["current_stage"] = None
                job["result"] = result
            self._condition.notify_all()

    def _mark_failed(self, job_id: str, error: str) -> None:
        with self._condition:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "failed"
            job["finished_at"] = job["finished_at"] or format_utc()
            job["current_stage"] = None
            job["error"] = error
            self._condition.notify_all()

    def _apply_event_locked(self, job: dict[str, Any], event: dict[str, Any]) -> None:
        event_type = event.get("type")
        stage_name = event.get("stage")
        stage = self._find_stage(job, stage_name) if stage_name else None

        if event_type == "run_started":
            job["status"] = "running"
            job["started_at"] = job["started_at"] or event.get("time") or format_utc()
        elif event_type == "stage_started" and stage:
            job["current_stage"] = stage_name
            stage["status"] = "running"
            stage["started_at"] = event.get("time") or format_utc()
            stage["message"] = event.get("message", "")
            stage["error"] = None
        elif event_type == "stage_succeeded" and stage:
            stage["status"] = "success"
            stage["finished_at"] = event.get("time") or format_utc()
            stage["message"] = event.get("message", "")
            stage["error"] = None
            if job.get("current_stage") == stage_name:
                job["current_stage"] = None
        elif event_type == "stage_failed" and stage:
            stage["status"] = "failed"
            stage["finished_at"] = event.get("time") or format_utc()
            stage["message"] = event.get("message", "")
            stage["error"] = event.get("error") or event.get("message")
            job["current_stage"] = None
            job["error"] = stage["error"]
        elif event_type == "run_succeeded":
            job["status"] = "success"
            job["finished_at"] = event.get("time") or format_utc()
            job["current_stage"] = None
            if isinstance(event.get("result"), dict):
                job["result"] = event["result"]
        elif event_type == "run_failed":
            job["status"] = "failed"
            job["finished_at"] = event.get("time") or format_utc()
            job["current_stage"] = None
            job["error"] = event.get("error") or event.get("message")

    def _find_stage(self, job: dict[str, Any], stage_name: str | None) -> dict[str, Any] | None:
        for stage in job.get("stages", []):
            if stage.get("name") == stage_name:
                return stage
        return None

    def _sanitize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        allowed = {"type", "stage", "message", "time", "error", "result"}
        safe_event = {key: value for key, value in event.items() if key in allowed}
        safe_event.setdefault("time", format_utc())
        if "message" in safe_event:
            safe_event["message"] = str(safe_event["message"])[:1000]
        if "error" in safe_event:
            safe_event["error"] = str(safe_event["error"])[:1000]
        if isinstance(safe_event.get("result"), dict):
            result = safe_event["result"]
            safe_event["result"] = {
                key: value
                for key, value in result.items()
                if key
                in {
                    "run_id",
                    "date",
                    "status",
                    "started_at",
                    "finished_at",
                    "output_dir",
                    "full_name",
                    "title",
                    "generation_mode",
                    "markdown_path",
                    "report_path",
                    "snapshot_path",
                    "style_reference_used",
                    "originality_checked",
                    "originality_passed",
                    "package_count",
                }
            }
        return safe_event

    def _event_to_log(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "time": event.get("time") or format_utc(),
            "stage": event.get("stage"),
            "type": event.get("type"),
            "message": event.get("message") or event.get("error") or event.get("type", ""),
        }

    def _serialize_result(self, result: Any) -> dict[str, Any] | None:
        if result is None:
            return None
        if hasattr(result, "model_dump"):
            payload = result.model_dump()
        elif hasattr(result, "dict"):
            payload = result.dict()
        elif isinstance(result, dict):
            payload = result
        else:
            return {"value": str(result)}
        return {
            key: value
            for key, value in payload.items()
            if key
            in {
                "run_id",
                "date",
                "status",
                "started_at",
                "finished_at",
                "output_dir",
                "full_name",
                "title",
                "generation_mode",
                "markdown_path",
                "report_path",
                "snapshot_path",
                "style_reference_used",
                "originality_checked",
                "originality_passed",
                "package_count",
            }
        }

    def _trim_jobs_locked(self) -> None:
        while len(self._jobs) > self.max_jobs:
            old_job_id, _ = self._jobs.popitem(last=False)
            self._events.pop(old_job_id, None)


job_manager = JobManager()
