# Contributing

Contributions are welcome, from a typo fix to a new case the action should handle. Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md). To report a vulnerability, use the private channel in [SECURITY.md](SECURITY.md) rather than an issue.

## Set up

```bash
make develop   # sync dependencies and install the git hooks
```

`make develop` sets up Git LFS only when `git-lfs` is installed, and `.gitattributes` stores images, audio, PDFs and Word documents in Git LFS, so install `git-lfs` first.

## Branches and commits

- Fork the repository and branch from a fresh `main`, named `<type>/<short-description>`.
- Commit subjects are Conventional Commits. The valid types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `style` and `test`, the description after the colon starts with a lowercase letter, and the whole subject runs to 50 characters at most. The `commit-msg` hooks check the form locally.
- Keep each commit to one logical change.
- Bring a branch up to date with `main` by merging, not rebasing, once it has been pushed.
- [`pr-catchup.yml`](.github/workflows/pr-catchup.yml) can add a commit titled `chore: merge main into #N` to your branch after a pull request merges. Pull before you push to that branch again. It does not reach a branch in a fork.

## Before you open a PR

```bash
make check   # tidy, run the pre-commit hooks, then the tests
```

The checks under [checks/](checks/) run the same PR-title, PR-body and commit-subject validation that CI runs. For example: `uv run python -m checks.check_pr_title "feat: add a rule"`. On a pull request, CI posts what they find as a comment. CI also comments with how many of the lines you changed a test ran; a member or collaborator can comment `/coverage-report` on the pull request to measure it again.

Write Markdown prose as one line per paragraph. The `unwrap-markdown-prose-py` hook reflows a hard-wrapped paragraph in place and stops the commit so you can see what changed.

A change to `action.yml` or to `.github/workflows/freeze-pr-links.yml` has to keep every property [SECURITY.md](SECURITY.md) lists; `tests/test_workflows.py` and `tests/test_workflow_injection.py` pin them.

## Opening the PR

- Merges are squash-only, and the PR title becomes the squash commit, so it must be a valid Conventional Commit. A single-commit PR squashes to that commit's subject instead, so keep the two identical.
- Fill in the [PR template](.github/pull_request_template.md). Summary and Testing always apply, and the checks fail without them.
- If you link to a file from a PR's description or comments, link to it on your branch, not at a commit: when the PR merges, this repository's own action repoints the link to the branch's last commit, so it keeps working after the branch is deleted.
- Open as a draft while the change is still moving.
- Read what a merge into `main` needs with `gh api repos/michen00/freeze-pr-links/rules/branches/main`. Dependabot's updates merge without a person once CI passes; label one `do not auto-merge` to keep it for a person to merge.

## Creating a release

The maintainer cuts releases, following [RELEASING.md](RELEASING.md); a contributor needs nothing from it.
