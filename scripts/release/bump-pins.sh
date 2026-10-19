#!/bin/sh
# Point this repository's own `uses:` pins at a release tag.
#
# Usage: bump-pins.sh <vX.Y.Z> [file...]
#
# Defaults to README.md alone. Only a reference to this repository with a full
# version, `michen00/freeze-pr-links@vX.Y.Z`, is rewritten. A reference to a
# branch or a commit SHA is left alone, and so is every other action's pin.
#
# The workflows in this repository do not pin the action by version: the one that
# runs it on this repository checks out the default branch and uses `./`, so a
# release has nothing there to move.
#
# Exits 2 on bad arguments and 3 when a named file contains no pin for this
# repository, so a release workflow fails loudly instead of shipping a stale pin.

set -eu

REPO_SLUG='michen00/freeze-pr-links'

usage() {
  echo "Usage: $0 <vX.Y.Z> [file...]" >&2
  exit 2
}

if [ "$#" -lt 1 ]; then
  usage
fi

tag="$1"
shift

# Reuse the release parser so an invalid tag cannot reach the files.
parse_version="$(dirname "$0")/parse-version.sh"
if [ ! -x "$parse_version" ]; then
  echo "Error: $parse_version is missing or not executable" >&2
  exit 2
fi

if ! tag="$("$parse_version" "$tag" --require-v)"; then
  usage
fi

if [ "$#" -eq 0 ]; then
  set -- README.md
fi

# The slug's slash and the version's dots are escaped for the expression. The
# tag, already validated as vX.Y.Z, carries no sed metacharacter of its own.
slug_pattern="$(printf '%s' "$REPO_SLUG" | sed 's/[./]/\\&/g')"
pin_pattern="${slug_pattern}@v[0-9]+\.[0-9]+\.[0-9]+"

status=0

for file in "$@"; do
  if [ ! -f "$file" ]; then
    echo "Error: file not found: $file" >&2
    exit 2
  fi

  if ! grep -Eq "$pin_pattern" "$file"; then
    echo "Error: no $REPO_SLUG@vX.Y.Z pin found in $file" >&2
    status=3
    continue
  fi

  tmp="$(mktemp)"
  # A digit after the match would mean it stopped inside a longer version, so
  # a pin must end at anything else, such as a sentence's full stop, or at the
  # end of the line.
  sed -E "s/${pin_pattern}([^0-9]|\$)/${slug_pattern}@${tag}\1/g" "$file" > "$tmp"

  if cmp -s "$tmp" "$file"; then
    echo "Already at $tag: $file"
  else
    cat "$tmp" > "$file"
    echo "Bumped to $tag: $file"
  fi
  rm -f "$tmp"
done

exit "$status"
