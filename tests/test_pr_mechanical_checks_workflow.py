"""Contract tests for the deterministic gate's step wiring.

The gate runs two independent checks: michen00/pr-checks on the title and body, and
the local commit-subject check. `continue-on-error` plus a final gate step is what
makes one run report both, and these tests pin the parts of that arrangement a
well-meaning edit would undo.

The wiring is asserted against the parsed YAML; the gate's verdict is asserted by
running the gate's own shell, because that is where the decision actually lives.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = yaml.safe_load(
    (_ROOT / '.github/workflows/pr-mechanical-checks.yml').read_text(encoding='utf-8')
)
_JOB = _WORKFLOW['jobs']['checks']
_STEPS = {step['id']: step for step in _JOB['steps'] if 'id' in step}
_GATE = _JOB['steps'][-1]
_PR_CHECKS = 'michen00/pr-checks@db89b15bfdb59cf850f498b56d9e3aaba0b2c005'
# pr-checks uploads this folder for the comment; it is the action's own at that pin.
_FINDINGS_DIR = '${{ runner.temp }}/pr-checks-findings'


def _run_gate(*, pr: str, commits: str) -> subprocess.CompletedProcess[str]:
    """Run the gate step's own shell against one combination of step outcomes.

    `env` is replaced rather than extended so a variable the gate reads but the
    workflow forgot to pass cannot be satisfied by one set in the surrounding shell.
    """
    return subprocess.run(
        ['bash', '-c', _GATE['run']],
        env={'PATH': os.environ['PATH'], 'PR': pr, 'COMMITS': commits},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize('step_id', ['pr', 'commits'])
def test_every_check_runs_whatever_the_other_did(step_id: str) -> None:
    """A failing check must not hide the next one's findings."""
    assert _STEPS[step_id]['continue-on-error'] is True


def test_the_title_and_body_are_checked_by_pr_checks() -> None:
    """The action is pinned to a commit, and uploads its findings for the comment."""
    step = _STEPS['pr']

    assert step['uses'] == _PR_CHECKS
    assert 'upload-findings' not in step['with']
    assert step['with']['max-length'] == '${{ env.SUBJECT_MAX_LENGTH }}'


def test_the_commit_findings_go_where_pr_checks_uploads_them() -> None:
    """The commit check writes into pr-checks' folder before pr-checks uploads it.

    Run after pr-checks, its files would miss the upload, and the comment would leave
    out the commit subjects while the job still went red on them.
    """
    commits = _STEPS['commits']
    steps = _JOB['steps']

    assert steps.index(commits) < steps.index(_STEPS['pr'])
    assert commits['env']['PR_ERRORS_FILE'] == (
        f'{_FINDINGS_DIR}/errors/commit-subjects.txt'
    )
    assert commits['env']['PR_WARNINGS_FILE'] == (
        f'{_FINDINGS_DIR}/warnings/commit-subjects.txt'
    )


def test_the_commit_check_runs_for_every_author() -> None:
    """It skips bot-authored commits from the inside, so the step has no `if:`."""
    assert 'if' not in _STEPS['commits']


def test_the_gate_step_fails_the_job_on_any_error() -> None:
    """continue-on-error makes every check advisory; this is what restores the block.

    The gate has to be the last step: a check added after it would be one the gate
    never reads.
    """
    assert _GATE['if'] == 'always()'
    assert _GATE['env'] == {
        'PR': '${{ steps.pr.outcome }}',
        'COMMITS': '${{ steps.commits.outcome }}',
    }


def test_the_gate_passes_when_both_checks_passed() -> None:
    """The ordinary green path, so the comparisons below are not vacuous."""
    assert _run_gate(pr='success', commits='success').returncode == 0


@pytest.mark.parametrize(
    ('pr', 'commits'),
    [
        ('failure', 'success'),
        ('success', 'failure'),
        ('skipped', 'success'),
        ('success', 'skipped'),
    ],
)
def test_the_gate_fails_unless_both_succeeded(pr: str, commits: str) -> None:
    """A skipped check is not a passing check.

    `continue-on-error` covers a check that ran and reported. When an earlier step
    fails hard, every later step is skipped, and `skipped` is not `failure`, so the
    gate compares against `success`.
    """
    assert _run_gate(pr=pr, commits=commits).returncode == 1


def test_the_gate_cannot_write_to_a_pull_request() -> None:
    """A `pull_request` run resolves the pull request's own merge commit.

    A branch author therefore writes every job in this file and the code it runs, so
    it holds nothing worth taking. The comment is posted by pr-advisory-comment.yml,
    whose definition comes from the default branch.
    """
    assert _WORKFLOW['permissions'] == {'contents': 'read'}


def test_the_job_carries_a_concurrency_group() -> None:
    """Two runs for one pull request finish in order, so the later findings win.

    `cancel-in-progress` must stay False: a canceled run's artifact would still be
    downloadable.
    """
    concurrency = _WORKFLOW['concurrency']
    assert concurrency['group'] == (
        'pr-mechanical-checks-${{ github.event.pull_request.number }}'
    )
    assert concurrency['cancel-in-progress'] is False
