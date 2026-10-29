"""The PR body check: required sections block, template leftovers only advise.

The required sections are this repository's template's, Summary and Testing.
"""

import time
from pathlib import Path

import pytest

from checks import check_pr_body
from checks.check_pr_body import check_body

__all__ = ()


# -- check_body --

_GOOD_BODY = """## Summary

Why, then what.

## Testing

- [x] CI green
"""


def test_body_with_required_sections_is_clean() -> None:
    """A body containing every required section is clean."""
    found = check_body(_GOOD_BODY, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_missing_required_section_is_an_error() -> None:
    """A body missing a required section blocks."""
    assert not check_body('## Summary\n\nonly this\n', ['Summary', 'Testing']).ok


def test_wrong_level_heading_does_not_satisfy() -> None:
    """'### Summary' does not satisfy the '## Summary' requirement."""
    body = '### Summary\n\nwhy\n\n### Testing\n\n- [x] ok\n'
    assert not check_body(body, ['Summary', 'Testing']).ok


def test_heading_with_extra_text_is_accepted() -> None:
    """A level-two heading whose text starts with the section satisfies it."""
    body = '## Summary of changes\n\nwhy\n\n## Testing details\n\n- [x] ok\n'
    assert check_body(body, ['Summary', 'Testing']).ok


def test_placeholder_token_warns_only() -> None:
    """A leftover angle-bracket placeholder advises but does not block."""
    body = '## Summary\n\n<reason>\n\n## Testing\n\n- [x] ok\n'
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert any('placeholder' in w for w in found.warnings)


def test_html_tag_is_not_a_placeholder() -> None:
    """An HTML tag such as <details> is not mistaken for a placeholder."""
    body = (
        '## Summary\n\n<details><summary>x</summary>y</details>\n\n'
        '## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_unlabeled_fence_warns_only() -> None:
    """A code fence without a language tag advises but does not block."""
    body = '## Summary\n\n```\nx\n```\n\n## Testing\n\n- [x] ok\n'
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert any('language' in w for w in found.warnings)


def test_labeled_fence_is_clean() -> None:
    """A code fence with a language tag produces no warning."""
    body = '## Summary\n\n```python\nx = 1\n```\n\n## Testing\n\n- [x] ok\n'
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_todo_marker_warns_only() -> None:
    """A TODO marker in an otherwise-complete body advises but does not block."""
    body = '## Summary\n\nwhy\n\n## Testing\n\n- [ ] TODO wire up CI\n'
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert any('TODO' in w for w in found.warnings)


# -- check_body: the marker scans ignore code, so quoted markers are not leftovers --


def test_todo_inside_a_fence_is_not_a_marker() -> None:
    """A TODO inside a fenced block is sample code, not an unfilled template."""
    body = (
        '## Summary\n\nwhy\n\n```python\n# TODO: wire this up\n```\n\n'
        '## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_tbd_inside_an_inline_code_span_is_not_a_marker() -> None:
    """A TBD in backticks is prose about the marker, not the marker itself."""
    body = '## Summary\n\nthe `TBD` body warning\n\n## Testing\n\n- [x] ok\n'
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_multi_backtick_code_span_is_not_a_marker() -> None:
    """A code span delimited by several backticks is stripped like a single one."""
    body = '## Summary\n\nwrite ``TODO`` to mean it\n\n## Testing\n\n- [x] ok\n'
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_placeholder_inside_a_fence_is_not_unfilled() -> None:
    """An angle-bracket token shown as sample template text is not unfilled."""
    body = (
        '## Summary\n\nwhy\n\n```text\nN/A — <reason>\n```\n\n## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_prose_todo_still_warns_beside_a_fence() -> None:
    """Stripping code does not hide a genuine TODO left in the prose."""
    body = (
        '## Summary\n\nTODO explain why\n\n```python\nx = 1\n```\n\n'
        '## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert any('TODO' in w for w in found.warnings)


def test_prose_placeholder_still_warns_beside_a_fence() -> None:
    """Stripping code does not hide a genuine unfilled placeholder."""
    body = '## Summary\n\n<reason>\n\n```python\nx = 1\n```\n\n## Testing\n\n- [x] ok\n'
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert any('placeholder' in w for w in found.warnings)


def test_todo_between_two_fences_still_warns() -> None:
    """A fence closes, so a marker in the prose after one is still visible."""
    body = (
        '## Summary\n\n```python\nx = 1\n```\n\nTODO explain\n\n'
        '```python\ny = 2\n```\n\n## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert any('TODO' in w for w in found.warnings)


def test_unlabeled_fence_holding_a_marker_warns_only_about_the_fence() -> None:
    """The fence check reads the raw body, so stripping code leaves it intact."""
    body = '## Summary\n\n```\nTODO\n```\n\n## Testing\n\n- [x] ok\n'
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert any('language' in w for w in found.warnings)
    assert not any('TODO' in w for w in found.warnings)


# -- check_body: markdownlint scaffolding is template noise in a published body --


@pytest.mark.parametrize(
    'directive',
    [
        '<!-- markdownlint-disable MD033 -->',
        '<!-- markdownlint-enable MD033 -->',
        '<!-- markdownlint-disable-next-line MD033 -->',
        '<!-- markdownlint-disable-file MD033 -->',
        '<!-- markdownlint-capture -->',
        '<!-- markdownlint-restore -->',
        '<!-- markdownlint-disable -->',
        '<!--markdownlint-disable   MD033  MD013-->',
    ],
)
def test_markdownlint_scaffolding_warns_only(directive: str) -> None:
    """Every markdownlint directive form advises but does not block."""
    body = f'## Summary\n\nwhy\n\n{directive}\n\n## Testing\n\n- [x] ok\n'
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert any('markdownlint' in w for w in found.warnings)


def test_a_placeholder_warning_names_the_slot_it_found() -> None:
    """Naming the slot is what turns the finding into something actionable.

    "contains an unfilled placeholder" tells an author a category, and a body may
    hold several slots with none of them highlighted. Quoting the one that matched
    lets them search for it, the way the markdownlint finding already quotes the
    directive it found.
    """
    body = (
        '## Summary\n\nwhy\n\n## Testing\n\n- [x] ok\n'
        '- [ ] <change-specific verification>\n'
    )
    found = check_body(body, ['Summary', 'Testing'])

    assert found.ok
    assert any('<change-specific verification>' in w for w in found.warnings)


def test_placeholder_scan_is_linear_in_unclosed_brackets() -> None:
    """A line of `<` with no `>` is scanned in linear time, not quadratic.

    Regression for CodeQL alert py/polynomial-redos: a slot that could contain `<`
    made each `<` read to the end of the line, so a body of 65,536 of them (GitHub's
    limit) took over 20 seconds. The bound is loose; the linear scan takes milliseconds.
    """
    body = '## Summary\n\n' + '<' * 65_536 + '\n\n## Testing\n\n- [x] ok\n'
    start = time.perf_counter()
    found = check_body(body, ['Summary', 'Testing'])

    assert time.perf_counter() - start < 1.0
    assert found.ok


def test_a_slot_after_a_stray_bracket_is_still_found() -> None:
    """A `<` before a slot is not part of it, so the slot alone is quoted."""
    body = '## Summary\n\na <<reason>\n\n## Testing\n\n- [x] ok\n'
    found = check_body(body, ['Summary', 'Testing'])

    assert any('placeholder <reason> ' in w for w in found.warnings)


def test_every_body_finding_says_what_to_do_about_it() -> None:
    """A finding that only names a problem leaves the reader to guess the remedy.

    The advisory comment is read by an author who may never have opened this
    repository's documentation, so each finding carries its own remedy rather than
    relying on one being found.
    """
    body = (
        '## Summary\n\nTODO explain <why>\n\n'
        '<!-- markdownlint-disable MD033 -->\n\n'
        '## Testing\n\n```\nnot labeled\n```\n'
    )
    found = check_body(body, ['Summary', 'Testing'])

    assert len(found.warnings) == 4
    for warning in found.warnings:
        assert ' — ' in warning, f'no remedy in: {warning}'


def test_markdownlint_warning_quotes_the_directive_it_found() -> None:
    """The warning names the directive, so the author can find and remove it."""
    body = (
        '## Summary\n\nwhy\n\n<!-- markdownlint-disable MD033 -->\n<details>\n'
        '<summary>Files touched</summary>\n</details>\n'
        '<!-- markdownlint-enable MD033 -->\n\n## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert any('<!-- markdownlint-disable MD033 -->' in w for w in found.warnings)


def test_the_markdownlint_remedy_spares_the_rest_of_the_line() -> None:
    """A directive can share its line with markup the body has to keep.

    Nothing obliges an author to give the directive a line of its own, and the
    published body is written by hand from a template rather than copied out of
    it -- so `<details><!-- markdownlint-disable MD033 -->` is one line, and a
    remedy that reads "delete the line" takes the disclosure block with it. The
    finding quotes the comment it found, which is the whole of what has to go and
    also the smallest thing an author can search for.
    """
    body = (
        '## Summary\n\nwhy\n\n<details><!-- markdownlint-disable MD033 -->\n'
        '<summary>Files touched</summary>\n</details>\n\n'
        '## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])

    assert found.ok
    assert any('<!-- markdownlint-disable MD033 -->' in w for w in found.warnings)
    assert not any('<details>' in w for w in found.warnings)


def test_ordinary_html_comment_is_not_scaffolding() -> None:
    """A plain HTML comment a body keeps on purpose is not a directive."""
    body = (
        '## Summary\n\n<!-- kept deliberately for the next reader -->\n\n'
        '## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_prose_naming_the_directive_is_not_scaffolding() -> None:
    """Prose saying markdownlint-disable is not the comment itself."""
    body = (
        '## Summary\n\nI dropped the markdownlint-disable lines from the body.\n\n'
        '## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_markdownlint_scaffolding_inside_a_fence_is_a_sample() -> None:
    """A body documenting the convention shows the scaffolding as fenced sample text."""
    body = (
        '## Summary\n\nwhy\n\n```markdown\n<!-- markdownlint-disable MD033 -->\n'
        '<details>\n</details>\n<!-- markdownlint-enable MD033 -->\n```\n\n'
        '## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_markdownlint_scaffolding_in_a_code_span_is_a_sample() -> None:
    """Naming the directive in backticks discusses it rather than leaves it behind."""
    body = (
        '## Summary\n\nomit `<!-- markdownlint-disable MD033 -->` from the body\n\n'
        '## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert not found.warnings


def test_prose_scaffolding_still_warns_beside_a_fenced_sample() -> None:
    """Stripping code does not hide scaffolding genuinely left in the body."""
    body = (
        '## Summary\n\n```markdown\n<!-- markdownlint-capture -->\n```\n\n'
        '<!-- markdownlint-disable MD033 -->\n\n## Testing\n\n- [x] ok\n'
    )
    found = check_body(body, ['Summary', 'Testing'])
    assert found.ok
    assert any('markdownlint-disable' in w for w in found.warnings)


@pytest.mark.parametrize(
    ('body', 'code'),
    [(_GOOD_BODY, 0), ('## Summary\n\nonly this\n', 1)],
)
def test_body_main_returns_exit_code_for_sections(
    body: str, code: int, tmp_path: Path
) -> None:
    """The body CLI exit code reflects whether every required section is present."""
    body_file = tmp_path / 'body.md'
    body_file.write_text(body, encoding='utf-8')
    assert check_pr_body.main(['--body-file', str(body_file)]) == code
