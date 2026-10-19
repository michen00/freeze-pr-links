<!-- markdownlint-configure-file { "first-line-heading": false } -->

This PR prepares release `@RELEASE_TAG@`.

## Included

- Stamps `@RELEASE_TAG@` into `CHANGELOG.md` as its own section
- Sets the package version to `@RELEASE_TAG@` in `pyproject.toml` and `uv.lock`
- Points the `README.md` usage snippet at `@RELEASE_TAG@`
- Ran the test suite before proposing the release

## Before merging

GitHub starts no workflow for a pull request that the default token opened, so this one's checks have not run. Mark it as a draft and then ready for review again to start them.

Merging this PR does not publish anything yet. `make release-approve` approves the two runs that wait on the `release` environment: one creates and pushes the signed tag `@RELEASE_TAG@`, and the other publishes the signed artifacts to the GitHub release.
