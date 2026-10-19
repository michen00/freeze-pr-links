# Claude Code Instructions for Python Projects

## 1. Repository Context

- This repository ships one GitHub Action, `action.yml`, which rewrites a merged pull request's head-branch links as commit permalinks. The transform is `src/freeze_pr_links/core.py`, and the action runs it from its own tree.
- **The action runs on `pull_request_target` with a write token.** Breaking a property in [SECURITY.md](SECURITY.md) is a security regression, so read it before changing `action.yml` or `.github/workflows/freeze-pr-links.yml`.
- **The package uses only the standard library.** The action runs it without installing anything, and the command installs with no dependencies. Do not add a runtime dependency.
- **Write in defined terms.** Say which links change and which do not, and name the step or check that does it. Avoid idiom and metaphor.
- Uses modern Python tooling: `uv` (dependency management), `ruff` (linting/formatting), `ty` (type checking), `basedpyright` and `pylint` (only the checks those two do not make), `pytest` (testing).
- The `Makefile` is the primary entry point for all development tasks.
- Follows Conventional Commits for version control.

## 2. Development Workflow

### Environment Setup

- **Dependency Manager:** `uv` automatically creates and manages a virtual environment (`.venv`) in the project root.
- **Execution:** Use `uv run <command>` to ensure commands execute within the virtual environment.
  - Example: `uv run python -m mymodule` (preferred over `python -m mymodule`)
- **Python Version:** Defined in `.python-version` and `pyproject.toml`.

### Git Configuration

- **Git LFS:** `.gitattributes` stores images, PDFs, Word documents and audio in Git LFS. `make develop` runs `git lfs install --local --skip-repo` when `git-lfs` is installed, and `make sync-main` runs `git lfs pull`.
- **Blame Ignore:** A `.git-blame-ignore-revs` file can be used to exclude formatting-only commits from `git blame` once you add the relevant commit hashes. Configure via `git config blame.ignoreRevsFile .git-blame-ignore-revs` (handled by `make develop`).

### Common Commands (Makefile)

Use the `Makefile` as the primary interface for development tasks:

- **Install Dependencies:** `make develop` (installs dev dependencies, configures git hooks and git settings)
- **Run All Checks:** `make check` (runs `make tidy`, the pre-commit hooks, and tests)
- **Run Tests:** `make test` (runs pytest with coverage)
- **Linting:** `make lint` (ruff check --fix)
- **Formatting:** `make format` (ruff format), `make tidy` (best-effort lint autofix + format), or `make tidy-all` (pre-commit + tidy)
- **Clean Artifacts:** `make clean` (removes build artifacts, caches, etc.)
- **Git Hooks:** `make enable-pre-commit` / `make disable-pre-commit`. Enabling auto-removes a local `core.hooksPath` if it's set to the default `.git/hooks` (a harmless leftover); a non-default value blocks with a remediation message (`git config --local --unset-all core.hooksPath`, or run `make develop WITH_HOOKS=false` to skip hook installation).

### Testing Philosophy

- **Test-Driven Development (TDD):** Write tests before implementation to ensure requirements are met.
- **Test Categories by Purpose:**
  - **Type 1: Executable Documentation** - Tests that serve as usage examples. Should be DAMP (Descriptive And Meaningful Phrases) and well-commented. Place these "above the fold" in test files.
  - **Type 2: Coverage & Reliability** - Tests for edge cases, path coverage, and confidence. Can be more DRY but must remain readable.
- **Testing Paradigms by Scope:**
  - **Unit Tests:** Individual components in isolation.
  - **Integration Tests:** Interactions between components or external systems.
  - **Smoke Tests:** Quick checks for critical paths.
  - **Functional/E2E Tests:** Full workflows from a user's perspective.
  - **Regression Tests:** Specific tests for bugs to prevent recurrence.
- **What to Test:**
  - **Public Interfaces:** Test user-facing code thoroughly.
  - **Private Implementation:** Avoid testing private methods directly; test them through public interfaces.
- **Pytest Best Practices:**
  - **Fixtures:** Use `pytest` fixtures for setup/teardown (prefer `yield` fixtures). Use `conftest.py` for shared fixtures.
  - **Parametrization:** Use `@pytest.mark.parametrize` for data-driven tests.
  - **Markers:** Use markers to categorize tests, and register each one under `markers` in `pytest.toml` before using it: `--strict-markers` makes an unregistered marker such as `@pytest.mark.slow` a collection error.
  - **Style:** Prefer functional tests over class-based tests.

## 3. Project Structure

```tree
freeze-pr-links/
├── action.yml                       # The published composite action
├── src/freeze_pr_links/             # The transform, and the freeze-pr-links command
├── scripts/                         # The coverage report, release helpers, the .gitignore generator
├── checks/                          # PR-title, PR-body and commit-subject checks run in CI
├── tests/                           # Test suite
├── .github/                         # GitHub Actions workflows
├── .specify/memory/constitution.md  # Project constitution
├── pyproject.toml                   # Project configuration
├── uv.lock                          # Locked dependencies
├── Makefile                         # Task runner
└── .venv/                           # Virtual environment (git-ignored)
```

### Configuration Files

- **Linting & Formatting:** `.ruff.toml`, `.pylintrc`, `.pre-commit-config.yaml`, `.codespellrc`, `.markdownlint.yml`, `.yamllint`, `.gitlint`, `.editorconfig`
- **Testing:** `pytest.toml` (pytest config), `.coveragerc` (coverage config)
- **Editor:** `.editorconfig`, `.vscode/settings.json`, `.vscode/extensions.json`
- **Type Checking:** `ty.toml`, `pyrightconfig.json` (basedpyright)
- **Git:** `.gitignore`, `.gitattributes`, `.git-blame-ignore-revs`
  - `.gitignore` is generated by `scripts/concat-gitignores.sh`; regenerate it rather than editing it by hand. Project-specific patterns go in `scripts/custom.gitignore`, which is appended verbatim to the end.

## 4. Coding Guidelines

### Commit Messages

Follow **Conventional Commits** format: `<type>(<scope>): <subject>`

- **Types:** `feat`, `fix`, `docs`, `style`, `test`, `build`, `ci`, `refactor`, `perf`, `chore`, `revert`
- **Imperative Mood:** Write subjects as commands (e.g., "add feature" not "added feature")
- **Lowercase Start:** The first character after the colon, and after a `[TICKET-123]` key if there is one, must be a lowercase letter. The commit-msg hook rejects any other start, and the PR checks reject a capital one, an acronym included: write `add the API client`, not `API client added`.
- **Summary Length:** Keep the subject line under 51 characters (≤50)
- **Body Line Length:** Wrap body text at 72 characters
- **Atomic Commits:** One logical change per commit

**Example:**

```text
feat(core): add user authentication module

Implement JWT-based authentication with refresh token support.
This includes login, logout, and token refresh endpoints.
```

### Code Style

- **Enforcement:** `ruff` (linting/formatting) and `ty` (type checking), with `basedpyright` and `pylint` running only the checks those two do not make
- **Verification:** Run `make check` before committing to ensure all checks pass

### Dependencies

The package uses only the standard library. Do not add a runtime dependency.

### CLI Guidelines

- Ensure all CLI tools have helpful `--help` messages.
- Use colors where helpful.
- Use heredocs (multi-line strings) for usage text and docstrings.

### Python Idioms & Best Practices

- **Concurrency:**
  - Use `concurrent.futures` for parallelism or `asyncio` for async I/O.
  - Concurrency should be optional (controlled by a flag). Always include a synchronous implementation.
- **Memory Optimization:** Use `__slots__` for classes where beneficial or to prevent dynamic attributes.
- **Return Values:** Use `NamedTuple` or `dataclass` for return values with >3 elements (avoid plain tuples).
- **Enums:** Use `StrEnum` (Python 3.11+) with `auto()` for string-based enumerations.
- **Path Manipulation:** Prefer `pathlib.Path` over `os.path` or string manipulation.
- **Membership Checks:** Use `set` for membership checks, but be mindful of casting overhead.
- **Loop Optimization:** Avoid repeated dot notation in tight loops. Cache methods/attributes outside loops.
- **Module Exports (`__all__`):** Define as a tuple (not list) near the top of the file, below the docstring. Omit the parentheses when it fits on one line.

### Type Hints

- Use modern type hints (Python 3.12+) for all function signatures: `list[str]`, `str | None`, etc.
- Annotate class attributes and significant variables.

### Documentation

- Follow **Google-style** docstrings.
- **Modules:** Include docstrings at the module level.
- **Classes:** All classes must have docstrings.
- **Constants & Enums:** Document constants and Enum members.
- **Functions & Methods:**
  - **`Args:` Section:** Use judiciously. Only include if it adds material value (complex logic, gotchas, non-obvious parameters).
  - **No Redundancy:** Don't repeat information already clear from the signature (types, self-explanatory names).
- **Syncing:** Keep `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, `.github/instructions/CI.instructions.md`, and `README.md` in sync with code changes.

## 5. Specific Task Instructions

### Adding a Dependency

1. Add it to `pyproject.toml`, under `[project] dependencies` or one of the `[dependency-groups]`: `ci` (nox and pre-commit, for CI's jobs; `dev` includes it), `dev` or `test`. A runtime dependency is not allowed.
2. Run `uv lock` to update `uv.lock`.
3. Run `make develop` to sync the virtual environment.
4. Verify with `make check`.

### Modifying CI/CD

- Edit `.github/workflows/CI.yml` for workflow changes.
- Note: CI may have different behavior than local runs (e.g., stricter linting args).

### Running Tests

- **All Tests:** `make test`
- **Specific Test:** `uv run --group test pytest tests/test_specific.py`
- **With Coverage:** `uv run --group test pytest --cov=src --cov-report=html`
- **Markers:** `uv run --group test pytest -m no_ci` (run only the tests marked `no_ci`)

### Code Quality Checks

Before committing or pushing:

1. Run `make tidy-all` to auto-fix and format code.
2. Run `make check` to run quality checks and tests locally.
3. Review `git status` and `git diff` to verify changes.

## 6. Working with Claude Code

### Preferred Workflow

1. **File Operations:** Use dedicated tools (Read, Edit, Write, Glob, Grep) instead of bash commands.
2. **Read Before Edit:** Always read files before modifying them to understand context.
3. **Use Make:** Prefer `make` commands over direct tool invocations (e.g., `make test` not `pytest`).
4. **Track Tasks:** Use TodoWrite for multi-step tasks to track progress.
5. **Verify:** Run `make check` before considering a task complete.

### Git Operations

When creating commits:

1. Run `git status` and `git diff` to understand changes.
2. Review `git log` to match the repository's commit message style.
3. Stage relevant files with `git add`. Another session may share the tree, so read `git status` and stage explicit paths rather than `git add -A`.
4. Create a commit with a conventional commit message.

   ```commit-message
   <type>(<scope>): <subject>

   <optional body>
   ```

5. Do not force-push, do not rewrite a commit that is already on the remote, and do not push work you did not write.

### Key Reminders

- This project uses `uv` - always use `uv run` for command execution.
- The `Makefile` is the primary interface - use it instead of running tools directly.
- Follow Conventional Commits for all commit messages.
- Run `make check` to verify changes before committing.
- Keep documentation in sync with code changes.
- Test public interfaces, not private implementation details.
- Prefer simple, focused solutions over over-engineering.
