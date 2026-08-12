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
from decimal import Decimal

from src.agents.state import StrategyLogic
from src.api.routers.agents import _persist_strategy_progress, _StrategyTracking
from src.core.db import get_session
from src.engine.paper_trading.paper_account import get_paper_account
from src.models.account import Account
from src.models.strategy import Strategy
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
