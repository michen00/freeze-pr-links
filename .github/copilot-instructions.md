# Repository Instructions for GitHub Copilot

## Project

- This repository ships one GitHub Action, `action.yml`, which rewrites a merged pull request's head-branch links as commit permalinks. The transform is `src/freeze_pr_links/core.py`, and the action runs it from its own tree.
- **The action runs on `pull_request_target` with a write token.** Breaking a property in [SECURITY.md](../SECURITY.md) is a security regression, so read it before changing `action.yml` or `.github/workflows/freeze-pr-links.yml`.
- **The package uses only the standard library.** Do not add a runtime dependency.

## 1) High‑Level Details

- **Language:** Python 3.13+
- **Dependency Management:** `uv` (manages `.venv` in project root).
- **Task Runner:** `Makefile` is the primary entry point for all development tasks.

## 2) Build and Validation Information

- **Run All Checks:** `make check` (runs `make tidy`, the pre-commit hooks, and tests).
- **Testing:** `make test` (runs `pytest` with coverage).
- **Linting:** `make lint` (ruff check --fix).
- **Formatting:** `make format` (ruff format), `make tidy` (best-effort lint autofix + format), or `make tidy-all` (pre-commit + tidy).
- **Execution:** Always use `uv run <command>` to ensure execution within the virtual environment.

## 3) Project Layout and Architecture

- `action.yml`: The composite action this repository publishes.
- `src/freeze_pr_links/`: The transform the action runs, also installed as the `freeze-pr-links` command.
- `scripts/`: Standalone scripts, not a package: the coverage report CI renders, the release helpers and `concat-gitignores.sh` (generates `.gitignore`).
- `checks/`: The standard-library PR-title, PR-body and commit-subject checks that `pr-mechanical-checks.yml` runs.
- `tests/`: Test suite.
- `.specify/memory/constitution.md`: Project constitution (design principles, quality gates, coding standards).
- `pyproject.toml`: Project configuration, dependencies, and tool settings.
- `uv.lock`: Exact dependency versions.
- `.github/`: CI/CD workflows and templates.

## 4) Conventional Commits and Contribution Workflow

### Commit Messages

Follow **Conventional Commits** format: `<type>(<scope>): <subject>`

- **Types:** `feat`, `fix`, `docs`, `style`, `test`, `build`, `ci`, `refactor`, `perf`, `chore`, `revert`
- **Imperative Mood:** Write subjects as commands (e.g., "add feature" not "added feature")
- **Lowercase Start:** The first character after the colon, and after a `[TICKET-123]` key if there is one, must be a lowercase letter. The commit-msg hook rejects any other start, and the PR checks reject a capital one, an acronym included: write `add the API client`, not `API client added`.
- **Summary Length:** Keep the subject line under 51 characters (≤50)
- **Body Line Length:** Wrap body text at 72 characters
- **Atomic Commits:** One logical change per commit

- **Recommended Workflow:**
  1. **Setup:** `make develop`
  2. **Develop:** Write code and tests (TDD encouraged).
  3. **Verify:** Run `make check` before committing.

- **Documentation Sync:** Ensure `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, `.github/instructions/CI.instructions.md`, and `README.md` are kept updated and synced with code changes.

---

Note to GitHub Copilot: Please trust these instructions and only perform additional searches if the information provided is incomplete or found to be in error.
