"""Seeds the three real fixture strategies frontend/cypress/e2e/strategies_review_panel.cy.ts
depends on (REL-044/045/046, and a later bugfix pass): a real F&O strategy with every new
logic/research-context/option field populated, plus a real BacktestResult with the AI-pipeline
verdict fields set; a separate, uniquely-named real pre-migration-shaped strategy (every new
field left honestly None); and a third, uniquely-named, zero-backtest strategy with real working
code, dedicated to the one spec test that genuinely triggers a live backtest through the UI (kept
separate from the F&O fixture above so that test's own real, verdict-less new backtest row never
becomes the "most recent" one other tests assert Pass/Approve against).

Both are uniquely named specifically so the Cypress spec's `cy.contains(name)` can never
accidentally land on a different row than the one it verified via a direct API call first --
every other real strategy in a long-lived dev database tends to share names across many past test
runs (e.g. "strategies-api-nouniv-strategy"), which is fine for those tests' own purposes but
would make an unambiguous by-name click unreliable here.

Idempotent by REUSE, not by destroy-and-recreate (REL-069 fix): the F&O fixture is also the real
target of the spec's own "submits a suggestion" / "AI review resolves a suggestion" tests, which
genuinely re-enter REL-048's Suggestion Regeneration pipeline (a real LLM call) and mutate the
strategy's own hypothesis/entry_conditions/confidence_score/asset_class/style/status/universe in
place -- exactly as that feature is designed to do in production. A prior version of this script
unconditionally deleted and recreated both fixtures by name on every run, which silently discarded
that same real, legitimate agent-driven progress every time -- not a reset, a regression each run.
Now: if a fixture with the target name already exists, it's left alone (whatever state real agent
research/analysis/backtest activity has since brought it to) rather than being destroyed. Only a
genuinely missing fixture is created fresh. Pass `--reset` to force a full delete-and-recreate back
to the canonical starting values (e.g. after the row has drifted into a state no longer useful as a
starting point, or to bootstrap a brand-new dev DB) -- an explicit, deliberate action, not the
default. Run via:
`docker exec tradingos-app python scripts/seed_strategies_cypress_fixtures.py [--reset]` (or
`docker compose run --rm app python scripts/seed_strategies_cypress_fixtures.py [--reset]` locally).
"""

import sys
import uuid
from datetime import date, timedelta
from decimal import Decimal

from src.core.db import get_session
from src.models.account import Account
from src.models.strategy import BacktestResult, Strategy, StrategySuggestion, StrategyVersion
from src.models.user import User

STRATEGY_NAME = "cypress-rel044-fno-fixture-strategy"
PREMIGRATION_STRATEGY_NAME = "cypress-rel044-premigration-fixture-strategy"
# Bug fix (real Strategy Detail page refresh-after-completion test): a dedicated, uniquely-named,
# zero-backtest fixture with REAL working strategy code (the same TCS 5/20 SMA crossover
# tests/integration/test_strategies_api.py's own _STRATEGY_CODE uses) for the one Cypress test
# that genuinely triggers a live ~60-90s backtest through the real UI button. Deliberately
# separate from STRATEGY_NAME above -- that fixture's own "most recent backtest" is depended on
# by several other tests to always carry the real agent-pipeline verdict fields (Pass/Approve);
# triggering a direct (non-pipeline) backtest against it would add a newer, verdict-less row and
# silently break those tests on every future run of this spec.
LIVE_TRIGGER_STRATEGY_NAME = "cypress-bugfix-live-trigger-fixture-strategy"
_LIVE_TRIGGER_STRATEGY_CODE = """
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


# REL-044: `total_trades` (BacktestResult's own persisted metrics column) and the real per-trade
# ledger (`trades`, REL-022) are two independently-populated columns -- see this fixture's own
# consuming spec's `findBacktestWithRealTrades` docstring for the same caveat. A fixture with
# total_trades=14 but no `trades` array makes the real /monte-carlo endpoint (which reads
# exclusively from `trades`, not `total_trades`) honestly report "not enough data", which is
# real/correct backend behaviour but not what this fixture is meant to exercise. 8 wins / 6
# losses to roughly match win_rate=58.00 below.
def _fno_fixture_trades() -> list[dict[str, float | str]]:
    trades = []
    for i in range(14):
        is_win = i < 8
        entry = date(2025, 1, 6) + timedelta(days=i * 24)
        exit_ = entry + timedelta(days=3)
        trades.append(
            {
                "entry_date": entry.isoformat(),
                "exit_date": exit_.isoformat(),
                "side": "buy",
                "size": 1.0,
                "entry_price": 3100.0 + i * 5,
                "exit_price": 3100.0 + i * 5 + (42.0 if is_win else -28.0),
                "pnl": 42.0 if is_win else -28.0,
                "return_pct": 1.35 if is_win else -0.9,
            }
        )
    return trades


def _delete_existing(name: str) -> None:
    with get_session() as session:
        for strategy in session.query(Strategy).filter(Strategy.name == name).all():
            # REL-048: StrategySuggestion FKs onto both strategies.id and (nullable)
            # strategy_versions.id -- must go before BacktestResult/StrategyVersion/Strategy
            # below, same FK-order lesson this script's own _seed_fno_fixture already learned for
            # Account/User.
            session.query(StrategySuggestion).filter(
                StrategySuggestion.strategy_id == strategy.id
            ).delete(synchronize_session=False)
            session.query(BacktestResult).filter(
                BacktestResult.strategy_version_id.in_(
                    session.query(StrategyVersion.id).filter(
                        StrategyVersion.strategy_id == strategy.id
                    )
                )
            ).delete(synchronize_session=False)
            session.query(StrategyVersion).filter(
                StrategyVersion.strategy_id == strategy.id
            ).delete(synchronize_session=False)
            account_id = strategy.account_id
            session.delete(strategy)
            session.flush()
            account = session.get(Account, account_id)
            if account is not None:
                user_id = account.user_id
                session.delete(account)
                session.flush()
                session.query(User).filter(User.id == user_id).delete()
        session.commit()


def _seed_fno_fixture() -> None:
    user_id, account_id, strategy_id, version_id, backtest_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"cypress-rel044-{user_id}@example.invalid",
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
            name=STRATEGY_NAME,
            hypothesis=(
                "Bull call spread on RELIANCE ahead of quarterly earnings, riding elevated IV "
                "crush post-results."
            ),
            asset_class="F&O",
            style="Swing",
            status="Backtesting",
            max_drawdown_limit=Decimal("15.00"),
            universe=["RELIANCE"],
            entry_conditions="IV rank below 30 and close above the 20-day high",
            exit_conditions=(
                "3 trading days before expiry, or 50% of max theoretical profit reached"
            ),
            stop_loss="Close below the entry-day low",
            take_profit="50% of max theoretical profit",
            position_sizing="1 lot per Rs 5,00,000 of allocated capital",
            confidence_score=Decimal("0.720"),
            research_context={
                "market_regime": "Risk-On",
                "priority_sectors": ["Energy", "IT"],
                "strategy_themes": ["Earnings-driven volatility"],
                "risk_tolerance": "Medium",
                "expected_outcomes": "2-3 high-conviction defined-risk options structures",
            },
            market_context={
                "sector_rankings": ["Energy", "IT", "Banking"],
                "volatility_assessment": "India VIX elevated into earnings week",
                "macro_outlook": "RBI on hold, no major macro event risk this week",
                "confidence_score": 0.68,
                "insights": ["FII flows turned net positive for the third consecutive session"],
            },
        )
        session.add(strategy)
        session.flush()
        version = StrategyVersion(
            id=version_id,
            strategy_id=strategy_id,
            version_no=1,
            python_code="def run_backtest(data, config):\n    return {}\n",
            validation_status="Passed",
            validator_feedback=(
                "Static safety check passed; no banned calls/imports; AST-parseable."
            ),
            option_legs=[
                {
                    "symbol": "RELIANCE24AUG3000CE",
                    "option_type": "CE",
                    "strike": 3000.0,
                    "side": "buy",
                    "quantity": 1,
                },
                {
                    "symbol": "RELIANCE24AUG3200CE",
                    "option_type": "CE",
                    "strike": 3200.0,
                    "side": "sell",
                    "quantity": 1,
                },
            ],
            option_expiry=date(2026, 8, 28),
            option_rationale=(
                "Bull call spread caps both cost and risk while keeping upside exposure into "
                "earnings."
            ),
        )
        session.add(version)
        session.flush()
        strategy.current_version_id = version_id

        session.add(
            BacktestResult(
                id=backtest_id,
                strategy_version_id=version_id,
                date_from=date(2025, 1, 1),
                date_to=date(2025, 12, 31),
                initial_capital=Decimal("100000.00"),
                sharpe_ratio=Decimal("1.82"),
                sortino_ratio=Decimal("2.10"),
                calmar_ratio=Decimal("1.45"),
                max_drawdown=Decimal("-0.082"),
                cagr=Decimal("0.184"),
                win_rate=Decimal("58.00"),
                profit_factor=Decimal("1.65"),
                expectancy=Decimal("420.50"),
                total_trades=14,
                trades=_fno_fixture_trades(),
                evaluation_verdict="Pass",
                optimization_best_params={"fast": 5.0, "slow": 20.0},
                optimization_robustness_score=Decimal("0.71"),
                risk_assessment_passed=True,
                risk_assessment_notes=(
                    "Within max drawdown limit; correlation check isolated-only per known gap."
                ),
                deployment_recommendation="Approve",
                deployment_rationale=(
                    "Sharpe and drawdown both clear the gate; recommend Paper Trading promotion."
                ),
            )
        )
        session.commit()


def _seed_premigration_fixture() -> None:
    user_id, account_id, strategy_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"cypress-rel044-premigration-{user_id}@example.invalid",
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
                name=PREMIGRATION_STRATEGY_NAME,
                hypothesis="A real strategy predating REL-044's logic-capture migration.",
                asset_class="Equity",
                style="Intraday",
                status="Ideation",
                max_drawdown_limit=Decimal("15.00"),
            )
        )
        session.commit()


def _seed_live_trigger_fixture() -> None:
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
                email=f"cypress-bugfix-live-trigger-{user_id}@example.invalid",
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
            name=LIVE_TRIGGER_STRATEGY_NAME,
            hypothesis="5/20 SMA crossover on TCS -- real, working code, seeded with zero "
            "backtests so a real UI-triggered run has something to actually prove.",
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
                python_code=_LIVE_TRIGGER_STRATEGY_CODE,
                validation_status="Passed",
            )
        )
        strategy.current_version_id = version_id
        session.commit()


def _exists(name: str) -> bool:
    with get_session() as session:
        return session.query(Strategy).filter(Strategy.name == name).first() is not None


def main() -> None:
    reset = "--reset" in sys.argv

    if reset:
        _delete_existing(STRATEGY_NAME)
        _delete_existing(PREMIGRATION_STRATEGY_NAME)
        _delete_existing(LIVE_TRIGGER_STRATEGY_NAME)

    if _exists(STRATEGY_NAME):
        print(
            f"{STRATEGY_NAME}: already exists, reusing its real current state as-is "
            f"(pass --reset to force a clean recreate)."
        )
    else:
        _seed_fno_fixture()
        print(f"{STRATEGY_NAME}: created fresh.")

    if _exists(PREMIGRATION_STRATEGY_NAME):
        print(
            f"{PREMIGRATION_STRATEGY_NAME}: already exists, reusing (pass --reset to force "
            f"a clean recreate)."
        )
    else:
        _seed_premigration_fixture()
        print(f"{PREMIGRATION_STRATEGY_NAME}: created fresh.")

    if _exists(LIVE_TRIGGER_STRATEGY_NAME):
        print(
            f"{LIVE_TRIGGER_STRATEGY_NAME}: already exists, reusing (it's expected to "
            f"accumulate real backtests each spec run -- pass --reset to force a clean recreate)."
        )
    else:
        _seed_live_trigger_fixture()
        print(f"{LIVE_TRIGGER_STRATEGY_NAME}: created fresh.")


if __name__ == "__main__":
    main()
