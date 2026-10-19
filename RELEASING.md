# Releasing

Releases are cut by the maintainer. Contributors do not need anything here; see [CONTRIBUTING.md](CONTRIBUTING.md) instead.

The flow is automated except for two approvals, which are deliberate: they are what stands between a merged pull request and a tag signed with the CI release key. A release publishes a GitHub Release with the `freeze-pr-links` command as a wheel and an sdist, a checksum file, Sigstore and GPG signatures for all three, and a build provenance attestation for each. Consumers of the action use the signed tag itself. Nothing is published to PyPI; `make push-test` and `make push-prod` stay manual.

## Default flow

1. **Release PR** (`.github/workflows/release-pr.yml`) opens the release PR by itself when a commit worth releasing lands on `main`. Every Conventional Commit type bumps at least the patch version, so the version cannot decide that alone; the workflow counts the commits `cliff.toml` puts in its features, fixes, performance and revert groups, plus anything marked breaking. Run the workflow by hand, or `make release-pr`, to choose the version or to release a batch with none of those; a manual run skips that check. Leave `version` empty to derive it with `git cliff --bumped-version`, or pass `X.Y.Z` or `vX.Y.Z`. The pull request stamps the version into `CHANGELOG.md`, `pyproject.toml`, `uv.lock` and the README's usage snippet, and its commit is signed by GitHub.
1. **Start its checks.** GitHub starts no workflow for a pull request that the default token opened. Mark the release PR as a draft and then ready for review again, and the required checks run.
1. Review and merge it (`chore(release): prepare vX.Y.Z`).
1. **Approve the release.** Run `make release-approve`. It finds the waiting **Release Tag** run, shows the tag it will create and the commit that tag will point at, and asks you to confirm. It then waits for the **Release Publish** run that the new tag dispatches and approves that too. Each run can also be approved from its page on GitHub. Rejecting the first approval leaves no tag behind.
1. **Release Tag** (`.github/workflows/release-tag.yml`) runs when a `release/*` branch from this repository merges into `main`, and waits on the protected `release` environment. Once approved, it creates a GPG-signed annotated tag, verifies it, pushes it, and dispatches **Release Publish** on that tag.
1. **Release Publish** (`.github/workflows/release-publish.yml`) checks out the tag and builds the distributions. `scripts/release/build-artifacts.sh` refuses a tag whose commit builds another version. The workflow then attests every artifact's provenance, signs it, and publishes them, with the version's `CHANGELOG.md` section as the release notes. It refuses to run from anything but the tag, because the attestation and the signatures name the ref the run started on. It waits on the same environment, so it needs an approval of its own.
1. **Release smoke** (`.github/workflows/release-smoke.yml`) runs the published tag against the pull request merged most recently, as a consumer's workflow would, and again every Monday against the newest release.

A release that is never approved waits. There is no timeout and no reminder, so a merged release PR can sit indefinitely; `make release-status` shows whether that has happened.

## Checking release status

```bash
make release-status   # latest tag, any open release PR, any run awaiting approval
make release-approve  # approve the waiting runs after confirming what will be tagged
```

Both read the repository through `gh` and need no other local state. `make release-approve` does nothing when no run is waiting, rather than guessing which run you meant. It approves a Release Publish run only when the run started on the tag it names, dispatched there as Release Tag does or started by a push of the tag, and on the commit that tag points at, because the publish job also holds the release key and a branch can carry the tag's name with a workflow of its own.

## Why Release PR sometimes does nothing

**Release PR** refuses to prepare a second release while the last prepared version is still untagged: on a push it says so and stops, and a manual run fails. That covers the approval window, in which a `fix` merged while **Release Tag** waits would otherwise propose a duplicate PR for the version already on its way out. It also holds when an approval is rejected, since that leaves a prepared version with no tag; clear it with the manual fallback below, which both publishes that release and satisfies the check.

If the version moves while a release PR is open, such as a `feat` landing on top of a pending patch, the next run opens a PR for the new version and closes the superseded one. **Release Tag** reads the version it creates from the `release/*` branch name, so leaving the stale PR open would leave a merge path that tags the wrong version.

## Manual fallback

1. Tag and push from `main` by hand, signed:
   - `git switch main && git pull`
   - `git tag -a vX.Y.Z -m vX.Y.Z -s`
   - `git push origin vX.Y.Z`
1. The tag push starts **Release Publish**, which waits for approval; `make release-approve` gives it. If needed, dispatch it on the tag, `gh workflow run release-publish.yml --ref vX.Y.Z -f tag=vX.Y.Z`, and approve it the same way.

Release Tag dispatches Release Publish explicitly rather than relying on the tag push, because a tag pushed with the default token does not trigger `on: push: tags`.

## Signing model

- **Tags** are annotated and GPG-signed. **Release Tag** signs with the CI release key rather than a maintainer's personal key, verifies the signature before pushing, and refuses to reuse an existing tag that is not a validly signed annotated tag at the merge commit. The tag rulesets keep every `vX.Y.Z` tag from being moved or deleted once pushed.
- **Commits** on `main` are signed, which a ruleset requires: GitHub signs the squash commit of every merge and the release PR's own commit, which the workflow makes through the API.
- **Artifacts** each get a Sigstore keyless signature, made in CI through GitHub's OIDC identity, a GPG detached signature made with the release key, and a build provenance attestation that binds the artifact's digest to this repository, `release-publish.yml` and the tag.
- The protected `release` environment is what keeps the key from being usable by anyone who can merge a `release/*` pull request: the tagging job and the publishing job each wait for the maintainer's approval before they run.

### One-time release key setup

The `release` environment exists with the maintainer as its required reviewer. The key is set up once, locally, as the maintainer. Never paste private key material into an issue, a pull request or a chat transcript.

```bash
# 1. Generate a dedicated release key (not your personal key), with a passphrase.
PASSPHRASE='<choose-a-strong-passphrase>'
gpg --batch --passphrase "$PASSPHRASE" \
    --quick-generate-key 'freeze-pr-links release <you@example.com>' rsa4096 sign 2y

# 2. Note its fingerprint.
gpg --list-secret-keys --keyid-format=long

# 3. Store the key as secrets of the `release` environment, so that only the
#    two jobs that wait for approval can read it.
gpg --armor --export-secret-keys <FINGERPRINT> |
  gh secret set RELEASE_GPG_PRIVATE_KEY --env release --repo michen00/freeze-pr-links
gh secret set RELEASE_GPG_PASSPHRASE --env release --repo michen00/freeze-pr-links \
  --body "$PASSPHRASE"

# 4. Register the public key so signed tags display as Verified on GitHub.
#    Paste the output at https://github.com/settings/gpg/new
gpg --armor --export <FINGERPRINT>
```

Piping the export straight into `gh secret set` leaves no key file on disk. Confirm the secrets landed with `gh secret list --env release`. Without the private key, **Release Tag** and **Release Publish** fail at the import step, so no tag is created and nothing is published; a GitHub App token cannot stand in for it, because GitHub signs commits it creates through the API but never an annotated tag. The key expires in two years; rotate it by repeating these steps.

## Verifying a release

```bash
# The tag, once the release key's public half is in your keyring
git verify-tag vX.Y.Z

# An artifact's provenance: this repository, this workflow, this tag
gh attestation verify artifact --repo michen00/freeze-pr-links \
  --signer-workflow michen00/freeze-pr-links/.github/workflows/release-publish.yml \
  --source-ref refs/tags/vX.Y.Z

# An artifact, by Sigstore
cosign verify-blob --signature artifact.sig --certificate artifact.pem \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity 'https://github.com/michen00/freeze-pr-links/.github/workflows/release-publish.yml@refs/tags/vX.Y.Z' \
  artifact

# An artifact, by GPG
gpg --verify artifact.asc artifact
```

Replace `vX.Y.Z` with the release you downloaded. Every release is built by the same workflow, so without `--source-ref`, or the tag in the certificate identity, another release's genuine artifact would pass as this one's.
