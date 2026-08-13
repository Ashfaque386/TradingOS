"""src/api/routers/agents.py's `_persist_suggestion_regeneration` (REL-048) against the real
Postgres -- the suggestion-regeneration analogue of `_persist_strategy_progress`, direct-called
with synthetic node outputs the same way test_persist_strategy_progress.py already does (no real
LLM calls needed here; the real end-to-end LLM path is covered by
test_strategies_api.py::test_suggestion_review_end_to_end_real_llm).

The one behavior this file exists specifically to prove `_persist_strategy_progress` does NOT
have: `strategy_generator` output updates the EXISTING strategy row in place rather than creating
a brand-new one, since a suggestion always targets a real, already-persisted Strategy.

Also covers BUG-011 (found live-testing this exact feature): `options_strategy_agent` returning
`{}` for an Equity strategy_logic streams as `output = None` from LangGraph's `updates` mode, not
`{}` -- `_persist_suggestion_regeneration` (and `_summarize_node_output`) must not crash on it.
"""

import uuid
from decimal import Decimal

from src.agents.state import PythonCode, StrategyLogic
from src.api.routers.agents import (
    _persist_suggestion_regeneration,
    _SuggestionRegenTracking,
    _summarize_node_output,
)
from src.core.db import get_session
from src.models.account import Account
from src.models.strategy import Strategy, StrategyVersion
from src.models.user import User

_ORIGINAL_LOGIC = StrategyLogic(
    hypothesis="Original hypothesis before any suggestion",
    asset_class="Equity",
    style="Intraday",
    universe=["RELIANCE"],
    entry_conditions="close > sma_20",
    exit_conditions="close < sma_20",
    stop_loss="2%",
    take_profit="5%",
    position_sizing="1% risk per trade",
    confidence_score=0.6,
)

_REGENERATED_LOGIC = StrategyLogic(
    hypothesis="Regenerated hypothesis reflecting the user's suggestion",
    asset_class="Equity",
    style="Swing",
    universe=["RELIANCE"],
    entry_conditions="close > sma_50",
    exit_conditions="close < sma_50 or stop hit",
    stop_loss="1%",
    take_profit="4%",
    position_sizing="0.5% risk per trade",
    confidence_score=0.81,
)


def _seed_strategy() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    user_id, account_id, strategy_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"persist-suggestion-regen-test-{user_id}@example.invalid",
                hashed_password="x",
                role="Trader",
            )
        )
        session.commit()
    with get_session() as session:
        session.add(
            Account(
                id=account_id,
                user_id=user_id,
                broker="Zerodha",
                account_type="Paper",
                capital_allocated=Decimal("100000.00"),
            )
        )
        session.commit()
    with get_session() as session:
        session.add(
            Strategy(
                id=strategy_id,
                account_id=account_id,
                name=_ORIGINAL_LOGIC.hypothesis[:150],
                hypothesis=_ORIGINAL_LOGIC.hypothesis,
                asset_class=_ORIGINAL_LOGIC.asset_class,
                style=_ORIGINAL_LOGIC.style,
                status="Backtesting",
                max_drawdown_limit=Decimal("15.00"),
                universe=_ORIGINAL_LOGIC.universe,
                entry_conditions=_ORIGINAL_LOGIC.entry_conditions,
                exit_conditions=_ORIGINAL_LOGIC.exit_conditions,
                stop_loss=_ORIGINAL_LOGIC.stop_loss,
                take_profit=_ORIGINAL_LOGIC.take_profit,
                position_sizing=_ORIGINAL_LOGIC.position_sizing,
                confidence_score=_ORIGINAL_LOGIC.confidence_score,
            )
        )
        session.commit()
    return user_id, account_id, strategy_id


def _cleanup(user_id: uuid.UUID, account_id: uuid.UUID, strategy_id: uuid.UUID) -> None:
    with get_session() as session:
        session.query(StrategyVersion).filter(StrategyVersion.strategy_id == strategy_id).delete()
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.query(Account).filter(Account.id == account_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()


def test_strategy_generator_output_updates_the_existing_strategy_not_a_new_row():
    user_id, account_id, strategy_id = _seed_strategy()
    try:
        with get_session() as session:
            before_count = session.query(Strategy).count()
            tracking = _SuggestionRegenTracking(strategy_id=strategy_id)
            _persist_suggestion_regeneration(
                session,
                node_name="strategy_generator",
                output={"strategy_logic": _REGENERATED_LOGIC},
                tracking=tracking,
            )
            session.commit()
            after_count = session.query(Strategy).count()
            assert after_count == before_count  # no new Strategy row was created

            strategy_row = session.get(Strategy, strategy_id)
            assert strategy_row is not None
            assert strategy_row.hypothesis == _REGENERATED_LOGIC.hypothesis
            assert strategy_row.style == "Swing"
            assert strategy_row.entry_conditions == _REGENERATED_LOGIC.entry_conditions
            assert float(strategy_row.confidence_score) == _REGENERATED_LOGIC.confidence_score
    finally:
        _cleanup(user_id, account_id, strategy_id)


def test_options_strategy_agent_none_output_does_not_crash_bug_011():
    """BUG-011: for an Equity strategy_logic, LangGraph streams `options_strategy_agent`'s real
    `{}` return as `output = None`. Both `_summarize_node_output` and
    `_persist_suggestion_regeneration` must handle that gracefully, not raise."""
    assert (
        _summarize_node_output("options_strategy_agent", None)
        == "options_strategy_agent completed with no new state fields"
    )

    user_id, account_id, strategy_id = _seed_strategy()
    try:
        with get_session() as session:
            tracking = _SuggestionRegenTracking(strategy_id=strategy_id)
            # Must not raise -- this is the exact call site that crashed before the fix.
            _persist_suggestion_regeneration(
                session, node_name="options_strategy_agent", output=None, tracking=tracking
            )
            session.commit()
            assert tracking.pending_option_legs is None
    finally:
        _cleanup(user_id, account_id, strategy_id)


def test_python_code_generator_creates_a_new_version_attached_to_the_existing_strategy():
    user_id, account_id, strategy_id = _seed_strategy()
    try:
        with get_session() as session:
            tracking = _SuggestionRegenTracking(strategy_id=strategy_id)
            _persist_suggestion_regeneration(
                session,
                node_name="python_code_generator",
                output={"python_code": PythonCode(code="def run_backtest(): ...", version_no=2)},
                tracking=tracking,
            )
            session.commit()

            assert tracking.new_version_id is not None
            version_row = session.get(StrategyVersion, tracking.new_version_id)
            assert version_row is not None
            assert version_row.strategy_id == strategy_id
            assert version_row.version_no == 2

            strategy_row = session.get(Strategy, strategy_id)
            assert strategy_row is not None
            assert strategy_row.current_version_id == tracking.new_version_id
            assert strategy_row.status == "Coding"
    finally:
        _cleanup(user_id, account_id, strategy_id)
