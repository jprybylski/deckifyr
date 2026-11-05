"""`build` writes its PPTX, previews and manifest atomically (issue #90).

A failed or killed build must never leave a PPTX, manifest or preview set that
looks like a complete, current build. These exercise the real
`compose_and_write` (previews stubbed where LibreOffice would run) and, for the
kill case, a real `deckifyr --json build` subprocess against a slow stub
`soffice`.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from test_pptx import _design, _presentation, project  # noqa: F401  (project is a fixture)

from deckifyr._proc import kill_process_tree
from deckifyr.pptx import staging as staging_module
from deckifyr.renderers.preview import PreviewRenderResult
from deckifyr.schema.errors import ContentValidationError

# `deckifyr.pptx` re-exports a `compose` *function* that shadows the submodule.
compose_module = importlib.import_module("deckifyr.pptx.compose")

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shebang scripts")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path) -> dict[str, str]:
    """Every file under `root` -> its hash (staging dirs included on purpose)."""
    return {
        str(p.relative_to(root)): _sha(p) for p in sorted(root.rglob("*")) if p.is_file()
    }


def _staging_leftovers(root: Path) -> list[str]:
    return [p.name for p in root.rglob(f"{staging_module.STAGING_PREFIX}*")]


def _fake_render(count: int, *, pdf: bool = False):
    """A stand-in for `render_slide_previews` that writes `count` PNGs (named the
    way the real one does) into the directory it is given."""

    def render(pptx_path, out_dir, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for page in range(1, count + 1):
            png = out_dir / f"{pptx_path.stem}-{page:02d}.png"
            png.write_bytes(f"png {page} of {pptx_path.name}".encode())
            paths.append(png)
        pdf_path = None
        if pdf and kwargs.get("keep_pdf"):
            pdf_path = out_dir / f"{pptx_path.stem}.pdf"
            pdf_path.write_bytes(b"%PDF fake")
        return PreviewRenderResult(image_paths=paths, pdf_path=pdf_path)

    return render


def _with_previews(presentation, monkeypatch, count=2, **kwargs):
    monkeypatch.setattr(compose_module, "render_slide_previews", _fake_render(count, **kwargs))
    presentation.build.previews = True
    return presentation


# --- success: final paths, nothing left behind -------------------------------


def test_successful_build_promotes_everything_and_leaves_no_staging(project, monkeypatch):
    presentation = _with_previews(_presentation(), monkeypatch, count=2, pdf=True)
    result = _build_with(project, presentation, keep_pdf=True)

    assert result.output_path.is_file() and result.manifest_path.is_file()
    assert [p.name for p in result.preview_paths] == ["out-01.png", "out-02.png"]
    assert all(p.parent == result.output_path.parent / "previews" for p in result.preview_paths)
    assert all(p.is_file() for p in result.preview_paths)
    assert result.preview_pdf_path.is_file()
    assert _staging_leftovers(project) == []

    manifest = json.loads(result.manifest_path.read_text())
    # The manifest names FINAL paths and the hash of the file actually there.
    assert manifest["output"]["path"] == str(result.output_path)
    assert manifest["output"]["sha256"] == _sha(result.output_path)
    assert manifest["previews"] == [str(p) for p in result.preview_paths]
    assert manifest["preview_pdf"] == str(result.preview_pdf_path)
    assert staging_module.STAGING_PREFIX not in json.dumps(manifest)


def _build_with(project, presentation, *, keep_pdf=False, preview_slides=None):
    from deckifyr.plan import expand_presentation
    from deckifyr.schema.layouts import Layout, LayoutsDocument

    design = _design()
    layouts = LayoutsDocument(deckifyr="0.1", layouts={"blank": Layout()})
    resolved = expand_presentation(presentation, design, layouts, strict=True)
    return compose_module.compose_and_write(
        presentation,
        design,
        resolved,
        project_root=project,
        presentation_path=project / "presentation.yaml",
        design_path=project / "design.yaml",
        layouts_path=project / "layouts.yaml",
        keep_preview_pdf=keep_pdf,
        preview_slides=preview_slides,
    )


# --- failure before promotion leaves the previous build byte-identical ------


def test_a_failing_preview_leaves_the_previous_build_byte_identical(project, monkeypatch):
    first = _build_with(project, _with_previews(_presentation(), monkeypatch, count=2))
    before = _tree(project)
    assert first.preview_paths

    def boom(pptx_path, out_dir, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{pptx_path.stem}-01.png").write_bytes(b"half a render")
        raise ContentValidationError("LibreOffice PDF conversion exceeded its 1s execution timeout")

    monkeypatch.setattr(compose_module, "render_slide_previews", boom)
    changed = _with_previews_flag(_presentation(alt_text="a different description"))
    with pytest.raises(ContentValidationError, match="exceeded its 1s"):
        _build_with(project, changed)

    assert _tree(project) == before  # PPTX, manifest, previews: all untouched
    assert _staging_leftovers(project) == []


def _with_previews_flag(presentation):
    presentation.build.previews = True
    return presentation


def test_a_failing_first_build_leaves_nothing_at_all(project, monkeypatch):
    def boom(*args, **kwargs):
        raise ContentValidationError("conversion failed")

    monkeypatch.setattr(compose_module, "render_slide_previews", boom)
    with pytest.raises(ContentValidationError):
        _build_with(project, _with_previews_flag(_presentation()))

    out_dir = project / "build"
    assert [p.name for p in out_dir.iterdir()] == [] if out_dir.exists() else True


def test_a_permission_error_while_promoting_the_pptx_restores_the_previous_build(
    project, monkeypatch
):
    _build_with(project, _presentation())
    before = _tree(project)

    def locked(staged, final):
        raise PermissionError(13, "Permission denied (open in PowerPoint)", str(final))

    monkeypatch.setattr(staging_module, "promote_file", locked)
    with pytest.raises(PermissionError):
        _build_with(project, _presentation(alt_text="changed"))

    assert _tree(project) == before
    assert _staging_leftovers(project) == []


# --- the preview set never mixes two builds ---------------------------------


def test_a_full_render_replaces_this_decks_stale_previews_but_not_other_decks(
    project, monkeypatch
):
    _build_with(project, _with_previews(_presentation(), monkeypatch, count=5))
    previews = project / "build" / "previews"
    (previews / "other-deck-01.png").write_bytes(b"someone else's")
    assert len(list(previews.glob("out-*.png"))) == 5

    result = _build_with(project, _with_previews(_presentation(), monkeypatch, count=2))

    assert sorted(p.name for p in previews.glob("out-*.png")) == ["out-01.png", "out-02.png"]
    assert (previews / "other-deck-01.png").read_bytes() == b"someone else's"
    assert [p.name for p in result.preview_paths] == ["out-01.png", "out-02.png"]


def test_a_slide_subset_render_only_touches_the_files_it_wrote(project, monkeypatch):
    _build_with(project, _with_previews(_presentation(), monkeypatch, count=3))
    previews = project / "build" / "previews"
    untouched = {p.name: p.read_bytes() for p in previews.glob("out-0[13].png")}

    def only_second(pptx_path, out_dir, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        png = out_dir / f"{pptx_path.stem}-02.png"
        png.write_bytes(b"re-rendered slide 2")
        return PreviewRenderResult(image_paths=[png])

    monkeypatch.setattr(compose_module, "render_slide_previews", only_second)
    _build_with(
        project, _with_previews_flag(_presentation()), preview_slides=[2]
    )

    assert (previews / "out-02.png").read_bytes() == b"re-rendered slide 2"
    assert {p.name: p.read_bytes() for p in previews.glob("out-0[13].png")} == untouched


def test_a_build_without_previews_leaves_an_existing_preview_dir_alone(project, monkeypatch):
    _build_with(project, _with_previews(_presentation(), monkeypatch, count=2))
    previews = project / "build" / "previews"
    before = _tree(previews)

    _build_with(project, _presentation(alt_text="no previews this time"))

    assert _tree(previews) == before


# --- stale staging from a killed build is swept ------------------------------


def _dead_pid() -> int:
    from deckifyr._proc import pid_alive

    pid = 4_000_000
    while pid_alive(pid):
        pid += 1
    return pid


def test_stale_staging_from_a_dead_build_is_swept_but_a_live_ones_is_not(project):
    out_dir = project / "build"
    out_dir.mkdir()
    dead = out_dir / f"{staging_module.STAGING_PREFIX}{_dead_pid()}-deadbeef"
    dead.mkdir()
    (dead / "out.pptx").write_bytes(b"truncated")
    dead_manifest = out_dir / f"{staging_module.STAGING_PREFIX}{_dead_pid()}-deadbeef.manifest"
    dead_manifest.write_text("{}")
    # The parent process is alive and not us: a concurrent build's directory.
    live = out_dir / f"{staging_module.STAGING_PREFIX}{os.getppid()}-cafef00d"
    live.mkdir()
    unrelated = out_dir / "keep-me.txt"
    unrelated.write_text("hello")

    _build_with(project, _presentation())

    assert not dead.exists() and not dead_manifest.exists()
    assert live.exists()
    assert unrelated.read_text() == "hello"


# --- a real killed build never leaves a lying manifest ----------------------

SLOW_SOFFICE = """#!{python}
import sys, time
open({marker!r}, "w").write("started")
time.sleep(120)
"""


@posix_only
def test_killing_a_build_partway_never_leaves_a_mismatched_manifest(minimal_deck_dir, tmp_path):
    deck = tmp_path / "deck"
    deck.mkdir()
    for name in ("design.yaml", "layouts.yaml", "presentation.yaml"):
        shutil.copyfile(minimal_deck_dir / name, deck / name)
    presentation_path = deck / "presentation.yaml"
    data = yaml.safe_load(presentation_path.read_text())
    marker = tmp_path / "soffice-started"
    slow = tmp_path / "slow-soffice"
    slow.write_text(SLOW_SOFFICE.format(python=sys.executable, marker=str(marker)))
    slow.chmod(0o755)

    # A previous, complete build (no previews).
    command = [sys.executable, "-m", "deckifyr", "--json", "build", str(presentation_path)]
    subprocess.run(command, check=True, capture_output=True)
    out_dir = (deck / data["build"]["output"]).resolve().parent
    pptx = (deck / data["build"]["output"]).resolve()
    manifest = (deck / data["build"]["manifest"]).resolve()
    before = (_sha(pptx), _sha(manifest))

    # The next build changes the deck, asks for previews, and hangs in soffice.
    data["metadata"]["title"] = "A changed deck"
    data["build"]["previews"] = True
    data["build"]["preview"] = {"binary": str(slow), "timeout_seconds": 300}
    presentation_path.write_text(yaml.safe_dump(data, sort_keys=False))
    proc = subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )
    try:
        deadline = time.monotonic() + 60
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists(), "the build never reached the preview step"
        assert _staging_leftovers(out_dir), "the build should be mid-flight in a staging dir"
    finally:
        kill_process_tree(proc)

    # Whatever is on disk is still the previous, self-consistent build.
    assert (_sha(pptx), _sha(manifest)) == before
    assert json.loads(manifest.read_text())["output"]["sha256"] == _sha(pptx)

    # The next build sweeps the dead build's leftovers.
    data["build"]["previews"] = False
    presentation_path.write_text(yaml.safe_dump(data, sort_keys=False))
    subprocess.run(command, check=True, capture_output=True)
    assert _staging_leftovers(out_dir) == []
    assert json.loads(manifest.read_text())["output"]["sha256"] == _sha(pptx)


def test_fsync_helpers_work_on_a_plain_file_and_directory(tmp_path):
    # Regression: `fsync_file` once opened the file read-only, which POSIX
    # tolerates but Windows rejects (`os.fsync` is `_commit` there: EBADF).
    # Every build failed on the Windows runner while macOS/Linux passed.
    target = tmp_path / "f.bin"
    target.write_bytes(b"data")
    staging_module.fsync_file(target)
    staging_module.write_text_synced(tmp_path / "t.txt", "text")
    staging_module.fsync_dir(tmp_path)  # a no-op where directories can't be opened
    assert target.read_bytes() == b"data" and (tmp_path / "t.txt").read_text() == "text"
