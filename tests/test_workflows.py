"""Tests for the workflows' security and release properties.

Each test reads a workflow definition, or runs one step of it against a stub `gh` and
throwaway git repositories, and pins one property that a later edit could remove
without any other check failing: who may write, what a privileged job checks out, what
auto-merge waits for and which commits it trusts, and what tests a release once it is
published. The no-interpolation rule is in test_workflow_injection.py.
"""

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

__all__ = ()

_WORKFLOWS = Path(__file__).resolve().parents[1] / '.github' / 'workflows'


def _load(name: str) -> dict[Any, Any]:
    """Return a parsed workflow definition."""
    document: dict[Any, Any] = yaml.safe_load(
        (_WORKFLOWS / name).read_text(encoding='utf-8')
    )
    return document


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    """Return a workflow's `on:` mapping, which YAML 1.1 parses as the key True."""
    triggers: dict[str, Any] = workflow['on'] if 'on' in workflow else workflow[True]
    return triggers


def _steps(workflow: dict[Any, Any], job: str) -> dict[str, dict[str, Any]]:
    """Return a job's steps keyed by name."""
    return {step.get('name', ''): step for step in workflow['jobs'][job]['steps']}


def _write_scopes(permissions: object) -> set[str]:
    """Return the scopes a `permissions:` value grants write on."""
    if permissions == 'write-all':
        return {'*'}
    if isinstance(permissions, dict):
        return {scope for scope, level in permissions.items() if level == 'write'}
    return set()


def test_auto_merge_waits_for_the_context_ci_reports() -> None:
    """The context the auto-merge gate requires is the name CI's run-ci job reports.

    Auto-merge merges as soon as main's rules are met, so without a ruleset that
    requires CI an armed pull request would merge while CI is still running. The gate
    arms only while a ruleset requires this context.
    """
    ci_name = _load('CI.yml')['jobs']['run-ci']['name']
    gate = _steps(_load('bot-automerge.yml'), 'bot-automerge')[
        'Check that the base branch requires CI'
    ]
    assert gate['env']['CONTEXT'] == ci_name


def test_auto_merge_arms_only_behind_the_ci_gate() -> None:
    """Approving and arming wait on the CI gate as well as on eligibility.

    Majors are eligible too, so the gate is what keeps a bot merge waiting for CI.
    """
    steps = _steps(_load('bot-automerge.yml'), 'bot-automerge')
    gate = steps['Check that the base branch requires CI']
    arm = steps['Re-check the kill switch, then approve and arm']
    assert gate['if'] == "steps.eligible.outputs.should_merge == 'true'"
    assert arm['if'] == (
        "steps.eligible.outputs.should_merge == 'true' && "
        "steps.gate.outputs.required == 'true'"
    )


def test_auto_merge_guards_on_the_pull_request_author() -> None:
    """The arming job checks who opened the pull request, not who caused the event.

    `github.actor` is whoever caused the event, such as a person who pushed to the
    branch, while the author stays `dependabot[bot]` for the life of the pull request.
    """
    guard = _load('bot-automerge.yml')['jobs']['bot-automerge']['if']
    assert "github.event.pull_request.user.login == 'dependabot[bot]'" in guard
    assert 'github.actor' not in guard


def test_auto_merge_approves_as_github_actions() -> None:
    """The approval is the default token's; only arming may use the App token.

    pr-catchup.yml pushes as the App, so under last-push approval an App approval would
    never count.
    """
    arm = _steps(_load('bot-automerge.yml'), 'bot-automerge')[
        'Re-check the kill switch, then approve and arm'
    ]
    assert arm['env']['GH_TOKEN'] == '${{ github.token }}'
    assert arm['env']['ARM_TOKEN'] == (
        '${{ steps.app-token.outputs.token || github.token }}'
    )
    lines = arm['run'].splitlines()
    approve = [line for line in lines if 'gh pr review --approve' in line]
    merge = [line for line in lines if 'gh pr merge --auto' in line]
    assert len(approve) == 1
    assert 'ARM_TOKEN' not in approve[0]
    assert [line.strip() for line in merge] == [
        'GH_TOKEN="$ARM_TOKEN" gh pr merge --auto --squash "$PR_NUMBER"'
    ]


def _git(repo: Path, *args: str, author: str = 'dependabot[bot]') -> str:
    """Run git in ``repo`` as ``author``, committed by GitHub, with no ambient config.

    GIT_* variables a hook runner sets would point git at this repository instead.
    """
    env = {
        key: value for key, value in os.environ.items() if not key.startswith('GIT_')
    }
    done = subprocess.run(
        ['git', *args],
        cwd=repo,
        env={
            **env,
            'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_AUTHOR_NAME': author,
            'GIT_AUTHOR_EMAIL': f'{author}@example.invalid',
            'GIT_COMMITTER_NAME': 'GitHub',
            'GIT_COMMITTER_EMAIL': 'noreply@github.com',
        },
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _write(repo: Path, name: str, text: str) -> None:
    """Write one line to a file in ``repo``."""
    (repo / name).write_text(f'{text}\n', encoding='utf-8')


def _dependabot_branch(tmp_path: Path) -> Path:
    """Return a repository on a Dependabot-style branch that main has moved on from.

    The branch changes a.txt and main changes b.txt, so merging main is clean.
    """
    repo = tmp_path / 'dev'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    for name in ('a', 'b', 'c'):
        _write(repo, f'{name}.txt', name)
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-qm', 'chore: start', author='michen00')
    _git(repo, 'switch', '-qc', 'bump')
    _write(repo, 'a.txt', 'a, bumped')
    _git(repo, 'commit', '-qam', 'build: bump a')
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'b.txt', 'b, changed on main')
    _git(repo, 'commit', '-qam', 'feat: change b', author='michen00')
    _git(repo, 'switch', '-q', 'bump')
    return repo


# Who the stub `gh` says each merge author is: `_ADMIN` is an admin, `_FLAKY`'s lookup
# fails, and anyone else has write. `<none>` stands for an author GitHub cannot name;
# the fixtures write it as `no-account`, since git strips `<` and `>` from a name.
_ADMIN = 'michen00'
_NON_ADMIN = 'contributor'
_FLAKY = 'flaky-lookup'


def _provenance(
    tmp_path: Path, repo: Path, total: str | None = None
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], list[str]]:
    """Run the provenance step on ``repo``'s branch as pull request 7.

    The branch becomes `refs/pull/7/head` on a bare origin, and the step runs in a clone
    of origin's main, as the checkout before it leaves the runner, so its fetch and
    `git merge-tree` are real. The stub `gh` answers the commit listing with
    `origin|kind|author|sha|parents` rows built from the branch's real commits, the
    shape the step's jq filter produces, so this tests what the step trusts, not the
    filter. Every commit reads as created by GitHub. It answers permission lookups as
    `_ADMIN`, `_FLAKY` and write describe, and records each one. It reports the commit
    count as ``total`` when one is given, and as the number of rows otherwise.

    Returns the finished step, the outputs it wrote, and the logins it looked up.
    """
    step = _steps(_load('bot-automerge.yml'), 'bot-automerge')[
        'Verify every commit was created by GitHub'
    ]
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'clone', '-q', '--mirror', str(repo), str(origin))
    _git(origin, 'update-ref', 'refs/pull/7/head', _git(repo, 'rev-parse', 'HEAD'))
    runner = tmp_path / 'runner'
    _git(tmp_path, 'clone', '-q', '--branch', 'main', str(origin), str(runner))
    rows = []
    for sha in _git(repo, 'rev-list', '--reverse', 'main..HEAD').split():
        _, *parents = _git(repo, 'rev-list', '--parents', '-n1', sha).split()
        kind = 'merge' if len(parents) >= 2 else 'plain'
        author = _git(repo, 'log', '-1', '--format=%an', sha)
        author = '<none>' if author == 'no-account' else author
        rows.append(f'github|{kind}|{author}|{sha}|{" ".join(parents)}')
    stub_dir = tmp_path / 'bin'
    stub_dir.mkdir()
    stub = stub_dir / 'gh'
    stub.write_text(
        '#!/usr/bin/env bash\n'
        'case "$*" in\n'
        '  *"/collaborators/"*)\n'
        '    login=${2#*/collaborators/}; login=${login%/permission}\n'
        '    echo "$login" >>"$LOOKUP_LOG"\n'
        '    case $login in\n'
        f'      {_ADMIN}) echo admin ;;\n'
        f'      {_FLAKY}) echo "gh: Server Error (HTTP 502)" >&2; exit 1 ;;\n'
        '      *) echo write ;;\n'
        '    esac ;;\n'
        '  *"/commits "*) printf \'%s\' "$FAKE_ROWS" ;;\n'
        '  *"--jq .commits") echo "$FAKE_TOTAL" ;;\n'
        '  *) echo "fake gh: unexpected call: $*" >&2; exit 64 ;;\n'
        'esac\n',
        encoding='utf-8',
    )
    stub.chmod(0o755)
    output = tmp_path / 'output'
    output.touch()
    lookups = tmp_path / 'lookups'
    lookups.touch()
    env = {
        key: value for key, value in os.environ.items() if not key.startswith('GIT_')
    }
    result = subprocess.run(
        ['bash', '-e', '-c', step['run']],
        cwd=runner,
        env={
            **env,
            'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_CONFIG_NOSYSTEM': '1',
            'PATH': f'{stub_dir}{os.pathsep}{os.environ["PATH"]}',
            'GITHUB_OUTPUT': str(output),
            'GH_REPO': 'michen00/freeze-pr-links',
            'PR_NUMBER': '7',
            'AUTHOR': 'dependabot[bot]',
            'FAKE_ROWS': ''.join(f'{row}\n' for row in rows),
            'FAKE_TOTAL': str(len(rows)) if total is None else total,
            'LOOKUP_LOG': str(lookups),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    outputs = dict(
        line.split('=', 1) for line in output.read_text(encoding='utf-8').splitlines()
    )
    return result, outputs, lookups.read_text(encoding='utf-8').split()


def _run_provenance(tmp_path: Path, repo: Path) -> tuple[str, str, list[str]]:
    """Run the provenance step, which must succeed, on ``repo``'s branch.

    Returns `trusted`, the step's log, and the logins it looked up.
    """
    result, outputs, looked_up = _provenance(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    return outputs['trusted'], result.stdout, looked_up


_HELD = "is neither a clean merge of two parents nor an admin's; holding."


def _edited_merge(repo: Path, author: str) -> None:
    """Merge main cleanly as ``author``, then amend an extra edit into the merge."""
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=author)
    _write(repo, 'c.txt', f'c, edited in the merge by {author}')
    _git(repo, 'commit', '-q', '--amend', '--no-edit', '--all', author=author)


def _resolved_merge(repo: Path, author: str) -> None:
    """Merge a conflicting main as ``author``, resolved by hand with an extra edit."""
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'a.txt', 'a, changed on main')
    _git(repo, 'commit', '-qam', 'feat: change a', author=_ADMIN)
    _git(repo, 'switch', '-q', 'bump')
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, 'merge', '-q', '--no-edit', 'main', author=author)
    _write(repo, 'a.txt', 'whatever the resolver typed')
    _write(repo, 'c.txt', 'and an edit elsewhere')
    _git(repo, 'add', 'a.txt', 'c.txt')
    _git(repo, 'commit', '-q', '--no-edit', author=author)


@pytest.mark.parametrize(
    'merger',
    ['github-actions[bot]', _NON_ADMIN, _ADMIN],
    ids=['catch-up', 'update-branch-by-a-non-admin', 'update-branch-by-an-admin'],
)
def test_a_clean_merge_keeps_the_pull_request_trusted(
    tmp_path: Path, merger: str
) -> None:
    """A clean merge of two branches passes, whoever authored it, with no lookup.

    pr-catchup.yml merges as github-actions[bot] or as the App, and Update branch as
    the person who clicked it. GitHub makes either only when the merge is clean.
    """
    repo = _dependabot_branch(tmp_path)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=merger)
    trusted, log, looked_up = _run_provenance(tmp_path, repo)
    assert trusted == 'true', log
    assert looked_up == []


def test_an_admins_resolved_merge_with_extra_edits_keeps_it_trusted(
    tmp_path: Path,
) -> None:
    """An admin's merge passes even when it resolves a conflict and edits more."""
    repo = _dependabot_branch(tmp_path)
    _resolved_merge(repo, _ADMIN)
    trusted, log, looked_up = _run_provenance(tmp_path, repo)
    assert trusted == 'true', log
    assert looked_up == [_ADMIN]


def test_an_admin_is_looked_up_once_for_several_merges(tmp_path: Path) -> None:
    """Two edited merges by one admin both pass on a single permission lookup."""
    repo = _dependabot_branch(tmp_path)
    _edited_merge(repo, _ADMIN)
    _git(repo, 'switch', '-q', 'main')
    _write(repo, 'b.txt', 'b, changed on main again')
    _git(repo, 'commit', '-qam', 'feat: change b again', author=_ADMIN)
    _git(repo, 'switch', '-q', 'bump')
    _edited_merge(repo, _ADMIN)
    trusted, log, looked_up = _run_provenance(tmp_path, repo)
    assert trusted == 'true', log
    assert looked_up == [_ADMIN]


@pytest.mark.parametrize(
    ('merger', 'lookups'),
    [(_NON_ADMIN, [_NON_ADMIN]), (_FLAKY, [_FLAKY]), ('no-account', [])],
    ids=['non-admin', 'failed-lookup', 'no-account'],
)
def test_an_edited_merge_by_anyone_but_an_admin_holds_the_pull_request(
    tmp_path: Path, merger: str, lookups: list[str]
) -> None:
    """An extra edit in a merge holds it unless an admin made it.

    A failed lookup, or an author GitHub cannot name, counts as not an admin, and the
    latter is never looked up.
    """
    repo = _dependabot_branch(tmp_path)
    _edited_merge(repo, merger)
    trusted, log, looked_up = _run_provenance(tmp_path, repo)
    assert trusted == 'false'
    assert _HELD in log
    assert looked_up == lookups


def test_a_conflict_a_non_admin_resolved_by_hand_holds_the_pull_request(
    tmp_path: Path,
) -> None:
    """A merge resolved by hand holds, though GitHub signs it, unless an admin made it.

    One resolved in GitHub's conflict editor can carry any content.
    """
    repo = _dependabot_branch(tmp_path)
    _resolved_merge(repo, _NON_ADMIN)
    trusted, log, _ = _run_provenance(tmp_path, repo)
    assert trusted == 'false'
    assert _HELD in log


def test_an_octopus_merge_by_a_non_admin_holds_the_pull_request(
    tmp_path: Path,
) -> None:
    """A clean merge of three branches has three parents, so it is not mechanical."""
    repo = _dependabot_branch(tmp_path)
    _git(repo, 'switch', '-qc', 'side', 'main~1')
    _write(repo, 'c.txt', 'c, changed on side')
    _git(repo, 'commit', '-qam', 'build: change c')
    _git(repo, 'switch', '-q', 'bump')
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', 'side', author=_NON_ADMIN)
    trusted, log, _ = _run_provenance(tmp_path, repo)
    assert trusted == 'false'
    assert _HELD in log


@pytest.mark.parametrize('total', ['null', '3abc', ''])
def test_a_commit_count_that_is_not_an_integer_holds_the_pull_request(
    tmp_path: Path, total: str
) -> None:
    """A count that is not an integer fails the step, leaving `trusted` unset.

    Unguarded, the `-gt` and `-ne` tests error inside `if`, read as false, and the step
    falls through to trusting the pull request.
    """
    repo = _dependabot_branch(tmp_path)
    result, outputs, _ = _provenance(tmp_path, repo, total=total)
    assert result.returncode != 0
    assert 'trusted' not in outputs
    assert "could not read the PR's commit count; holding." in result.stdout


def test_the_kill_switch_reaches_every_pull_request() -> None:
    """The disarm workflow runs on every `do not auto-merge` label, with no other test.

    It must reach every pull request the arming job can, including one retargeted after
    arming.
    """
    disarm = _load('bot-automerge-disarm.yml')
    assert _triggers(disarm) == {'pull_request': {'types': ['labeled']}}
    assert disarm['jobs']['disarm']['if'] == (
        "github.event.label.name == 'do not auto-merge'"
    )


def test_the_link_freeze_runs_nothing_from_the_pull_request() -> None:
    """The privileged link freeze runs the action from the default branch."""
    workflow = _load('freeze-pr-links.yml')
    assert set(_triggers(workflow)) == {'pull_request_target', 'workflow_dispatch'}
    steps = workflow['jobs']['freeze']['steps']
    checkouts = [
        step
        for step in steps
        if str(step.get('uses', '')).startswith('actions/checkout@')
    ]
    assert len(checkouts) == 1
    options = checkouts[0]['with']
    assert options['ref'] == '${{ github.event.repository.default_branch }}'
    assert options['persist-credentials'] is False
    assert [step['uses'] for step in steps if step not in checkouts] == ['./']


def test_the_action_checks_out_nothing() -> None:
    """The action runs only its own tree, so no step of it may check anything out."""
    action: dict[Any, Any] = yaml.safe_load(
        (_WORKFLOWS.parents[1] / 'action.yml').read_text(encoding='utf-8')
    )
    used = [str(step.get('uses', '')) for step in action['runs']['steps']]
    assert used, 'the action has no steps; this test needs rewriting'
    assert not [uses for uses in used if uses.startswith('actions/checkout@')]


def test_workflows_that_run_pull_request_code_cannot_write() -> None:
    """CI and the mechanical checks run pull request code with read-only tokens."""
    for name in ('CI.yml', 'pr-mechanical-checks.yml'):
        workflow = _load(name)
        assert 'pull_request' in _triggers(workflow)
        assert _write_scopes(workflow.get('permissions')) == set(), name
        for job_name, job in workflow['jobs'].items():
            assert _write_scopes(job.get('permissions')) == set(), (name, job_name)


def test_release_publish_smoke_tests_the_tag_it_published() -> None:
    """Release Publish calls the smoke workflow with the tag it has just published.

    Release Publish creates the release with the default token, and an event that
    token causes starts no workflow, so a smoke run triggered by `release:
    published` would never start after a release.
    """
    publish = _load('release-publish.yml')
    smoke = publish['jobs']['smoke']
    assert smoke['uses'] == './.github/workflows/release-smoke.yml'
    assert smoke['needs'] == 'release-publish'
    assert smoke['with']['tag'] == '${{ needs.release-publish.outputs.tag }}'
    assert publish['jobs']['release-publish']['outputs']['tag'] == (
        '${{ steps.release-tag.outputs.tag }}'
    )
    triggers = _triggers(_load('release-smoke.yml'))
    assert triggers['workflow_call']['inputs']['tag']['required'] is True
    assert 'release' not in triggers
