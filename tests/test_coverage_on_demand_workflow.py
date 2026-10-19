"""Contract tests for the on-demand coverage measurement.

`workflow_dispatch` and `issue_comment` are both repository-level events, so
every job here always runs the copy on the default branch -- there is no
pull_request-triggered job whose definition a branch could rewrite, unlike
ci.yml. That property needs no pinning here the way pr-advisory-comment.yml
and coverage-comment.yml pin their `workflow_run` trigger and ref-less
checkout, because it is true of the trigger types themselves rather than a
default an edit could quietly undo.

What does need pinning is the split this workflow introduces: `measure`
checks out the pull request's own code under `contents: read` alone, and
`comment` is the only job holding `pull-requests: write`, and it never checks
out anything but this workflow's own script. Folding the two together would
run pull-request-authored code beside a token that can write to the
conversation -- the same risk ci.yml's own split (against coverage-comment.yml)
exists to avoid, and the one thing about this workflow most likely to be
undone by an edit that looks like a simplification.

Neither trigger can be exercised before this file reaches the default branch,
so these tests are the only pre-merge evidence there is.
"""

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_PATH = _ROOT / '.github/workflows/coverage-on-demand.yml'
_WORKFLOW = yaml.safe_load(_PATH.read_text(encoding='utf-8'))
_JOBS = _WORKFLOW['jobs']
_RESOLVE = _JOBS['resolve']
_MEASURE = _JOBS['measure']
_COMMENT = _JOBS['comment']


def test_the_workflow_holds_no_permission_at_top_level() -> None:
    """Every scope is granted per job, so a reader sees exactly what each needs."""
    assert _WORKFLOW['permissions'] == {'contents': 'read'}


def test_the_gate_requires_a_pull_request_not_any_issue() -> None:
    """`issue_comment` fires on plain issues too, which have no code to measure."""
    assert 'github.event.issue.pull_request != null' in _RESOLVE['if']


def test_the_gate_requires_the_trigger_phrase() -> None:
    """A comment must open with the command, not merely mention it."""
    assert "startsWith(github.event.comment.body, '/coverage-report')" in _RESOLVE['if']


def test_the_gate_requires_a_trusted_author_association() -> None:
    """The commenter's association is the trust boundary for running PR code.

    Named exactly, so widening it later is a diff a reader can see rather
    than a silent drift.
    """
    assert 'fromJSON(\'["OWNER", "MEMBER", "COLLABORATOR"]\')' in _RESOLVE['if']
    assert 'github.event.comment.author_association' in _RESOLVE['if']


def test_the_gate_expression_parses_as_one_line() -> None:
    """A folded scalar with a misindented continuation silently becomes multi-line.

    actionlint and GitHub both tolerate that, so a YAML-level check is the
    only thing that catches it -- the exact trap grilling-station's own
    coverage.yml (PR #369) hit and pinned a test against.
    """
    assert '\n' not in _RESOLVE['if']


def test_workflow_dispatch_needs_no_author_check() -> None:
    """GitHub already restricts who may dispatch a workflow by hand.

    The comment-author check exists only for the trigger that has no
    equivalent gate of its own.
    """
    assert 'workflow_dispatch' in _RESOLVE['if']
    dispatch_clause = _RESOLVE['if'].split('||')[0]
    assert 'author_association' not in dispatch_clause


def test_the_pr_number_is_validated_before_use() -> None:
    """A bad number would address the wrong resource rather than fail.

    The number is interpolated into a REST path.
    """
    resolve_step = next(s for s in _RESOLVE['steps'] if s.get('id') == 'pr')

    assert '*[!0-9]*)' in resolve_step['run']


def test_the_head_sha_is_shape_checked_before_becoming_an_output() -> None:
    """A malformed SHA must not reach `measure`'s checkout as a ref."""
    resolve_step = next(s for s in _RESOLVE['steps'] if s.get('id') == 'pr')

    assert '^[0-9a-f]{40}$' in resolve_step['run']


def test_measure_checks_out_the_resolved_sha_not_a_branch_name() -> None:
    """A branch can move between jobs; the SHA `resolve` validated cannot."""
    checkout = next(
        s
        for s in _MEASURE['steps']
        if str(s.get('uses', '')).startswith('actions/checkout')
    )

    assert checkout['with']['ref'] == '${{ needs.resolve.outputs.head_sha }}'
    assert checkout['with']['repository'] == '${{ needs.resolve.outputs.head_repo }}'


def test_measure_holds_no_write_scope() -> None:
    """This is the job that runs the pull request's own code."""
    assert _MEASURE['permissions'] == {'contents': 'read'}


def test_comment_takes_no_ref_on_its_checkout() -> None:
    """The privileged job must never check out the code `measure` just ran."""
    checkout = next(
        s
        for s in _COMMENT['steps']
        if str(s.get('uses', '')).startswith('actions/checkout')
    )

    assert 'ref' not in checkout.get('with', {})
    assert 'repository' not in checkout.get('with', {})


def test_comment_holds_the_write_scope_and_nothing_extra() -> None:
    """Named exactly, so a scope added here has to be argued for in a diff."""
    assert _COMMENT['permissions'] == {'contents': 'read', 'pull-requests': 'write'}


def test_comment_posts_the_sha_measure_actually_measured() -> None:
    """The provenance footer must name the commit `measure` checked out."""
    post = next(
        s for s in _COMMENT['steps'] if s.get('name') == 'Post the coverage comment'
    )

    assert post['env']['HEAD_SHA'] == '${{ needs.resolve.outputs.head_sha }}'
    assert post['env']['PR_NUMBER'] == '${{ needs.resolve.outputs.pr_number }}'


def test_the_reaction_never_fails_the_run() -> None:
    """A failed reaction is not worth reddening the run over.

    Ten minutes of silence after typing a command already reads as broken.
    """
    react = next(
        s
        for s in _RESOLVE['steps']
        if s.get('name') == 'React to the triggering comment'
    )

    assert react['continue-on-error'] is True


def test_the_artifact_upload_fails_loudly_if_the_report_is_missing() -> None:
    """Unlike ci.yml's own upload, a missing report here is this job's whole job."""
    upload = next(
        s
        for s in _MEASURE['steps']
        if str(s.get('uses', '')).startswith('actions/upload-artifact')
    )

    assert upload['with']['if-no-files-found'] == 'error'
