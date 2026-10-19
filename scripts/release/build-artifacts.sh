#!/bin/sh
# Build the distributions a release publishes, and their checksums.
#
# Usage: build-artifacts.sh <vX.Y.Z> [output_dir]
#
# The action itself is consumed from the tag, so it needs no artifact. What a
# release adds is the `freeze-pr-links` command as a wheel and an sdist, built by
# `uv build`, plus a checksum file covering both. sign-artifacts.sh signs all
# three afterwards.
#
# The sdist's filename is the build backend's own statement of the version it
# built, so that, not pyproject.toml, is what is checked against the tag. A tag
# whose commit never had its version bumped is refused here rather than
# published under the wrong number.

set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "Usage: $0 <vX.Y.Z> [output_dir]" >&2
  exit 1
fi

script_dir="$(CDPATH='' cd -- "$(dirname "$0")" && pwd)"
repo_root="$(CDPATH='' cd -- "$script_dir/../.." && pwd)"

if ! tag="$("$script_dir/parse-version.sh" "$1" --require-v)"; then
  exit 1
fi

out_dir="${2:-dist}"
case "$out_dir" in
  /*) ;;
  *) out_dir="$repo_root/$out_dir" ;;
esac

if ! command -v uv > /dev/null 2>&1; then
  echo "Error: uv is required to build release artifacts" >&2
  exit 1
fi

# A stale file from an earlier attempt must never be uploaded under a new tag.
rm -rf "$out_dir"
(cd "$repo_root" && uv build --out-dir "$out_dir")

# PEP 625 names the sdist after the normalized project name: lowercased, with
# runs of `-`, `_` and `.` collapsed to `_`.
dist_name="$(cd "$repo_root" && uv run --no-project python -c '
import pathlib, re, tomllib
name = tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["name"]
print(re.sub(r"[-_.]+", "_", name).lower())
')"

set -- "$out_dir"/*.tar.gz
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "Error: expected exactly one sdist in $out_dir" >&2
  exit 1
fi
stem="$(basename "$1" .tar.gz)"
case "$stem" in
  "$dist_name"-*) ;;
  *)
    echo "Error: unexpected sdist filename $stem (expected $dist_name-*)" >&2
    exit 1
    ;;
esac
built="${stem#"$dist_name"-}"
if [ "$built" != "${tag#v}" ]; then
  echo "Error: $tag does not match the built version $built." >&2
  echo "Bump with 'uv version ${tag#v}' and 'uv lock' in the release PR." >&2
  exit 1
fi

set -- "$out_dir"/*.whl
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "Error: expected exactly one wheel in $out_dir" >&2
  exit 1
fi

sha256_of() {
  if command -v sha256sum > /dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

checksums="$out_dir/freeze-pr-links-$tag-checksums.txt"
for artifact in "$out_dir"/*.tar.gz "$out_dir"/*.whl; do
  printf '%s  %s\n' "$(sha256_of "$artifact")" "$(basename "$artifact")"
done > "$checksums"

echo "Built release artifacts for $tag:"
for artifact in "$out_dir"/*; do
  echo " - $artifact"
done
