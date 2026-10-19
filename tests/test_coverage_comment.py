"""Contract tests for the coverage-comment upsert.

The report has to be idempotent across every push to a pull request, so the
two outcomes that matter are create and edit -- unlike the advisory findings
this mirrors, a coverage report is never cleared, since there is always a
totals table to show even when nothing changed. Modeled directly on
tests/test_pr_warnings_comment.py's stubbing technique: a fake `gh` on PATH,
the real script run as a subprocess.
"""

import os
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / '.github/scripts/coverage-comment.sh'
_COMMENT_MAX = 65536


def _run(
    tmp_path: Path,
    *,
    report: str,
    existing: str = '',
    head_sha: str = '',
    run_url: str = '',
    command_live: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run the script against a stubbed `gh` and a report file on disk."""
    report_file = tmp_path / 'report.md'
    report_file.write_text(report, encoding='utf-8')

    binaries = tmp_path / 'bin'
    binaries.mkdir(exist_ok=True)
    stub = binaries / 'gh'
    probe_exit = '0' if command_live else '1'
    stub.write_text(
        '#!/usr/bin/env bash\n'
        'case "$*" in\n'
        f'  *"issues/7/comments"*) echo \'{existing}\' ;;\n'
        f'  *"coverage-on-demand.yml"*) exit {probe_exit} ;;\n'
        '  *"-X PATCH"*) last="${@: -1}"; '
        'printf \'PATCH %s\\n%s\\n\' "$*" "$(cat "${last#body=@}")" ;;\n'
        '  *"pr comment"*) printf \'POST\\n%s\\n\' "$(cat "${@: -1}")" ;;\n'
        'esac\n',
        encoding='utf-8',
    )
    stub.chmod(0o755)

    return subprocess.run(
        ['bash', str(_SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
        cwd=_ROOT,
        env={
            **os.environ,
            'PATH': f'{binaries}{os.pathsep}{os.environ["PATH"]}',
            'REPO': 'owner/name',
            'PR_NUMBER': '7',
            'REPORT_FILE': str(report_file),
            'HEAD_SHA': head_sha,
            'RUN_URL': run_url,
        },
    )


def test_a_report_with_no_existing_comment_is_posted(tmp_path: Path) -> None:
    """The first push on a pull request creates the comment."""
    result = _run(tmp_path, report='## Coverage\n\nsomething')

    assert 'POST' in result.stdout
    assert '## Coverage' in result.stdout


def test_a_report_replaces_an_existing_comment(tmp_path: Path) -> None:
    """Every later push edits the same comment rather than adding another."""
    result = _run(tmp_path, report='## Coverage\n\nupdated', existing='42')

    assert 'PATCH' in result.stdout
    assert 'issues/comments/42' in result.stdout
    assert 'updated' in result.stdout
    assert 'POST' not in result.stdout


def test_the_marker_precedes_the_report(tmp_path: Path) -> None:
    """The upsert lookup depends on the marker opening the body."""
    result = _run(tmp_path, report='## Coverage\n\nbody')
    posted = result.stdout.split('POST\n', 1)[1]

    assert posted.startswith('<!-- ci:coverage-report -->')


def test_the_footer_names_the_measured_commit(tmp_path: Path) -> None:
    """A reader must be able to tell whether the comment describes this head."""
    result = _run(tmp_path, report='## Coverage\n\nbody', head_sha='abc1234')

    assert 'Measured on abc1234' in result.stdout


def test_the_footer_links_the_run_when_given_one(tmp_path: Path) -> None:
    """The run log link is optional, and only appears when a URL was passed."""
    result = _run(
        tmp_path,
        report='## Coverage\n\nbody',
        head_sha='abc1234',
        run_url='https://example.invalid/run/1',
    )

    assert '[run log](https://example.invalid/run/1)' in result.stdout


def test_no_head_sha_omits_the_measured_line_entirely(tmp_path: Path) -> None:
    """A caller that supplies no commit gets no unearned claim about one."""
    result = _run(tmp_path, report='## Coverage\n\nbody')

    assert 'Measured on' not in result.stdout


def test_the_refresh_line_appears_only_when_the_command_is_live(tmp_path: Path) -> None:
    """The self-referential line is gated on the on-demand workflow existing.

    `workflow_dispatch` and `issue_comment` fire only for a copy of the file
    on the default branch, so advertising `/coverage-report` before that file
    reaches it would be false. The gate is a probe of the default branch,
    not a hardcoded flag, so the line starts appearing on its own the day
    that file merges.
    """
    live = _run(tmp_path, report='## Coverage\n\nbody', command_live=True)
    dead = _run(tmp_path, report='## Coverage\n\nbody', command_live=False)

    assert '/coverage-report' in live.stdout
    assert '/coverage-report' not in dead.stdout


def test_an_oversized_report_is_cut_on_a_line_boundary(tmp_path: Path) -> None:
    """A report past GitHub's cap is trimmed rather than refused outright."""
    huge = '## Coverage\n\n' + ('x' * 70000)
    result = _run(tmp_path, report=huge)
    posted = result.stdout.split('POST\n', 1)[1]

    assert len(posted) <= _COMMENT_MAX
    assert 'Truncated' in posted


def test_truncation_closes_an_open_details_block(tmp_path: Path) -> None:
    """A cut that lands inside <details> must not swallow the footer.

    coverage-report.mjs's own bug: a blind byte-offset slice landed inside
    the report's one unbounded section (the uncovered-lines list) and shipped
    with an unclosed tag, hiding the truncation notice and the footer inside
    a collapsed block. Pinned against a realistic oversized report rather
    than a synthetic one, so a fix that only satisfies a contrived shape does
    not pass here.
    """
    lines = '\n'.join(f'- file_{i}.py — {i}' for i in range(4000))
    huge = (
        f'## Coverage\n\n<details open><summary>x</summary>\n\n{lines}\n\n</details>\n'
    )
    result = _run(tmp_path, report=huge, head_sha='abc1234')
    posted = result.stdout.split('POST\n', 1)[1]

    assert posted.count('<details') == posted.count('</details>')
    assert 'Measured on abc1234' in posted


def test_a_report_that_fits_is_not_truncated(tmp_path: Path) -> None:
    """The budget is computed, so an off-by-one would truncate everything."""
    result = _run(tmp_path, report='## Coverage\n\nshort report')

    assert 'Truncated' not in result.stdout
