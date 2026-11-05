"""In-memory background build-job tracking for `deckifyr.web` (spec
section 12).

A `deckifyr build` can take real wall-clock time (Quarto/LibreOffice
subprocesses may run as part of it), so `POST /api/build` (`app.py`)
can't just block the HTTP request on it -- it submits a job here and
returns immediately with an id to poll. Jobs live in a plain dict, not
a database: this is a local-first, single-process authoring tool (spec
section 12), not a multi-worker service, and a restart losing
in-flight job history is an acceptable trade for not adding a
persistence layer this Phase 3 slice doesn't ask for.

Each job shells out to a real `python -m deckifyr --json build ...`
subprocess rather than calling `deckifyr.pptx.compose_and_write`
in-process, deliberately reusing the same stdout/stdout-on-success,
stderr-on-failure JSON handshake `R/run-python.R` already relies on
(see CLAUDE.md's writeup of that contract) -- the CLI's error path is
already a tested, stable `code`/`message` contract; reusing it here
means a failed build surfaces exactly the shape a `deckifyr build` run
from a terminal would give, not a second, web-only error format.

Jobs are bounded and cancellable (issue #84): each child runs in its own
process group with a job-level timeout, and `cancel` (or a timeout) kills
the whole tree -- see `deckifyr._proc` for why a plain `subprocess.run`
timeout isn't enough. A job that overruns reports `status: failed` with an
`E_TIMEOUT` error; a cancelled one reports `status: cancelled`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deckifyr._proc import kill_process_tree, run_in_group
from deckifyr.schema.errors import ErrorCode

# Comfortably above `build.preview.timeout_seconds`' own 120s default, so the
# preview renderer's own (more specific) timeout normally fires first and
# this is the backstop for a hang anywhere else in the build.
DEFAULT_JOB_TIMEOUT_SECONDS = 600.0

ACTIVE_STATUSES = ("queued", "running")


@dataclass
class Job:
    id: str
    project_root: Path
    presentation_name: str
    # queued -> running -> succeeded | failed | cancelled
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    # Keyed by a stable name ("pptx", "manifest", "preview-0", ...) --
    # never a raw filesystem path from a request, so the download route
    # (`app.py`'s `GET /api/jobs/{id}/artifacts/{key}`) can only ever
    # serve a path this module itself put here.
    artifacts: dict[str, str] = field(default_factory=dict)
    # Internal bookkeeping (never serialized): the live subprocess, so
    # `cancel` can kill its tree, and whether a cancel was asked for.
    proc: subprocess.Popen | None = field(default=None, repr=False)
    cancel_requested: bool = False
    started_at: float | None = None


def _artifacts_from_result(result: dict[str, Any]) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    if result.get("output"):
        artifacts["pptx"] = result["output"]
    if result.get("manifest"):
        artifacts["manifest"] = result["manifest"]
    for index, preview in enumerate(result.get("previews") or []):
        artifacts[f"preview-{index}"] = preview
    # Only a `deckifyr preview` job's result ever carries this key (issue
    # #27's embedded-PDF-viewer support) -- an ordinary build's result
    # dict simply doesn't have it, so this is a no-op there.
    if result.get("preview_pdf"):
        artifacts["pdf"] = result["preview_pdf"]
    return artifacts


class JobManager:
    """uuid4-keyed in-memory build jobs, each backed by a real subprocess.

    `job_timeout_seconds` bounds every job (`None`/`<= 0` disables the
    limit). `argv_prefix` is the command every job runs, with the job's own
    arguments appended -- the real `python -m deckifyr --json` by default;
    a test seam, not user configuration.
    """

    def __init__(
        self,
        *,
        job_timeout_seconds: float | None = DEFAULT_JOB_TIMEOUT_SECONDS,
        argv_prefix: Sequence[str] | None = None,
    ) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.job_timeout_seconds = (
            job_timeout_seconds if job_timeout_seconds and job_timeout_seconds > 0 else None
        )
        self._argv_prefix = (
            tuple(argv_prefix)
            if argv_prefix is not None
            else (sys.executable, "-m", "deckifyr", "--json")
        )

    def _start(self, job: Job, args: list[str]) -> Job:
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(
            target=self._run_subprocess_job, args=(job, args), daemon=True
        )
        thread.start()
        return job

    def submit_build(self, project_root: Path, presentation_name: str) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            project_root=project_root,
            presentation_name=presentation_name,
        )
        return self._start(job, ["build", job.presentation_name])

    def submit_preview(
        self, project_root: Path, presentation_name: str, slides: list[int] | None = None
    ) -> Job:
        """Same shape as `submit_build`, shelling out to `deckifyr preview`
        instead (issue #27's Build-tab preview action) -- `slides`
        (1-indexed) is forwarded as `--slides` (`_parse_slides_arg` in
        `cli.py`), omitted entirely for "every slide".
        """
        job = Job(
            id=str(uuid.uuid4()),
            project_root=project_root,
            presentation_name=presentation_name,
        )
        args = ["preview", job.presentation_name]
        if slides:
            args += ["--slides", ",".join(str(n) for n in slides)]
        return self._start(job, args)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active_jobs(self) -> list[Job]:
        """Jobs that are queued or still running."""
        with self._lock:
            return [j for j in self._jobs.values() if j.status in ACTIVE_STATUSES]

    def active_count(self) -> int:
        return len(self.active_jobs())

    def cancel(self, job_id: str) -> Job | None:
        """Cancel a queued/running job and kill its whole process tree.

        Returns the job (`None` if unknown). Idempotent: a job that already
        finished is returned unchanged rather than flipped to `cancelled`.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status not in ACTIVE_STATUSES:
                return job
            job.cancel_requested = True
            job.status = "cancelled"
            proc = job.proc
        # Outside the lock: killing a tree can take a moment.
        if proc is not None:
            kill_process_tree(proc)
        return job

    def _run_subprocess_job(self, job: Job, command_args: list[str]) -> None:
        with self._lock:
            if job.cancel_requested:  # cancelled while still queued
                return
            job.status = "running"
            job.started_at = time.monotonic()

        def on_start(proc: subprocess.Popen) -> None:
            with self._lock:
                job.proc = proc
                cancelled = job.cancel_requested
            # A cancel that landed between "running" and the process
            # existing had no handle to kill yet.
            if cancelled:
                kill_process_tree(proc)

        try:
            proc = run_in_group(
                [*self._argv_prefix, *command_args],
                cwd=job.project_root,
                timeout=self.job_timeout_seconds,
                on_start=on_start,
            )
        except subprocess.TimeoutExpired:
            self._finish(
                job,
                status="failed",
                error={
                    "code": ErrorCode.TIMEOUT,
                    "message": (
                        f"{command_args[0]} job exceeded its "
                        f"{self.job_timeout_seconds:g}s job timeout and was terminated"
                    ),
                },
            )
            return
        except OSError as exc:
            self._finish(job, status="failed", error={"code": "E_IO", "message": str(exc)})
            return

        if proc.returncode == 0:
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                self._finish(
                    job,
                    status="failed",
                    error={
                        "code": "E_IO",
                        "message": (
                            "build subprocess exited 0 but did not print valid "
                            f"JSON on stdout: {proc.stdout!r}"
                        ),
                    },
                )
                return
            result = {k: v for k, v in payload.items() if k != "status"}
            self._finish(
                job,
                status="succeeded",
                result=result,
                artifacts=_artifacts_from_result(result),
            )
        else:
            # Mirrors R/run-python.R's own stderr-JSON-on-failure handshake
            # (CLAUDE.md): `cli.py`'s `main()` writes `{"status": "error",
            # "code": ..., "message": ...}` to stderr, never stdout, on any
            # non-zero exit.
            try:
                payload = json.loads(proc.stderr)
                error = {k: v for k, v in payload.items() if k != "status"}
            except json.JSONDecodeError:
                error = {
                    "code": "E_IO",
                    "message": proc.stderr.strip()
                    or f"build subprocess exited {proc.returncode}",
                }
            self._finish(job, status="failed", error=error)

    def _finish(
        self,
        job: Job,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        artifacts: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            job.proc = None
            # `cancel` already marked the job `cancelled`; whatever the
            # killed process left behind (a signal exit, or a build that
            # happened to finish in the same instant) is discarded so a
            # cancelled job never reports a result or error.
            if job.cancel_requested:
                job.status = "cancelled"
                return
            job.result = result
            job.error = error
            job.artifacts = artifacts or {}
            job.status = status
