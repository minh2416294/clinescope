import sys
from pathlib import Path

import pytest

from clinescope.__main__ import main
from clinescope.apply_recovery import ApplyRecoveryScore
from clinescope.diff_coherence import DiffCoherenceScore
from clinescope.diff_minimality import DiffMinimalityScore
from clinescope.report import render_report, render_score_out_of_100
from clinescope.tool_selection import score_tool_selection
from clinescope.world_a import ToolCall, Trace, load_trace

GOLDEN = Path(
    "C:/Users/admin/PycharmProjects/cline/sdk/packages/core/fixtures/messages/success.messages.json"
)


def _trace(*tool_names: str) -> Trace:
    tool_calls = tuple(
        ToolCall(
            id=f"tool-call-{i}",
            name=name,
            input={},
            result_content=None,
            is_error=None,
        )
        for i, name in enumerate(tool_names)
    )
    return Trace(version=1, turns=(), tool_calls=tool_calls, dropped_items=())


# --- Verbose dump (the historical output; now behind verbose=True) ------------


def test_report_verbose_contains_score_1_and_matched_tool() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files"})

    report = render_report(trace, score, session_id="fixture-success-01", verbose=True)

    assert isinstance(report, str)
    assert "1.0" in report
    assert "matched:        read_files" in report
    assert "missing:        -" in report
    assert "unexpected:     -" in report
    assert "sessionId:      fixture-success-01" in report
    assert "trace.version:  1" in report


def test_report_verbose_shows_missing_name_when_extra_expected() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files", "write_file"})

    report = render_report(trace, score, session_id="fixture-success-01", verbose=True)

    assert "0.5000" in report
    assert "matched:        read_files" in report
    assert "missing:        write_file" in report


def test_report_verbose_multiple_expected_names_render_sorted() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"write_file", "read_files", "search"})

    report = render_report(trace, score, verbose=True)

    assert "expected:       read_files, search, write_file" in report
    assert "missing:        search, write_file" in report


def test_report_verbose_session_id_defaults_to_unknown() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files"})

    report = render_report(trace, score, verbose=True)

    assert "sessionId:      <unknown>" in report


# --- Default summary rendering ------------------------------------------------


def test_summary_is_the_default_and_hides_the_dump() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files"})

    report = render_report(trace, score, session_id="s1")

    # The scannable header + the one-line tool_selection summary are present...
    assert "clinescope report - session s1 (1 tool calls)" in report
    assert "tool_selection  100/100  PASS" in report
    # ...and NONE of the verbose dump leaks into the default.
    assert "=== clinescope report ===" not in report
    assert "[tool_selection]" not in report
    assert "score:          " not in report
    assert "matched:" not in report


def test_verbose_true_restores_the_full_dump() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files"})

    report = render_report(trace, score, session_id="s1", verbose=True)

    assert "[tool_selection]" in report
    assert "score:          1.0000" in report
    # The summary header is NOT in the verbose form (they are distinct renderings).
    assert "clinescope report - session s1 (1 tool calls)" not in report


def test_summary_session_id_defaults_to_unknown() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files"})

    report = render_report(trace, score)

    assert "session <unknown>" in report


def test_summary_tool_selection_partial_shows_missing_and_no_verdict_word() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files", "write_file"})

    report = render_report(trace, score, session_id="s1")

    line = _summary_line(report, "tool_selection")
    assert "50/100" in line
    assert "(missing: write_file)" in line
    # A recall metric has no threshold, so no PASS/FAIL word on a partial score.
    assert "PASS" not in line
    assert "FAIL" not in line


def test_summary_diff_coherence_hard_zero_stays_0_100_not_na() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files"})
    coherence = DiffCoherenceScore(
        score=0.0,
        passed_gates=frozenset(),
        failed_gates=frozenset(),
        violations=("no apply_patch tool call in trace",),
        apply_patch_call_count=0,
        cline_apply_is_error=None,
    )

    report = render_report(trace, score, session_id="s1", diff_coherence=coherence)

    line = _summary_line(report, "diff_coherence")
    assert "0/100" in line
    assert "FAIL" in line
    assert "n/a" not in line


def test_summary_abstaining_scorers_show_na_not_zero() -> None:
    trace = _trace("read_files")
    score = score_tool_selection(trace, {"read_files"})
    minimality = DiffMinimalityScore(
        score=None,
        applicable=False,
        blind_rewrite_hunks=0,
        hunks_with_body=0,
        violations=("no apply_patch tool call in trace",),
        mean_context_density=None,
        add_file_lines=0,
        apply_patch_call_count=0,
        cline_apply_is_error=None,
    )
    recovery = ApplyRecoveryScore(
        score=None,
        applicable=False,
        total_failed_pairs=0,
        confirmed_recovered_pairs=0,
        unrecovered_pairs=0,
        partially_recovered_failures=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=None,
        failed_target_paths=(),
        recovery_pairs=(),
        unparseable_failed_calls=0,
        apply_patch_call_count=0,
        violations=("no apply_patch tool call in trace",),
        cline_apply_is_error=None,
    )

    report = render_report(
        trace,
        score,
        session_id="s1",
        diff_minimality=minimality,
        apply_recovery=recovery,
    )

    min_line = _summary_line(report, "diff_minimality")
    rec_line = _summary_line(report, "apply_recovery")
    assert "n/a" in min_line and "0/100" not in min_line
    assert "n/a" in rec_line and "0/100" not in rec_line
    # The abstain verdict word is "n/a", never a misleading PASS/FAIL.
    assert "FAIL" not in min_line and "PASS" not in min_line
    assert "FAIL" not in rec_line and "PASS" not in rec_line
    # A scorer that did not run reports no failed/total count.
    assert "recovered)" not in rec_line


def test_summary_apply_recovery_reports_recovered_count() -> None:
    trace = _trace("read_files", "apply_patch")
    score = score_tool_selection(trace, {"read_files", "apply_patch"})
    recovery = ApplyRecoveryScore(
        score=0.5,
        applicable=True,
        total_failed_pairs=2,
        confirmed_recovered_pairs=1,
        unrecovered_pairs=1,
        partially_recovered_failures=0,
        same_file_refail_count=0,
        unverified_reattempt_pairs=0,
        verdict_coverage=1.0,
        failed_target_paths=("a.py", "b.py"),
        recovery_pairs=((0, 3, "a.py"),),
        unparseable_failed_calls=0,
        apply_patch_call_count=4,
        violations=(),
        cline_apply_is_error=True,
    )

    report = render_report(trace, score, session_id="s1", apply_recovery=recovery)

    line = _summary_line(report, "apply_recovery")
    assert "50/100" in line
    assert "FAIL" in line
    assert "(1/2 failed patches recovered)" in line


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "n/a"),
        (0.0, "0/100"),
        (1.0, "100/100"),
        (0.75, "75/100"),
        (0.3333, "33/100"),
        # Round-half-up: 0.125 is an exactly-representable half; int(12.5)=12 would
        # be truncation, so 13 proves the +0.5. 0.005 documents the intent (->1).
        (0.125, "13/100"),
        (0.005, "1/100"),
        (0.994, "99/100"),
        (0.996, "100/100"),
    ],
)
def test_render_score_out_of_100_rounds_half_up(
    value: float | None, expected: str
) -> None:
    assert render_score_out_of_100(value) == expected


def _summary_line(report: str, scorer_name: str) -> str:
    for line in report.splitlines():
        if line.startswith(scorer_name):
            return line
    raise AssertionError(f"no summary line for {scorer_name!r} in:\n{report}")


# --- Golden-fixture end-to-end (verbose dump + CLI) ---------------------------


@pytest.mark.skipif(
    not GOLDEN.exists(), reason="Cline golden fixture not checked out at expected path"
)
def test_report_verbose_on_real_golden_fixture_end_to_end() -> None:
    trace = load_trace(GOLDEN)
    score = score_tool_selection(trace, {"read_files"})

    report = render_report(trace, score, session_id="fixture-success-01", verbose=True)

    assert "score:          1.0000" in report
    assert "matched:        read_files" in report
    assert "sessionId:      fixture-success-01" in report
    assert "trace.version:  1" in report
    assert "turns:          4" in report
    assert "tool_calls:     1" in report


@pytest.mark.skipif(
    not GOLDEN.exists(), reason="Cline golden fixture not checked out at expected path"
)
def test_cli_main_verbose_reads_session_id_and_prints_dump(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Proves the on-disk sessionId lift (main -> _read_session_id) is exercised:
    # sessionId is NOT hand-passed here, so it can only appear if read from the file.
    exit_code = main([str(GOLDEN), "--expected", "read_files", "--verbose"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "sessionId:      fixture-success-01" in out
    assert "score:          1.0000" in out
    assert "matched:        read_files" in out


@pytest.mark.skipif(
    not GOLDEN.exists(), reason="Cline golden fixture not checked out at expected path"
)
def test_cli_main_default_prints_summary_not_dump(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(GOLDEN), "--expected", "read_files"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "clinescope report - session fixture-success-01" in out
    assert "tool_selection  100/100  PASS" in out
    assert "[tool_selection]" not in out


@pytest.mark.skipif(
    not GOLDEN.exists(), reason="Cline golden fixture not checked out at expected path"
)
def test_cli_verbose_flag_toggles_dump(capsys: pytest.CaptureFixture[str]) -> None:
    main([str(GOLDEN), "--expected", "read_files"])
    default_out = capsys.readouterr().out
    main([str(GOLDEN), "--expected", "read_files", "--verbose"])
    verbose_out = capsys.readouterr().out

    assert "[tool_selection]" not in default_out
    assert "[tool_selection]" in verbose_out


# --- CLI load-error boundary: a clean one-liner, never a raw traceback --------
# The main CLI must normalize every load failure (bad path, unsupported version,
# malformed / non-object JSON) to a single `error: ...` line on stderr + exit 1,
# mirroring the sibling clinescope.gate CLI. A raw Python traceback is a bug.

RECOVERY_EXAMPLE = (
    Path(__file__).resolve().parent.parent / "examples" / "apply-recovery-trace.json"
)


def _run_main_stderr(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    exit_code = main(argv)
    return exit_code, capsys.readouterr().err


def test_cli_nonexistent_path_prints_clean_error_not_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does-not-exist.json"

    exit_code, err = _run_main_stderr(
        [str(missing), "--expected", "read_files"], capsys
    )

    assert exit_code == 1
    assert err.startswith("error: could not load trace ")
    assert "FileNotFoundError" in err
    assert "Traceback (most recent call last)" not in err


def test_cli_unsupported_version_prints_clean_error_not_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "version2.json"
    bad.write_text('{"version": 2, "messages": []}', encoding="utf-8")

    exit_code, err = _run_main_stderr([str(bad), "--expected", "read_files"], capsys)

    assert exit_code == 1
    assert err.startswith("error: could not load trace ")
    assert "TraceVersionError" in err
    assert "Traceback (most recent call last)" not in err


def test_cli_malformed_json_prints_clean_error_not_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "malformed.json"
    bad.write_text('{"version": 1, "messages": [', encoding="utf-8")

    exit_code, err = _run_main_stderr([str(bad), "--expected", "read_files"], capsys)

    assert exit_code == 1
    assert err.startswith("error: could not load trace ")
    assert "JSONDecodeError" in err
    assert "Traceback (most recent call last)" not in err


def test_cli_json_not_object_prints_clean_error_not_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "notobject.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")

    exit_code, err = _run_main_stderr([str(bad), "--expected", "read_files"], capsys)

    assert exit_code == 1
    assert err.startswith("error: could not load trace ")
    assert "WorldATraceError" in err
    assert "Traceback (most recent call last)" not in err


@pytest.mark.skipif(
    not RECOVERY_EXAMPLE.exists(), reason="apply-recovery example trace not present"
)
def test_cli_valid_trace_still_scores_and_exits_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The error boundary must not regress the happy path.
    exit_code = main([str(RECOVERY_EXAMPLE), "--expected", "read_files", "apply_patch"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "clinescope report - session" in captured.out
    assert captured.err == ""


# --- The in-CLI feedback footer: a one-line, zero-egress, TTY-only nudge -------
# It fires right after someone scored their own trace (the highest-intent moment).
# To STDERR so it never pollutes a piped/redirected stdout report; only when
# stdout is a real terminal, so pipes, CI, and tool consumers never see it.

FEEDBACK_URL_FRAGMENT = "issues/new/choose"


@pytest.mark.skipif(
    not RECOVERY_EXAMPLE.exists(), reason="apply-recovery example trace not present"
)
def test_feedback_footer_prints_to_stderr_when_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Under pytest, capsys makes stdout a non-TTY buffer, so the footer is
    # normally suppressed -- forcing isatty True is what makes this assertion go
    # red before the footer exists, and green after.
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    exit_code = main([str(RECOVERY_EXAMPLE), "--expected", "read_files"])

    captured = capsys.readouterr()
    assert exit_code == 0
    # The nudge is on stderr...
    assert FEEDBACK_URL_FRAGMENT in captured.err
    # ...and NEVER on stdout, so a piped/redirected report stays machine-clean.
    assert FEEDBACK_URL_FRAGMENT not in captured.out


@pytest.mark.skipif(
    not RECOVERY_EXAMPLE.exists(), reason="apply-recovery example trace not present"
)
def test_feedback_footer_silent_when_stdout_not_a_tty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A pipe / redirect / CI run: stdout is not a terminal, so the footer must
    # stay silent on BOTH streams (no noise for tool consumers).
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    exit_code = main([str(RECOVERY_EXAMPLE), "--expected", "read_files"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert FEEDBACK_URL_FRAGMENT not in captured.err
    assert FEEDBACK_URL_FRAGMENT not in captured.out
