"""Check a pull request body for required sections and leftover template noise.

A missing required section is an error and exits non-zero. Leftover placeholder tokens,
TBD or TODO markers, markdownlint directive comments, and fenced code blocks without a
language tag are warnings, because each can have a legitimate exception. The
placeholder, marker, and directive scans read the body with its code removed, so a
token quoted as an example is not mistaken for a leftover.

The required sections are the two the pull request template always asks for, Summary
and Testing.

Usage:
    python -m checks.check_pr_body --body-file body.md
    gh pr view 12 --json body -q .body | python -m checks.check_pr_body
"""

from __future__ import annotations

__all__ = ('check_body', 'main')

import argparse
import re
import sys
import typing
from pathlib import Path

from ._common import Findings

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

_REQUIRED = ('Summary', 'Testing')
_HTML_TAGS = frozenset(
    {
        'b',
        'br',
        'code',
        'details',
        'em',
        'hr',
        'i',
        'kbd',
        'sub',
        'summary',
        'sup',
    }
)
_PLACEHOLDER = re.compile(r'<([^<>\n]+)>')
_TBD = re.compile(r'\b(?:TBD|TODO)\b')
_INLINE_CODE = re.compile(r'(?P<ticks>`+).+?(?P=ticks)')
_MARKDOWNLINT = re.compile(
    r'<!--\s*markdownlint-(?:disable|enable|capture|restore|configure-file)\b[^>]*-->'
)


def _unfilled_placeholder(text: str) -> str | None:
    """Return the first unfilled angle-bracket placeholder, or None.

    It returns the slot rather than a bare yes, because a body can hold several and the
    finding is actionable only if it says which one. An HTML tag the author meant to
    keep is skipped, which is what stops `<details>` reading as a slot left unfilled.
    """
    for match in _PLACEHOLDER.finditer(text):
        inner = match.group(1).strip().lstrip('/')
        first = inner.split(maxsplit=1)[0].lower() if inner else ''
        if first in _HTML_TAGS:
            continue
        if inner[:1].isalpha():
            return match.group(0)
    return None


def _markdownlint_scaffolding(text: str) -> str | None:
    """Return the first markdownlint directive comment in the body, or None.

    GitHub never lints a pull request body, so a directive reaching one is noise the
    author meant to strip. The directive is returned rather than its line, because it
    is the whole of what has to go and a body paragraph can be as long as the body. The
    scan is line by line, so a match never spans a newline.
    """
    for line in text.splitlines():
        if (match := _MARKDOWNLINT.search(line)) is not None:
            return match.group(0)
    return None


def _iter_fence_state(body: str) -> Iterator[tuple[str, bool, bool]]:
    """Yield each line, whether it opens a fence, and whether it is part of one."""
    in_fence = False
    for line in body.splitlines():
        is_marker = line.lstrip().startswith('```')
        opens_fence = is_marker and not in_fence
        if is_marker:
            in_fence = not in_fence
        yield line, opens_fence, is_marker or in_fence


def _strip_code(body: str) -> str:
    """Return the body with fenced blocks dropped and inline code spans blanked out.

    A marker or placeholder written as code is being shown, not left behind, so the
    noise scans run on this rather than on the raw body.
    """
    return '\n'.join(
        _INLINE_CODE.sub(' ', line)
        for line, _, is_code in _iter_fence_state(body)
        if not is_code
    )


def _has_unlabeled_fence(body: str) -> bool:
    """Whether any opening code fence lacks a language tag."""
    return any(
        opens_fence and not line.lstrip()[3:].strip()
        for line, opens_fence, _ in _iter_fence_state(body)
    )


def _has_heading(body: str, section: str) -> bool:
    """Whether the body has a level-two heading whose text starts with the section."""
    pattern = rf'^##[ \t]+{re.escape(section)}\b'
    return re.search(pattern, body, re.IGNORECASE | re.MULTILINE) is not None


def check_body(body: str, required: typing.Sequence[str] = _REQUIRED) -> Findings:
    """Validate a pull request body against the required sections and noise checks."""
    found = Findings()
    found.errors.extend(
        f"missing required section '## {section}'"
        for section in required
        if not _has_heading(body, section)
    )
    prose = _strip_code(body)
    if (slot := _unfilled_placeholder(prose)) is not None:
        found.warnings.append(
            f'unfilled template placeholder {slot} — replace it with the real value, '
            'or delete the line'
        )
    if (marker := _TBD.search(prose)) is not None:
        found.warnings.append(
            f'a {marker.group(0)} marker is still in the body — resolve it, or say in '
            'the body why it stays'
        )
    if (directive := _markdownlint_scaffolding(prose)) is not None:
        found.warnings.append(
            f'leftover markdownlint directive {directive} — delete it, and its line '
            'too when the line holds nothing else'
        )
    if _has_unlabeled_fence(body):
        found.warnings.append(
            'a fenced code block has no language tag — add one, using text when the '
            'block is not code'
        )
    return found


def main(argv: list[str] | None = None) -> int:
    """Validate the body and return a process exit code."""
    parser = argparse.ArgumentParser(description='Check a pull request body.')
    parser.add_argument(
        '--body-file',
        type=Path,
        help='path to the body; reads standard input when omitted',
    )
    parser.add_argument(
        '--require',
        nargs='*',
        default=list(_REQUIRED),
        help='required section headings (default: Summary, Testing)',
    )
    args = parser.parse_args(argv)
    if args.body_file:
        body = args.body_file.read_text(encoding='utf-8')
    else:
        body = sys.stdin.read()
    return check_body(body, args.require).emit('body OK')


if __name__ == '__main__':
    raise SystemExit(main())
