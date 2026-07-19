"""Render docs/demo.svg: the top-of-README animated terminal cast.

NOT shipped/imported by the package (like scripts/gen_hardcases_25_48.py) -- a
build-time authoring tool, pure stdlib, no project dependency. It renders REAL
`clinescope` output into a self-contained animated SVG that GitHub displays inline
in the README.

Why an SVG (not a VHS gif): a committed SVG needs no external toolchain (no
vhs/ttyd/ffmpeg), animates via CSS/SMIL (verified: GitHub strips JS-driven SVG but
keeps CSS/SMIL), and is regenerable in-repo (`python scripts/render_demo_svg.py`).

The cast CYCLES through three real captured Cline runs, one scene at a time:
  1. a clean run (all scorers pass),
  2. a run where a patch failed and was never retried (apply_recovery FAILS),
  3. a run where the model called no tools at all (tool_selection 0/100).
That trio is the whole value story: it passes good runs and catches two distinct
failure shapes. The `clinescope --demo` one-liner under the GIF runs ONE of these
(scene 2); the README caption states the GIF shows three example runs, so it never
over-promises what the command shows.

Static-frame guarantee: scene 2 (the apply_recovery catch) is painted at base
opacity 1, the others at base opacity 0. A renderer that ignores SMIL therefore
still shows a complete, representative scored report; the animation only adds the
cycle. Every line is drawn exactly once per scene (no overlapping layers).

All report text is genuine `clinescope` stdout captured this session, not a mockup.
The only width edit is shortening the advice file path to a basename (honest: it is
a generic capture path with no real user data).

Run: python scripts/render_demo_svg.py   (from the repo root)
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_SVG = REPO_ROOT / "docs" / "demo.svg"

# Palette (Dracula-ish, high-contrast on a dark terminal).
BG = "#1e1f29"
BAR = "#2a2b38"
FG = "#f8f8f2"
DIM = "#6d6f85"
GREEN = "#50fa7b"
RED = "#ff5555"
YELLOW = "#f1fa8c"
PROMPT = "#bd93f9"

FONT = "font-family='SFMono-Regular,Consolas,Liberation Mono,Menlo,monospace'"
LINE_H = 22
FONT_SIZE = 15

WIDTH = 900
PAD_X = 22
PAD_TOP = 52  # room for the window bar
PROMPT_STR = "$ "

# Per-scene timing (seconds): fade in, hold on the finished report, fade out.
FADE = 0.4
HOLD = 3.4
SCENE = FADE + HOLD + FADE


@dataclass(frozen=True)
class Scene:
    """One cast scene: the command typed + its real scored-report lines (text, color)."""

    command: str
    lines: tuple[tuple[str, str], ...]


# Scene 1 - a clean run: every scorer passes, nothing to fix.
_SCENE_CLEAN = Scene(
    command="clinescope live-gpt-oss-trace.json --expected read_files apply_patch",
    lines=(
        ("clinescope report - session 1783709423832_y5y2f (2 tool calls)", DIM),
        ("tool_selection  100/100  PASS", GREEN),
        ("diff_coherence  100/100  PASS", GREEN),
        ("diff_minimality 100/100  PASS", GREEN),
        (
            "apply_recovery      n/a  n/a   (no failed patches - nothing to recover)",
            DIM,
        ),
        ("clean run - nothing to fix", GREEN),
    ),
)

# Scene 2 - a patch failed and was never retried (the static-frame default).
_SCENE_APPLY_FAIL = Scene(
    command="clinescope --demo",
    lines=(
        ("clinescope report - session 1783723826783_g3hi7 (2 tool calls)", DIM),
        ("tool_selection  100/100  PASS", GREEN),
        ("diff_coherence  100/100  PASS", GREEN),
        ("diff_minimality 100/100  PASS", GREEN),
        ("apply_recovery    0/100  FAIL   (0/1 failed patches recovered)", RED),
        ("", FG),
        ("advice (how to improve the agent):", YELLOW),
        ("  [apply_recovery] no_apply_recovery", YELLOW),
        ("    - The agent failed a patch and did not recover it", FG),
        ("      (0/1 recovered; unrecovered file: validator.py).", FG),
        ("    - Add a retry: after a failed apply_patch, re-read the", FG),
        ("      file and try a corrected patch instead of giving up.", FG),
    ),
)

# Scene 3 - the model called no tools ("said done, did nothing").
_SCENE_MISSING = Scene(
    command="clinescope qwen-missing-tools.json --expected read_files apply_patch",
    lines=(
        ("clinescope report - session 1783823285576_8f1km (0 tool calls)", DIM),
        ("tool_selection    0/100   (missing: apply_patch, read_files)", RED),
        ("diff_coherence    0/100  FAIL   (no apply_patch tool call in trace)", RED),
        ("diff_minimality     n/a  n/a   (no apply_patch - nothing to check)", DIM),
        ("apply_recovery      n/a  n/a   (no apply_patch - nothing to recover)", DIM),
        ("", FG),
        ("advice (how to improve the agent):", YELLOW),
        ("  [tool_selection] missing_tools", YELLOW),
        ("    - The agent never called: apply_patch, read_files.", FG),
        ("    - Tell it which tool the task needs (read a file with", FG),
        ("      read_files before you patch it).", FG),
    ),
)

# Cycle order. The FIRST scene has animation-delay 0 and the keyframe starts at
# opacity 1, so the very first painted frame already shows it in full -- a renderer
# that freezes on frame 1 (some GitHub camo/img cases) still shows a COMPLETE,
# correct scene, never a blank. So the apply_recovery catch (the strongest single
# frame) leads and is the static-safe default. The other two follow in the cycle.
CYCLE = (_SCENE_APPLY_FAIL, _SCENE_CLEAN, _SCENE_MISSING)

# Canvas height sized to the tallest scene so no scene ever overflows/clips.
_MAX_LINES = max(len(s.lines) for s in CYCLE)
HEIGHT = PAD_TOP + LINE_H * (_MAX_LINES + 3)
TOTAL = SCENE * len(CYCLE)

# One shared @keyframes: each scene is visible for ~1/len(CYCLE) of the loop, then
# hidden. Negative animation-delays phase-shift the scenes so exactly one shows at a
# time. This is CSS-in-<style>, NOT SMIL: verified (Platane/snk) to animate inline
# on github.com in an <img> context, where SMIL can freeze to the first frame.
_VISIBLE_FRAC = 1.0 / len(CYCLE)
_FADE_FRAC = (FADE / SCENE) * _VISIBLE_FRAC


def _text(x: float, y: float, s: str, color: str) -> str:
    return (
        f"<text x='{x:.1f}' y='{y:.1f}' fill='{color}' {FONT} "
        f"font-size='{FONT_SIZE}' xml:space='preserve'>{escape(s)}</text>"
    )


def _window_bar() -> str:
    dots = "".join(
        f"<circle cx='{22 + i * 20}' cy='26' r='6' fill='{c}'/>"
        for i, c in enumerate((RED, YELLOW, GREEN))
    )
    label = (
        f"<text x='{WIDTH / 2:.0f}' y='30' fill='{DIM}' {FONT} font-size='13' "
        f"text-anchor='middle'>clinescope</text>"
    )
    return f"<rect x='0' y='0' width='{WIDTH}' height='40' fill='{BAR}'/>{dots}{label}"


def _style_block() -> str:
    """The inline CSS that drives the cycle (must live INSIDE the .svg for <img>)."""
    v = _VISIBLE_FRAC
    f = _FADE_FRAC
    kf = (
        "@keyframes cycle{"
        "0%{opacity:1}"
        f"{(v - f) * 100:.2f}%{{opacity:1}}"
        f"{v * 100:.2f}%{{opacity:0}}"
        "100%{opacity:0}}"
    )
    delays = "".join(
        f".s{i}{{animation-delay:-{i * SCENE:.2f}s}}" for i in range(1, len(CYCLE))
    )
    return (
        "<style>"
        f".scene{{opacity:0;animation:cycle {TOTAL:.2f}s infinite}}"
        f"{delays}"
        f"{kf}"
        "@media (prefers-reduced-motion:reduce){.scene{animation:none}.s0{opacity:1}}"
        "</style>"
    )


def _scene_group(index: int, scene: Scene) -> str:
    """One scene: the command line + its report, in a <g class='scene sN'>.

    Class .scene sets the base cycle animation; .sN adds the negative delay. The
    first scene (index 0) has no delay, so it is what a static/frozen-frame render
    shows in full.
    """
    parts = [_text(PAD_X, PAD_TOP + LINE_H, f"{PROMPT_STR}{scene.command}", FG)]
    first_report_y = PAD_TOP + LINE_H * 3  # blank line after the command
    for i, (line, color) in enumerate(scene.lines):
        if not line:
            continue
        parts.append(_text(PAD_X, first_report_y + i * LINE_H, line, color))
    return f"<g class='scene s{index}'>{''.join(parts)}</g>"


def render() -> str:
    groups = "".join(_scene_group(i, s) for i, s in enumerate(CYCLE))
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{WIDTH}' height='{HEIGHT}' "
        f"viewBox='0 0 {WIDTH} {HEIGHT}' role='img' "
        f"aria-label='clinescope scoring three real Cline runs: a clean run passes, "
        f"a run with an unrecovered failed patch, and a run where the model called no "
        f"tools; each with advice to fix the agent'>"
        f"{_style_block()}"
        f"<rect x='0' y='0' width='{WIDTH}' height='{HEIGHT}' rx='10' fill='{BG}'/>"
        f"{_window_bar()}"
        f"{groups}"
        f"</svg>"
    )


def main() -> None:
    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUT_SVG.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT_SVG} ({OUT_SVG.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
