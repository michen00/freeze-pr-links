"""Shared validation helpers for the deterministic PR checks.

A finding is an error, which blocks, or a warning, which advises. A finding is an error
only when its detection is exact, so a heuristic or ambiguous finding is always a
warning. An exact detection may still advise: a plan identifier is matched exactly and
only advises.
"""

from __future__ import annotations

__all__ = (
    'CONVENTIONAL_TYPES',
    'SUBJECT_MAX_DEFAULT',
    'Findings',
    'check_subject',
    'max_length_argument',
    'parse_max_length',
    'subject_max_length',
)

import argparse
import os
import re
import sys
import typing
from dataclasses import dataclass, field
from pathlib import Path

if typing.TYPE_CHECKING:
    from collections.abc import Mapping

CONVENTIONAL_TYPES = (
    'feat',
    'fix',
    'docs',
    'style',
    'refactor',
    'perf',
    'test',
    'build',
    'ci',
    'chore',
    'revert',
)

_CONVENTIONAL = re.compile(
    r'^(?:' + '|'.join(CONVENTIONAL_TYPES) + r')'
    r'(?:\([^)]+\))?!?: (?P<subject>.+)$'
)

# One maximum, for a title as typed and a commit subject alike, and 50 is git's own:
# git-commit(1) asks for "a single short (no more than 50 characters) line summarizing
# the change". The `" (#123)"` a squash merge appends to a title is GitHub's rather than
# the author's, and a title at 50 still lands inside the 72 characters where GitHub
# truncates a subject. SUBJECT_MAX_LENGTH rebinds it for a repository that answers to
# another house rule: gitlint defaults to 72 and commitlint to 100.
SUBJECT_MAX_DEFAULT = 50

_MAX_LENGTH_VARIABLE = 'SUBJECT_MAX_LENGTH'

# The settings that leave the length unchecked, matched in any case. `false` is among
# them so that a workflow writing the setting as a YAML boolean turns the check off too.
_UNCHECKED = frozenset({'off', 'none', 'false'})

# Common non-imperative first words: third-person and past forms we see most often.
_NON_IMPERATIVE = frozenset(
    {
        'added',
        'adds',
        'fixed',
        'fixes',
        'updated',
        'updates',
        'removed',
        'removes',
        'changed',
        'changes',
        'refactored',
        'renamed',
        'moved',
        'deleted',
        'created',
        'implemented',
        'introduced',
        'bumped',
        'merged',
    }
)

_PLAN_ID = re.compile(r'\b(?:F\d+|S\d+|Phase\s*\d+|Slice\s*\w+)\b')

# The Jira key CONTRIBUTING.md places straight after the colon, as in
# `feat: [PLT-12] add a rule`. The first word is read after it, so that a ticketed
# subject answers to the same case and mood rules as any other.
_TICKET_KEY = re.compile(r'^\[[A-Z][A-Z0-9]*-[0-9]+\] ')


@dataclass(slots=True)
class Findings:
    """Result of a check: errors block, warnings advise."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: Findings) -> None:
        """Fold another result into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    @property
    def ok(self) -> bool:
        """Whether nothing blocks, i.e. there are no errors."""
        return not self.errors

    def _publish(self, severity: str, message: str) -> None:
        """Print one finding, as a workflow annotation when running under Actions.

        An annotation reaches the Checks tab and the run summary; a plain stderr
        line reaches only a job log, which nobody opens when the job is green.
        Workflow commands are read from stdout, so the annotation form goes there
        while a local run keeps the stream and the wording it always had.
        """
        if os.environ.get('GITHUB_ACTIONS', ''):
            print(f'::{severity}::{message}')
        else:
            print(f'{severity}: {message}', file=sys.stderr)

    def _record_to(self, env_var: str, items: list[str], *, label: str) -> None:
        """Append `items` to the file the environment variable `env_var` names, if any.

        pr-mechanical-checks.yml names one file per check, under PR_WARNINGS_FILE and
        PR_ERRORS_FILE, and hands them to pr-advisory-comment.yml, which posts them on
        the pull request; its gate step also folds the errors into its own failure
        message. Without the variable -- every local run -- nothing is written, and a
        check with nothing to report writes no file. The log `_publish` writes is the
        durable record, so a failed write is reported as a warning, never raised: it
        must not turn a clean check red.
        """
        target = os.environ.get(env_var, '').strip()
        if not target or not items:
            return
        path = Path(target)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as handle:
                handle.writelines(f'{item}\n' for item in items)
        except OSError as error:
            self._publish('warning', f'could not record {label} to {path}: {error}')

    def emit(self, ok_message: str) -> int:
        """Print and record the findings, and return an exit code: 0 unless one blocks.

        Recording writes the files PR_WARNINGS_FILE and PR_ERRORS_FILE name, when set.
        """
        publish = self._publish
        for warning in self.warnings:
            publish('warning', warning)
        for error in self.errors:
            publish('error', error)
        self._record_to('PR_WARNINGS_FILE', self.warnings, label='warnings')
        self._record_to('PR_ERRORS_FILE', self.errors, label='errors')
        if self.ok:
            suffix = ' (with warnings)' if self.warnings else ''
            print(f'{ok_message}{suffix}')
            return 0
        return 1


def _looks_non_imperative(first_word: str) -> bool:
    """Whether the first word reads as non-imperative (past tense or third person)."""
    low = first_word.lower()
    return low in _NON_IMPERATIVE or low.endswith('ing')


def parse_max_length(setting: int | str) -> int | None:
    """Return the maximum a setting names, or None when it leaves the length unchecked.

    A setting is a positive whole number, or `off` to leave the length unchecked; `none`
    and `false` mean `off` too, and case and surrounding spaces do not matter.

    Raises:
        ValueError: The setting is neither a positive whole number nor `off`.
    """
    text = str(setting).strip()
    if text.lower() in _UNCHECKED:
        return None
    if text.isdigit() and int(text) > 0:
        return int(text)
    msg = f'expected a positive whole number or off, not {setting!r}'
    raise ValueError(msg)


def max_length_argument(text: str) -> str:
    """Return a `--max-length` value unchanged once parse_max_length accepts it.

    An unusable value is a usage error naming the flag, rather than the fallback an
    unusable SUBJECT_MAX_LENGTH gets: the person who typed it is there to read it.

    Raises:
        argparse.ArgumentTypeError: parse_max_length rejects the value.
    """
    try:
        parse_max_length(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return text


def subject_max_length(
    explicit: int | str | None = None, *, environ: Mapping[str, str] | None = None
) -> int | None:
    """Return the number of characters a subject line may spend, or None if unchecked.

    An argument beats the environment, and the environment beats the default; either is
    read by parse_max_length. An unusable variable is ignored rather than raised on:
    this runs as a gate on every pull request, and a typo in a repository variable
    should not fail all of them with a traceback that names the variable instead of the
    title.

    Raises:
        ValueError: The argument is neither a positive whole number nor `off`.
    """
    if explicit is not None:
        return parse_max_length(explicit)
    source = os.environ if environ is None else environ
    try:
        return parse_max_length(source.get(_MAX_LENGTH_VARIABLE, ''))
    except ValueError:
        return SUBJECT_MAX_DEFAULT


def check_subject(
    subject_line: str, *, label: str = 'subject', max_length: int | str | None = None
) -> Findings:
    """Validate one Conventional Commit subject line against the conventions.

    These are the rules that govern every subject, a commit's as much as a title's. A
    title and a commit subject answer to one maximum, resolved by subject_max_length,
    and with the length unchecked every other rule still applies.
    """
    found = Findings()
    maximum = subject_max_length(max_length)
    match = _CONVENTIONAL.match(subject_line)
    if match is None:
        found.errors.append(
            f"{label}: not Conventional Commit form 'type(scope): subject' "
            f'(types: {", ".join(CONVENTIONAL_TYPES)})'
        )
        return found

    subject = match.group('subject')

    # Deterministic and unambiguous -> errors (block).
    first_word = _TICKET_KEY.sub('', subject, count=1).split(' ', 1)[0]
    if maximum is not None and len(subject_line) > maximum:
        found.errors.append(
            f'{label}: {len(subject_line)} chars exceeds hard max {maximum}'
        )
    if subject_line.endswith('.'):
        found.errors.append(f'{label}: must not end with a period')
    # The few verbs written with a capital (Americanize, OK, URL-encode) each have a
    # rewording that opens on another word, so a capital blocks without exception.
    if first_word[:1].isupper():
        found.errors.append(
            f"{label}: subject must start lowercase ('{first_word}'); if that word "
            'is a name or an acronym, open on another word'
        )

    # Heuristic or ambiguous -> warnings (advise).
    if _looks_non_imperative(first_word):
        found.warnings.append(
            f"{label}: subject may not be imperative ('{first_word}')"
        )
    if _PLAN_ID.search(subject):
        found.warnings.append(
            f'{label}: contains a plan identifier; keep it out of the subject'
        )
    return found
