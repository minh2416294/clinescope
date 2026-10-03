"""Tests for the README hero generator (scripts/render_demo_svg.py).

The script is a build-time authoring tool, not shipped in the package, so it is not
on the pytest pythonpath (only src/ is). It is imported here by file path. Two things
matter and are pinned:

1. The STATIC-FRAME GUARANTEE the module docstring promises: a renderer that ignores
   the CSS animation (GitHub's <img> camo in some cases) must still show a complete,
   representative scene. That means scene 0 carries no negative animation-delay and the
   prefers-reduced-motion rule forces `.s0` visible. If that guarantee regressed, the
   README hero would render blank for those users.
2. DRIFT: the committed docs/demo.svg must equal render() byte-for-byte, so the checked-in
   hero can never silently diverge from the generator (mirrors tests/test_fixture_drift.py).
3. REAL OUTPUT: each scene's lines, with the script's two stated width edits undone, must
   equal what `clinescope` prints today for that scene's command. Check 2 alone could not
   see the report change under the hero: the session id gained quotes and the advice was
   reworded while the SVG still matched its own generator.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from clinescope.__main__ import main

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "render_demo_svg.py"
_COMMITTED_SVG = _REPO_ROOT / "docs" / "demo.svg"

# The typed command shows a bare file name; these are the committed traces it names.
_SCENE_TRACES = {
    "live-gpt-oss-trace.json": _REPO_ROOT / "examples" / "live-gpt-oss-trace.json",
    "qwen-missing-tools.json": _REPO_ROOT
    / "examples"
    / "corpus"
    / "qwen-missing-tools.json",
}
# Width edit 1: the advice path is shortened to its basename.
_ADVICE_PATH = (
    "'C:\\\\Users\\\\user\\\\clinescope-day11\\\\cap2\\\\repo\\\\validator.py'"
)


def _load_render_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("render_demo_svg", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the module's @dataclass(frozen=True) Scene can resolve its
    # own __module__ during class creation (dataclasses introspects sys.modules).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_render_emits_a_well_formed_svg_with_the_animation_style() -> None:
    svg = _load_render_module().render()
    assert svg.startswith("<svg xmlns='http://www.w3.org/2000/svg'")
    assert svg.endswith("</svg>")
    # The cycle is driven by CSS keyframes in an inline <style>, NOT SMIL (the whole
    # reason the hero animates inline on GitHub). Its presence is contractual.
    assert "<style>" in svg
    assert "@keyframes cycle{" in svg


def test_render_keeps_the_static_frame_guarantee() -> None:
    svg = _load_render_module().render()
    # Scene 0 leads and MUST be paintable in full on a frozen first frame: it is the
    # only scene class without a negative animation-delay (`.s1`, `.s2` carry delays).
    assert "class='scene s0'" in svg
    assert ".s0{animation-delay" not in svg
    # And a reduced-motion / no-animation renderer forces scene 0 visible at opacity 1,
    # so the hero is never a blank frame. This exact rule is the guarantee.
    assert (
        "@media (prefers-reduced-motion:reduce){.scene{animation:none}.s0{opacity:1}}"
        in svg
    )


def test_committed_demo_svg_matches_the_generator() -> None:
    # docs/demo.svg is checked in; render() must reproduce it byte-for-byte, so the
    # committed hero can never drift from the code that generates it. Regenerate with
    # `python scripts/render_demo_svg.py` if this fails after an intentional change.
    rendered = _load_render_module().render()
    committed = _COMMITTED_SVG.read_text(encoding="utf-8")
    assert rendered == committed


@pytest.mark.parametrize("index", [0, 1, 2])
def test_scene_lines_match_real_clinescope_output(
    index: int, capsys: pytest.CaptureFixture[str]
) -> None:
    scene = _load_render_module().CYCLE[index]
    _, *argv = scene.command.split()
    argv = [str(_SCENE_TRACES.get(arg, arg)) for arg in argv]

    assert main(argv) == 0
    real = capsys.readouterr().out.replace(_ADVICE_PATH, "'validator.py'").splitlines()

    # Width edit 2: a line wider than the canvas carries "\n" plus indent at each wrap.
    shown = [re.sub(r"\n *", " ", text) for text, _ in scene.lines]
    assert shown == real
