"""Deterministic, language-agnostic pull request checks.

Each module is a small standalone CLI that reports errors (which block) and warnings
(which advise), following the rule that a tool's action may not exceed the certainty
of its detection. Invoke a check as a module, for example:

    python -m checks.check_pr_title "feat: add config precedence rule"

The modules are pure standard library on purpose: CI runs them with a bare
`actions/setup-python` and no project install, so the gate resolves no dependencies
from the pull request it checks. It does run that pull request's copy of these
modules, so a pull request can change the checks applied to it.
"""

__all__ = ()
