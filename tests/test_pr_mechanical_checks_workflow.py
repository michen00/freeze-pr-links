"""Contract tests for the deterministic gate's step wiring.

The gate runs three independent checks. Before this wiring a failing title check
aborted the job, so an author with two unrelated problems learned about them one
per round-trip. `continue-on-error` plus a final gate step is what makes one run
report all three, and these tests pin the parts of that arrangement a well-meaning
edit would undo.

The wiring is asserted against the parsed YAML; the gate's verdict is asserted by
running the gate's own shell, because that is where the decision actually lives.
The staged findings carry the errors as well as the warnings, because the comment
says why the checks failed.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_TEXT = (_ROOT / '.github/workflows/pr-mechanical-checks.yml').read_text(
    encoding='utf-8'
)
_WORKFLOW = yaml.safe_load(_WORKFLOW_TEXT)
_JOB = _WORKFLOW['jobs']['checks']
_STEPS = {step['id']: step for step in _JOB['steps'] if 'id' in step}
_BOT_EXEMPT = "!endsWith(github.event.pull_request.user.login, '[bot]')"


def _step_named(name: str) -> dict[str, Any]:
    """The one step with this `name`, so a rename fails here rather than elsewhere."""
    return next(step for step in _JOB['steps'] if step.get('name') == name)


_STAGING_STEP = _step_named('Stage the findings for the commenting workflow')
_UPLOAD_STEP = _step_named('Upload the findings')
_GATE = _step_named('Fail if any check did not pass')


def _run_gate(
    *,
    title: str,
    commits: str,
    body: str,
    author_is_human: bool = True,
    title_errors: str = '',
    commits_errors: str = '',
    body_errors: str = '',
) -> subprocess.CompletedProcess[str]:
    """Run the gate step's own shell against one combination of step outcomes.

    The gate decides whether the job goes red, and it decides in shell rather
    than in Python, so asserting on the YAML alone would leave the verdict
    itself uncovered. This executes the very text the workflow carries, which
    is what makes an edit to that text visible here.

    `env` is replaced rather than extended so a variable the gate reads but the
    workflow forgot to pass cannot be satisfied by one that happens to be set
    in the surrounding shell. PATH is kept because bash needs it.

    Each `*_errors` parameter is the *content* a check would have recorded to
    its own error file, not a path. Empty is the default and means "no file",
    which is what every call site above relies on to exercise the gate exactly
    as it did before this parameter existed. `/dev/null` stands in for that
    case rather than a path that does not exist, since the gate's shell must
    tolerate both -- a check can be skipped with no file ever created -- and
    covering only the one a real skip produces would leave the other untested.
    """
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            'PATH': os.environ['PATH'],
            'AUTHOR_IS_HUMAN': 'true' if author_is_human else 'false',
            'TITLE_OUTCOME': title,
            'COMMITS_OUTCOME': commits,
            'BODY_OUTCOME': body,
        }
        for var, content in (
            ('TITLE_ERRORS_FILE', title_errors),
            ('COMMITS_ERRORS_FILE', commits_errors),
            ('BODY_ERRORS_FILE', body_errors),
        ):
            if content:
                path = Path(tmp) / var
                path.write_text(content, encoding='utf-8')
                env[var] = str(path)
            else:
                env[var] = '/dev/null'
        return subprocess.run(
            ['bash', '-c', _GATE['run']],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.mark.parametrize('step_id', ['title', 'commits', 'body'])
def test_every_check_runs_whatever_the_others_did(step_id: str) -> None:
    """A failing check must not hide the next one's findings."""
    assert _STEPS[step_id]['continue-on-error'] is True


def test_the_gate_step_fails_the_job_on_any_error() -> None:
    """continue-on-error makes every check advisory; this is what restores the block.

    The gate has to be the last step: a check added after it would be one the
    gate never reads, which is a silent loss of coverage rather than a failure.
    """
    assert _JOB['steps'][-1] is _GATE
    assert _GATE['if'] == 'always()'
    assert set(_GATE['env']) == {
        'AUTHOR_IS_HUMAN',
        'TITLE_OUTCOME',
        'COMMITS_OUTCOME',
        'BODY_OUTCOME',
        'TITLE_ERRORS_FILE',
        'COMMITS_ERRORS_FILE',
        'BODY_ERRORS_FILE',
    }
    assert 'exit 1' in _GATE['run']


def test_the_gate_reads_the_bot_exemption_from_the_same_expression() -> None:
    """The gate's idea of who is exempt must be the steps' idea, not a copy of it.

    The gate accepts `skipped` from the title and body checks only for a bot
    author. If its condition and the `if:` on those steps ever disagreed, the
    disagreement would show up as a red job on a Dependabot pull request or as
    an accepted skip on a human's -- so the two are pinned to the same string
    rather than left to match by inspection.
    """
    assert _GATE['env']['AUTHOR_IS_HUMAN'] == '${{ ' + _BOT_EXEMPT + ' }}'


def test_the_gate_passes_when_every_check_passed() -> None:
    """The ordinary green path, so the stricter comparison is not vacuous."""
    result = _run_gate(title='success', commits='success', body='success')
    assert result.returncode == 0


def test_the_gate_rejects_a_check_that_never_ran() -> None:
    """A skipped check is not a passing check.

    `continue-on-error` covers a check that ran and reported. It does nothing
    for a check that never ran at all: when an earlier step fails hard, every
    later step is skipped, and `skipped` is not `failure`. The gate used to
    compare against `failure` alone, so it announced that every check was clean
    for a job in which none had executed -- which is exactly what happened when
    setup-uv's version fetch failed, since that fetch is a single network call
    with no retry. The job was still red, but only on the failing step's own
    account; anything that made that step non-fatal would have produced a green
    gate over nothing verified.

    All three are named in the message because an author reading it needs to
    know the scope of what did not happen, not just that something did not.
    """
    result = _run_gate(title='skipped', commits='skipped', body='skipped')
    assert result.returncode == 1
    assert 'title=skipped' in result.stdout
    assert 'commit-subjects=skipped' in result.stdout
    assert 'body=skipped' in result.stdout


def test_the_gate_still_fails_on_a_reported_error() -> None:
    """The step's original job, which the stricter comparison must not trade away."""
    result = _run_gate(title='failure', commits='success', body='success')
    assert result.returncode == 1
    assert 'title=failure' in result.stdout


def test_the_gate_accepts_the_skips_a_bot_author_earns() -> None:
    """For a bot, the title and body checks are held back on purpose.

    Requiring `success` from all three would have turned every Dependabot pull
    request red -- the failure mode a stricter gate invites, and the reason the
    gate needs to know who the author is at all.
    """
    result = _run_gate(
        title='skipped', commits='success', body='skipped', author_is_human=False
    )
    assert result.returncode == 0


def test_the_gate_still_requires_the_commit_check_for_a_bot() -> None:
    """The exemption covers the title and body checks and stops there.

    The commit-subject step carries no `if:` of its own; it already skips
    bot-authored commits from the inside, so a skip here still means it did not
    run.
    """
    result = _run_gate(
        title='skipped', commits='skipped', body='skipped', author_is_human=False
    )
    assert result.returncode == 1
    assert 'commit-subjects=skipped' in result.stdout


def test_a_human_authored_run_may_not_skip_the_title_check() -> None:
    """The exemption is conditional, so the condition is worth its own test.

    Without this, a gate that accepted `skipped` unconditionally would pass
    every test above.
    """
    result = _run_gate(title='skipped', commits='success', body='success')
    assert result.returncode == 1
    assert 'title=skipped' in result.stdout


def test_the_bot_exemption_survives_the_rewiring() -> None:
    """Tool-generated titles and bodies keep their own format and are not checked.

    `if: always()` would have replaced these conditions rather than joining them,
    which is the trap continue-on-error exists here to avoid.
    """
    assert _BOT_EXEMPT in _STEPS['title']['if']
    assert _BOT_EXEMPT in _STEPS['body']['if']
    assert 'if' not in _STEPS['commits']


_CHECK_STEP_IDS = {'title', 'commits', 'body'}


def test_every_check_names_its_own_warnings_file() -> None:
    """The stem is what tells a reader which check raised a finding."""
    stems = {
        step['env']['PR_WARNINGS_FILE'].rsplit('/', 1)[-1]
        for step in _JOB['steps']
        if step.get('id') in _CHECK_STEP_IDS
    }
    assert stems == {'title.txt', 'commit-subjects.txt', 'body.txt'}


def test_every_check_names_its_own_errors_file() -> None:
    """The stem is what tells the gate which check's file to read for detail."""
    stems = {
        step['env']['PR_ERRORS_FILE'].rsplit('/', 1)[-1]
        for step in _JOB['steps']
        if step.get('id') in _CHECK_STEP_IDS
    }
    assert stems == {'title.txt', 'commit-subjects.txt', 'body.txt'}


def test_the_gate_reads_each_check_s_own_errors_file() -> None:
    """A path that drifted between a check and the gate would read silently.

    Each check would still run and still emit its `::error::` lines, and the
    gate would still go red on the outcome alone -- so the only symptom of the
    two paths disagreeing is a gate message with no detail in it, which looks
    identical to "this check recorded nothing."
    """
    for step_id, gate_var in (
        ('title', 'TITLE_ERRORS_FILE'),
        ('commits', 'COMMITS_ERRORS_FILE'),
        ('body', 'BODY_ERRORS_FILE'),
    ):
        assert _GATE['env'][gate_var] == _STEPS[step_id]['env']['PR_ERRORS_FILE']


def test_the_gate_names_the_actual_problem() -> None:
    """A red job should say what is wrong, not just which check failed.

    `body=failure` alone sends a reader into the full job log to find the
    "Check PR body" step's own annotation. Folding its recorded error text
    into the gate's own message means the one line GitHub shows in the pull
    request's checks list -- and the one `gh pr checks` prints -- already
    says it.
    """
    result = _run_gate(
        title='success',
        commits='success',
        body='failure',
        body_errors="missing required section '## Summary'\n",
    )
    assert result.returncode == 1
    assert "body=failure: missing required section '## Summary'" in result.stdout


def test_the_gate_joins_more_than_one_recorded_error() -> None:
    """A check can raise several errors at once; the gate must not show only one."""
    result = _run_gate(
        title='success',
        commits='success',
        body='failure',
        body_errors=(
            "missing required section '## Summary'\n"
            "missing required section '## Test plan'\n"
        ),
    )
    assert result.returncode == 1
    assert (
        "missing required section '## Summary'; missing required section '## Test plan'"
    ) in result.stdout


def test_every_check_writes_into_the_staged_directories() -> None:
    """A check writing outside the staged directories would fail silently.

    The staging step only copies `FINDINGS_DIR`'s `warnings` and `errors`. A check
    whose files drifted elsewhere would still run and still record its findings, but
    the artifact would carry empty directories and every run would look clean -- the
    exact failure mode a green job can never reveal on its own. This derives the
    expected prefixes from the staging step's own `FINDINGS_DIR` rather than
    hardcoding them a second time, so the two are pinned to agree.

    Filtered to the three check ids by name, not by "has an id" -- the gate
    step and the staging step are natural candidates for an `id` of their own
    (a future step output would need one), and neither carries a
    `PR_WARNINGS_FILE`, so a loose filter would turn that ordinary addition
    into a `KeyError` here instead of a clean, readable failure.
    """
    findings_dir = _STAGING_STEP['env']['FINDINGS_DIR']
    for step in _JOB['steps']:
        if step.get('id') not in _CHECK_STEP_IDS:
            continue
        warnings_file = step['env']['PR_WARNINGS_FILE']
        errors_file = step['env']['PR_ERRORS_FILE']
        assert warnings_file.rsplit('/', 1)[0] == f'{findings_dir}/warnings'
        assert errors_file.rsplit('/', 1)[0] == f'{findings_dir}/errors'


def test_the_gate_can_no_longer_write_to_a_pull_request() -> None:
    """The whole point of moving the comment out: this file grants nothing worth taking.

    A `pull_request` run resolves the pull request's own merge commit, so a branch
    author writes every job in this file and the code it runs. While the write scope
    lived here, the only things making that safe were a
    repository setting and a fork check. Now there is nothing to protect: the comment
    is posted by pr-advisory-comment.yml, whose definition comes from the default
    branch. Re-adding a write scope here would silently restore the exposure, which
    is why this asserts the absence rather than trusting the comment above it.
    """
    assert _WORKFLOW['permissions'] == {'contents': 'read'}


def test_the_findings_are_staged_and_uploaded_even_when_nothing_was_found() -> None:
    """An empty findings directory is a message, not an absence.

    It is what tells the commenting workflow to delete a comment an earlier
    revision left behind. Skipping the upload when no check wrote a file would
    strand stale advice on the conversation for good, so both steps run under
    `always()` and the upload treats a missing directory as an error rather
    than as nothing to do.
    """
    assert 'always()' in _STAGING_STEP['if']
    assert 'always()' in _UPLOAD_STEP['if']
    assert _UPLOAD_STEP['with']['if-no-files-found'] == 'error'


def test_neither_advisory_step_runs_for_a_bot() -> None:
    """Advice is noise on a generated change, and the gate is where that is decided."""
    assert _BOT_EXEMPT in _STAGING_STEP['if']
    assert _BOT_EXEMPT in _UPLOAD_STEP['if']


def test_the_artifact_does_not_carry_the_pull_request_number() -> None:
    """The number must not be attacker-supplied, and here it would be.

    A fork's `pull_request` run supplies this file's own definition, so anything
    this job writes into the artifact is under the fork's control. A pull request
    number carried across would let one pull request address another, and the
    workflow that reads it holds `pull-requests: write` under the base
    repository's token -- so the comment would post. The commenting workflow
    resolves the number from the API against the run's recorded head SHA instead,
    and this pins the staging step to keep it that way.
    """
    assert 'PR_NUMBER' not in _STAGING_STEP.get('env', {})
    assert 'pr-number' not in _STAGING_STEP['run']


def test_the_job_carries_a_concurrency_group() -> None:
    """The advisory step is a read-modify-write against the PR conversation.

    `opened` followed seconds later by `edited` is this repository's normal
    path, and both runs spend the same time in checkout and setup before
    reaching the advisory step -- so two overlapping runs can each list an
    empty result and each POST, leaving a permanent duplicate that only the
    first id's PATCH ever touches again. `cancel-in-progress` must stay
    False: a canceled run's advisory step still fires under `if: always()`.
    """
    concurrency = _WORKFLOW['concurrency']
    assert concurrency['group'] == (
        'pr-mechanical-checks-${{ github.event.pull_request.number }}'
    )
    assert concurrency['cancel-in-progress'] is False
