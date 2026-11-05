"""Tests for `deckifyr.renderers.preview` (spec section 12/18 Phase 3).

`_require_soffice` is a pure PATH check -- always runs. `render_slide_previews`
shells out to a real `soffice` binary (and the optional `pymupdf`
dependency), so that test skips cleanly when `soffice` isn't on PATH --
mirroring `test_renderers_quarto.py`'s own quarto-binary skip pattern
(see CLAUDE.md): expected local/CI behavior, not a gap to mock around.
"""

from __future__ import annotations

import shutil

import pytest
from pptx import Presentation

from deckifyr.renderers.preview import PreviewRenderConfig, render_slide_previews
from deckifyr.schema.errors import ContentValidationError, MissingDependencyError

requires_soffice = pytest.mark.skipif(
    shutil.which("soffice") is None, reason="soffice binary not found on PATH"
)


def test_require_soffice_names_the_missing_binary(tmp_path):
    # Exercise the real public entry point rather than the private
    # `_require_soffice` helper directly, so this also proves
    # `render_slide_previews` checks for the binary before touching
    # pymupdf or the filesystem -- `pptx_path`/`out_dir` are deliberately
    # nonsense paths that would fail loudly if reached.
    config = PreviewRenderConfig(binary="definitely-not-a-real-binary")
    with pytest.raises(ContentValidationError, match="definitely-not-a-real-binary"):
        render_slide_previews(
            tmp_path / "does-not-exist.pptx", tmp_path / "out", config=config
        )


def test_require_soffice_raises_a_structured_dependency_error(tmp_path):
    # R/run-python.R's .handle_missing_dependency() reacts to this exact
    # shape (see CLAUDE.md's "Preview rendering" note) -- pin it down so
    # a refactor here can't silently drop the `dependency` payload R
    # depends on.
    config = PreviewRenderConfig(binary="definitely-not-a-real-binary")
    with pytest.raises(MissingDependencyError) as exc_info:
        render_slide_previews(
            tmp_path / "does-not-exist.pptx", tmp_path / "out", config=config
        )
    payload = exc_info.value.to_dict()
    assert payload["code"] == "E_MISSING_DEPENDENCY"
    assert payload["dependency"] == {
        "name": "soffice",
        "display_name": "LibreOffice",
        "install_url": "https://www.libreoffice.org/download/download/",
    }


@requires_soffice
def test_render_slide_previews_produces_one_png_per_slide(tmp_path):
    prs = Presentation()
    blank_layout = next(
        layout for layout in prs.slide_layouts if layout.name == "Blank"
    )
    prs.slides.add_slide(blank_layout)
    prs.slides.add_slide(blank_layout)
    pptx_path = tmp_path / "two-slides.pptx"
    prs.save(str(pptx_path))

    out_dir = tmp_path / "previews"
    result = render_slide_previews(pptx_path, out_dir)

    assert len(result.image_paths) == 2
    assert [p.name for p in result.image_paths] == [
        "two-slides-01.png",
        "two-slides-02.png",
    ]
    for image_path in result.image_paths:
        assert image_path.is_file()
        assert image_path.stat().st_size > 0
    assert result.pdf_path is None


@requires_soffice
def test_render_slide_previews_slides_filter_renders_only_requested_pages(tmp_path):
    prs = Presentation()
    blank_layout = next(
        layout for layout in prs.slide_layouts if layout.name == "Blank"
    )
    for _ in range(3):
        prs.slides.add_slide(blank_layout)
    pptx_path = tmp_path / "three-slides.pptx"
    prs.save(str(pptx_path))

    out_dir = tmp_path / "previews"
    result = render_slide_previews(pptx_path, out_dir, slides=[2])

    assert [p.name for p in result.image_paths] == ["three-slides-02.png"]
    assert not (out_dir / "three-slides-01.png").exists()
    assert not (out_dir / "three-slides-03.png").exists()


@requires_soffice
def test_render_slide_previews_slides_filter_rejects_out_of_range_index(tmp_path):
    prs = Presentation()
    blank_layout = next(
        layout for layout in prs.slide_layouts if layout.name == "Blank"
    )
    prs.slides.add_slide(blank_layout)
    pptx_path = tmp_path / "one-slide.pptx"
    prs.save(str(pptx_path))

    with pytest.raises(ContentValidationError, match="out of range"):
        render_slide_previews(pptx_path, tmp_path / "previews", slides=[5])


@requires_soffice
def test_render_slide_previews_keep_pdf_saves_the_intermediate_pdf(tmp_path):
    prs = Presentation()
    blank_layout = next(
        layout for layout in prs.slide_layouts if layout.name == "Blank"
    )
    prs.slides.add_slide(blank_layout)
    pptx_path = tmp_path / "one-slide.pptx"
    prs.save(str(pptx_path))

    out_dir = tmp_path / "previews"
    result = render_slide_previews(pptx_path, out_dir, keep_pdf=True)

    assert result.pdf_path == out_dir / "one-slide.pdf"
    assert result.pdf_path.is_file()
    assert result.pdf_path.stat().st_size > 0


# --- isolated profile + group kill (issue #84) -----------------------------
#
# These use a fake `soffice` (a tiny script) so they run without LibreOffice
# and can observe exactly how it was invoked.

import subprocess  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import os  # noqa: E402

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shebang scripts")


def _one_slide_pptx(tmp_path, name="deck.pptx"):
    prs = Presentation()
    blank_layout = next(layout for layout in prs.slide_layouts if layout.name == "Blank")
    prs.slides.add_slide(blank_layout)
    path = tmp_path / name
    prs.save(str(path))
    return path


def _fake_soffice(tmp_path, body: str):
    script = tmp_path / "fake-soffice"
    script.write_text(f"#!{sys.executable}\n{body}")
    script.chmod(0o755)
    return script


# Records its argv's UserInstallation to a log, then writes a real 1-page PDF
# where `--convert-to pdf --outdir` told it to.
_RECORDING_FAKE = '''
import os, sys, time
args = sys.argv[1:]
log = os.environ.get("FAKE_SOFFICE_LOG") or {log!r}
profile = next(a for a in args if a.startswith("-env:UserInstallation="))
outdir = args[args.index("--outdir") + 1]
src = args[-1]
with open(log, "a") as fh:
    fh.write(profile + "\\n")
time.sleep(0.5)  # overlap with a concurrent call
import pymupdf
doc = pymupdf.open(); doc.new_page()
stem = os.path.splitext(os.path.basename(src))[0]
doc.save(os.path.join(outdir, stem + ".pdf"))
'''


@posix_only
def test_each_render_gets_its_own_private_libreoffice_profile(tmp_path):
    pytest.importorskip("pymupdf")
    log = tmp_path / "profiles.log"
    fake = _fake_soffice(tmp_path, _RECORDING_FAKE.format(log=str(log)))
    config = PreviewRenderConfig(binary=str(fake), timeout_seconds=60)
    errors = []

    def render(index):
        try:
            pptx = _one_slide_pptx(tmp_path, f"deck{index}.pptx")
            render_slide_previews(pptx, tmp_path / f"out{index}", config=config)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=render, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, errors
    profiles = log.read_text().split()
    assert len(profiles) == 2
    assert all(p.startswith("-env:UserInstallation=file:///") for p in profiles)
    # Concurrent calls must never share a profile (the lock that makes the
    # second one silently no-op or hang).
    assert profiles[0] != profiles[1]
    # ...and the profile is private scratch space, gone after the call.
    for profile in profiles:
        assert not os.path.exists(profile.removeprefix("-env:UserInstallation=file://"))


@posix_only
def test_a_hung_render_times_out_and_leaves_no_orphaned_libreoffice(tmp_path):
    pidfile = tmp_path / "pids.txt"
    # Like the real launcher: starts a detached "soffice.bin" in its own
    # session, then hangs.
    fake = _fake_soffice(
        tmp_path,
        f'''
import os, subprocess, sys, time
gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
open({str(pidfile)!r}, "w").write(f"{{os.getpid()}} {{gc.pid}}")
time.sleep(120)
''',
    )
    pptx = _one_slide_pptx(tmp_path)
    config = PreviewRenderConfig(binary=str(fake), timeout_seconds=2)

    pytest.importorskip("pymupdf")
    with pytest.raises(ContentValidationError, match="exceeded its 2s execution timeout"):
        render_slide_previews(pptx, tmp_path / "out", config=config)

    deadline = time.monotonic() + 15
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    parent, grandchild = (int(x) for x in pidfile.read_text().split())

    def alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        stat = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
        ).stdout.strip()
        return bool(stat) and not stat.startswith("Z")

    deadline = time.monotonic() + 15
    while (alive(parent) or alive(grandchild)) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not alive(parent)
    assert not alive(grandchild), "soffice.bin-style grandchild was orphaned"


@requires_soffice
def test_two_concurrent_real_previews_both_succeed(tmp_path):
    pytest.importorskip("pymupdf")
    results, errors = {}, []

    def render(index):
        try:
            pptx = _one_slide_pptx(tmp_path, f"real{index}.pptx")
            results[index] = render_slide_previews(pptx, tmp_path / f"out{index}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=render, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=180)

    assert not errors, errors
    assert sorted(results) == [0, 1]
    for result in results.values():
        assert len(result.image_paths) == 1 and result.image_paths[0].is_file()
