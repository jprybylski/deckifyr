"""Run an external command so a timeout or cancel really stops it (issue #84).

`subprocess.run(..., timeout=...)` kills only the *direct* child on
timeout. That is not enough for the tools deckifyr shells out to:
LibreOffice's `soffice` launcher spawns a detached `soffice.bin`, and a
background job is `python -m deckifyr build`, which itself spawns
LibreOffice/Quarto/Rscript. Killing just the top process orphans all of
them -- still running, still holding a LibreOffice profile lock, still
burning CPU after the editor reported the job dead.

So every command here starts in its own session/process group, and
`kill_process_tree` takes down the whole tree. This mirrors the helper
quartifyr already uses for LibreOffice (`recalculate_fields.py`:
`start_new_session=True` + `os.killpg`), extended in two ways quartifyr's
single-level case didn't need:

* A job's CLI child starts *its own* session for the LibreOffice it runs
  (that is what makes the preview timeout safe on its own), so the job's
  process group does not contain it. `kill_process_tree` therefore also
  walks the parent/child tree (via `ps`) and kills every descendant's
  group, instead of assuming one group covers everything.
* Windows has no process groups to `killpg`; `taskkill /T` walks the
  tree natively.

stdout/stderr go to temp files, not pipes: a child that outlives a killed
parent (the very case this module exists for) can keep a pipe's write end
open, and `communicate()` would then block forever waiting for EOF -- the
same pipe-deadlock quartifyr's helper documents.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"


@dataclass
class GroupRunResult:
    returncode: int
    stdout: str
    stderr: str


def _group_kwargs() -> dict:
    if _IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _descendant_pids(root_pid: int) -> set[int]:
    """Every live descendant of `root_pid`, from one `ps` snapshot.

    Best effort: if `ps` is unavailable the caller still kills the root's
    own group, which is what quartifyr's single-level helper does.
    """
    try:
        listing = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid="],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    children: dict[int, list[int]] = defaultdict(list)
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children[int(parts[1])].append(int(parts[0]))
    found: set[int] = set()
    stack = [root_pid]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill `proc` and everything it started. Safe to call more than once."""
    if _IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            proc.kill()
        except OSError:
            pass
    else:
        # Snapshot the tree *before* killing anything: once the launcher
        # dies its children are re-parented to init and the walk loses them.
        pids = {proc.pid} | _descendant_pids(proc.pid)
        own_group = os.getpgrp()
        groups = {proc.pid}  # `start_new_session` made pgid == pid
        for pid in pids:
            try:
                groups.add(os.getpgid(pid))
            except (ProcessLookupError, PermissionError):
                continue
        groups.discard(own_group)  # never take down ourselves
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_in_group(
    cmd: Sequence[str],
    *,
    timeout: float | None,
    cwd: str | Path | None = None,
    on_start: Callable[[subprocess.Popen], None] | None = None,
) -> GroupRunResult:
    """Run `cmd` in its own process group, killing the whole tree on timeout.

    Raises `subprocess.TimeoutExpired` (after the tree is dead) when
    `timeout` elapses; `OSError` if the command cannot be started.
    `on_start` receives the live `Popen` so a caller (the web job manager)
    can cancel it from another thread with `kill_process_tree`. A process
    killed that way simply returns with a non-zero `returncode`.
    """
    with (
        tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out,
        tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as err,
    ):
        proc = subprocess.Popen(
            list(cmd),
            cwd=None if cwd is None else str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            **_group_kwargs(),
        )
        try:
            if on_start is not None:
                on_start(proc)
            proc.wait(timeout=timeout)
        except BaseException:
            # Timeout, Ctrl-C, or an `on_start` failure: never leave the
            # tree running behind us.
            kill_process_tree(proc)
            raise
        out.seek(0)
        err.seek(0)
        return GroupRunResult(proc.returncode, out.read(), err.read())
