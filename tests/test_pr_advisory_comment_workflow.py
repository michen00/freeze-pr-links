"""Contract tests for the workflow that posts the PR checks' findings.

This workflow exists to hold a `pull-requests: write` scope somewhere a pull request
cannot rewrite. On a `workflow_run` event GitHub takes the definition from the default
branch, so a branch author can change every line of the gate and still not reach this
file -- which is not true of any *job* boundary inside the gate, since the same author
writes both jobs.

That property is a set of defaults rather than a setting: the trigger, and a checkout
with no `ref:`. Both are the kind of thing an ordinary-looking edit undoes without
looking wrong, so each is pinned below.

The workflow cannot be exercised before it merges -- `workflow_run` only fires for the
default branch's copy -- so these tests are the only pre-merge evidence there is.
"""

from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_PATH = _ROOT / '.github/workflows/pr-advisory-comment.yml'
_WORKFLOW = yaml.safe_load(_PATH.read_text(encoding='utf-8'))
_JOB = _WORKFLOW['jobs']['comment']
_STEPS = {step['id']: step for step in _JOB['steps'] if 'id' in step}
_GATE_NAME = 'PR mechanical checks'


def _step_named(name: str) -> dict[str, Any]:
    """The one step with this `name`, so a rename fails here rather than elsewhere."""
    return next(step for step in _JOB['steps'] if step.get('name') == name)


def test_it_runs_on_the_gates_completion() -> None:
    """The trigger is the security property, not a scheduling detail.

    `workflow_run` is what makes GitHub read this file from the default branch. Any
    other trigger that can see a pull request -- `pull_request` above all -- would
    hand the definition back to the branch and quietly undo the whole change.
    """
    # `on` parses as the boolean True under YAML 1.1, which is why this is not "on".
    trigger = _WORKFLOW[True]

    assert list(trigger) == ['workflow_run']
    assert trigger['workflow_run']['workflows'] == [_GATE_NAME]
    assert trigger['workflow_run']['types'] == ['completed']


def test_the_named_gate_workflow_exists_under_that_name() -> None:
    """A `workflow_run` naming a workflow that does not exist never fires, silently.

    The name is matched against the gate's `name:` field rather than its filename,
    so renaming the gate breaks this workflow with no error anywhere -- the runs
    simply stop happening, and a missing advisory comment looks exactly like having
    no findings.
    """
    gate = yaml.safe_load(
        (_ROOT / '.github/workflows/pr-mechanical-checks.yml').read_text(
            encoding='utf-8'
        )
    )

    assert gate['name'] == _GATE_NAME


def test_it_runs_on_the_gate_completing_however_the_gate_ended() -> None:
    """Advice on a failing pull request is worth more than advice on a passing one.

    `types: [completed]` covers a red gate as well as a green one. Narrowing this to
    a success conclusion would withhold advice from exactly the pull requests most
    likely to need it.
    """
    assert 'conclusion' not in yaml.dump(_WORKFLOW[True])


def test_the_checkout_takes_no_ref() -> None:
    """A `ref:` here would fetch the pull request's code into the privileged context.

    On `workflow_run` the default is the default branch, which is what makes the
    script this job runs the reviewed one. Adding `ref:` to check out the head --
    an edit that looks reasonable, and is how most workflows are written -- would
    execute branch-authored code beside a `pull-requests: write` token.
    """
    checkout = next(
        s
        for s in _JOB['steps']
        if str(s.get('uses', '')).startswith('actions/checkout')
    )

    assert 'ref' not in checkout.get('with', {})


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


def test_the_pull_request_number_comes_from_the_api() -> None:
    """The number must not be read from the artifact, which a fork controls.

    A fork's `pull_request` run supplies the gate's own definition, so a number
    carried across in the artifact would be attacker-chosen -- and this job would
    post onto whichever pull request it named, under the base repository's token.
    Resolving it from the run's recorded head SHA takes the choice away: GitHub
    records that field, and the endpoint answers from the base repository.
    """
    resolve = _STEPS['pr']

    assert resolve['env']['HEAD_SHA'] == '${{ github.event.workflow_run.head_sha }}'
    assert 'commits/${HEAD_SHA}/pulls' in resolve['run']
    assert 'advisory/pr-number' not in yaml.dump(_WORKFLOW)


def test_a_non_numeric_pull_request_number_is_refused() -> None:
    """A bad number would address the wrong resource rather than fail.

    The number is interpolated into a REST path, and an empty value in particular
    would produce a plausible-looking URL. The guard turns both cases into a loud
    stop.
    """
    assert '*[!0-9]*)' in _STEPS['pr']['run']


def test_the_comment_step_reads_the_number_the_guard_produced() -> None:
    """Belt and braces are worth nothing if the value used bypasses them."""
    post = _step_named('Post or clear the findings')

    assert post['env']['PR_NUMBER'] == '${{ steps.pr.outputs.number }}'


def test_forks_are_no_longer_excluded() -> None:
    """The exclusion existed because the old token could not write; this one can.

    A fork's `pull_request` run holds a read-only token whatever its `permissions:`
    block says, so the gate skipped fork heads rather than failing on them. This job
    runs under the base repository's token, so the advice now reaches the authors who
    had no way to see it -- and re-adding a fork check would remove that for no
    remaining reason.
    """
    assert 'head.repo.full_name' not in yaml.dump(_WORKFLOW)
    assert 'fork' not in yaml.dump(_JOB['steps'])


def test_a_failed_delivery_is_not_silent() -> None:
    """continue-on-error hides a script failure inside an otherwise-green job.

    The script runs under `set -euo pipefail`, so a `gh` failure kills it before it
    can say anything -- and to a reader that is indistinguishable from "there were no
    warnings", because this surface's entire signal is whether a comment exists. The
    step must raise its own `::warning::`, the same way `_record` in
    checks/_common.py makes a lost recording visible rather than silent.
    """
    post = _step_named('Post or clear the findings')

    assert post['continue-on-error'] is True
    assert '::warning::' in post['run']


def test_a_missing_artifact_is_tolerated_and_explained() -> None:
    """The gate uploads nothing for a bot pull request, so absence is the normal case.

    Without `continue-on-error` on the download, every bot pull request would leave a
    red run behind for a reason that is not a problem.
    """
    assert _STEPS['findings']['continue-on-error'] is True
    assert _step_named('Say why nothing was posted')['if'] == (
        "steps.findings.outcome != 'success'"
    )


def test_the_job_is_serialized_per_pull_request() -> None:
    """The upsert is a read-modify-write, so two overlapping runs would double-post.

    Keyed on the head repository and branch rather than on a pull request number,
    which the `workflow_run` payload does not carry for a fork. `cancel-in-progress`
    must stay false: a run canceled after listing the comments but before writing is
    the one state that leaves a duplicate nothing later reconciles.
    """
    group = _WORKFLOW['concurrency']['group']

    assert 'workflow_run.head_repository.full_name' in group
    assert 'workflow_run.head_branch' in group
    assert _WORKFLOW['concurrency']['cancel-in-progress'] is False


def test_the_comment_reads_the_errors_as_well_as_the_warnings() -> None:
    """The comment says why a check failed, so it is handed the errors directory too."""
    post = _step_named('Post or clear the findings')

    assert post['env']['PR_ERRORS_DIR'].endswith('/advisory/errors')
    assert post['env']['PR_WARNINGS_DIR'].endswith('/advisory/warnings')
