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
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Job:
    id: str
    project_root: Path
    presentation_name: str
    # queued -> running -> succeeded | failed
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    # Keyed by a stable name ("pptx", "manifest", "preview-0", ...) --
    # never a raw filesystem path from a request, so the download route
    # (`app.py`'s `GET /api/jobs/{id}/artifacts/{key}`) can only ever
    # serve a path this module itself put here.
    artifacts: dict[str, str] = field(default_factory=dict)


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
    """uuid4-keyed in-memory build jobs, each backed by a real subprocess."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def submit_build(self, project_root: Path, presentation_name: str) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            project_root=project_root,
            presentation_name=presentation_name,
        )
        self._jobs[job.id] = job
        thread = threading.Thread(
            target=self._run_subprocess_job,
            args=(job, ["build", job.presentation_name]),
            daemon=True,
        )
        thread.start()
        return job

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
        self._jobs[job.id] = job
        thread = threading.Thread(
            target=self._run_subprocess_job, args=(job, args), daemon=True
        )
        thread.start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _run_subprocess_job(self, job: Job, command_args: list[str]) -> None:
        job.status = "running"
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "deckifyr", "--json", *command_args],
                cwd=str(job.project_root),
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            job.error = {"code": "E_IO", "message": str(exc)}
            job.status = "failed"
            return

        if proc.returncode == 0:
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                job.error = {
                    "code": "E_IO",
                    "message": (
                        "build subprocess exited 0 but did not print valid "
                        f"JSON on stdout: {proc.stdout!r}"
                    ),
                }
                job.status = "failed"
                return
            job.result = {k: v for k, v in payload.items() if k != "status"}
            job.artifacts = _artifacts_from_result(job.result)
            job.status = "succeeded"
        else:
            # Mirrors R/run-python.R's own stderr-JSON-on-failure handshake
            # (CLAUDE.md): `cli.py`'s `main()` writes `{"status": "error",
            # "code": ..., "message": ...}` to stderr, never stdout, on any
            # non-zero exit.
            try:
                payload = json.loads(proc.stderr)
                job.error = {k: v for k, v in payload.items() if k != "status"}
            except json.JSONDecodeError:
                job.error = {
                    "code": "E_IO",
                    "message": proc.stderr.strip()
                    or f"build subprocess exited {proc.returncode}",
                }
            job.status = "failed"
