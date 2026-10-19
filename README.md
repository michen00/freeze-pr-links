# freeze-pr-links

A pull request often links files on its own head branch, as `https://github.com/OWNER/REPO/blob/my-branch/src/app.py`. Once the pull request merges and the branch is deleted, those links return 404. This action runs when a pull request merges and rewrites each such link as a permalink to the head commit, as `https://github.com/OWNER/REPO/blob/<head-sha>/src/app.py`, which keeps working after the branch is gone.

It edits the pull request body, its conversation comments, its review-thread replies, and its submitted review summaries.

## Usage

Add a workflow that runs on merge:

```yaml
name: Freeze PR links

on:
  pull_request_target:
    types: [closed]

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: freeze-pr-links-${{ github.event.pull_request.number }}
  cancel-in-progress: false

jobs:
  freeze:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    steps:
      - uses: michen00/freeze-pr-links@v0.1.0
```

To freeze a pull request that merged before the workflow existed, add a `workflow_dispatch` trigger with a `pr_number` input and pass it as `pr-number: ${{ github.event.pull_request.number || inputs.pr_number }}`. This repository's own [workflow](.github/workflows/freeze-pr-links.yml) does that.

The action needs `bash`, `jq` and `gh` on the runner, which GitHub-hosted Ubuntu and macOS runners have. It sets up Python 3.13 itself, so give it a job of its own.

### Inputs

| Input | Default | Meaning |
| -- | -- | -- |
| `pr-number` | the pull request that triggered the run | The merged pull request to freeze. |
| `github-token` | `github.token` | A token that can read the pull request and edit its body and comments. It needs `pull-requests: write`. |

## What changes and what does not

A link changes only when all of these hold:

- It points under `/blob/` or `/tree/` at the repository the head branch lives in, which is this repository or the fork the pull request came from.
- It names the pull request's head branch, in any percent-encoded spelling of the branch name.
- Its path exists at the head commit.

The rewritten link always points at the base repository. Merging keeps the head commit reachable there through `refs/pull/<n>/head`, while a link into a fork stops working once the fork is deleted. When a `/blob/` link names a directory, or a `/tree/` link names a file, the rewrite corrects that as well.

Everything else stays as written:

- links that already name a commit or a tag
- links to the default branch or to other branches
- other repositories
- commit, compare and issue URLs
- text inside code spans and fenced code blocks
- paths that no longer exist at the head commit, which are reported as skipped

The action runs only for a pull request that merged into the default branch from another branch. Before writing, it reads the body or comment again and leaves it alone if it changed while the action ran. A second run over the same pull request changes nothing.

## Command line

The transform is also a standard-library Python command, `freeze-pr-links`, which rewrites one body or comment file:

```console
$ freeze-pr-links --body-file body.md \
    --head-repository OWNER/REPO --base-repository OWNER/REPO \
    --head-ref my-branch --head-sha <40-character sha> \
    --files-from files.txt --directories-from directories.txt \
    --write --json
```

`files.txt` and `directories.txt` list the paths at the head commit, one per line. `freeze-pr-links --help` describes every option.

## Development

```bash
make develop   # dependencies and the git hooks
make check     # the full local gate
```

[CONTRIBUTING.md](CONTRIBUTING.md) has the commit and pull-request rules.

## Security

The workflow runs on `pull_request_target`, so it holds a write token while it reads text that the pull request's author wrote. [SECURITY.md](SECURITY.md) says what the action guarantees about that text and what a calling workflow has to keep true.

## Documentation

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/michen00/freeze-pr-links)
