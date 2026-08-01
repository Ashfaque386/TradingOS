"""Strategy Deployment & Backtest Review API integration test (Phase 4 Epic E4.3): the endpoints
wired in src/api/routers/strategies.py, backing Phase_7_Frontend_Architecture.md §2.3, against the
real FastAPI app + real Postgres + a real vectorbt backtest run in the sandbox against the real
TCS EOD data ingested in Phase 1 (same real data test_real_backtest_runner.py uses).

Slow (~60-90s for the backtest job to complete): vectorbt's numba JIT compiles cold inside the
fresh sandboxed subprocess every run, matching test_real_backtest_runner.py's own timing note.
"""

import time
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR
from src.models.account import Account
from src.models.strategy import BacktestResult, Strategy, StrategyVersion
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)

_STRATEGY_CODE = """
import polars as pl
import vectorbt as vbt


def run_backtest(data: pl.DataFrame, config: dict) -> dict:
    close = data["close"].to_pandas()
    close.index = data["date"].to_pandas()
    fast = close.rolling(5).mean()
    slow = close.rolling(20).mean()
    entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    pf = vbt.Portfolio.from_signals(
        close, entries, exits, init_cash=config.get("init_cash", 100000), freq="1D"
    )

    def clean(x):
        try:
            x = float(x)
            return x if x == x and abs(x) != float("inf") else None
        except Exception:
            return None

    metrics = {
        "sharpe_ratio": clean(pf.sharpe_ratio()),
        "sortino_ratio": clean(pf.sortino_ratio()),
        "calmar_ratio": clean(pf.calmar_ratio()),
        "max_drawdown": clean(pf.max_drawdown()),
        "cagr": clean(pf.annualized_return()),
        "win_rate": clean(pf.trades.win_rate()),
        "profit_factor": clean(pf.trades.profit_factor()),
        "expectancy": clean(pf.trades.expectancy()),
        "total_trades": int(pf.trades.count()),
    }
    equity_curve = [{"date": str(d.date()), "equity": float(v)} for d, v in pf.value().items()]
    return {"metrics": metrics, "equity_curve": equity_curve}
"""


def _create_fixture_rows() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
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
                email=f"strategies-api-{user_id}@example.invalid",
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
            name="strategies-api-test-strategy",
            hypothesis="5/20 SMA crossover on TCS",
            asset_class="Equity",
            style="Intraday",
            status="Backtesting",
            max_drawdown_limit=Decimal("15.00"),
            universe=["TCS"],
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

    return user_id, account_id, strategy_id, version_id


def _cleanup_fixture_rows(
    user_id: uuid.UUID, account_id: uuid.UUID, strategy_id: uuid.UUID, version_id: uuid.UUID
) -> None:
    with get_session() as session:
        session.query(BacktestResult).filter(
            BacktestResult.strategy_version_id == version_id
        ).delete()
        session.query(StrategyVersion).filter(StrategyVersion.id == version_id).delete()
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.query(Account).filter(Account.id == account_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()


def test_strategy_list_detail_version_backtest_and_promote_end_to_end():
    ids = _create_fixture_rows()
    user_id, account_id, strategy_id, version_id = ids
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)

    try:
        list_response = client.get("/api/v1/strategies")
        assert list_response.status_code == 200
        assert any(s["id"] == str(strategy_id) for s in list_response.json())

        detail_response = client.get(f"/api/v1/strategies/{strategy_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["name"] == "strategies-api-test-strategy"
        assert detail["universe"] == ["TCS"]
        assert len(detail["versions"]) == 1
        assert detail["versions"][0]["validation_status"] == "Passed"
        assert detail["backtests"] == []

        version_response = client.get(f"/api/v1/strategies/{strategy_id}/versions/1")
        assert version_response.status_code == 200
        assert "run_backtest" in version_response.json()["python_code"]

        # Real backtest, real sandbox, real TCS data -- polled to completion (~60-90s).
        trigger_response = client.post(
            f"/api/v1/strategies/{strategy_id}/backtest", headers=headers
        )
        assert trigger_response.status_code == 202
        job_id = trigger_response.json()["job_id"]

        deadline = time.monotonic() + 150
        job_status = None
        while time.monotonic() < deadline:
            job_response = client.get(f"/api/v1/strategies/backtests/jobs/{job_id}/status")
            assert job_response.status_code == 200
            job_status = job_response.json()
            if job_status["status"] != "Running":
                break
            time.sleep(3)

        assert job_status is not None and job_status["status"] == "Completed", job_status
        backtest_id = job_status["backtest_result_id"]
        assert backtest_id is not None

        detail_after = client.get(f"/api/v1/strategies/{strategy_id}").json()
        assert len(detail_after["backtests"]) == 1
        backtest_summary = detail_after["backtests"][0]
        assert backtest_summary["id"] == backtest_id
        assert backtest_summary["sharpe_ratio"] is not None or backtest_summary["total_trades"] == 0

        equity_response = client.get(f"/api/v1/strategies/backtests/{backtest_id}/equity-curve")
        assert equity_response.status_code == 200
        if backtest_summary["has_equity_curve"]:
            points = equity_response.json()
            assert len(points) > 200  # a full trailing year of real trading days
            assert points[0]["equity"] > 0

        promote_response = client.post(
            f"/api/v1/strategies/{strategy_id}/promote", json={"to_status": "Live"}, headers=headers
        )
        assert promote_response.status_code == 200
        assert promote_response.json()["status"] == "Live"
    finally:
        _cleanup_fixture_rows(*ids)
        cleanup_user(admin_id)


def test_backtest_rejects_a_strategy_with_no_universe_recorded():
    user_id, account_id = uuid.uuid4(), uuid.uuid4()
    strategy_id, version_id = uuid.uuid4(), uuid.uuid4()

    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"strategies-api-nouniv-{user_id}@example.invalid",
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
            name="strategies-api-nouniv-strategy",
            asset_class="Equity",
            style="Intraday",
            status="Ideation",
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
                validation_status="Pending",
            )
        )
        strategy.current_version_id = version_id
        session.commit()

    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)

    try:
        backtest_response = client.post(
            f"/api/v1/strategies/{strategy_id}/backtest", headers=headers
        )
        assert backtest_response.status_code == 409

        promote_response = client.post(
            f"/api/v1/strategies/{strategy_id}/promote",
            json={"to_status": "Backtesting"},
            headers=headers,
        )
        assert promote_response.status_code == 409  # Ideation strategies have nothing to promote
    finally:
        _cleanup_fixture_rows(user_id, account_id, strategy_id, version_id)
        cleanup_user(admin_id)


def test_backtest_trigger_requires_authentication():
    """REL-011 E10.11.0: POST /{strategy_id}/backtest was found with NO auth dependency at all
    -- any caller, including unauthenticated ones, could launch a real vectorbt backtest run.
    A random UUID 404s (or 401s first, before any DB lookup) either way -- what matters here is
    that this never reaches 202/409, proving the gate runs before the handler body."""
    response = client.post(f"/api/v1/strategies/{uuid.uuid4()}/backtest")
    assert response.status_code == 401


def test_backtest_trigger_requires_the_gated_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            f"/api/v1/strategies/{uuid.uuid4()}/backtest", headers=auth_header(token)
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)
