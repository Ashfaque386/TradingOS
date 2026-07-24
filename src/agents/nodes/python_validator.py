"""Python Validator Agent node (AGT-005, PMPT-005) — Phase 2 Epic E2.3 / Phase 3 Epic E3.1.

Per Phase_4_AI_Agent_Design.md §5 ("Memory: None. Stateless execution"), this node is
deterministic rather than another LLM call. Three real checks, in order:
  1. static_safety_check (AST ban-list) -- a hard gate. Code that fails this is never even
     handed to the sandbox; there's no reason to execute code we've already proven is unsafe.
  2. run_linter (ruff) -- style/correctness, run alongside the sandbox since it doesn't need
     the AST gate to pass first.
  3. execute_dry_run_sandbox (Phase 3 Epic E3.1, src/engine/sandbox/runner.py) -- the real
     sandboxed dry-run named in the Phase 4 agent spec, only reached if step 1 passed.
Loops back to the Code Generator up to 3 times on failure (Phase_4 §5) -- enforced by
graph.py's conditional edge using code_validation_retry_count, not this node.
"""

from src.agents.state import TradingOSGraphState, ValidationResult
from src.agents.tools.registry import get_skill_registry

MAX_RETRIES = 3


def python_validator_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.python_code is None:
        raise ValueError("python_validator_node requires state.python_code")
    code = state.python_code.code

    registry = get_skill_registry()
    safety = registry.execute("static_safety_check", code=code)

    if not safety["passed"]:
        return _fail(state, severity="Critical", violations=list(safety["violations"]))

    lint = registry.execute("run_linter", code=code)
    sandbox = registry.execute("execute_dry_run_sandbox", code=code)

    violations: list[str] = []
    if not lint["passed"]:
        violations.append(f"lint findings: {lint['findings']}")
    if not sandbox["passed"]:
        violations.append(f"sandbox execution failed: {sandbox['error']}")

    if violations:
        return _fail(state, severity="Medium", violations=violations)

    return {
        "validation_result": ValidationResult(status="Pass"),
        "code_validation_retry_count": state.code_validation_retry_count,
    }


def _fail(state: TradingOSGraphState, *, severity: str, violations: list[str]) -> dict[str, object]:
    result = ValidationResult(
        status="Fail",
        severity=severity,  # type: ignore[arg-type]
        error_trace=None,
        feedback="; ".join(violations),
    )
    return {
        "validation_result": result,
        "code_validation_retry_count": state.code_validation_retry_count + 1,
    }
