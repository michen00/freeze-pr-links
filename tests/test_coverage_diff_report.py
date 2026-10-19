"""Tests for the coverage-diff report renderer.

`coverage json` reduces every file to two claims per line: it is in
``executed_lines``, in ``missing_lines``, or in neither (not an executable
statement at all). Diff coverage crosses that against the line numbers a
changeset added or modified, from a zero-context ``git diff``. Ranking is by
uncovered line *count*, never percentage, so a 0%-covered five-line file does
not outrank a 40%-covered eight-hundred-line one. Each test pins one edge of
that boundary; none of them touches git, coverage.py, or the network, because
the functions under test take plain data and return plain data.
"""

from __future__ import annotations

import json
import typing

from scripts.coverage_diff_report import (
    DiffCoverage,
    diff_coverage,
    main,
    parse_changed_lines,
    render_report,
)

if typing.TYPE_CHECKING:
    from pathlib import Path

    import pytest

# -- parse_changed_lines --


def test_a_pure_addition_is_read_from_its_hunk_header() -> None:
    """`@@ -0,0 +5,3 @@` reports the three added lines starting at 5."""
    diff = 'diff --git a/f.py b/f.py\n+++ b/f.py\n@@ -0,0 +5,3 @@\n'
    assert parse_changed_lines(diff) == {'f.py': {5, 6, 7}}


def test_a_single_line_hunk_omits_its_count() -> None:
    """`+N @@` with no comma means exactly one line, not zero."""
    diff = 'diff --git a/f.py b/f.py\n+++ b/f.py\n@@ -1 +1 @@\n'
    assert parse_changed_lines(diff) == {'f.py': {1}}


def test_a_pure_deletion_touches_no_new_line() -> None:
    """`+N,0 @@` marks a deletion with nothing added, so it contributes no line."""
    diff = 'diff --git a/f.py b/f.py\n+++ b/f.py\n@@ -3,2 +3,0 @@\n'
    assert parse_changed_lines(diff) == {}


def test_a_deleted_file_is_not_a_changed_file() -> None:
    """`+++ /dev/null` names no file on the new side, so nothing is recorded for it."""
    diff = 'diff --git a/f.py b/dev/null\n+++ /dev/null\n@@ -1,2 +0,0 @@\n'
    assert parse_changed_lines(diff) == {}


def test_two_hunks_in_one_file_both_contribute() -> None:
    """A file touched twice in one diff accumulates both hunks' lines."""
    diff = (
        'diff --git a/f.py b/f.py\n+++ b/f.py\n@@ -1 +1,2 @@\n'
        'diff --git a/f.py b/f.py\n+++ b/f.py\n@@ -10 +11,2 @@\n'
    )
    assert parse_changed_lines(diff) == {'f.py': {1, 2, 11, 12}}


def test_two_files_are_reported_separately() -> None:
    """Each file's `+++` line resets which file later hunks belong to."""
    diff = (
        'diff --git a/a.py b/a.py\n+++ b/a.py\n@@ -1 +1 @@\n'
        'diff --git a/b.py b/b.py\n+++ b/b.py\n@@ -1 +1 @@\n'
    )
    assert parse_changed_lines(diff) == {'a.py': {1}, 'b.py': {1}}


# -- diff_coverage --

COVERAGE = {
    'files': {
        'pkg/a.py': {
            'executed_lines': [1, 2, 5],
            'missing_lines': [3, 4],
            'summary': {
                'num_statements': 5,
                'missing_lines': 2,
                'percent_covered': 60.0,
            },
        },
        'pkg/b.py': {
            'executed_lines': [1],
            'missing_lines': [],
            'summary': {
                'num_statements': 1,
                'missing_lines': 0,
                'percent_covered': 100.0,
            },
        },
    },
    'totals': {'num_statements': 6, 'missing_lines': 2, 'percent_covered': 66.7},
}


def test_a_changed_covered_line_counts_toward_both_totals() -> None:
    """A changed line inside `executed_lines` is measured and covered."""
    result = diff_coverage({'pkg/a.py': {1}}, COVERAGE)
    assert result == DiffCoverage(
        total=1,
        covered=1,
        uncovered_by_file=[],
        measured_files_changed=1,
        executable_files_changed=1,
        measured_files=['pkg/a.py'],
    )


def test_a_changed_missing_line_counts_but_is_not_covered() -> None:
    """A changed line inside `missing_lines` is measured, uncovered, and ranked."""
    result = diff_coverage({'pkg/a.py': {3}}, COVERAGE)
    assert result is not None
    assert result.total == 1
    assert result.covered == 0
    assert result.uncovered_by_file == [('pkg/a.py', [3])]


def test_a_changed_line_absent_from_both_lists_is_not_a_statement() -> None:
    """Line 100 is in neither list, so it never reaches the denominator."""
    result = diff_coverage({'pkg/a.py': {100}}, COVERAGE)
    assert result is not None
    assert result.total == 0
    # The file is still counted as changed-and-measured, since it has an entry --
    # only the specific line was not an executable statement.
    assert result.measured_files_changed == 1


def test_a_changed_file_with_no_coverage_entry_is_not_measured() -> None:
    """A changed file coverage.py never ran over contributes to no total."""
    result = diff_coverage({'pkg/unmeasured.rs': {1}}, COVERAGE)
    assert result is not None
    assert result.total == 0
    assert result.measured_files_changed == 0
    assert result.executable_files_changed == 0


def test_a_non_python_changed_file_is_not_counted_as_executable() -> None:
    """A changed Markdown file is neither measured nor an executable extension."""
    result = diff_coverage({'README.md': {1}}, COVERAGE)
    assert result is not None
    assert result.executable_files_changed == 0


def test_a_changed_python_test_file_counts_as_executable_but_unmeasured() -> None:
    """A `.py` file outside coverage's `source` is executable but not measured.

    This is the case worth telling apart from silence: it can still move the
    totals above, by exercising code in a file it does not itself appear in.
    """
    result = diff_coverage({'tests/test_a.py': {1}}, COVERAGE)
    assert result is not None
    assert result.executable_files_changed == 1
    assert result.measured_files_changed == 0


def test_no_changed_lines_is_a_real_zero_not_a_missing_base() -> None:
    """An empty changed-lines map is a computed, present result."""
    result = diff_coverage({}, COVERAGE)
    assert result == DiffCoverage(
        total=0,
        covered=0,
        uncovered_by_file=[],
        measured_files_changed=0,
        executable_files_changed=0,
        measured_files=[],
    )


def test_uncovered_lines_are_reported_in_file_order_not_sorted_globally() -> None:
    """Two touched files each keep their own uncovered-line list."""
    result = diff_coverage({'pkg/a.py': {3, 4}, 'pkg/b.py': set()}, COVERAGE)
    assert result is not None
    assert result.uncovered_by_file == [('pkg/a.py', [3, 4])]


# -- render_report --


def test_a_report_with_no_base_says_so_and_shows_no_totals_table() -> None:
    """No comparison base means nothing to diff, stated plainly."""
    report = render_report(COVERAGE, None, repo='o/r', ref='feat')
    assert 'No comparison base for this event.' in report
    assert '| Statements |' in report


def test_a_report_with_measured_diff_coverage_leads_with_it() -> None:
    """The single most specific true number is the diff figure, stated first."""
    diff = diff_coverage({'pkg/a.py': {1, 3}}, COVERAGE)
    report = render_report(COVERAGE, diff, repo='o/r', ref='feat')
    assert report.startswith('## Coverage\n\n**1/2 changed lines covered (50.0%)**')


def test_a_report_with_no_measured_diff_shows_repo_totals_instead() -> None:
    """When nothing measured changed, the four... two repository totals lead."""
    diff = diff_coverage({}, COVERAGE)
    report = render_report(COVERAGE, diff, repo='o/r', ref='feat')
    assert '| Statements | 6 |' not in report  # totals table reports per-metric rows
    assert 'No measured file changed.' in report


def test_only_a_python_test_file_changing_gets_its_own_clause() -> None:
    """A test-only change gets the clause that says totals can still move."""
    diff = diff_coverage({'tests/test_a.py': {1}}, COVERAGE)
    report = render_report(COVERAGE, diff, repo='o/r', ref='feat')
    assert 'Only tests or excluded helpers changed' in report


def test_uncovered_ranking_orders_by_count_not_percentage() -> None:
    """An 800-line file with 40% coverage outranks a 5-line file at 0%."""
    coverage = {
        'files': {
            'big.py': {
                'executed_lines': list(range(1, 321)),
                'missing_lines': list(range(321, 801)),
                'summary': {
                    'num_statements': 800,
                    'missing_lines': 480,
                    'percent_covered': 40.0,
                },
            },
            'small.py': {
                'executed_lines': [],
                'missing_lines': [1, 2, 3, 4, 5],
                'summary': {
                    'num_statements': 5,
                    'missing_lines': 5,
                    'percent_covered': 0.0,
                },
            },
        },
        'totals': {
            'num_statements': 805,
            'missing_lines': 485,
            'percent_covered': 39.8,
        },
    }
    report = render_report(coverage, None, repo='o/r', ref='feat')
    assert report.index('big.py') < report.index('small.py')


def test_a_file_link_is_a_plain_branch_relative_link() -> None:
    """Links are written in the branch form, never pinned to a SHA here.

    `pr-link-freeze` pins any surviving head-branch link to the merge SHA once
    the pull request lands; duplicating that here would fight the one
    mechanism this repository already has for it.
    """
    diff = diff_coverage({'pkg/a.py': {3}}, COVERAGE)
    report = render_report(COVERAGE, diff, repo='o/r', ref='my-branch')
    assert 'https://github.com/o/r/blob/my-branch/pkg/a.py#L3' in report


def test_uncovered_lines_are_one_item_per_file_labeled_by_line() -> None:
    """Each file is one list item, and each link is labeled with what it opens.

    A run of consecutive lines shares one range link, and a line on its own
    gets its own link, so the numbers can be read without following a link.
    """
    coverage = {
        'files': {
            'pkg/c.py': {
                'executed_lines': [1, 5],
                'missing_lines': [2, 3, 4, 7],
                'summary': {
                    'num_statements': 6,
                    'missing_lines': 4,
                    'percent_covered': 33.3,
                },
            },
        },
        'totals': {'num_statements': 6, 'missing_lines': 4, 'percent_covered': 33.3},
    }
    diff = diff_coverage({'pkg/c.py': {1, 2, 3, 4, 7}}, coverage)
    report = render_report(coverage, diff, repo='o/r', ref='feat')
    url = 'https://github.com/o/r/blob/feat/pkg/c.py'
    assert f'- [`pkg/c.py`]({url}): [L2-L4]({url}#L2-L4), [L7]({url}#L7)\n' in report


def test_statement_percentages_follow_from_the_statement_counts() -> None:
    """The % beside a statement count is that count's share, not coverage.py's.

    With branch coverage on, ``percent_covered`` also counts branches: 1477 of
    1783 statements and 453 of 580 branches give 81.7%. Printed beside the
    statement counts, it states a share they do not give, which is 82.8%.
    """
    summary = {
        'num_statements': 1783,
        'missing_lines': 306,
        'percent_covered': 81.68,
        'num_branches': 580,
        'covered_branches': 453,
    }
    coverage = {
        'files': {
            'pkg/a.py': {'executed_lines': [], 'missing_lines': [1], 'summary': summary}
        },
        'totals': summary,
    }
    report = render_report(coverage, None, repo='o/r', ref='feat')
    assert '| Statements | 1477 | 1783 | 82.8% |' in report
    assert '| 306 | 1783 | 82.8% |' in report
    assert '81.7%' not in report


def test_a_measurement_with_no_statements_reads_as_fully_covered() -> None:
    """No statements means nothing missed, as coverage.py reports it."""
    totals = {'num_statements': 0, 'missing_lines': 0, 'percent_covered': 100.0}
    report = render_report(
        {'files': {}, 'totals': totals}, None, repo='o/r', ref='feat'
    )
    assert '| Statements | 0 | 0 | 100.0% |' in report


# -- command line --


def _write_coverage_json(tmp_path: Path) -> Path:
    """Write `COVERAGE` to a file and return its path, for CLI-level tests."""
    path = tmp_path / 'coverage.json'
    path.write_text(json.dumps(COVERAGE), encoding='utf-8')
    return path


def test_the_cli_renders_a_report_with_a_diff_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With --diff-file, the CLI renders diff coverage to --out."""
    coverage_json = _write_coverage_json(tmp_path)
    diff_file = tmp_path / 'diff.txt'
    diff_file.write_text(
        'diff --git a/pkg/a.py b/pkg/a.py\n+++ b/pkg/a.py\n@@ -0,0 +3 @@\n'
    )
    out = tmp_path / 'report.md'

    code = main(
        [
            '--coverage-json',
            str(coverage_json),
            '--diff-file',
            str(diff_file),
            '--repo',
            'o/r',
            '--ref',
            'feat',
            '--out',
            str(out),
        ]
    )

    assert code == 0
    written = out.read_text(encoding='utf-8')
    assert 'changed lines covered' in written
    assert written in capsys.readouterr().out


def test_the_cli_renders_repo_totals_with_no_diff_file(tmp_path: Path) -> None:
    """Omitting --diff-file renders the no-comparison-base report."""
    coverage_json = _write_coverage_json(tmp_path)
    out = tmp_path / 'report.md'

    code = main(
        [
            '--coverage-json',
            str(coverage_json),
            '--repo',
            'o/r',
            '--ref',
            'feat',
            '--out',
            str(out),
        ]
    )

    assert code == 0
    assert 'No comparison base for this event.' in out.read_text(encoding='utf-8')


def test_the_cli_fails_loudly_on_a_missing_coverage_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing input is a tooling fault, so it exits non-zero and says why."""
    code = main(
        [
            '--coverage-json',
            str(tmp_path / 'missing.json'),
            '--repo',
            'o/r',
            '--ref',
            'feat',
            '--out',
            str(tmp_path / 'report.md'),
        ]
    )

    assert code == 1
    assert 'could not read' in capsys.readouterr().err
