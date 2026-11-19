"""Contract tests for the workflow that posts the PR checks' findings.

This workflow exists to hold a `pull-requests: write` scope somewhere a pull request
cannot rewrite. On a `workflow_run` event GitHub takes the definition from the default
branch, so a branch author can change every line of the gate and still not reach this
file.

The workflow cannot be exercised before it merges -- `workflow_run` only fires for the
default branch's copy -- so these tests are the only pre-merge evidence there is.
"""

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_PATH = _ROOT / '.github/workflows/pr-advisory-comment.yml'
_WORKFLOW = yaml.safe_load(_PATH.read_text(encoding='utf-8'))
_JOB = _WORKFLOW['jobs']['comment']
_GATE_NAME = 'PR mechanical checks'
_COMMENT = 'michen00/pr-checks/comment@db89b15bfdb59cf850f498b56d9e3aaba0b2c005'


def test_it_runs_on_the_gates_completion() -> None:
    """The trigger is the security property, not a scheduling detail.

    `workflow_run` is what makes GitHub read this file from the default branch. Any
    other trigger that can see a pull request -- `pull_request` above all -- would
    hand the definition back to the branch.
    """
    # `on` parses as the boolean True under YAML 1.1, which is why this is not "on".
    trigger = _WORKFLOW[True]

    assert list(trigger) == ['workflow_run']
    assert trigger['workflow_run']['workflows'] == [_GATE_NAME]
    assert trigger['workflow_run']['types'] == ['completed']


def test_the_named_gate_workflow_exists_under_that_name() -> None:
    """A `workflow_run` naming a workflow that does not exist never fires, silently.

    The name is matched against the gate's `name:` field rather than its filename, so
    renaming the gate stops the comment with no error anywhere.
    """
    gate = yaml.safe_load(
        (_ROOT / '.github/workflows/pr-mechanical-checks.yml').read_text(
            encoding='utf-8'
        )
    )

    assert gate['name'] == _GATE_NAME


def test_it_runs_on_the_gate_completing_however_the_gate_ended() -> None:
    """`types: [completed]` covers a red gate as well as a green one."""
    assert 'conclusion' not in yaml.dump(_WORKFLOW[True])


def test_it_runs_only_the_pinned_comment_action() -> None:
    """No checkout, so no code from any branch runs beside the write scope.

    The marker is the one this repository's comments already start with, so the
    comment on an open pull request is edited rather than left behind.
    """
    (step,) = _JOB['steps']

    assert step['uses'] == _COMMENT
    assert step['with'] == {'marker': '<!-- pr-mechanical-checks:findings -->'}


def test_it_holds_exactly_the_scopes_it_needs() -> None:
    """`actions: read` reaches the other run's artifact; the write posts the comment.

    Named exactly rather than checked for a subset, so a scope added here has to be
    argued for in a diff that shows it.
    """
    assert _WORKFLOW['permissions'] == {
        'contents': 'read',
        'actions': 'read',
        'pull-requests': 'write',
    }


def test_the_job_is_serialized_per_pull_request() -> None:
    """The upsert is a read-modify-write, so two overlapping runs would double-post.

    Keyed on the head repository and branch rather than on a pull request number,
    which the `workflow_run` payload does not carry for a fork. `cancel-in-progress`
    must stay false: a run canceled after listing the comments but before writing is
    the one state that leaves a duplicate.
    """
    group = _WORKFLOW['concurrency']['group']

    assert 'workflow_run.head_repository.full_name' in group
    assert 'workflow_run.head_branch' in group
    assert _WORKFLOW['concurrency']['cancel-in-progress'] is False
