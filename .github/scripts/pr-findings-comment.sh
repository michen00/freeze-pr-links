#!/usr/bin/env bash
#
# The findings surface for pr-mechanical-checks.yml: one comment on the pull request,
# upserted as it changes and deleted once nothing is left to say. It leads with the
# errors that turned the `checks` job red, so a reader learns why without opening a
# log, then lists the warnings, which only advise.
#
# Keyed on a marker rather than on position, so it finds its own comment among any
# number of others. The author must also be a bot, so a human quoting the marker is
# never edited or deleted.
#
# This script is where a finding crosses from plain text into Markdown, so it is where
# the escaping belongs. The checks write prose for a log; everything below renders it
# for a reader, and the two want different things.
#
# Environment: GH_TOKEN, REPO, PR_NUMBER, PR_ERRORS_DIR, PR_WARNINGS_DIR.

set -euo pipefail

# Render one finding's text so a reader sees the characters the check actually wrote.
#
# A finding may quote something an author wrote, so it can contain anything. Dropped
# into Markdown unescaped, GitHub deletes whatever looks like HTML, so a finding naming
# an unfilled `<placeholder>` would lose the very word it named. It is also a trust
# boundary: without this an author could put live HTML, or a link whose label hides
# where it goes, into a comment github-actions[bot] signs.
#
# `&` is substituted first, because the rules after it introduce ampersands of their
# own. In a sed replacement a bare `&` means the whole match, so a literal one is
# written `\&`.
escape_for_markdown() {
  sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/[][`*_~\\]/\\&/g'
}

readonly MARKER="<!-- pr-mechanical-checks:findings -->"

# GitHub refuses a comment body longer than this, and a refused body posts nothing.
# Counted in bytes, which errs toward cutting early.
readonly BODY_MAX=65536

readonly TRUNCATION_NOTICE='**The findings are cut off here.** GitHub limits how long a comment may be, and the rest did not fit. The job log and the uploaded findings artifact hold every finding in full.'

body_file="$(mktemp)"
readonly body_file
findings_file="$(mktemp)"
readonly findings_file
handoff_file="$(mktemp)"
readonly handoff_file
list_file="$(mktemp)"
readonly list_file
trap 'rm -f "${body_file}" "${findings_file}" "${handoff_file}" "${list_file}"' EXIT

# Append one section: a heading, a sentence, then each file's findings grouped under the
# file's name, which is the check that raised them. Prints whether anything was written,
# because a heading with nothing under it is worse than silence.
render_section() {
  local dir="$1" heading="$2" lead="$3" wrote=false file name
  for file in "${dir}"/*.txt; do
    [ -s "${file}" ] || continue
    if [ "${wrote}" = false ]; then
      printf '### %s\n\n%s\n\n' "${heading}" "${lead}" >> "${findings_file}"
      wrote=true
    fi
    name="$(basename "${file}" .txt)"
    {
      printf '**%s**\n\n' "${name}"
      while IFS= read -r line; do
        printf -- '- %s\n' "$(printf '%s' "${line}" | escape_for_markdown)"
      done < "${file}"
      printf '\n'
    } >> "${findings_file}"
  done
  printf '%s' "${wrote}"
}

printf '%s\n' "${MARKER}" > "${body_file}"
errors_found="$(render_section "${PR_ERRORS_DIR}" 'Why the checks failed' \
  '**These block the merge.** Fix each one, and the checks run again on the next push or edit.')"
warnings_found="$(render_section "${PR_WARNINGS_DIR}" 'Advisory findings' \
  '**These do not block.** Each takes a judgment, about whether it is really a problem or how to fix it, so the checks raise it and leave the decision with you. Deciding not to act on one is a valid answer.')"

found=false
if [ "${errors_found}" = true ] || [ "${warnings_found}" = true ]; then
  found=true
fi

# A handoff an author can pass straight to a coding agent. It names the pull request
# rather than this comment, because on the create path the comment has no id yet. It
# asks for a decision on each warning rather than "fix these", because a warning is
# advisory precisely because acting on it takes judgment.
if [ "${found}" = true ]; then
  {
    printf '<details>\n<summary>Hand these to a coding agent</summary>\n\n'
    printf '```text\n'
    printf 'The PR checks on %s#%s left findings in a comment from\n' "${REPO}" "${PR_NUMBER}"
    printf 'github-actions[bot]. Read them with:\n'
    printf '  gh pr view %s --repo %s --comments\n' "${PR_NUMBER}" "${REPO}"
    if [ "${errors_found}" = true ]; then
      printf 'Fix every finding under the heading that says why the checks failed.\n'
    fi
    if [ "${warnings_found}" = true ]; then
      printf 'For each advisory finding, decide whether it is worth acting on, fix\n'
      printf 'the ones that are, and reply on the pull request saying which you\n'
      printf 'rejected and why.\n'
    fi
    printf '```\n\n'
    printf '</details>\n'
  } >> "${handoff_file}"
fi

# Give the findings whatever room the fixed parts leave, then wind a cut back to the last
# space, which keeps the body valid UTF-8 and spares a reader half a word or escape.
notice=$'\n\n'"${TRUNCATION_NOTICE}"$'\n\n'
readonly notice
fixed=$(($(wc -c < "${body_file}") + $(wc -c < "${handoff_file}") + ${#notice}))
budget=$((BODY_MAX - fixed))
readonly fixed budget

if [ "$(wc -c < "${findings_file}")" -gt "${budget}" ]; then
  kept="$(head -c "${budget}" "${findings_file}")"
  printf '%s%s' "${kept% *}" "${notice}" >> "${body_file}"
else
  cat "${findings_file}" >> "${body_file}"
fi
cat "${handoff_file}" >> "${body_file}"

# Redirected to a file rather than piped into `head -n 1`, so `gh` is never cut off by
# SIGPIPE under `set -e` when it finds more than one id.
gh api "repos/${REPO}/issues/${PR_NUMBER}/comments" --paginate \
  --jq ".[] | select(.user.type == \"Bot\")
        | select(.body | startswith(\"${MARKER}\")) | .id" \
  > "${list_file}"
existing="$(head -n 1 "${list_file}")"

if [ "${found}" = true ]; then
  if [ -n "${existing}" ]; then
    gh api -X PATCH "repos/${REPO}/issues/comments/${existing}" -F "body=@${body_file}"
  else
    gh pr comment "${PR_NUMBER}" --repo "${REPO}" --body-file "${body_file}"
  fi
elif [ -n "${existing}" ]; then
  gh api -X DELETE "repos/${REPO}/issues/comments/${existing}"
fi
