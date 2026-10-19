"""Render a coverage-diff report: diff coverage, or the repository totals.

`coverage json` reduces every source line to one of three claims: it ran
(``executed_lines``), it did not (``missing_lines``), or it is not an
executable statement at all (absent from both). Diff coverage crosses that
against the line numbers a changeset added or modified, read from a
zero-context ``git diff``, so the report can lead with the single most
specific true number there is: how many of *this changeset's* lines a test
actually touched.

Nothing here fails on a coverage number. There is no threshold and no
ratchet -- see the reasoning already recorded in pyproject.toml -- so this
module only ever renders; a caller decides separately whether to fail on a
missing input file.

Every function here takes plain data and returns plain data. No subprocess,
no ``gh``, no filesystem access beyond what the thin CLI at the bottom reads
and writes -- the same split ``scripts/freeze_pr_links.py`` uses, so this can
be tested by calling it directly and so the workflow that runs it owns every
external call.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    'DiffCoverage',
    'diff_coverage',
    'main',
    'parse_changed_lines',
    'render_report',
]

_HUNK_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')
_NEW_FILE_RE = re.compile(r'^\+\+\+ b/(.+)$')

# Ranked repository-wide files beyond this many are not worth a reader's scroll;
# identical to grilling-station's own cutoff, kept here rather than rediscovered.
_WORST_FILE_COUNT = 12

# A changed file with this extension executes even when coverage.py never measured
# it -- a test file, most often -- which is the one case worth a clause of its own:
# silence there would read as "nothing happened" to the person likeliest to have
# moved the totals.
_EXECUTABLE_SUFFIXES = ('.py',)


def parse_changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Return each file's added or modified line numbers, from a zero-context diff.

    Reads only ``+++`` and ``@@`` lines, so it is indifferent to the diff's own
    content -- including a hunk body that itself contains lines shaped like a
    diff header, which a content-sensitive parser could mistake for one.
    """
    by_file: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        new_file = _NEW_FILE_RE.match(line)
        if new_file:
            current = None if new_file.group(1) == '/dev/null' else new_file.group(1)
            continue
        hunk = _HUNK_RE.match(line)
        if hunk and current is not None:
            start = int(hunk.group(1))
            count = 1 if hunk.group(2) is None else int(hunk.group(2))
            if count == 0:
                continue  # a pure deletion touches no line on the new side
            by_file.setdefault(current, set()).update(range(start, start + count))
    return by_file


@dataclass(slots=True)
class DiffCoverage:
    """Coverage of only the lines a changeset added or modified."""

    total: int
    covered: int
    uncovered_by_file: list[tuple[str, list[int]]] = field(default_factory=list)
    measured_files_changed: int = 0
    executable_files_changed: int = 0
    measured_files: list[str] = field(default_factory=list)


def diff_coverage(
    changed_lines: dict[str, set[int]], coverage: dict[str, Any]
) -> DiffCoverage:
    """Cross-reference changed lines against a `coverage json` report.

    Always returns a result -- there being no changed lines is a real,
    present zero, distinct from having no comparison base at all, which a
    caller signals by passing ``None`` to `render_report` instead of calling
    this at all.
    """
    files: dict[str, Any] = coverage['files']
    total = 0
    covered = 0
    measured_files_changed = 0
    executable_files_changed = 0
    measured_files: list[str] = []
    uncovered_by_file: list[tuple[str, list[int]]] = []

    for path, lines in changed_lines.items():
        if path.endswith(_EXECUTABLE_SUFFIXES):
            executable_files_changed += 1
        entry = files.get(path)
        if entry is None:
            continue  # not coverage.py's concern: a test, a workflow, a doc
        measured_files_changed += 1
        measured_files.append(path)
        executed = set(entry['executed_lines'])
        missing = set(entry['missing_lines'])
        uncovered: list[int] = []
        for lineno in sorted(lines):
            if lineno in executed:
                total += 1
                covered += 1
            elif lineno in missing:
                total += 1
                uncovered.append(lineno)
            # else: not an executable statement, outside both lists
        if uncovered:
            uncovered_by_file.append((path, uncovered))

    return DiffCoverage(
        total=total,
        covered=covered,
        uncovered_by_file=uncovered_by_file,
        measured_files_changed=measured_files_changed,
        executable_files_changed=executable_files_changed,
        measured_files=measured_files,
    )


def _blob_url(repo: str, ref: str, path: str, anchor: str = '') -> str:
    """Return a plain head-branch URL.

    Deliberately not pinned to a commit: `.steering/pr-conventions.md` writes
    the branch form regardless, and `pr-link-freeze` rewrites any surviving
    one to the head SHA once this pull request merges. Duplicating that here
    would build a second, competing pinning mechanism for no benefit.
    """
    return f'https://github.com/{repo}/blob/{ref}/{path}{anchor}'


def _file_link(repo: str, ref: str, path: str) -> str:
    """Render a link to a whole file, labeled with its path."""
    return f'[`{path}`]({_blob_url(repo, ref, path)})'


def _line_runs(lines: list[int]) -> list[tuple[int, int]]:
    """Group sorted line numbers into runs of consecutive ones, as (first, last)."""
    runs: list[tuple[int, int]] = []
    for line in lines:
        if runs and line == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], line)
        else:
            runs.append((line, line))
    return runs


def _uncovered_item(repo: str, ref: str, path: str, lines: list[int]) -> str:
    """Render one file's uncovered changed lines as a single list item.

    Each link is labeled with the line or range it opens. Labeling every link
    with the path instead made a file's lines one column of identical
    bullets, with the number visible only in the URL.
    """
    links = []
    for first, last in _line_runs(lines):
        label = f'L{first}' if first == last else f'L{first}-L{last}'
        links.append(f'[{label}]({_blob_url(repo, ref, path, f"#{label}")})')
    return f'- {_file_link(repo, ref, path)}: {", ".join(links)}'


def _statement_percent(summary: dict[str, Any]) -> float:
    """Return the share of statements that ran, as a percentage.

    Not coverage.py's ``percent_covered``: with branch coverage on, that figure
    counts branches as well, so it disagrees with the statement counts printed
    beside it. A file with no statements is fully covered, as coverage.py has it.
    """
    total: int = summary['num_statements']
    missing: int = summary['missing_lines']
    if not total:
        return 100.0
    return (total - missing) / total * 100


def _rank(files: dict[str, Any]) -> list[tuple[str, Any]]:
    """Order files by uncovered line *count*, descending.

    Never by percentage: a 0%-covered five-line file is worth less attention
    than a 40%-covered eight-hundred-line one, and percentage ranking buries
    the second behind the first.
    """
    ranked = [
        (path, entry['summary'])
        for path, entry in files.items()
        if entry['summary']['missing_lines'] > 0
    ]
    ranked.sort(key=lambda item: item[1]['missing_lines'], reverse=True)
    return ranked


def _metrics_table(summary: dict[str, Any]) -> list[str]:
    """Render the two metrics coverage.py actually has -- no `functions` row.

    v8-based tools report statements, branches, functions, and lines as four
    distinct counts; coverage.py does not distinguish a line from the
    statement on it, and has no function-level metric at all. Reporting a
    metric this tool cannot compute would be a claim nothing here checked.
    """
    out = ['| Metric | Covered | Total | % |', '| --- | ---: | ---: | ---: |']
    covered = summary['num_statements'] - summary['missing_lines']
    pct = _statement_percent(summary)
    out.append(f'| Statements | {covered} | {summary["num_statements"]} | {pct:.1f}% |')
    if 'num_branches' in summary:
        b_covered = summary.get('covered_branches', 0)
        b_total = summary.get('num_branches', 0)
        b_pct = (b_covered / b_total * 100) if b_total else 0.0
        out.append(f'| Branches | {b_covered} | {b_total} | {b_pct:.1f}% |')
    return out


def render_report(
    coverage: dict[str, Any], diff: DiffCoverage | None, *, repo: str, ref: str
) -> str:
    """Render the full Markdown coverage report.

    Leads with the single most specific true number there is: diff coverage
    when the changeset touched a measured line, the repository totals
    otherwise -- and, only then, one clause of context for why the diff
    figure reads empty, when that is worth saying at all.
    """
    files: dict[str, Any] = coverage['files']
    totals: dict[str, Any] = coverage['totals']
    lines = ['## Coverage', '']

    has_diff = diff is not None and diff.total > 0
    if diff is not None and has_diff:
        pct = (diff.covered / diff.total) * 100
        lines.append(
            f'**{diff.covered}/{diff.total} changed lines covered ({pct:.1f}%)**'
        )
        lines.append('')
    else:
        lines.extend(_metrics_table(totals))
        lines.append('')
        if diff is None:
            lines.append('_No comparison base for this event._')
        elif diff.measured_files_changed > 0:
            lines.append('_No executable statements changed._')
        elif diff.executable_files_changed > 0:
            lines.append(
                '_Only tests or excluded helpers changed; the totals above can still '
                'move._',
            )
        else:
            lines.append('_No measured file changed._')
        lines.append('')

    if diff is not None and has_diff and diff.uncovered_by_file:
        lines.append('<details open><summary>Changed lines with no coverage</summary>')
        lines.append('')
        lines.extend(
            _uncovered_item(repo, ref, path, uncovered)
            for path, uncovered in diff.uncovered_by_file
        )
        lines.append('')
        lines.append('</details>')
        lines.append('')

    touched = (
        _rank({p: files[p] for p in diff.measured_files}) if diff is not None else []
    )
    if touched:
        lines.append('### Uncovered in the files you changed')
        lines.append('')
        lines.append('| File | Uncovered | Statements | % |')
        lines.append('| --- | ---: | ---: | ---: |')
        for path, summary in touched:
            lines.append(
                f'| {_file_link(repo, ref, path)} | {summary["missing_lines"]} '
                f'| {summary["num_statements"]} | {_statement_percent(summary):.1f}% |'
            )
        lines.append('')

    worst = _rank(files)[:_WORST_FILE_COUNT]
    if worst:
        lines.append('<details><summary>Repository-wide</summary>')
        lines.append('')
        if has_diff:
            lines.extend(_metrics_table(totals))
            lines.append('')
        lines.append('| File | Uncovered | Statements | % |')
        lines.append('| --- | ---: | ---: | ---: |')
        for path, summary in worst:
            lines.append(
                f'| {_file_link(repo, ref, path)} | {summary["missing_lines"]} '
                f'| {summary["num_statements"]} | {_statement_percent(summary):.1f}% |'
            )
        lines.append('')
        lines.append('</details>')
        lines.append('')

    return '\n'.join(lines).rstrip() + '\n'


def _build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser for the coverage-diff report."""
    parser = argparse.ArgumentParser(description='Render a coverage-diff report.')
    parser.add_argument(
        '--coverage-json', required=True, help="path to coverage.py's json report"
    )
    parser.add_argument(
        '--diff-file',
        help='path to a `git diff --unified=0` file; omit with no comparison base',
    )
    parser.add_argument('--repo', required=True, help='owner/name, for rendered links')
    parser.add_argument(
        '--ref', required=True, help='head branch name, for rendered links'
    )
    parser.add_argument(
        '--out', required=True, help='where to write the rendered report'
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Render the report to `--out`, and to stdout when not running under Actions."""
    args = _build_parser().parse_args(argv)

    try:
        coverage = json.loads(Path(args.coverage_json).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        print(
            f'coverage_diff_report: could not read {args.coverage_json}: {error}',
            file=sys.stderr,
        )
        return 1

    diff: DiffCoverage | None = None
    if args.diff_file:
        try:
            diff_text = Path(args.diff_file).read_text(encoding='utf-8')
        except OSError as error:
            print(
                f'coverage_diff_report: could not read {args.diff_file}: {error}',
                file=sys.stderr,
            )
            return 1
        diff = diff_coverage(parse_changed_lines(diff_text), coverage)

    report = render_report(coverage, diff, repo=args.repo, ref=args.ref)
    Path(args.out).write_text(report, encoding='utf-8')
    print(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
