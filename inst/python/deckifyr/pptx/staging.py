"""Staging and promotion for `build`'s output files (issue #90).

A build used to write the PPTX in place, then render previews next to it, then
write the manifest. Anything that stopped it partway (a LibreOffice timeout, a
cancelled job, a `PermissionError` because the file is open in PowerPoint)
left a new PPTX beside the *previous* build's manifest -- whose hash no longer
matched -- and a preview set mixing two builds. A launcher recording artifact
hashes could not tell that from a complete build.

So `compose_and_write` builds everything into a private staging directory
(next to the output, so renames stay on one filesystem), and only once every
step succeeded *promotes* it: previous manifest set aside, PPTX renamed into
place, previews, then the new manifest last. A failure before promotion
deletes the staging directory and leaves the previous build's files
byte-identical. This module is the mechanism (names, fsync, sweeping,
promotion); `compose_and_write` stays the orchestration.

Why the old manifest is set aside rather than overwritten last: a process
killed between "new PPTX in place" and "new manifest in place" would leave the
old manifest next to the new PPTX -- exactly the mismatch this exists to
prevent. With the old one moved out of the way first, that window can only
leave *no* manifest, which a consumer correctly reads as "not a complete
build".

Cancel/timeout kill the whole process tree with SIGKILL (`deckifyr._proc`), so
no `finally` runs and a staging directory can be left behind;
`sweep_stale_staging` removes those at the start of the next build.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path

from deckifyr._proc import pid_alive

STAGING_PREFIX = ".deckifyr-staging-"
_STAGING_PID_RE = re.compile(rf"^{re.escape(STAGING_PREFIX)}(\d+)-")


def new_staging_token() -> str:
    """`<pid>-<random>`: the PID lets a later build tell a dead build's leftovers
    from a live concurrent build's working directory."""
    return f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def staging_dir_name(token: str) -> str:
    return f"{STAGING_PREFIX}{token}"


def fsync_file(path: Path) -> None:
    """Flush a finished file's bytes to disk before it becomes visible.

    Opened read-write on purpose: on Windows `os.fsync` is `_commit`, which
    fails with `EBADF` on a read-only handle (POSIX does not care). The file
    was just written by us, so write access is always available.
    """
    with open(path, "r+b") as handle:
        os.fsync(handle.fileno())


def fsync_dir(path: Path) -> None:
    """Persist a directory's entries (renames). A no-op where a directory
    can't be opened for fsync (Windows)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_text_synced(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def remove_path(path: Path) -> None:
    """Delete a file or directory tree, ignoring a path that is already gone."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def sweep_stale_staging(directory: Path) -> list[Path]:
    """Remove staging leftovers in `directory` from builds that no longer run.

    Only entries whose embedded PID is not alive are touched, so a concurrent
    build's live staging directory (and this process's own) is left alone.
    Returns what was removed.
    """
    removed: list[Path] = []
    if not directory.is_dir():
        return removed
    for entry in directory.iterdir():
        match = _STAGING_PID_RE.match(entry.name)
        if not match:
            continue
        pid = int(match.group(1))
        if pid == os.getpid() or pid_alive(pid):
            continue
        remove_path(entry)
        removed.append(entry)
    return removed


def promote_file(staged: Path, final: Path) -> None:
    """Atomically move a finished file into place (`os.replace`)."""
    os.replace(staged, final)
    fsync_dir(final.parent)
