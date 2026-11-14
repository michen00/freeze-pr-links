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
    approve = [line for line in lines if '/reviews"' in line]
    merge = [line for line in lines if 'gh pr merge --auto' in line]
    assert len(approve) == 1
    assert 'ARM_TOKEN' not in approve[0]
    assert len(merge) == 1
    assert merge[0].strip().startswith('GH_TOKEN="$ARM_TOKEN" ')


def test_auto_merge_approves_and_arms_only_the_verified_head() -> None:
    """The approval names the commit the provenance step inspected, and so does arming.

    Without both, a push between the check and the approval would be approved and
    merged unchecked: GitHub approves whatever the head is, and arms it.
    """
    arm = _steps(_load('bot-automerge.yml'), 'bot-automerge')[
        'Re-check the kill switch, then approve and arm'
    ]
    assert arm['env']['VERIFIED_HEAD'] == '${{ steps.provenance.outputs.head }}'
    script = ' '.join(arm['run'].replace('\\\n', ' ').split())
    assert 'gh pr review' not in script
    assert (
        'gh api -X POST "repos/${GH_REPO}/pulls/${PR_NUMBER}/reviews" '
        '-f event=APPROVE -f commit_id="$VERIFIED_HEAD"'
    ) in script
    assert (
        'gh pr merge --auto --squash --match-head-commit "$VERIFIED_HEAD" "$PR_NUMBER"'
    ) in script


def _git(repo: Path, *args: str, author: str = 'dependabot[bot]') -> str:
    """Run git in ``repo`` as ``author``, committed by GitHub, with no global config."""
    # GIT_* variables a hook runner sets would point git at this repository instead.
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
_ZERO = '0' * 40


def _created(after: str, pusher: str = 'dependabot[bot]') -> str:
    """Return the push-history record of ``pusher`` creating the branch at ``after``."""
    return f'branch_creation|{pusher}|{_ZERO}|{after}'


def _pushed(pusher: str, before: str, after: str, change: str = 'push') -> str:
    """Return the push-history record of ``pusher`` moving the branch to ``after``."""
    return f'{change}|{pusher}|{before}|{after}'


def _provenance(
    tmp_path: Path,
    repo: Path,
    *,
    total: str | None = None,
    head: str | None = None,
    event_head: str | None = None,
    pushes: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], list[str]]:
    """Run the provenance step on ``repo``'s branch as pull request 7.

    The step runs in a clone of origin's main, with the branch as `refs/pull/7/head`, so
    its fetch and `git merge-tree` are real. The stub `gh` lists the branch's real
    commits in the step's row shape, each created by GitHub, so this tests what the step
    trusts, not its jq filter. It reports the commit count as ``total`` if given, and as
    the number of rows otherwise, and the head as ``head`` if given, and as the branch's
    tip otherwise. The event brings ``event_head``, by default the head the stub
    reports. The stub lists ``pushes`` as the branch's push history, newest first, by
    default Dependabot creating the branch at that head.

    Returns the finished step, the outputs it wrote, and the logins it looked up.
    """
    step = _steps(_load('bot-automerge.yml'), 'bot-automerge')[
        'Verify every commit was created by GitHub'
    ]
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'clone', '-q', '--mirror', str(repo), str(origin))
    _git(origin, 'update-ref', 'refs/pull/7/head', _git(repo, 'rev-parse', 'HEAD'))
    # GitHub serves a commit by its SHA after a force push has left it unreachable.
    _git(origin, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
    reported = _git(repo, 'rev-parse', 'HEAD') if head is None else head
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
        '  *"/activity "*) printf \'%s\' "$FAKE_PUSHES" ;;\n'
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
        '  *"--jq .head.sha") echo "$FAKE_HEAD" ;;\n'
        '  *) echo "fake gh: unexpected call: $*" >&2; exit 64 ;;\n'
        'esac\n',
        encoding='utf-8',
    )
    stub.chmod(0o755)
    sleep = stub_dir / 'sleep'
    sleep.write_text(
        '#!/usr/bin/env bash\necho "$1" >>"$SLEEP_LOG"\n', encoding='utf-8'
    )
    sleep.chmod(0o755)
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
            'EVENT_HEAD': reported if event_head is None else event_head,
            'HEAD_REF': 'bump',
            'FAKE_PUSHES': ''.join(
                f'{push}\n' for push in pushes or [_created(reported)]
            ),
            'FAKE_ROWS': ''.join(f'{row}\n' for row in rows),
            'FAKE_TOTAL': str(len(rows)) if total is None else total,
            'FAKE_HEAD': reported,
            'LOOKUP_LOG': str(lookups),
            'SLEEP_LOG': str(tmp_path / 'sleeps'),
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
    """A clean merge of two branches passes, whoever authored it, with no lookup."""
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
    """An extra edit in a merge holds it unless an admin made it."""
    repo = _dependabot_branch(tmp_path)
    _edited_merge(repo, merger)
    trusted, log, looked_up = _run_provenance(tmp_path, repo)
    assert trusted == 'false'
    assert _HELD in log
    assert looked_up == lookups


def test_a_conflict_a_non_admin_resolved_by_hand_holds_the_pull_request(
    tmp_path: Path,
) -> None:
    """A merge resolved by hand holds the pull request, though GitHub signs it."""
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
    """A count that is not an integer fails the step, leaving `trusted` unset."""
    repo = _dependabot_branch(tmp_path)
    result, outputs, _ = _provenance(tmp_path, repo, total=total)
    assert result.returncode != 0
    assert 'trusted' not in outputs
    assert "could not read the PR's commit count; holding." in result.stdout


def test_a_trusted_verdict_names_the_head_it_inspected(tmp_path: Path) -> None:
    """A trusted run outputs its head commit, which approving and arming then name."""
    repo = _dependabot_branch(tmp_path)
    result, outputs, _ = _provenance(tmp_path, repo)
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'true', 'head': _git(repo, 'rev-parse', 'HEAD')}


def test_a_head_that_moved_during_the_check_holds_the_pull_request(
    tmp_path: Path,
) -> None:
    """A head the API reports that is not the commit inspected holds, naming no head."""
    repo = _dependabot_branch(tmp_path)
    moved = _git(repo, 'rev-parse', 'main')
    result, outputs, _ = _provenance(tmp_path, repo, head=moved, event_head=moved)
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'false'}
    assert 'the head moved while it was being inspected; holding.' in result.stdout


# An App's login, as a catch-up push reports its pusher. The stub `gh` gives it write.
_APP = 'catch-up-app[bot]'


def _tip(repo: Path) -> str:
    """Return the branch's tip."""
    return _git(repo, 'rev-parse', 'HEAD')


@pytest.mark.parametrize('pusher', [_NON_ADMIN, _APP])
def test_a_plain_commit_pushed_by_anyone_but_dependabot_or_an_admin_holds(
    tmp_path: Path, pusher: str
) -> None:
    """A commit authored as Dependabot passes the per-commit rules; its pusher does not.

    GitHub signs a commit an App or a token creates through its API, with any author,
    so only the push, which GitHub attributes itself, shows who added it.
    """
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _write(repo, 'c.txt', 'c, changed by someone posing as Dependabot')
    _git(repo, 'commit', '-qam', 'build: bump c')
    pushes = [_pushed(pusher, created, _tip(repo)), _created(created)]
    result, outputs, _ = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'false'}
    assert 'which is not a clean merge of two parents; holding.' in result.stdout


def test_a_clean_merge_pushed_by_an_app_keeps_the_pull_request_trusted(
    tmp_path: Path,
) -> None:
    """A catch-up push is a clean merge of main, so an App pushing one passes.

    Main's own commits come in with the merge; they are not the pusher's, so only the
    merge is held to the rule.
    """
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=_APP)
    pushes = [_pushed(_APP, created, _tip(repo)), _created(created)]
    result, outputs, looked_up = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs['trusted'] == 'true', result.stdout
    assert looked_up == [_APP]


def test_a_plain_commit_hidden_behind_a_clean_merge_holds(tmp_path: Path) -> None:
    """A plain commit brought in through a merge's second parent is still checked."""
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _git(repo, 'switch', '-qc', 'smuggled', 'main')
    _write(repo, 'c.txt', 'c, smuggled in')
    _git(repo, 'commit', '-qam', 'build: bump c')
    _git(repo, 'switch', '-q', 'bump')
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'smuggled', author=_APP)
    pushes = [_pushed(_APP, created, _tip(repo)), _created(created)]
    result, outputs, _ = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'false'}
    assert 'which is not a clean merge of two parents; holding.' in result.stdout


def test_a_held_push_stays_held_after_a_clean_push(tmp_path: Path) -> None:
    """A clean catch-up push does not vouch for a plain commit an earlier push added.

    The run on the catch-up sees only a clean merge in its own push, so the earlier
    push is found in the branch's push history.
    """
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _write(repo, 'c.txt', 'c, changed by someone posing as Dependabot')
    _git(repo, 'commit', '-qam', 'build: bump c')
    smuggled = _tip(repo)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=_APP)
    pushes = [
        _pushed(_APP, smuggled, _tip(repo)),
        _pushed(_APP, created, smuggled),
        _created(created),
    ]
    result, outputs, _ = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'false'}
    assert f'{_APP} pushed {smuggled}, which is not a clean merge' in result.stdout


@pytest.mark.parametrize(
    ('pusher', 'trusted'), [(_NON_ADMIN, 'false'), (_ADMIN, 'true')]
)
def test_a_merge_authored_as_an_admin_passes_only_when_an_admin_pushed_it(
    tmp_path: Path, pusher: str, trusted: str
) -> None:
    """An author login comes from an email, so the pusher decides a resolved merge."""
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _resolved_merge(repo, _ADMIN)
    pushes = [_pushed(pusher, created, _tip(repo)), _created(created)]
    result, outputs, _ = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs['trusted'] == trusted, result.stdout


def test_a_change_other_than_a_push_holds(tmp_path: Path) -> None:
    """Only a push or a branch creation can be checked commit by commit."""
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=_APP)
    pushes = [_pushed(_APP, created, _tip(repo), change='pr_merge'), _created(created)]
    result, outputs, _ = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'false'}
    assert f'{_APP} changed the branch by pr_merge; holding.' in result.stdout


def test_only_pushes_since_the_branch_was_last_created_count(tmp_path: Path) -> None:
    """Pushes to an earlier branch of the same name are never read.

    Their commits are made up here, so reading them would fail the step.
    """
    repo = _dependabot_branch(tmp_path)
    pushes = [
        _created(_tip(repo)),
        _pushed(_NON_ADMIN, 'e' * 40, 'f' * 40),
        _created('e' * 40),
    ]
    result, outputs, looked_up = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs['trusted'] == 'true', result.stdout
    assert looked_up == []


def test_a_push_history_that_does_not_reach_the_head_holds(tmp_path: Path) -> None:
    """A history whose newest push is not the head is read again, then holds."""
    repo = _dependabot_branch(tmp_path)
    pushes = [_created(_git(repo, 'rev-parse', 'main'))]
    result, outputs, _ = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'false'}
    assert "the branch's push history does not reach its head; holding." in (
        result.stdout
    )
    assert (tmp_path / 'sleeps').read_text(encoding='utf-8').split() == ['5', '5']


def test_a_push_history_with_a_gap_holds(tmp_path: Path) -> None:
    """A missing push leaves its commits unread, so a break in the chain holds.

    Here the history omits the push that added a plain commit, and the clean push after
    it starts where no listed push ended.
    """
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _write(repo, 'c.txt', 'c, changed by someone posing as Dependabot')
    _git(repo, 'commit', '-qam', 'build: bump c')
    smuggled = _tip(repo)
    _git(repo, 'merge', '-q', '--no-ff', '--no-edit', 'main', author=_APP)
    pushes = [_pushed(_APP, smuggled, _tip(repo)), _created(created)]
    result, outputs, _ = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'false'}
    assert "the branch's push history skips a change; holding." in result.stdout


def test_a_push_history_that_does_not_reach_the_creation_holds(
    tmp_path: Path,
) -> None:
    """A history with no branch creation may be missing the pushes that matter."""
    repo = _dependabot_branch(tmp_path)
    pushes = [_pushed('dependabot[bot]', 'e' * 40, _tip(repo))]
    result, outputs, _ = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'false'}
    assert "the branch's push history does not reach its creation;" in result.stdout


def test_a_head_this_event_did_not_bring_holds(tmp_path: Path) -> None:
    """A run vouches only for its own event's head, never for a later push's."""
    repo = _dependabot_branch(tmp_path)
    result, outputs, _ = _provenance(
        tmp_path, repo, event_head=_git(repo, 'rev-parse', 'main')
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'false'}
    assert 'the head is no longer the one this event brought; holding.' in (
        result.stdout
    )


def _rewritten_branch(tmp_path: Path) -> tuple[Path, list[str]]:
    """Return a Dependabot branch rewritten after a push, and its push history.

    The newest record, the rewrite, names no pusher yet: callers format it in.
    """
    repo = _dependabot_branch(tmp_path)
    created = _tip(repo)
    _write(repo, 'c.txt', 'c, before the rewrite')
    _git(repo, 'commit', '-qam', 'build: bump c')
    replaced = _tip(repo)
    # Kept by a ref, as GitHub keeps a commit a force push replaced.
    _git(repo, 'update-ref', 'refs/keep/replaced', replaced)
    _git(repo, 'reset', '-q', '--hard', 'HEAD~1')
    _write(repo, 'c.txt', 'c, after the rewrite')
    _git(repo, 'commit', '-qam', 'build: bump c again')
    return repo, [
        _pushed('{pusher}', replaced, _tip(repo), change='force_push'),
        _pushed('dependabot[bot]', created, replaced),
        _created(created),
    ]


def test_a_rewrite_pushed_by_anyone_but_dependabot_or_an_admin_holds(
    tmp_path: Path,
) -> None:
    """A force push by such a pusher holds when it adds a plain commit."""
    repo, pushes = _rewritten_branch(tmp_path)
    pushes[0] = pushes[0].format(pusher=_NON_ADMIN)
    result, outputs, _ = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs == {'trusted': 'false'}
    assert f'{_NON_ADMIN} pushed {_tip(repo)}, which is not a clean merge' in (
        result.stdout
    )


@pytest.mark.parametrize('pusher', ['dependabot[bot]', _ADMIN])
def test_a_rewrite_pushed_by_dependabot_or_an_admin_keeps_it_trusted(
    tmp_path: Path, pusher: str
) -> None:
    """Dependabot rebases its own branches, so its force pushes pass, as admins' do."""
    repo, pushes = _rewritten_branch(tmp_path)
    pushes[0] = pushes[0].format(pusher=pusher)
    result, outputs, _ = _provenance(tmp_path, repo, pushes=pushes)
    assert result.returncode == 0, result.stderr
    assert outputs['trusted'] == 'true', result.stdout


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
        '${{ needs.build.outputs.tag }}'
    )
    triggers = _triggers(_load('release-smoke.yml'))
    assert triggers['workflow_call']['inputs']['tag']['required'] is True
    assert 'release' not in triggers
