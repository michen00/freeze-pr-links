# Security policy

## Supported versions

Fixes go to the latest release. Every `vX.Y.Z` tag stays where it was published: a ruleset over `refs/tags/v*.*.*` blocks updating or deleting it for every actor, with no bypass, and a second ruleset over `refs/tags/v*` blocks deletion.

Release tags are annotated and GPG-signed with the release key, and each release's wheel, sdist and checksum file carry a Sigstore signature, a GPG signature and a build provenance attestation naming the tag they were built from. [RELEASING.md](RELEASING.md#verifying-a-release) shows how to verify each one.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: [report a vulnerability](https://github.com/michen00/freeze-pr-links/security/advisories/new). Please do not open a public issue for a security report.

This is a personal project maintained on a best-effort basis. Expect an acknowledgment within a week, and a fix as a patch release.

## What the action can reach

The action runs on `pull_request_target`, so it holds a token that can edit the pull request while it reads text the pull request's author controls: the body, the comments, the head branch name and the head repository name. Three properties make that safe, and a change that breaks any of them is a security regression rather than a bug:

- Nothing from the pull request is checked out or executed. The transform is the copy in the action's own tree, at the ref the calling workflow pinned.
- No pull request text reaches a shell through a workflow expression. An expression in a `run:` block is substituted before the shell parses the line, so each value travels through `env:` or a file instead. The pull request number, branch name, repository name and commit SHA are checked for shape before use. `tests/test_workflow_injection.py` fails on any expression in a `run:` block of `action.yml` or of a workflow here.
- Every write is a compare-and-swap. The action reads the body or comment again just before writing and leaves it alone if it changed while the action ran.

The paths a link is checked against come from the git tree at the head commit, read from the base repository rather than from the fork. The transform is standard-library Python, opens no network connection, and evaluates nothing it reads, so a body written to attack it produces wrong text at worst.

## Consumer guidance

- Trigger the action from `pull_request_target` with `types: [closed]`, and gate the job on `github.event.pull_request.merged == true`. The action also confirms through the API that the pull request merged into the default branch, and skips it otherwise.
- Do not check out the pull request head in the same job. Under `pull_request_target`, that would run code from the pull request with the write token.
- Grant `contents: read` and `pull-requests: write`, and nothing more. The action pushes nothing.
- Pin the action to a `vX.Y.Z` tag, or to a full commit SHA if your threat model includes compromise of this repository.
