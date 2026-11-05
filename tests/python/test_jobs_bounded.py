"""Bounded, cancellable background jobs and the shared process helper (issue #84).

These use a real hanging command (a Python child that itself spawns a
grandchild in a *separate session*, the way `deckifyr preview` spawns
LibreOffice) rather than mocks, because "no orphaned child processes" is
the whole point.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time

import pytest

from deckifyr._proc import kill_process_tree, run_in_group
from deckifyr.web.jobs import JobManager

IS_WINDOWS = sys.platform == "win32"

# Python starts slower on a Windows runner, and the tree has to exist (child
# *and* grandchild started, PIDs recorded) before the timeout fires or the
# test would pass vacuously. Generous there, tight on POSIX to keep it fast.
TIMEOUT = 8 if IS_WINDOWS else 2

# A child that starts a grandchild in its own session / process group (like
# the CLI's soffice), records both PIDs, then hangs. `taskkill /T` (the
# Windows path under test) follows parent/child links, so the grandchild is
# only reachable through a real tree walk there too.
HANGING_TREE = textwrap.dedent(
    """
    import os, subprocess, sys, time
    pidfile = sys.argv[-1]
    detach = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    gc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        **detach,
    )
    with open(pidfile, "w") as fh:
        fh.write(f"{os.getpid()} {gc.pid}")
    time.sleep(120)
    """
)


def _pid_alive_windows(pid: int) -> bool:
    # `os.kill(pid, 0)` must never be used here: on Windows any signal other
    # than CTRL_C/CTRL_BREAK calls TerminateProcess, so it would *kill* the
    # process it was only meant to probe.
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == error_access_denied  # exists, just not ours to open
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    if IS_WINDOWS:
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(0); treat it as dead.
    try:
        status = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
        ).stdout.strip()
    except OSError:
        return True
    return bool(status) and not status.startswith("Z")


def _wait_for(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _read_pids(path):
    assert _wait_for(path.exists), "child never wrote its pidfile"
    assert _wait_for(lambda: len(path.read_text().split()) == 2)
    parent, grandchild = (int(x) for x in path.read_text().split())
    return parent, grandchild


def _manager(tmp_path, timeout):
    pidfile = tmp_path / "pids.txt"
    # JobManager appends the job's own args ("build", "presentation.yaml");
    # the hanging script ignores them except it reads the pidfile from
    # argv via the fixed prefix below.
    script = tmp_path / "hang.py"
    script.write_text(HANGING_TREE)
    manager = JobManager(
        job_timeout_seconds=timeout,
        argv_prefix=[sys.executable, str(script)],
    )
    return manager, pidfile


def _submit(manager, tmp_path, pidfile):
    # The script takes the pidfile as its *last* argv, so smuggle it in as
    # the presentation name (the final arg a build job appends).
    return manager.submit_build(tmp_path, str(pidfile))


# --- run_in_group ----------------------------------------------------------


def test_run_in_group_timeout_kills_the_whole_tree(tmp_path):
    script = tmp_path / "hang.py"
    script.write_text(HANGING_TREE)
    pidfile = tmp_path / "pids.txt"

    with pytest.raises(subprocess.TimeoutExpired):
        run_in_group([sys.executable, str(script), str(pidfile)], timeout=TIMEOUT)

    parent, grandchild = _read_pids(pidfile)
    assert _wait_for(lambda: not _pid_alive(parent))
    # The grandchild is in a different session from the child: only a tree
    # walk (not a single killpg) reaches it.
    assert _wait_for(lambda: not _pid_alive(grandchild)), "grandchild was orphaned"


def test_run_in_group_captures_output_and_returncode(tmp_path):
    result = run_in_group(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
        timeout=30,
    )
    assert result.returncode == 3
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"


def test_kill_process_tree_is_safe_on_an_already_finished_process():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    kill_process_tree(proc)  # must not raise


# --- JobManager ------------------------------------------------------------


def test_job_timeout_fails_the_job_and_leaves_no_orphans(tmp_path):
    manager, pidfile = _manager(tmp_path, timeout=TIMEOUT)
    job = _submit(manager, tmp_path, pidfile)

    assert _wait_for(lambda: job.status in ("failed", "succeeded"), timeout=30)
    assert job.status == "failed"
    assert job.error["code"] == "E_TIMEOUT"
    assert f"{TIMEOUT}s job timeout" in job.error["message"]

    parent, grandchild = _read_pids(pidfile)
    assert _wait_for(lambda: not _pid_alive(parent))
    assert _wait_for(lambda: not _pid_alive(grandchild)), "grandchild was orphaned"
    assert manager.active_count() == 0


def test_cancel_kills_the_running_job_and_its_process_tree(tmp_path):
    manager, pidfile = _manager(tmp_path, timeout=120)
    job = _submit(manager, tmp_path, pidfile)
    parent, grandchild = _read_pids(pidfile)
    assert job.status == "running"
    assert manager.active_count() == 1

    cancelled = manager.cancel(job.id)

    assert cancelled is job
    assert job.status == "cancelled"
    assert job.result is None and job.error is None
    assert _wait_for(lambda: not _pid_alive(parent))
    assert _wait_for(lambda: not _pid_alive(grandchild)), "grandchild was orphaned"
    # The runner thread settles without flipping the status back.
    assert _wait_for(lambda: job.proc is None)
    assert job.status == "cancelled"
    assert manager.active_count() == 0


def test_cancel_unknown_job_returns_none():
    assert JobManager().cancel("nope") is None


def test_cancelling_a_finished_job_is_idempotent(tmp_path):
    manager = JobManager(argv_prefix=[sys.executable, "-c", "import json;print(json.dumps({'status':'ok'}))"])
    job = manager.submit_build(tmp_path, "presentation.yaml")
    assert _wait_for(lambda: job.status != "queued" and job.status != "running")
    assert job.status == "succeeded"

    assert manager.cancel(job.id).status == "succeeded"


def test_zero_timeout_disables_the_limit():
    assert JobManager(job_timeout_seconds=0).job_timeout_seconds is None
    assert JobManager(job_timeout_seconds=None).job_timeout_seconds is None
    assert JobManager(job_timeout_seconds=5).job_timeout_seconds == 5
