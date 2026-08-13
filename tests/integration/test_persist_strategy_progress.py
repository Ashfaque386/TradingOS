"""src/api/routers/agents.py's `_persist_strategy_progress` (REL-*: Strategy/StrategyVersion
persistence off the real graph run) against the real Postgres.

Regression coverage for the "strategy_generator" branch's account lookup: it must resolve the
one seeded Paper Trading Account the same way every other caller does (`get_paper_account`,
src/engine/paper_trading/paper_account.py -- `broker == "PAPER"` AND `account_type == "Paper"`),
not an unfiltered `select(Account.id).first()`. An unfiltered first-row lookup would silently
misattribute every newly generated Strategy to whichever Account row happens to sort first --
harmless with exactly one Account seeded, wrong the moment a second Account row exists (a stray
fixture left behind in this shared dev DB, a second paper account, a real broker account). This
test seeds an extra, non-paper Account row ahead of the real seeded paper account and confirms
the real paper account still wins.
"""

import uuid
from datetime import date
from decimal import Decimal

from src.agents.state import (
    MarketContext,
    PythonCode,
    ResearchDirective,
    StrategyLogic,
    StrategyOptionLeg,
)
from src.api.routers.agents import _persist_strategy_progress, _StrategyTracking
from src.core.db import get_session
from src.engine.paper_trading.paper_account import get_paper_account
from src.models.account import Account
from src.models.strategy import Strategy, StrategyVersion
from src.models.user import User

_STRATEGY_LOGIC = StrategyLogic(
    hypothesis="Momentum breakout on Nifty 50 constituents",
    asset_class="Equity",
    style="Intraday",
    universe=["RELIANCE"],
    entry_conditions="close > sma_20",
    exit_conditions="close < sma_20",
    stop_loss="2%",
    take_profit="5%",
    position_sizing="1% risk per trade",
    confidence_score=0.7,
)


def _seed_stray_account() -> tuple[uuid.UUID, uuid.UUID]:
    """A second, real Account row that is NOT the seeded paper account -- e.g. a stray fixture
    or a real broker account -- and, critically, has a lower id than the real paper account's
    UUID doesn't matter: `select(Account.id).first()` has no ORDER BY, so Postgres is free to
    return either row. Seeding this proves the fix picks the paper account on *filter*, not on
    insertion order or luck."""
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"persist-strategy-progress-test-{user_id}@example.invalid",
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
                account_type="Live",
                capital_allocated=Decimal("50000.00"),
            )
        )
        session.commit()
    return user_id, account_id


def _cleanup(user_id: uuid.UUID, account_id: uuid.UUID, strategy_id: uuid.UUID | None) -> None:
    with get_session() as session:
        if strategy_id is not None:
            session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.query(Account).filter(Account.id == account_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()


def test_strategy_generator_persistence_picks_the_real_paper_account_not_an_arbitrary_row():
    stray_user_id, stray_account_id = _seed_stray_account()
    strategy_id = None
    try:
        with get_session() as session:
            real_paper_account_id = get_paper_account(session).id

            tracking = _StrategyTracking()
            _persist_strategy_progress(
                session,
                node_name="strategy_generator",
                output={"strategy_logic": _STRATEGY_LOGIC},
                tracking=tracking,
                agent_run_id=uuid.uuid4(),
            )
            session.commit()

            assert tracking.strategy_id is not None
            strategy_id = tracking.strategy_id
            assert tracking.account_id == real_paper_account_id
            assert tracking.account_id != stray_account_id

            strategy_row = session.get(Strategy, strategy_id)
            assert strategy_row is not None
            assert strategy_row.account_id == real_paper_account_id
    finally:
        _cleanup(stray_user_id, stray_account_id, strategy_id)


def test_ceo_and_market_analyst_context_is_captured_onto_the_strategy_row_rel_044():
    """REL-044: ceo_agent/market_analyst both fire before strategy_generator creates the
    Strategy row -- this drives the real 3-node sequence (in the same order the real graph
    fires them) through _persist_strategy_progress and confirms their real output lands on the
    new research_context/market_context columns, and that StrategyLogic's own
    entry/exit/stop/take-profit/position-sizing/confidence fields -- computed by the LLM on
    every run but previously discarded -- are now persisted too."""
    directive = ResearchDirective(
        market_regime="Risk-On",
        priority_sectors=["IT", "Banking"],
        strategy_themes=["Momentum breakout"],
        risk_tolerance="Medium",
        participating_agents=["MarketAnalystAgent", "StrategyGeneratorAgent"],
        expected_outcomes="Identify 2-3 high-conviction momentum setups",
    )
    context = MarketContext(
        market_regime="Risk-On",
        sector_rankings=["IT", "Banking", "Pharma"],
        volatility_assessment="India VIX at 13.2, below the 1-year average",
        macro_outlook="RBI on hold, no major event risk this week",
        confidence_score=0.72,
        insights=["FII flows turned net positive for the third consecutive session"],
    )

    strategy_id = None
    try:
        with get_session() as session:
            tracking = _StrategyTracking()
            run_id = uuid.uuid4()

            _persist_strategy_progress(
                session,
                node_name="ceo_agent",
                output={"research_directive": directive},
                tracking=tracking,
                agent_run_id=run_id,
            )
            _persist_strategy_progress(
                session,
                node_name="market_analyst",
                output={"market_context": context},
                tracking=tracking,
                agent_run_id=run_id,
            )
            assert tracking.strategy_id is None  # neither node creates a Strategy row itself

            _persist_strategy_progress(
                session,
                node_name="strategy_generator",
                output={"strategy_logic": _STRATEGY_LOGIC},
                tracking=tracking,
                agent_run_id=run_id,
            )
            session.commit()

            assert tracking.strategy_id is not None
            strategy_id = tracking.strategy_id

            strategy_row = session.get(Strategy, strategy_id)
            assert strategy_row is not None
            assert strategy_row.entry_conditions == _STRATEGY_LOGIC.entry_conditions
            assert strategy_row.exit_conditions == _STRATEGY_LOGIC.exit_conditions
            assert strategy_row.stop_loss == _STRATEGY_LOGIC.stop_loss
            assert strategy_row.take_profit == _STRATEGY_LOGIC.take_profit
            assert strategy_row.position_sizing == _STRATEGY_LOGIC.position_sizing
            assert strategy_row.confidence_score is not None
            assert float(strategy_row.confidence_score) == _STRATEGY_LOGIC.confidence_score
            assert strategy_row.research_context is not None
            assert strategy_row.research_context["market_regime"] == "Risk-On"
            assert strategy_row.research_context["priority_sectors"] == ["IT", "Banking"]
            assert strategy_row.market_context is not None
            assert strategy_row.market_context["macro_outlook"] == context.macro_outlook
            assert strategy_row.market_context["confidence_score"] == 0.72
    finally:
        if strategy_id is not None:
            with get_session() as session:
                session.query(Strategy).filter(Strategy.id == strategy_id).delete()
                session.commit()


def test_options_strategy_agent_rationale_is_persisted_onto_the_strategy_version_rel_044():
    """REL-044: the Options Strategy Agent's real rationale for its declared legs -- computed on
    every F&O run (OptionsStrategyProposal.rationale) but discarded before REL-044 even inside
    the node itself -- is now staged and persisted onto StrategyVersion.option_rationale."""
    fo_logic = StrategyLogic(
        hypothesis="Bull call spread ahead of earnings",
        asset_class="F&O",
        style="Swing",
        universe=["RELIANCE"],
        entry_conditions="IV rank below 30 and price above 20-day high",
        exit_conditions="3 days before expiry or 50% of max profit reached",
        stop_loss="close below entry-day low",
        take_profit="50% of max theoretical profit",
        position_sizing="1 lot per Rs 5,00,000 capital",
        confidence_score=0.65,
        option_legs=[
            StrategyOptionLeg(
                symbol="RELIANCE24AUG3000CE",
                option_type="CE",
                strike=3000.0,
                side="buy",
                quantity=1,
            )
        ],
    )
    strategy_id = None
    try:
        with get_session() as session:
            tracking = _StrategyTracking()
            run_id = uuid.uuid4()

            _persist_strategy_progress(
                session,
                node_name="strategy_generator",
                output={"strategy_logic": fo_logic},
                tracking=tracking,
                agent_run_id=run_id,
            )
            strategy_id = tracking.strategy_id
            assert strategy_id is not None

            _persist_strategy_progress(
                session,
                node_name="options_strategy_agent",
                output={
                    "strategy_logic": fo_logic,
                    "option_expiry": date(2026, 8, 28),
                    "option_rationale": "Bullish structure with defined risk ahead of earnings.",
                },
                tracking=tracking,
                agent_run_id=run_id,
            )
            assert tracking.pending_option_rationale == (
                "Bullish structure with defined risk ahead of earnings."
            )

            _persist_strategy_progress(
                session,
                node_name="python_code_generator",
                output={"python_code": PythonCode(code="def run_backtest(): ...", version_no=1)},
                tracking=tracking,
                agent_run_id=run_id,
            )
            session.commit()

            strategy_row = session.get(Strategy, strategy_id)
            assert strategy_row is not None and strategy_row.current_version_id is not None
            version_row = session.get(StrategyVersion, strategy_row.current_version_id)
            assert version_row is not None
            assert (
                version_row.option_rationale
                == "Bullish structure with defined risk ahead of earnings."
            )
    finally:
        if strategy_id is not None:
            with get_session() as session:
                session.query(StrategyVersion).filter(
                    StrategyVersion.strategy_id == strategy_id
                ).delete()
                session.query(Strategy).filter(Strategy.id == strategy_id).delete()
                session.commit()
