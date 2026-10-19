"""Each finding is recorded where pr-mechanical-checks.yml hands it to the comment."""

from pathlib import Path

import pytest

from checks._common import Findings

__all__ = ()


@pytest.fixture(autouse=True)
def local(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Run every test as a terminal would, so findings print in their plain form."""
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.delenv('PR_WARNINGS_FILE', raising=False)
    monkeypatch.delenv('PR_ERRORS_FILE', raising=False)
    return monkeypatch


def test_warnings_are_recorded_for_the_comment(
    local: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The comment step reads these files; the stem names the check that raised them."""
    target = tmp_path / 'warnings' / 'title.txt'
    local.setenv('PR_WARNINGS_FILE', str(target))

    Findings(
        warnings=["title: subject may not be imperative ('added')", 'title: not a verb']
    ).emit('ok')

    assert target.read_text(encoding='utf-8').splitlines() == [
        "title: subject may not be imperative ('added')",
        'title: not a verb',
    ]


def test_errors_are_recorded_for_the_comment_and_the_gate(
    local: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The errors file is what lets a red job, and the comment, name the problem."""
    target = tmp_path / 'errors' / 'body.txt'
    local.setenv('PR_ERRORS_FILE', str(target))

    Findings(errors=["missing required section '## Summary'"]).emit('ok')

    assert target.read_text(encoding='utf-8').splitlines() == [
        "missing required section '## Summary'"
    ]


def test_errors_and_warnings_are_recorded_to_separate_files(
    local: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A blocking error never lands among the advice, and both are kept."""
    warnings_target = tmp_path / 'warnings' / 'title.txt'
    errors_target = tmp_path / 'errors' / 'title.txt'
    local.setenv('PR_WARNINGS_FILE', str(warnings_target))
    local.setenv('PR_ERRORS_FILE', str(errors_target))
    found = Findings(
        errors=['title: not Conventional Commit form'],
        warnings=['title: not a verb'],
    )

    assert found.emit('ok') == 1
    assert warnings_target.read_text(encoding='utf-8').splitlines() == [
        'title: not a verb'
    ]
    assert errors_target.read_text(encoding='utf-8').splitlines() == [
        'title: not Conventional Commit form'
    ]


@pytest.mark.parametrize('variable', ['PR_WARNINGS_FILE', 'PR_ERRORS_FILE'])
def test_a_clean_check_writes_no_file(
    local: pytest.MonkeyPatch, tmp_path: Path, variable: str
) -> None:
    """An empty file would make the comment post a heading with nothing under it."""
    target = tmp_path / 'findings.txt'
    local.setenv(variable, str(target))

    Findings().emit('ok')

    assert not target.exists()


def test_recording_is_off_without_the_variables(
    local: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A local run sets neither variable, and must not litter the working tree."""
    local.chdir(tmp_path)

    Findings(errors=['not Conventional Commit form'], warnings=['not a verb']).emit(
        'ok'
    )

    assert list(tmp_path.iterdir()) == []


def test_a_warnings_recording_failure_is_reported_and_still_passes(
    local: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A lost warnings file never loses the warning or fails the check."""
    blocker = tmp_path / 'blocker'
    blocker.write_text('not a directory', encoding='utf-8')
    target = blocker / 'warnings' / 'title.txt'
    local.setenv('PR_WARNINGS_FILE', str(target))

    assert Findings(warnings=['title: not a verb']).emit('ok') == 0
    assert str(target) in capsys.readouterr().err


def test_an_errors_recording_failure_is_reported_and_still_fails(
    local: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A lost errors file never loses the error or changes the check's verdict."""
    blocker = tmp_path / 'blocker'
    blocker.write_text('not a directory', encoding='utf-8')
    target = blocker / 'errors' / 'title.txt'
    local.setenv('PR_ERRORS_FILE', str(target))

    assert Findings(errors=['title: not Conventional Commit form']).emit('ok') == 1
    assert str(target) in capsys.readouterr().err
