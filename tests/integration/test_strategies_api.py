"""Strategy Deployment & Backtest Review API integration test (Phase 4 Epic E4.3): the endpoints
wired in src/api/routers/strategies.py, backing Phase_7_Frontend_Architecture.md §2.3, against the
real FastAPI app + real Postgres + a real vectorbt backtest run in the sandbox against the real
TCS EOD data ingested in Phase 1 (same real data test_real_backtest_runner.py uses).

Slow (~60-90s for the backtest job to complete): vectorbt's numba JIT compiles cold inside the
fresh sandboxed subprocess every run, matching test_real_backtest_runner.py's own timing note.
"""

import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import polars as pl
from fastapi.testclient import TestClient
from sqlalchemy import delete

from src.api.main import app
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR
from src.data.provenance import get_provenance, upsert_provenance
from src.models.account import Account
from src.models.market_data_provenance import MarketDataProvenance
from src.models.strategy import BacktestResult, Strategy, StrategySuggestion, StrategyVersion
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

    trades = []
    for _, row in pf.trades.records_readable.iterrows():
        trades.append(
            {
                "entry_date": str(row["Entry Timestamp"].date()),
                "exit_date": str(row["Exit Timestamp"].date()),
                "side": "long" if str(row["Direction"]).lower() == "long" else "short",
                "size": float(row["Size"]),
                "entry_price": float(row["Avg Entry Price"]),
                "exit_price": float(row["Avg Exit Price"]),
                "pnl": float(row["PnL"]),
                "return_pct": float(row["Return"]),
            }
        )

    entries_exits = [
        {"date": str(d.date()), "entry": bool(en), "exit": bool(ex)}
        for d, en, ex in zip(entries.index, entries.values, exits.values, strict=True)
    ]

    return {
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
        "entries_exits": entries_exits,
    }
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

    # REL-073: seed a known, real TCS provenance row so the assertion below is deterministic --
    # whether a real managed/scheduled ingestion has touched TCS *today* (this test's own run
    # time) is genuinely non-deterministic (depends on whether real EOD data has published yet),
    # so this test controls it directly rather than depending on incidental live timing.
    # Restores whatever real state existed before, never destroys real provenance.
    with get_session() as session:
        original_tcs_provenance = get_provenance(session, "TCS")
        upsert_provenance(
            session,
            symbol="TCS",
            provider="upstox_v3",
            retrieved_at=datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
        )

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
        # REL-072: run_real_backtest's new adjust_for_corporate_actions defaults to True, and
        # this endpoint's own _run_backtest_job now threads outcome.data_adjusted onto the
        # persisted row -- a real backtest through the real trigger endpoint must report it.
        assert backtest_summary["data_adjusted"] is True
        # REL-073: real reproducibility provenance -- the known provenance row seeded above must
        # be looked up and threaded through the real trigger endpoint, not silently dropped.
        assert backtest_summary["provider_used"] == "upstox_v3"
        assert backtest_summary["data_retrieved_at"] is not None
        # A bodyless trigger (this call passes no `json=` kwarg at all) must keep behaving exactly
        # as before the optional BacktestTriggerRequest was added -- DEFAULT_INITIAL_CAPITAL, now
        # actually surfaced on the response for the first time.
        assert backtest_summary["initial_capital"] == 100_000.0

        equity_response = client.get(f"/api/v1/strategies/backtests/{backtest_id}/equity-curve")
        assert equity_response.status_code == 200
        if backtest_summary["has_equity_curve"]:
            points = equity_response.json()
            assert len(points) > 200  # a full trailing year of real trading days
            assert points[0]["equity"] > 0

        # REL-022 exit criterion: a real, non-empty trades list, persisted by the real endpoint
        # (not the runner function directly, unlike test_real_backtest_runner.py), verified via a
        # direct SELECT on the new column -- and its total real PnL matches the equity curve's
        # own real net change, proving the ledger isn't just present but numerically consistent.
        with get_session() as session:
            result_row = session.get(BacktestResult, uuid.UUID(backtest_id))
            assert result_row is not None
            assert result_row.trades is not None
            assert len(result_row.trades) == backtest_summary["total_trades"]
            trades = list(result_row.trades)
            mc_p95 = result_row.monte_carlo_p95_max_drawdown
            historical_max_dd = result_row.max_drawdown
            walk_forward_results = (
                list(result_row.walk_forward_results) if result_row.walk_forward_results else None
            )
        if trades:
            total_trade_pnl = sum(t["pnl"] for t in trades)
            net_equity_change = points[-1]["equity"] - points[0]["equity"]
            # Open positions at the window's end and cash-drag mean these aren't identical, but
            # a real ledger's PnL must be within the same order of magnitude as the real equity
            # curve's own net change, not wildly divergent or zero.
            assert abs(total_trade_pnl - net_equity_change) < abs(net_equity_change) * 0.5 + 1

        # REL-023 exit criterion: a real Monte Carlo P95 max drawdown, computed from the same
        # real per-trade returns just verified above (not the daily-equity-curve approximation
        # optimization_node's own LangGraph path still uses) -- >= the real historical
        # max_drawdown is the actual defining property of a P95 worst-case tail metric, not just
        # "some non-null number got written."
        if len(trades) >= 2:
            assert mc_p95 is not None
            assert float(mc_p95) >= 0
            if historical_max_dd is not None:
                assert float(mc_p95) >= float(historical_max_dd) * 0.99

        # REL-023 E23.2: the new trades endpoint reconciles exactly against the same DB row --
        # same discipline as REL-018's orders-endpoint reconciliation test.
        trades_response = client.get(f"/api/v1/strategies/backtests/{backtest_id}/trades")
        assert trades_response.status_code == 200
        assert trades_response.json() == trades

        # REL-024 exit criterion: real Walk-Forward Optimization windows, computed from the real
        # entries_exits/close_curve this same backtest run captured -- the real 365-day window
        # this endpoint always requests comfortably covers walk_forward_adapter.py's real
        # train=4mo/test=1mo/step=1mo sizing (>= 3 rolling windows, verified empirically in
        # tests/unit/test_walk_forward_adapter.py), so this should never be honestly empty for a
        # v3-contract strategy with real historical data, unlike Monte Carlo/trades above which
        # can legitimately be empty for a zero-trade window.
        assert walk_forward_results is not None
        assert len(walk_forward_results) >= 3
        for window in walk_forward_results:
            assert window["train_start"] < window["train_end"] == window["test_start"]
            assert window["test_start"] < window["test_end"]
            assert isinstance(window["out_of_sample_passed"], bool)

        # REL-024 E24.3: the new walk-forward endpoint reconciles exactly against the same DB
        # row -- same discipline as the trades endpoint above.
        wf_response = client.get(f"/api/v1/strategies/backtests/{backtest_id}/walk-forward")
        assert wf_response.status_code == 200
        assert wf_response.json() == walk_forward_results

        promote_response = client.post(
            f"/api/v1/strategies/{strategy_id}/promote", json={"to_status": "Live"}, headers=headers
        )
        assert promote_response.status_code == 200
        assert promote_response.json()["status"] == "Live"
    finally:
        with get_session() as session:
            if original_tcs_provenance is not None:
                upsert_provenance(
                    session,
                    symbol="TCS",
                    provider=original_tcs_provenance.provider,
                    retrieved_at=original_tcs_provenance.retrieved_at,
                )
            else:
                session.execute(
                    delete(MarketDataProvenance).where(MarketDataProvenance.symbol == "TCS")
                )
                session.commit()
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


def test_backtest_trigger_accepts_custom_date_range_and_capital():
    """A caller-supplied date_from/date_to/initial_capital round-trips into the persisted
    BacktestResult and the response, replacing the endpoint's own defaults rather than being
    ignored -- the direct fix for "no way to configure or see what a backtest used." Real
    backtest, real sandbox, real TCS data, polled to completion (~60-90s), same pattern as
    test_strategy_list_detail_version_backtest_and_promote_end_to_end above."""
    from src.core.config import get_settings
    from src.data.datalake.query import DataLake

    ids = _create_fixture_rows()
    user_id, account_id, strategy_id, version_id = ids
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)

    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    lake_latest = lake.latest_date("TCS")
    assert lake_latest is not None
    custom_date_to = lake_latest
    custom_date_from = custom_date_to.fromordinal(custom_date_to.toordinal() - 200)
    custom_capital = 250_000.0

    try:
        trigger_response = client.post(
            f"/api/v1/strategies/{strategy_id}/backtest",
            headers=headers,
            json={
                "date_from": custom_date_from.isoformat(),
                "date_to": custom_date_to.isoformat(),
                "initial_capital": custom_capital,
            },
        )
        assert trigger_response.status_code == 202
        job_id = trigger_response.json()["job_id"]

        deadline = time.monotonic() + 150
        job_status = None
        while time.monotonic() < deadline:
            job_response = client.get(f"/api/v1/strategies/backtests/jobs/{job_id}/status")
            job_status = job_response.json()
            if job_status["status"] != "Running":
                break
            time.sleep(3)
        assert job_status is not None and job_status["status"] == "Completed", job_status
        backtest_id = job_status["backtest_result_id"]

        detail = client.get(f"/api/v1/strategies/{strategy_id}").json()
        summary = next(b for b in detail["backtests"] if b["id"] == backtest_id)
        assert summary["date_from"] == custom_date_from.isoformat()
        assert summary["date_to"] == custom_date_to.isoformat()
        assert summary["initial_capital"] == custom_capital

        with get_session() as session:
            result_row = session.get(BacktestResult, uuid.UUID(backtest_id))
            assert result_row is not None
            assert result_row.date_from == custom_date_from
            assert result_row.date_to == custom_date_to
            assert float(result_row.initial_capital) == custom_capital
    finally:
        _cleanup_fixture_rows(*ids)
        cleanup_user(admin_id)


def test_backtest_trigger_rejects_date_to_beyond_lake_coverage():
    from src.core.config import get_settings
    from src.data.datalake.query import DataLake

    ids = _create_fixture_rows()
    user_id, account_id, strategy_id, version_id = ids
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)

    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    lake_latest = lake.latest_date("TCS")
    assert lake_latest is not None
    beyond = lake_latest.fromordinal(lake_latest.toordinal() + 1)

    try:
        response = client.post(
            f"/api/v1/strategies/{strategy_id}/backtest",
            headers=headers,
            json={"date_to": beyond.isoformat()},
        )
        assert response.status_code == 409
        assert "beyond the last ingested date" in response.json()["detail"]
    finally:
        _cleanup_fixture_rows(*ids)
        cleanup_user(admin_id)


def test_backtest_trigger_rejects_date_from_not_before_date_to():
    ids = _create_fixture_rows()
    user_id, account_id, strategy_id, version_id = ids
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)

    try:
        response = client.post(
            f"/api/v1/strategies/{strategy_id}/backtest",
            headers=headers,
            json={"date_from": "2024-06-01", "date_to": "2024-01-01"},
        )
        assert response.status_code == 400
        assert "must be before" in response.json()["detail"]
    finally:
        _cleanup_fixture_rows(*ids)
        cleanup_user(admin_id)


def test_backtest_trigger_rejects_non_positive_initial_capital():
    ids = _create_fixture_rows()
    user_id, account_id, strategy_id, version_id = ids
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)

    try:
        response = client.post(
            f"/api/v1/strategies/{strategy_id}/backtest",
            headers=headers,
            json={"initial_capital": 0},
        )
        # Pydantic's own gt=0 validation, before any DB/lake work.
        assert response.status_code == 422
    finally:
        _cleanup_fixture_rows(*ids)
        cleanup_user(admin_id)


def test_strategy_logic_and_research_context_and_option_fields_serialize_rel_044():
    """REL-044: real Strategy/StrategyVersion columns (entry/exit/stop/take-profit/position-
    sizing/confidence, research_context/market_context, option_legs/option_expiry/
    option_rationale, current_version_validation_status) round-trip through GET /strategies and
    GET /strategies/{id} -- a direct-insert test (no real LangGraph run needed) matching this
    file's own established convention, since _persist_strategy_progress's own persistence logic
    is already covered separately by tests/integration/test_persist_strategy_progress.py."""
    ids = _create_fixture_rows()
    user_id, account_id, strategy_id, version_id = ids

    try:
        with get_session() as session:
            strategy = session.get(Strategy, strategy_id)
            assert strategy is not None
            strategy.entry_conditions = "close crosses above 20-day SMA"
            strategy.exit_conditions = "close crosses below 20-day SMA"
            strategy.stop_loss = "2% below entry"
            strategy.take_profit = "5% above entry"
            strategy.position_sizing = "1% account risk per trade"
            strategy.confidence_score = 0.68
            strategy.research_context = {
                "market_regime": "Risk-On",
                "priority_sectors": ["IT", "Auto"],
                "strategy_themes": ["Momentum breakout"],
                "risk_tolerance": "Medium",
                "expected_outcomes": "2-3 high-conviction setups",
            }
            strategy.market_context = {
                "sector_rankings": ["IT", "Auto", "FMCG"],
                "volatility_assessment": "India VIX subdued",
                "macro_outlook": "No major event risk this week",
                "confidence_score": 0.7,
                "insights": ["FII flows turned net positive"],
            }
            version = session.get(StrategyVersion, version_id)
            assert version is not None
            version.option_legs = None
            version.option_expiry = None
            version.option_rationale = None
            session.commit()

        list_response = client.get("/api/v1/strategies")
        assert list_response.status_code == 200
        row = next(s for s in list_response.json() if s["id"] == str(strategy_id))
        assert row["confidence_score"] == 0.68
        assert row["entry_conditions"] == "close crosses above 20-day SMA"
        assert row["research_context"]["market_regime"] == "Risk-On"
        assert row["market_context"]["macro_outlook"] == "No major event risk this week"
        assert row["current_version_validation_status"] == "Passed"  # set by _create_fixture_rows

        detail_response = client.get(f"/api/v1/strategies/{strategy_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["stop_loss"] == "2% below entry"
        assert detail["current_version_validation_status"] == "Passed"
        version_summary = next(v for v in detail["versions"] if v["id"] == str(version_id))
        assert version_summary["option_legs"] is None
        assert version_summary["option_rationale"] is None

        # Pre-migration-shaped row: every new field genuinely null, not fabricated.
        no_logic_ids = _create_fixture_rows()
        try:
            no_logic_detail = client.get(f"/api/v1/strategies/{no_logic_ids[2]}").json()
            assert no_logic_detail["entry_conditions"] is None
            assert no_logic_detail["research_context"] is None
            assert no_logic_detail["confidence_score"] is None
        finally:
            _cleanup_fixture_rows(*no_logic_ids)
    finally:
        _cleanup_fixture_rows(*ids)


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


def _run_real_backtest(strategy_id: uuid.UUID, headers: dict[str, str]) -> str:
    """Shared with the end-to-end test above: triggers and polls a real vectorbt run to
    completion (~60-90s) and returns the resulting backtest_result_id."""
    trigger_response = client.post(f"/api/v1/strategies/{strategy_id}/backtest", headers=headers)
    assert trigger_response.status_code == 202
    job_id = trigger_response.json()["job_id"]

    deadline = time.monotonic() + 150
    job_status = None
    while time.monotonic() < deadline:
        job_response = client.get(f"/api/v1/strategies/backtests/jobs/{job_id}/status")
        job_status = job_response.json()
        if job_status["status"] != "Running":
            break
        time.sleep(3)

    assert job_status is not None and job_status["status"] == "Completed", job_status
    backtest_id: str = job_status["backtest_result_id"]
    assert backtest_id is not None
    return backtest_id


def test_cross_strategy_backtest_views_rel_040():
    """REL-040: backtest_count, the 8 hidden AI-pipeline fields, /backtests/latest,
    /backtests/compare (honest omission + the 6-id cap), /backtests/{id}/monte-carlo (bucket-sum
    + 409-under-2-trades gate), and /backtests/{id}/export -- one real vectorbt run for strategy A
    (so equity_curve/trades/Monte Carlo are all real), plus a directly-inserted second
    BacktestResult row for strategy B (no equity curve, no trades) so /latest and /compare have a
    genuine second strategy to combine without paying for a second ~60-90s sandbox run."""
    ids_a = _create_fixture_rows()
    user_a, account_a, strategy_a, version_a = ids_a
    ids_b = _create_fixture_rows()
    user_b, account_b, strategy_b, version_b = ids_b
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)
    backtest_b_id = uuid.uuid4()

    try:
        backtest_a_id = uuid.UUID(_run_real_backtest(strategy_a, headers))

        # REL-005/REL-040: the 8 AI-pipeline columns are real DB columns, populated by the
        # Evaluator/Optimization/RiskManager/Deployment agents elsewhere, not by the backtest
        # endpoint itself -- set them directly here to prove the *serialization* path works.
        with get_session() as session:
            result_a = session.get(BacktestResult, backtest_a_id)
            assert result_a is not None
            result_a.evaluation_verdict = "Pass"
            result_a.evaluation_failure_reasons = None
            result_a.optimization_best_params = {"fast": 5.0, "slow": 20.0}
            result_a.optimization_robustness_score = 0.82
            result_a.risk_assessment_passed = True
            result_a.risk_assessment_notes = "Within max drawdown limit."
            result_a.deployment_recommendation = "Approve"
            result_a.deployment_rationale = "Sharpe and drawdown both pass gates."
            session.add(result_a)
            session.commit()

            session.add(
                BacktestResult(
                    id=backtest_b_id,
                    strategy_version_id=version_b,
                    date_from=date(2025, 1, 1),
                    date_to=date(2025, 12, 31),
                    initial_capital=100000.00,
                    sharpe_ratio=1.1,
                    total_trades=0,
                    trades=[],
                    evaluation_verdict="Fail",
                    evaluation_failure_reasons=["Sharpe ratio below 1.5 threshold"],
                    risk_assessment_passed=False,
                    risk_assessment_notes="Too few trades to assess risk.",
                )
            )
            session.commit()

        # backtest_count (REL-040): one real backtest each, reflected without an N+1 query.
        list_response = client.get("/api/v1/strategies")
        assert list_response.status_code == 200
        by_id = {s["id"]: s for s in list_response.json()}
        assert by_id[str(strategy_a)]["backtest_count"] == 1
        assert by_id[str(strategy_b)]["backtest_count"] == 1

        # Hidden fields now visible via the existing detail endpoint.
        detail_a = client.get(f"/api/v1/strategies/{strategy_a}").json()
        backtest_summary_a = next(b for b in detail_a["backtests"] if b["id"] == str(backtest_a_id))
        assert backtest_summary_a["evaluation_verdict"] == "Pass"
        assert backtest_summary_a["deployment_recommendation"] == "Approve"
        assert backtest_summary_a["optimization_best_params"] == {"fast": 5.0, "slow": 20.0}

        # /backtests/latest: both strategies present, each tagged with its own strategy_id/name.
        latest_response = client.get("/api/v1/strategies/backtests/latest")
        assert latest_response.status_code == 200
        latest_by_strategy = {row["strategy_id"]: row for row in latest_response.json()}
        assert latest_by_strategy[str(strategy_a)]["id"] == str(backtest_a_id)
        assert (
            latest_by_strategy[str(strategy_a)]["strategy_name"] == "strategies-api-test-strategy"
        )
        assert latest_by_strategy[str(strategy_b)]["id"] == str(backtest_b_id)
        assert latest_by_strategy[str(strategy_b)]["evaluation_verdict"] == "Fail"

        # /backtests/compare: real equity curve for A, honestly empty for the direct-inserted B,
        # and a nonexistent id in the middle is silently omitted rather than failing the batch.
        compare_response = client.get(
            "/api/v1/strategies/backtests/compare",
            params={"ids": f"{backtest_a_id},{uuid.uuid4()},{backtest_b_id}"},
        )
        assert compare_response.status_code == 200
        compare_rows = compare_response.json()
        assert len(compare_rows) == 2
        compare_by_id = {row["id"]: row for row in compare_rows}
        assert len(compare_by_id[str(backtest_a_id)]["equity_curve"]) > 200
        assert compare_by_id[str(backtest_b_id)]["equity_curve"] == []

        # 422 once more than 6 ids are requested, before any DB resolution happens.
        too_many_ids = ",".join(str(uuid.uuid4()) for _ in range(7))
        capped_response = client.get(
            "/api/v1/strategies/backtests/compare", params={"ids": too_many_ids}
        )
        assert capped_response.status_code == 422

        # /monte-carlo: real trade-return distribution for A (>=2 trades) resamples cleanly;
        # zero-trade B hits the same 409 gate the trades/walk-forward endpoints already use.
        mc_response = client.get(f"/api/v1/strategies/backtests/{backtest_a_id}/monte-carlo")
        if backtest_summary_a["total_trades"] and backtest_summary_a["total_trades"] >= 2:
            assert mc_response.status_code == 200
            mc = mc_response.json()
            assert sum(mc["bucket_counts"]) == mc["n_simulations"]
            assert len(mc["bucket_edges"]) == len(mc["bucket_counts"]) + 1
            assert mc["percentile_95_max_drawdown"] >= 0
        else:
            assert mc_response.status_code == 409

        mc_empty_response = client.get(f"/api/v1/strategies/backtests/{backtest_b_id}/monte-carlo")
        assert mc_empty_response.status_code == 409

        # /export: real per-trade CSV/NDJSON report for A.
        csv_response = client.get(f"/api/v1/strategies/backtests/{backtest_a_id}/export")
        assert csv_response.status_code == 200
        assert csv_response.headers["content-type"].startswith("text/csv")
        assert "entry_date" in csv_response.text.splitlines()[0]

        ndjson_response = client.get(
            f"/api/v1/strategies/backtests/{backtest_a_id}/export", params={"format": "ndjson"}
        )
        assert ndjson_response.status_code == 200
        if backtest_summary_a["total_trades"]:
            first_line = ndjson_response.text.splitlines()[0]
            assert "entry_date" in first_line
    finally:
        with get_session() as session:
            session.query(BacktestResult).filter(BacktestResult.id == backtest_b_id).delete()
            session.commit()
        _cleanup_fixture_rows(*ids_a)
        _cleanup_fixture_rows(*ids_b)
        cleanup_user(admin_id)


def _write_equity_curve_parquet(backtest_id: uuid.UUID, equities: list[float]) -> None:
    """Same real path/schema src.engine.sandbox.backtest_runner.write_equity_curve_parquet uses
    in production -- writing it directly here (rather than via a real ~60-90s sandbox run) lets
    the correlation endpoint be exercised against a real, readable parquet file with a known
    return series, matching test_cross_strategy_backtest_views_rel_040's own precedent of
    directly inserting a BacktestResult row instead of always paying for a real sandbox run."""
    root = get_settings().data_lake_root.parent / "equity_curves"
    root.mkdir(parents=True, exist_ok=True)
    dates = [f"2026-08-{i + 1:02d}" for i in range(len(equities))]
    pl.DataFrame({"date": dates, "equity": equities}).write_parquet(root / f"{backtest_id}.parquet")


def test_backtest_compare_correlation_and_wider_monte_carlo_percentiles_rel_069():
    """REL-069: GET /backtests/compare/correlation (real pairwise return correlation, honest
    None for insufficient-overlap/zero-curve pairs, same 6-id cap + omission convention as
    /backtests/compare) and the extended /monte-carlo response (P50/P75/P90/P95/P99, all derived
    from the same simulated_max_drawdowns array the existing P95 field already used)."""
    ids_a = _create_fixture_rows()
    ids_b = _create_fixture_rows()
    rising = [100.0, 102.0, 101.0, 105.0, 103.0, 108.0, 106.0, 110.0, 109.0, 112.0, 115.0]
    inverted = [100.0]
    for i in range(1, len(rising)):
        pct = (rising[i] - rising[i - 1]) / rising[i - 1]
        inverted.append(inverted[-1] * (1 - pct))
    backtest_up_id = uuid.uuid4()
    backtest_down_id = uuid.uuid4()
    backtest_empty_id = uuid.uuid4()

    try:
        with get_session() as session:
            session.add(
                BacktestResult(
                    id=backtest_up_id,
                    strategy_version_id=ids_a[3],
                    date_from=date(2025, 1, 1),
                    date_to=date(2025, 12, 31),
                    initial_capital=100000.00,
                    total_trades=4,
                    trades=[
                        {"return_pct": 0.05},
                        {"return_pct": -0.03},
                        {"return_pct": 0.02},
                        {"return_pct": 0.01},
                    ],
                    equity_curve_path=str(
                        get_settings().data_lake_root.parent
                        / "equity_curves"
                        / f"{backtest_up_id}.parquet"
                    ),
                )
            )
            session.add(
                BacktestResult(
                    id=backtest_down_id,
                    strategy_version_id=ids_b[3],
                    date_from=date(2025, 1, 1),
                    date_to=date(2025, 12, 31),
                    initial_capital=100000.00,
                    total_trades=0,
                    trades=[],
                    equity_curve_path=str(
                        get_settings().data_lake_root.parent
                        / "equity_curves"
                        / f"{backtest_down_id}.parquet"
                    ),
                )
            )
            session.add(
                BacktestResult(
                    id=backtest_empty_id,
                    strategy_version_id=ids_a[3],
                    date_from=date(2025, 1, 1),
                    date_to=date(2025, 12, 31),
                    initial_capital=100000.00,
                    total_trades=0,
                    trades=[],
                )
            )
            session.commit()
        _write_equity_curve_parquet(backtest_up_id, rising)
        _write_equity_curve_parquet(backtest_down_id, inverted)

        response = client.get(
            "/api/v1/strategies/backtests/compare/correlation",
            params={
                "ids": f"{backtest_up_id},{backtest_down_id},{backtest_empty_id},{uuid.uuid4()}"
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["run_ids"]) == 3  # the random 4th id is silently omitted
        idx = {rid: i for i, rid in enumerate(body["run_ids"])}
        matrix = body["matrix"]

        assert matrix[idx[str(backtest_up_id)]][idx[str(backtest_up_id)]] == 1.0
        # up and down are exact sign-inverted return series -> perfectly anti-correlated.
        down_corr = matrix[idx[str(backtest_up_id)]][idx[str(backtest_down_id)]]
        assert down_corr < -0.99
        # symmetric.
        assert down_corr == matrix[idx[str(backtest_down_id)]][idx[str(backtest_up_id)]]
        # the empty curve has no real points at all -> None, never a fabricated 0.
        assert matrix[idx[str(backtest_up_id)]][idx[str(backtest_empty_id)]] is None

        too_many_ids = ",".join(str(uuid.uuid4()) for _ in range(7))
        capped_response = client.get(
            "/api/v1/strategies/backtests/compare/correlation", params={"ids": too_many_ids}
        )
        assert capped_response.status_code == 422

        mc_response = client.get(f"/api/v1/strategies/backtests/{backtest_up_id}/monte-carlo")
        assert mc_response.status_code == 200
        mc = mc_response.json()
        assert (
            0
            <= mc["percentile_50_max_drawdown"]
            <= mc["percentile_75_max_drawdown"]
            <= mc["percentile_90_max_drawdown"]
            <= mc["percentile_95_max_drawdown"]
            <= mc["percentile_99_max_drawdown"]
        )
    finally:
        with get_session() as session:
            for bid in (backtest_up_id, backtest_down_id, backtest_empty_id):
                session.query(BacktestResult).filter(BacktestResult.id == bid).delete()
            session.commit()
        for bid in (backtest_up_id, backtest_down_id):
            path = get_settings().data_lake_root.parent / "equity_curves" / f"{bid}.parquet"
            path.unlink(missing_ok=True)
        _cleanup_fixture_rows(*ids_a)
        _cleanup_fixture_rows(*ids_b)


# --- Suggestions (REL-048/049) -----------------------------------------------------------------


def test_submit_and_list_suggestions_round_trip():
    """Submitting a suggestion is open to any authenticated user, including the most restricted
    real role -- ROLE_READ_ONLY_AUDITOR here proves that deliberately, not just a convenient
    choice of role to test with."""
    ids = _create_fixture_rows()
    strategy_id = ids[2]
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    suggestion_id = None
    try:
        submit_response = client.post(
            f"/api/v1/strategies/{strategy_id}/suggestions",
            json={"text": "Widen the stop-loss slightly to reduce whipsaw exits."},
            headers=auth_header(token),
        )
        assert submit_response.status_code == 201
        body = submit_response.json()
        assert body["status"] == "Pending"
        assert body["strategy_id"] == str(strategy_id)
        assert body["submitted_by_user_id"] == str(user_id)
        assert body["ai_verdict"] is None
        suggestion_id = uuid.UUID(body["id"])

        empty_submit = client.post(
            f"/api/v1/strategies/{strategy_id}/suggestions",
            json={"text": "   "},
            headers=auth_header(token),
        )
        assert empty_submit.status_code == 422

        list_response = client.get(f"/api/v1/strategies/{strategy_id}/suggestions")
        assert list_response.status_code == 200
        listed = list_response.json()
        assert any(s["id"] == str(suggestion_id) for s in listed)
    finally:
        if suggestion_id is not None:
            with get_session() as session:
                session.query(StrategySuggestion).filter(
                    StrategySuggestion.id == suggestion_id
                ).delete()
                session.commit()
        _cleanup_fixture_rows(*ids)
        cleanup_user(user_id)


def test_suggestion_review_requires_authentication():
    response = client.post(f"/api/v1/strategies/{uuid.uuid4()}/suggestions/{uuid.uuid4()}/review")
    assert response.status_code == 401


def test_suggestion_review_requires_the_gated_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            f"/api/v1/strategies/{uuid.uuid4()}/suggestions/{uuid.uuid4()}/review",
            headers=auth_header(token),
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


def test_suggestion_review_end_to_end_real_llm():
    """REL-048's real deliverable: submit a suggestion against a real strategy, trigger a real
    AI review (real LLM call, no mocking, matching this file's own established convention), and
    poll to completion. Asserted honestly per the plan's own convention -- the terminal state is
    whichever the real LLM actually returns (Applied with a real resulting_version_id, or
    Rejected with real reasoning), not forced to always expect one outcome. Slow: a full
    regeneration re-enters the real agent pipeline (multiple real LLM calls, a real sandboxed
    backtest) -- same order of magnitude as this file's own real backtest tests."""
    ids = _create_fixture_rows()
    strategy_id = ids[2]
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    suggestion_id = None
    try:
        submit_response = client.post(
            f"/api/v1/strategies/{strategy_id}/suggestions",
            json={"text": "Tighten the stop-loss to reduce max drawdown."},
            headers=auth_header(admin_token),
        )
        assert submit_response.status_code == 201
        suggestion_id = uuid.UUID(submit_response.json()["id"])

        trigger_response = client.post(
            f"/api/v1/strategies/{strategy_id}/suggestions/{suggestion_id}/review",
            headers=auth_header(admin_token),
        )
        assert trigger_response.status_code == 202
        job_id = trigger_response.json()["job_id"]

        deadline = time.monotonic() + 300
        job_status = None
        while time.monotonic() < deadline:
            job_response = client.get(f"/api/v1/strategies/suggestions/jobs/{job_id}/status")
            job_status = job_response.json()
            if job_status["status"] != "Running":
                break
            time.sleep(5)

        assert job_status is not None and job_status["status"] == "Completed", job_status
        suggestion = job_status["suggestion"]
        assert suggestion["ai_verdict"] is not None
        assert suggestion["ai_reasoning"] is not None
        assert suggestion["status"] in ("Applied", "Rejected")
        if suggestion["status"] == "Applied":
            assert suggestion["resulting_version_id"] is not None
    finally:
        # A real regeneration can retry python_code_generator several times before validation
        # passes (or exhausts its retries) -- each attempt is its own real StrategyVersion row,
        # not just the one `resulting_version_id` names, so every version this strategy now has
        # (beyond the one _create_fixture_rows itself seeded) must be swept up before
        # _cleanup_fixture_rows' own Strategy delete, or its FK constraint 409s on cleanup.
        with get_session() as session:
            if suggestion_id is not None:
                session.query(StrategySuggestion).filter(
                    StrategySuggestion.id == suggestion_id
                ).delete()
            version_ids = [
                row[0]
                for row in session.query(StrategyVersion.id)
                .filter(StrategyVersion.strategy_id == strategy_id, StrategyVersion.id != ids[3])
                .all()
            ]
            if version_ids:
                session.query(BacktestResult).filter(
                    BacktestResult.strategy_version_id.in_(version_ids)
                ).delete(synchronize_session=False)
                session.query(StrategyVersion).filter(StrategyVersion.id.in_(version_ids)).delete(
                    synchronize_session=False
                )
                strategy_row = session.get(Strategy, strategy_id)
                if strategy_row is not None and strategy_row.current_version_id in version_ids:
                    strategy_row.current_version_id = ids[3]
            session.commit()
        _cleanup_fixture_rows(*ids)
        cleanup_user(admin_id)


# --- Manual registration / metadata update (API-041/042, REL-062) --------------------------


def test_create_strategy_requires_the_gated_role():
    response = client.post(
        "/api/v1/strategies",
        json={"name": "manual-strategy", "asset_class": "Equity", "style": "Swing"},
    )
    assert response.status_code == 401


def test_create_strategy_registers_a_hypothesis_against_the_real_paper_account():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)
    marker = f"manual-strategy-{uuid.uuid4().hex[:8]}"
    strategy_id = None
    try:
        response = client.post(
            "/api/v1/strategies",
            json={
                "name": marker,
                "hypothesis": "Manually registered hypothesis, no LangGraph run behind it.",
                "asset_class": "Equity",
                "style": "Swing",
                "universe": ["TCS"],
            },
            headers=headers,
        )
        assert response.status_code == 201
        body = response.json()
        strategy_id = uuid.UUID(body["id"])
        assert body["name"] == marker
        assert body["status"] == "Ideation"
        assert body["max_drawdown_limit"] == 15.0

        with get_session() as session:
            row = session.get(Strategy, strategy_id)
            assert row is not None
            assert row.created_by_agent == "Human"
            assert row.account_id is not None
    finally:
        if strategy_id is not None:
            with get_session() as session:
                session.query(Strategy).filter(Strategy.id == strategy_id).delete()
                session.commit()
        cleanup_user(admin_id)


def test_create_strategy_rejects_an_unknown_asset_class():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            "/api/v1/strategies",
            json={"name": "bad-strategy", "asset_class": "Crypto", "style": "Swing"},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 422
    finally:
        cleanup_user(admin_id)


def test_update_strategy_requires_the_gated_role():
    ids = _create_fixture_rows()
    try:
        response = client.patch(
            f"/api/v1/strategies/{ids[2]}", json={"hypothesis": "unauthorized update"}
        )
        assert response.status_code == 401
    finally:
        _cleanup_fixture_rows(*ids)


def test_update_strategy_patches_only_the_provided_fields():
    ids = _create_fixture_rows()
    _, _, strategy_id, _ = ids
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.patch(
            f"/api/v1/strategies/{strategy_id}",
            json={"hypothesis": "revised hypothesis text"},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["hypothesis"] == "revised hypothesis text"
        # Untouched fields (set via _create_fixture_rows) must survive a partial PATCH.
        assert body["name"] == "strategies-api-test-strategy"
        assert body["universe"] == ["TCS"]
    finally:
        _cleanup_fixture_rows(*ids)
        cleanup_user(admin_id)


def test_update_strategy_404s_for_an_unknown_strategy():
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.patch(
            f"/api/v1/strategies/{uuid.uuid4()}",
            json={"hypothesis": "x"},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 404
    finally:
        cleanup_user(admin_id)
