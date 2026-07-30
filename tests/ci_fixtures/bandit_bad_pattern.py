"""REL-009 E9.3 deliberate-verification fixture -- a real, Bandit-flaggable eval() pattern,
kept ONLY to prove the CI Bandit gate genuinely catches something real, never imported or
executed by any real code or by pytest (this directory is outside `tests/unit`/`tests/integration`,
never collected). Deliberately excluded from the real CI Bandit scan target
(`bandit -c pyproject.toml -r src` only scans `src/`, not `tests/`) -- see the REL-009 plan's
Verification section for the one-time manual proof-of-catch this fixture is for.
"""


def dangerous_eval(user_input: str) -> object:
    return eval(user_input)  # noqa: S307 -- deliberately unsafe, see module docstring
