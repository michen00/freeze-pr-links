"""Contract tests for the PR findings comment upsert.

The comment has to be idempotent across every synchronize on a pull request, so
the three outcomes that matter are create, edit, and delete. The fourth -- no
findings and no existing comment -- must touch the API not at all, because a
workflow that posts an empty comment on every clean run is worse than no comment.
"""

import os
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / '.github/scripts/pr-findings-comment.sh'
_LIST_MATCH = '*"issues/7/comments"*'

# GitHub's cap on an issue-comment body, over which the API answers 422 and posts
# nothing. Duplicated from the script deliberately: a test that read the constant
# out of the script would pass just as happily if the constant were wrong.
_COMMENT_MAX = 65536


def _run(
    tmp_path: Path,
    *,
    warnings: dict[str, str],
    errors: dict[str, str] | None = None,
    existing: str = '',
    list_branch: str | None = None,
    warnings_dir_exists: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run the script against a stubbed `gh` and a warnings directory.

    `list_branch` overrides the shell run for the existing-comment lookup, so a
    test can make that call misbehave -- stream output slowly, say -- without
    every other test needing to know that branch exists.

    `warnings_dir_exists` set to False leaves the directory uncreated, which is
    the common case on a real pull request: `_record` in checks/_common.py only
    creates it when something warns, so a clean run never has one at all. That
    is a different branch through the glob than an empty, existing directory.
    """
    warnings_dir = tmp_path / 'warnings'
    if warnings_dir_exists:
        warnings_dir.mkdir()
        for stem, body in warnings.items():
            (warnings_dir / f'{stem}.txt').write_text(body, encoding='utf-8')
    errors_dir = tmp_path / 'errors'
    if errors is not None:
        errors_dir.mkdir()
        for stem, body in errors.items():
            (errors_dir / f'{stem}.txt').write_text(body, encoding='utf-8')

    binaries = tmp_path / 'bin'
    binaries.mkdir()
    stub = binaries / 'gh'
    resolved_list_branch = (
        list_branch if list_branch is not None else f"echo '{existing}'"
    )
    stub.write_text(
        '#!/usr/bin/env bash\n'
        'case "$*" in\n'
        f'  {_LIST_MATCH}) {resolved_list_branch} ;;\n'
        '  *"-X PATCH"*) last="${@: -1}"; '
        'printf \'PATCH %s\\n%s\\n\' "$*" "$(cat "${last#body=@}")" ;;\n'
        '  *"-X DELETE"*) echo "DELETE $*" ;;\n'
        '  *"pr comment"*) printf \'POST\\n%s\\n\' "$(cat "${@: -1}")" ;;\n'
        'esac\n',
        encoding='utf-8',
    )
    stub.chmod(0o755)

    return subprocess.run(
        ['bash', str(_SCRIPT)],
        capture_output=True,
        text=True,
        check=True,
        cwd=_ROOT,
        env={
            **os.environ,
            'PATH': f'{binaries}{os.pathsep}{os.environ["PATH"]}',
            'REPO': 'owner/name',
            'PR_NUMBER': '7',
            'PR_WARNINGS_DIR': str(warnings_dir),
            'PR_ERRORS_DIR': str(errors_dir),
        },
    )


def test_findings_with_no_existing_comment_are_posted(tmp_path: Path) -> None:
    """The first synchronize that raises anything is what creates the comment."""
    result = _run(tmp_path, warnings={'title': 'title: not a verb\n'})

    assert 'POST' in result.stdout
    assert 'title: not a verb' in result.stdout


def _sections_by_heading(text: str, headings: tuple[str, ...]) -> dict[str, str]:
    """Split `text` into the slice following each `**heading**` marker.

    Headings are located in whatever order they actually occur, rather than the
    order `headings` lists them in, because the script orders its output by
    lexical glob expansion of the warnings directory, not by dict insertion
    order -- so a test must not assume `title` renders before `body`.
    """
    positions = sorted((text.index(f'**{heading}**'), heading) for heading in headings)
    sections: dict[str, str] = {}
    for index, (start, heading) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        sections[heading] = text[start:end]
    return sections


def test_the_body_groups_findings_by_the_check_that_raised_them(
    tmp_path: Path,
) -> None:
    """The file stem is the only thing carrying which check a warning came from.

    Presence of both headings is not enough: a bug that dropped a finding's
    text, or filed it under the other check's heading, would still pass a
    weaker assertion. This checks that each finding's own text lands in its
    own section and nowhere else.
    """
    result = _run(
        tmp_path,
        warnings={'title': 'title: not a verb\n', 'body': 'contains a TBD marker\n'},
    )

    sections = _sections_by_heading(result.stdout, ('title', 'body'))

    assert 'title: not a verb' in sections['title']
    assert 'contains a TBD marker' not in sections['title']
    assert 'contains a TBD marker' in sections['body']
    assert 'title: not a verb' not in sections['body']


def test_findings_replace_an_existing_comment(tmp_path: Path) -> None:
    """A second comment per push would bury the pull request in its own advice.

    Asserts the PATCH body carries the finding text, not only that a PATCH ran
    against the right id -- the edit path is the one a live pull request takes
    on every push after its first, so it should not get the weaker check the
    POST path already outgrew.
    """
    result = _run(tmp_path, warnings={'title': 'title: not a verb\n'}, existing='42')

    assert 'PATCH' in result.stdout
    assert 'issues/comments/42' in result.stdout
    assert 'title: not a verb' in result.stdout
    assert 'POST' not in result.stdout


def test_clearing_the_findings_deletes_the_comment(tmp_path: Path) -> None:
    """A resolved warning should leave no residue on the conversation."""
    result = _run(tmp_path, warnings={}, existing='42')

    assert 'DELETE' in result.stdout
    assert 'issues/comments/42' in result.stdout


def test_a_clean_run_with_no_comment_touches_nothing(tmp_path: Path) -> None:
    """The common case must be silent, or the surface becomes noise."""
    result = _run(tmp_path, warnings={})

    assert result.stdout.strip() == ''


def test_a_nonexistent_warnings_directory_touches_nothing(tmp_path: Path) -> None:
    """The most common real path: a clean pull request never creates the directory.

    `_record` only creates `PR_WARNINGS_DIR` when a check actually warns, so on
    every clean pull request it never exists at all -- unlike the empty,
    already-created directory `test_a_clean_run_with_no_comment_touches_nothing`
    covers, which is a different branch through the glob. An unset variable is
    not tested here: under `set -u` it correctly exits 1, matching the house
    convention of reading required variables bare.
    """
    result = _run(tmp_path, warnings={}, warnings_dir_exists=False)

    assert result.returncode == 0
    assert result.stdout.strip() == ''


def test_a_finding_naming_html_still_says_what_it_named(tmp_path: Path) -> None:
    """A finding is plain text going into Markdown, so the boundary must escape it.

    The checks emit prose for a log; this script renders it as a Markdown bullet.
    GitHub then deletes anything HTML-shaped, which silently ate the substance of
    two real findings: `contains an unfilled <placeholder> token` reached a reader
    as "contains an unfilled  token", deleting the very word it named, and
    `contains markdownlint scaffolding: <!-- ... -->` reached them as a heading and
    a bare colon. Measured against GitHub's own renderer, not inferred.

    Asserting the escaped form rather than the raw one is the point: the raw text
    is what the artifact and the job log keep, and both must stay plain.
    """
    result = _run(
        tmp_path,
        warnings={'body': 'contains an unfilled <placeholder> token\n'},
    )

    assert '&lt;placeholder&gt;' in result.stdout
    assert '<placeholder>' not in result.stdout


def test_a_finding_cannot_smuggle_markup_into_a_bot_comment(tmp_path: Path) -> None:
    """The escape is a trust boundary, not only a rendering fix.

    A finding can quote text an author wrote, and `_unfilled_placeholder` quotes
    whatever sits between angle brackets with only the tags a body legitimately
    keeps exempted -- so an author could put live HTML, or a link wearing a label
    that hides where it goes, into a comment authored by github-actions[bot],
    which a reader trusts further than a comment authored by the author. A bare
    URL still autolinks and that is left alone: it shows a reader where it leads,
    which is the deception this defuses.

    The payload is deliberately broader than any one finding can carry -- a slot
    cannot hold a `>`, so it cannot hold a closing tag -- because the escape is
    generic and the property under test is that whatever reaches it comes out
    inert. It is matched exactly rather than by a bare `<details>`, because the
    comment emits a disclosure block of its own for the agent handoff -- the looser
    assertion this replaces failed the moment that block was added.
    """
    result = _run(
        tmp_path,
        warnings={
            'body': (
                'contains markdownlint scaffolding: '
                '<details><summary>go</summary>[click](http://evil.example)</details>\n'
            )
        },
    )

    assert '<details><summary>go</summary>' not in result.stdout
    assert '&lt;details&gt;&lt;summary&gt;go&lt;/summary&gt;' in result.stdout
    assert '[click](' not in result.stdout
    assert r'\[click\]' in result.stdout


def test_an_oversized_body_is_cut_off_where_a_reader_can_see_it(
    tmp_path: Path,
) -> None:
    """Escaping can carry a finding past the length GitHub will accept.

    The expansion is up to fivefold, because `&` becomes `&amp;`, and the text a
    finding quotes is an author's: `_unfilled_placeholder` returns whatever sits
    between angle brackets, and a body paragraph carries no manual line breaks, so
    the span has no length limit of its own short of the body's. Measured, the slot
    below renders as a 100,761-character comment.

    Left unbounded, that comment is refused whole, and the step that posts it
    continues on error -- so the pull request keeps showing whatever findings it
    showed before, with nothing on the conversation to say the list is stale. The
    truncation is the visible failure that replaces the invisible one, which is why
    the notice is asserted here alongside the length.

    The handoff has to survive the cut as well: the findings are what get trimmed,
    and the disclosure block that closes the comment is script-owned and short.
    """
    result = _run(tmp_path, warnings={'body': f'unfilled slot <a{"&" * 20000}>\n'})

    posted = result.stdout.split('POST\n', 1)[1]

    assert len(posted) <= _COMMENT_MAX
    assert 'unfilled slot' in posted
    assert 'cut off here' in posted
    assert posted.rstrip().endswith('</details>')


def test_findings_that_fit_are_not_cut_off(tmp_path: Path) -> None:
    """The budget is computed, so a mistake in it would truncate everything.

    A negative budget fails loudly -- `head` refuses it and the script exits -- but
    one that is merely too small does not, and every comment would quietly lose its
    tail. This is the other side of the length bound, and it is the side a reader
    would never report, because a finding they never saw is a finding they cannot
    miss.
    """
    result = _run(tmp_path, warnings={'title': 'title: not a verb\n'})

    assert 'cut off here' not in result.stdout


def test_the_comment_ends_with_a_handoff_naming_this_pull_request(
    tmp_path: Path,
) -> None:
    """The comment carries a way to act on itself, aimed at the right pull request.

    The prompt names the pull request rather than this comment because on the create
    path no comment id exists yet. Pinning the number is what stops a template that
    reads plausibly from sending an agent to the wrong one.

    It also pins that the prompt asks for a decision rather than a fix. Every finding
    here is advisory because acting on it takes judgment, and an agent told to fix a
    list will fix the list.
    """
    result = _run(tmp_path, warnings={'title': 'title: not a verb\n'})

    assert 'Hand these to a coding agent' in result.stdout
    assert 'owner/name#7' in result.stdout
    assert 'gh pr view 7 --repo owner/name --comments' in result.stdout
    assert 'decide whether it is worth acting on' in result.stdout


def test_a_second_marker_comment_does_not_crash_the_lookup(tmp_path: Path) -> None:
    """Two racing workflow runs can each find nothing and each post once.

    The lookup used to pipe `gh api ... --paginate --jq ...` into `head -n 1`,
    which reads one line and exits, closing its end of the pipe. When `gh` --
    modeled here by a stub that writes a second id only after a short delay --
    then tried to write that second line, it took SIGPIPE and died, and `set
    -e` aborted the whole script before it ever reached the PATCH it owed the
    first, still-live id. Surviving that crash is all this pins: the script
    patches the first id and leaves the second comment untouched, so this run
    does not reconcile the duplicate away either -- it only stops crashing.
    """
    result = _run(
        tmp_path,
        warnings={'title': 'title: not a verb\n'},
        list_branch="printf '42\\n'; sleep 0.2; printf '43\\n'",
    )

    assert 'PATCH' in result.stdout
    assert 'issues/comments/42' in result.stdout


def test_an_error_says_why_the_checks_failed(tmp_path: Path) -> None:
    """A red `checks` row is explained on the conversation, under its own heading."""
    result = _run(
        tmp_path,
        warnings={},
        errors={'title': 'title: 53 chars exceeds hard max 50\n'},
    )

    assert 'POST' in result.stdout
    assert 'Why the checks failed' in result.stdout
    assert 'title: 53 chars exceeds hard max 50' in result.stdout
    assert 'Advisory findings' not in result.stdout


def test_errors_come_before_warnings(tmp_path: Path) -> None:
    """What blocks the merge is read first; what only advises follows it."""
    result = _run(
        tmp_path,
        warnings={'title': "title: subject may not be imperative ('adds')\n"},
        errors={'body': "missing required section '## Testing'\n"},
    )

    blocking = result.stdout.index('Why the checks failed')
    advisory = result.stdout.index('Advisory findings')
    assert blocking < result.stdout.index('missing required section') < advisory
    assert advisory < result.stdout.index('may not be imperative')


def test_warnings_alone_do_not_claim_a_failure(tmp_path: Path) -> None:
    """A green run with advice never says the checks failed."""
    result = _run(tmp_path, warnings={'title': 'title: not a verb\n'})

    assert 'Advisory findings' in result.stdout
    assert 'Why the checks failed' not in result.stdout


def test_an_error_is_escaped_like_a_warning(tmp_path: Path) -> None:
    """The errors cross the same trust boundary, so they get the same escaping."""
    result = _run(
        tmp_path,
        warnings={},
        errors={'body': 'unfilled slot <img src=x onerror=alert(1)>\n'},
    )

    assert '<img' not in result.stdout
    assert '&lt;img' in result.stdout
