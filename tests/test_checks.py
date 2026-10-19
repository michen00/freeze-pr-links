"""Tests for the commit-subject and pull-request-title checks in checks/.

Each test pins which findings one input produces: errors block and warnings advise.
"""

import os
import subprocess
from pathlib import Path

import pytest

from checks import check_commit_messages, check_pr_title
from checks._common import (
    SUBJECT_MAX_DEFAULT,
    Findings,
    check_subject,
    parse_max_length,
    subject_max_length,
)
from checks.check_commit_messages import check_commits

__all__ = ()

# The subject the org's initialization workflow gives its commit: 52 characters,
# over the 50-character hard limit, and capitalized.
_INIT_SUBJECT = 'chore: Initialize project with cookiecutter template'


@pytest.fixture(autouse=True)
def _default_maximum(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear SUBJECT_MAX_LENGTH, so a value in the shell cannot move a bound."""
    monkeypatch.delenv('SUBJECT_MAX_LENGTH', raising=False)


def _subject_of_length(length: int) -> str:
    """Return a valid Conventional Commit subject exactly `length` characters long."""
    prefix = 'docs: add '
    return prefix + 'a' * (length - len(prefix))


def test_a_conventional_subject_is_clean() -> None:
    """A well-formed subject raises no error and no warning."""
    found = check_subject('feat: add the RTK benchmark notebook')
    assert found.errors == []
    assert found.warnings == []


def test_a_scope_and_a_breaking_marker_are_accepted() -> None:
    """A scope and a `!` breaking marker are part of the Conventional form."""
    assert check_subject('feat(checks)!: drop the preferred length rule').ok


@pytest.mark.parametrize(
    'subject', ['fix(CI): guard the label read', 'feat(NB-2): add the comparison']
)
def test_a_scope_with_capitals_is_accepted(subject: str) -> None:
    """A scope may hold any characters but `)`, as gitlint and the ruleset allow."""
    assert check_subject(subject).ok


@pytest.mark.parametrize(
    'subject',
    ['update the readme', 'wip: try a thing', 'Feat: add a rule', 'feat:add a rule'],
)
def test_a_subject_outside_the_conventional_form_is_an_error(subject: str) -> None:
    """A subject without a known type, a colon and a space is an error."""
    found = check_subject(subject)
    assert not found.ok
    assert 'not Conventional Commit form' in found.errors[0]


def test_a_subject_at_the_hard_maximum_is_clean() -> None:
    """Fifty characters is within the hard maximum."""
    assert check_subject(_subject_of_length(50)).ok


def test_a_subject_over_the_hard_maximum_is_an_error() -> None:
    """Fifty-one characters exceeds the hard maximum."""
    found = check_subject(_subject_of_length(51))
    assert found.errors == ['subject: 51 chars exceeds hard max 50']


def test_the_environment_sets_the_maximum() -> None:
    """A repository rebinds the maximum without editing a check."""
    assert subject_max_length(environ={'SUBJECT_MAX_LENGTH': '72'}) == 72


def test_an_explicit_maximum_beats_the_environment() -> None:
    """The caller's argument is the last word, so one run can override the repo's."""
    assert subject_max_length(72, environ={'SUBJECT_MAX_LENGTH': '50'}) == 72


@pytest.mark.parametrize('value', ['', '   ', 'sixty', '0', '-3', '3.5'])
def test_an_unusable_maximum_falls_back_to_the_default(value: str) -> None:
    """A gate that crashed on a typo in a variable would fail every pull request."""
    assert (
        subject_max_length(environ={'SUBJECT_MAX_LENGTH': value}) == SUBJECT_MAX_DEFAULT
    )


def test_the_error_names_the_maximum_applied() -> None:
    """The bound in the message is the bound that was applied."""
    subject = _subject_of_length(60)
    assert check_subject(subject, max_length=72).ok
    assert check_subject(subject, max_length=55).errors == [
        'subject: 60 chars exceeds hard max 55'
    ]


def test_the_environment_reaches_check_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no argument, check_subject reads SUBJECT_MAX_LENGTH."""
    monkeypatch.setenv('SUBJECT_MAX_LENGTH', '72')
    assert check_subject(_subject_of_length(60)).ok


@pytest.mark.parametrize('setting', ['off', 'OFF', ' Off ', 'none', 'false'])
def test_off_leaves_the_length_unchecked(setting: str) -> None:
    """`off`, or `none` or `false` in any case, turns the length rule off."""
    assert parse_max_length(setting) is None
    assert subject_max_length(setting) is None
    assert subject_max_length(environ={'SUBJECT_MAX_LENGTH': setting}) is None


def test_an_unchecked_length_keeps_every_other_rule() -> None:
    """With the length off, a long subject passes and a trailing period still blocks."""
    assert check_subject(_subject_of_length(200), max_length='off').ok
    assert check_subject('fix: guard the empty body.', max_length='off').errors == [
        'subject: must not end with a period'
    ]


@pytest.mark.parametrize('setting', ['', 'sixty', '0', '-3', '3.5'])
def test_an_unusable_argument_is_an_error(setting: str) -> None:
    """An argument is the caller's own, so a bad one is raised rather than replaced."""
    with pytest.raises(ValueError, match='positive whole number or off'):
        subject_max_length(setting)


def test_a_trailing_period_is_an_error() -> None:
    """A subject ending in a period is an error."""
    found = check_subject('fix: guard the empty body.')
    assert found.errors == ['subject: must not end with a period']


@pytest.mark.parametrize(
    'subject',
    [
        'fix: added a guard',
        'fix: adding a guard',
        'feat: add parser for slice F2',
    ],
)
def test_a_style_problem_is_a_warning_only(subject: str) -> None:
    """Non-imperative mood and plan identifiers advise but do not block."""
    found = check_subject(subject)
    assert found.ok
    assert len(found.warnings) == 1


@pytest.mark.parametrize(
    'subject',
    [
        'fix: Guard the empty body',
        'fix: URL-encode the owner',
        'feat: [PLT-12] Add a rule',
    ],
)
def test_a_capitalized_start_blocks(subject: str) -> None:
    """A capital blocks, after a ticket key too, and a capitalized verb included."""
    found = check_subject(subject)
    assert not found.ok
    assert any('must start lowercase' in error for error in found.errors)


def test_a_ticketed_subject_reads_the_word_after_the_key() -> None:
    """A ticket key is not the first word: the case and mood rules read past it."""
    assert check_subject('feat: [PLT-12] add a rule').ok
    found = check_subject('feat: [PLT-12] added a rule')
    assert any("imperative ('added')" in warning for warning in found.warnings)


@pytest.mark.parametrize(
    'author', ['dependabot[bot]', 'github-actions', 'pre-commit-ci[bot]']
)
def test_an_automation_commit_is_exempt(author: str) -> None:
    """A bot's commit passes whatever its subject."""
    assert check_commits([('1' * 40, author, _INIT_SUBJECT)]).ok


def test_the_same_subject_from_a_person_fails() -> None:
    """A person's commit with that subject fails, so the exemption is by author."""
    found = check_commits([('2' * 40, 'Michael I Chen', _INIT_SUBJECT)])
    assert found.errors[0] == '2222222: 52 chars exceeds hard max 50'
    assert "must start lowercase ('Initialize')" in found.errors[1]


def test_a_bad_commit_after_a_clean_one_is_still_reported() -> None:
    """Every commit in the range is checked, not only the first."""
    rows = [
        ('3' * 40, 'Michael I Chen', 'docs: describe the layout'),
        ('4' * 40, 'Michael I Chen', 'update stuff'),
    ]
    found = check_commits(rows)
    assert len(found.errors) == 1
    assert found.errors[0].startswith('4444444:')


def _isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the user's global and system git configuration out of a test."""
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')


def _commit(repo: Path, author: str, subject: str) -> None:
    """Make an empty, unsigned commit in a throwaway repository."""
    subprocess.run(
        [
            'git',
            '-c',
            'commit.gpgsign=false',
            '-c',
            f'user.name={author}',
            '-c',
            'user.email=someone@example.com',
            'commit',
            '--allow-empty',
            '--quiet',
            '-m',
            subject,
        ],
        cwd=repo,
        check=True,
    )


def test_the_commit_check_reads_the_range_from_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The commit check reads subjects and authors from git log over the range."""
    _isolate_git(monkeypatch)
    subprocess.run(['git', 'init', '--quiet'], cwd=tmp_path, check=True)
    _commit(tmp_path, 'Michael I Chen', 'chore: start')
    _commit(tmp_path, 'github-actions', _INIT_SUBJECT)
    _commit(tmp_path, 'Michael I Chen', 'docs: describe the layout')
    monkeypatch.chdir(tmp_path)
    assert check_commit_messages.main(['HEAD~2..HEAD']) == 0
    _commit(tmp_path, 'Michael I Chen', 'update stuff')
    assert check_commit_messages.main(['HEAD~3..HEAD']) == 1


def test_the_commit_check_reports_a_bad_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A range git cannot resolve exits 2 rather than passing."""
    _isolate_git(monkeypatch)
    subprocess.run(['git', 'init', '--quiet'], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    assert check_commit_messages.main(['no-such-ref..HEAD']) == 2


@pytest.mark.parametrize(
    ('title', 'code'),
    [('feat: add the RTK notebook', 0), ('add the RTK notebook', 1)],
)
def test_the_title_check_exits_by_validity(title: str, code: int) -> None:
    """The title check exits 0 for a valid title and 1 for an invalid one."""
    assert check_pr_title.main([title]) == code


def test_the_title_check_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PR_TITLE supplies the title, which is measured as typed."""
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.setenv('PR_TITLE', _subject_of_length(50))
    # A number in the environment is not read: the `" (#123)"` a squash merge appends is
    # GitHub's, so a title at the maximum passes with nothing to report.
    monkeypatch.setenv('PR_NUMBER', '100')
    assert check_pr_title.main([]) == 0
    assert capsys.readouterr() == ('title OK\n', '')


def test_both_checks_take_a_maximum() -> None:
    """The flag reaches the title check and every commit in the range."""
    title = _subject_of_length(60)
    assert check_pr_title.main([title]) == 1
    assert check_pr_title.main([title, '--max-length', '72']) == 0
    rows = [('3' * 40, 'Michael I Chen', title), ('4' * 40, 'Michael I Chen', title)]
    assert len(check_commits(rows).errors) == 2
    assert check_commits(rows, max_length=72).ok
    assert check_commits(rows, max_length='off').ok


def test_off_on_the_command_line_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--max-length off` passes a long title, and the log says so."""
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    assert check_pr_title.main([_subject_of_length(60), '--max-length', 'off']) == 0
    assert capsys.readouterr() == ('title OK, length not checked\n', '')


@pytest.mark.parametrize('setting', ['0', '-3', 'sixty'])
def test_an_unusable_flag_is_a_usage_error(
    setting: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bad `--max-length` stops with a usage error that names the flag."""
    with pytest.raises(SystemExit) as stopped:
        check_pr_title.main(['docs: fix a typo', '--max-length', setting])
    assert stopped.value.code == 2
    assert 'argument --max-length: expected a positive whole number or off' in (
        capsys.readouterr().err
    )


def test_the_title_check_needs_a_title(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no argument and no PR_TITLE the title check stops with a usage error."""
    monkeypatch.delenv('PR_TITLE', raising=False)
    with pytest.raises(SystemExit):
        check_pr_title.main([])


def test_a_warning_becomes_an_annotation_under_actions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Under GitHub Actions a finding is printed as a workflow command on stdout."""
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    code = Findings(warnings=['title: advice']).emit('title OK')
    assert code == 0
    assert (
        capsys.readouterr().out
        == '::warning::title: advice\ntitle OK (with warnings)\n'
    )


def test_an_error_makes_the_exit_code_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A finding with an error returns 1 and prints it to stderr outside Actions."""
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    code = Findings(errors=['title: broken']).emit('title OK')
    assert code == 1
    assert capsys.readouterr().err == 'error: title: broken\n'
