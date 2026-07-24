"""Python Code Generator Agent node (AGT-004, PMPT-004) — Phase 2 Epic E2.3.

Searches the real Qdrant `code_templates` RAG collection (search_code_templates,
src/agents/tools/skills.py) before writing code, per Phase_4_AI_Agent_Design.md §4. Output is
formatted with the real `format_python_code` skill (black) before being handed to the
Validator.
"""

from src.agents.llm_router import complete
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import PythonCode, TradingOSGraphState
from src.agents.tools.registry import get_skill_registry

PROMPT_SLUG = "python_code_generator_agent"
TASK_PROMPT_SLUG = "python_code_generator_agent_task"


def python_code_generator_node(state: TradingOSGraphState) -> dict[str, PythonCode]:
    if state.strategy_logic is None:
        raise ValueError("python_code_generator_node requires state.strategy_logic")

    system_prompt = get_active_prompt(PROMPT_SLUG)
    templates = get_skill_registry().execute(
        "search_code_templates", query=state.strategy_logic.hypothesis, top_k=3
    )

    user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
        strategy_json=state.strategy_logic.model_dump_json(),
        templates=templates,
    )

    response = complete(
        "coding",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    code = response.choices[0].message.content.strip()
    if code.startswith("```"):
        code = code.split("```")[1]
        if code.startswith("python"):
            code = code[len("python") :]
        code = code.strip()

    formatted = get_skill_registry().execute("format_python_code", code=code)
    version_no = (state.python_code.version_no + 1) if state.python_code else 1
    return {"python_code": PythonCode(code=formatted, version_no=version_no)}
