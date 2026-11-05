"""A timed-out quarto/flextable render must not orphan its children.

`quarto` spawns pandoc/deno/R or Jupyter kernels and `Rscript` can spawn
workers; `subprocess.run(..., timeout=...)` kills only the direct child.
The renderers now go through `deckifyr._proc.run_in_group` (issue #84), the
same helper the preview renderer and the web job manager use. These use
fake binaries that start a separate-session grandchild and hang -- the same
shape as `test_jobs_bounded.py`'s check -- so they run without Quarto or R.
"""

from __future__ import annotations

import sys
import tempfile

import pytest
from test_jobs_bounded import HANGING_TREE, _pid_alive, _read_pids, _wait_for

from deckifyr.renderers.flextable import FlextableExecutionConfig, render_flextable_png
from deckifyr.renderers.quarto import QuartoExecutionConfig, render_native
from deckifyr.schema.errors import ContentValidationError

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shebang scripts")


def _fake_binary(tmp_path, name, pidfile):
    """An executable that records its PID and a separate-session grandchild's, then hangs."""
    script = tmp_path / name
    body = HANGING_TREE.replace("sys.argv[-1]", repr(str(pidfile)))
    script.write_text(f"#!{sys.executable}\n{body}")
    script.chmod(0o755)
    return script


def _assert_tree_dead(pidfile):
    parent, grandchild = _read_pids(pidfile)
    assert _wait_for(lambda: not _pid_alive(parent)), "the render process survived its timeout"
    assert _wait_for(lambda: not _pid_alive(grandchild)), "a grandchild was orphaned"


@posix_only
def test_a_hung_quarto_render_times_out_and_leaves_no_orphans(tmp_path):
    pidfile = tmp_path / "pids.txt"
    fake = _fake_binary(tmp_path, "fake-quarto", pidfile)
    qmd = tmp_path / "fragment.qmd"
    qmd.write_text("Hello\n", encoding="utf-8")

    with pytest.raises(ContentValidationError, match="exceeded its 2s execution timeout"):
        render_native(qmd, config=QuartoExecutionConfig(binary=str(fake), timeout_seconds=2))

    _assert_tree_dead(pidfile)


@posix_only
def test_a_hung_flextable_render_times_out_and_leaves_no_orphans(tmp_path, monkeypatch):
    # The renderer reserves its output PNG with `tempfile.mkstemp`; route that
    # into tmp_path so "no temp PNG left behind" is actually observable.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    pidfile = tmp_path / "pids.txt"
    fake = _fake_binary(tmp_path, "fake-rscript", pidfile)
    rds = tmp_path / "table.rds"
    rds.write_bytes(b"not a real rds; the fake binary never reads it")

    with pytest.raises(ContentValidationError, match="exceeded its 2s execution timeout"):
        render_flextable_png(rds, config=FlextableExecutionConfig(binary=str(fake), timeout_seconds=2))

    _assert_tree_dead(pidfile)
    # The temp PNG the renderer reserved must not be left behind either.
    assert not list(scratch.glob("deckifyr-flextable-*.png"))
