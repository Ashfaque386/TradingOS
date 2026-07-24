"""Go-Live Readiness API integration test (Phase 4 Epic E4.4): GET
/api/v1/go-live/readiness/{strategy_id} (src/api/routers/go_live_readiness.py,
src/engine/go_live_gate.py) against the real FastAPI app + real Postgres.

Condition 3 (Shadow Mode clean streak) reads a GLOBAL ledger shared with every other test and
any real usage of the system -- like tests/integration/test_shadow_mode_api.py's own
test_status_reports_zero_consecutive_days_honestly_when_nothing_has_run, this file does not
assert a specific value for it, only that the reported gate_met is the real logical AND of all
four reported conditions. Conditions 1, 2, and 4 are strategy-scoped and fully deterministic, so
those ARE asserted directly.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.models.account import Account
from src.models.paper_trading import PaperTrade
from src.models.strategy import BacktestResult, Strategy, StrategyVersion
from src.models.user import User

client = TestClient(app)

_STRATEGY_CODE = "def generate_signals(data):\n    return data"


def _seed_strategy_with_backtest(
    *, win_rate: float | None
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    user_id, account_id, strategy_id, version_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"go-live-readiness-{user_id}@example.invalid",
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
        strategy = Strategy(
            id=strategy_id,
            account_id=account_id,
            name="go-live-readiness-test-strategy",
            asset_class="Equity",
            style="Intraday",
            status="PaperTrading",
            max_drawdown_limit=Decimal("15.00"),
        )
        session.add(strategy)
        session.flush()
        session.add(
            StrategyVersion(
                id=version_id,
                strategy_id=strategy_id,
                version_no=1,
                python_code=_STRATEGY_CODE,
                validation_status="Passed",
            )
        )
        strategy.current_version_id = version_id
        session.commit()

        if win_rate is not None:
            session.add(
                BacktestResult(
                    strategy_version_id=version_id,
                    date_from=datetime.now(UTC).date() - timedelta(days=365),
                    date_to=datetime.now(UTC).date(),
                    initial_capital=Decimal("100000.00"),
                    win_rate=Decimal(str(win_rate)),
                    total_trades=100,
                )
            )
            session.commit()

    return user_id, account_id, strategy_id, version_id


def _cleanup(
    user_id: uuid.UUID, account_id: uuid.UUID, strategy_id: uuid.UUID, version_id: uuid.UUID
) -> None:
    with get_session() as session:
        session.query(PaperTrade).filter(PaperTrade.strategy_id == strategy_id).delete()
        session.query(BacktestResult).filter(
            BacktestResult.strategy_version_id == version_id
        ).delete()
        session.query(StrategyVersion).filter(StrategyVersion.id == version_id).delete()
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.query(Account).filter(Account.id == account_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()


def _seed_round_trip_trades(*, strategy_id: uuid.UUID, win_count: int, loss_count: int) -> None:
    """win_count + loss_count round trips (2 PaperTrade rows each), spread across the last 25
    days so the calendar-span condition (>=21 days) is also satisfied by the same fixture."""
    total = win_count + loss_count
    now = datetime.now(UTC)
    with get_session() as session:
        for i in range(total):
            symbol = f"GATE{i:03d}"
            days_ago = 25 - (25 * i / max(total - 1, 1))
            buy_time = now - timedelta(days=days_ago, minutes=2)
            sell_time = now - timedelta(days=days_ago)
            is_win = i < win_count
            exit_price = 110.0 if is_win else 90.0
            session.add(
                PaperTrade(
                    strategy_id=strategy_id,
                    symbol=symbol,
                    side="BUY",
                    requested_quantity=10,
                    filled_quantity=10,
                    reference_price=100.0,
                    fill_price=100.0,
                    slippage_bps=0.0,
                    depth_snapshot={},
                    executed_at=buy_time,
                )
            )
            session.add(
                PaperTrade(
                    strategy_id=strategy_id,
                    symbol=symbol,
                    side="SELL",
                    requested_quantity=10,
                    filled_quantity=10,
                    reference_price=exit_price,
                    fill_price=exit_price,
                    slippage_bps=0.0,
                    depth_snapshot={},
                    executed_at=sell_time,
                )
            )
        session.commit()


def test_a_fresh_strategy_with_no_data_fails_every_condition():
    ids = _seed_strategy_with_backtest(win_rate=None)
    try:
        response = client.get(f"/api/v1/go-live/readiness/{ids[2]}")
        assert response.status_code == 200
        body = response.json()

        assert body["gate_met"] is False
        conditions_by_label = {c["label"]: c for c in body["conditions"]}
        assert conditions_by_label["Minimum trade count"]["met"] is False
        assert conditions_by_label["Minimum calendar span"]["met"] is False
        assert conditions_by_label["Live vs. backtest win-rate divergence"]["met"] is False
    finally:
        _cleanup(*ids)


def test_strategy_specific_conditions_pass_when_live_win_rate_matches_the_backtest():
    ids = _seed_strategy_with_backtest(win_rate=0.60)
    strategy_id = ids[2]
    # 12 wins, 8 losses = 0.60 live win rate, exactly matching the backtest -> zero divergence.
    # 40 total filled trades (>= MIN_TRADE_COUNT=30), spanning ~25 days (>= MIN_CALENDAR_DAYS=21).
    _seed_round_trip_trades(strategy_id=strategy_id, win_count=12, loss_count=8)
    try:
        response = client.get(f"/api/v1/go-live/readiness/{strategy_id}")
        assert response.status_code == 200
        body = response.json()

        conditions_by_label = {c["label"]: c for c in body["conditions"]}
        assert conditions_by_label["Minimum trade count"]["met"] is True
        assert conditions_by_label["Minimum calendar span"]["met"] is True
        assert conditions_by_label["Live vs. backtest win-rate divergence"]["met"] is True

        # The Shadow Mode streak reads a ledger shared with every other test in this suite (and
        # any real usage) -- assert the composition is honest rather than guessing its value.
        assert body["gate_met"] == all(c["met"] for c in body["conditions"])
    finally:
        _cleanup(*ids)


def test_unknown_strategy_returns_404():
    response = client.get(f"/api/v1/go-live/readiness/{uuid.uuid4()}")
    assert response.status_code == 404
