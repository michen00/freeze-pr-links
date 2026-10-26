# Contributing

Contributions are welcome, from a typo fix to a new case the action should handle. Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md). To report a vulnerability, use the private channel in [SECURITY.md](SECURITY.md) rather than an issue.

## Set up

```bash
make develop   # sync dependencies and install the git hooks
```

`make develop` also sets two options in this clone's `.git/config`: `blame.ignoreRevsFile`, and Git LFS when `git-lfs` is installed. It never includes a tracked file as git configuration, because git would then run whatever a checked-out branch put in that file. `blame.ignoreRevsFile` names a tracked file, but git reads only revision IDs from it.

## Branches and commits

- Fork the repository and branch from a fresh `main`, named `<type>/<short-description>`.
- Commit subjects are Conventional Commits. The valid types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style` and `test`, the description after the colon starts with a lowercase letter, and the whole subject runs to 50 characters at most. The `commit-msg` hooks check the form locally.
- Keep each commit to one logical change.
- Bring a branch up to date with `main` by merging, not rebasing, once it has been pushed.
- After a pull request merges, `pr-catchup.yml` merges `main` into every open branch in this repository that is behind and does not conflict, as a commit titled `chore: merge main into #N`. Pull before you push to such a branch again. It does not reach a branch in a fork.

## Before you open a PR

```bash
make check   # tidy, run the pre-commit hooks, then the tests
```

The checks under [checks/](checks/) run the same PR-title, PR-body and commit-subject validation that CI runs. For example: `uv run python -m checks.check_pr_title "feat: add a rule"`. On a pull request they post a comment saying what failed and what they advise, and remove it once there is nothing left to say. CI also posts a coverage comment: how many of the lines you changed a test ran. A member or collaborator can comment `/coverage-report` on the pull request to measure it again.

Write Markdown prose as one line per paragraph. The `unwrap-markdown-prose-py` hook reflows a hard-wrapped paragraph in place and stops the commit so you can see what changed.

A change to `action.yml` or to `.github/workflows/freeze-pr-links.yml` has to keep every property [SECURITY.md](SECURITY.md) lists; `tests/test_workflows.py` and `tests/test_workflow_injection.py` pin them.

## Opening the PR

- Merges are squash-only, and the PR title becomes the squash commit, so it must be a valid Conventional Commit. A single-commit PR squashes to that commit's subject instead, so keep the two identical.
- Fill in the [PR template](.github/pull_request_template.md). Summary and Testing always apply, and the checks fail without them.
- If you link to a file from a PR's description or comments, use the link on your branch rather than one pinned to a commit. While the PR is open, that link shows the latest version, and when it merges, this repository's own action points it at the branch's last commit so it keeps working after the branch is deleted.
- Open as a draft while the change is still moving.
- Read what a merge into `main` needs with `gh api repos/michen00/freeze-pr-links/rules/branches/main`. The ruleset `main-protect` requires `Run CI (3.13)` and `checks` to pass, an approving review from someone other than whoever pushed last, and every review thread resolved. `bot-automerge.yml` approves Dependabot's updates, in every ecosystem and majors included, and arms them for auto-merge, so they merge once CI passes. Any pull request labeled `do not auto-merge` waits for a person.

## Creating a release

The maintainer cuts releases, and [RELEASING.md](RELEASING.md) is the runbook. A release PR opens by itself when a release-worthy commit lands on `main`. Merging it and approving two runs creates a signed tag and publishes signed artifacts; `make release-status` shows where a release stands.

## Editor

[.vscode/extensions.json](.vscode/extensions.json) recommends the extensions that match the hooks, including ty, Ruff, Pylint and markdownlint.
