"""REL-008 E8.5: `check_drift_and_recommend_retrain()` -- the real trigger Phase_5 §6 describes,
wired into the Scheduler (src/agents/scheduler.py) as a daily job.

Honest scope note on the Sharpe trigger: Phase_5 §6 says "the live model's rolling 30-day Sharpe
Ratio" -- this project has no live-trading feedback loop to attribute a Sharpe figure to a
specific deployed model (Business Rule 3: no code path ever places a live trade). This
implementation uses the underlying symbol's own realized rolling-30-day price-return Sharpe as an
honest, real, market-regime-health proxy for "the live model is degrading" instead -- a
documented scope simplification, not a fabricated per-model live Sharpe that doesn't exist.

Produces a new Staging candidate only -- never promotes (REL-008's confirmed always-human-gated
promotion decision)."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal, cast

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.ml.drift.detector import (
    DRIFT_FEATURE_COLUMNS,
    DRIFT_JS_THRESHOLD,
    DRIFT_SHARPE_THRESHOLD,
    compute_feature_drift,
    compute_rolling_sharpe,
)
from src.ml.features.store import build_feature_frame
from src.ml.training.orchestrator import run_training_job
from src.models.ml import MLModel

DRIFT_RETRAIN_WINDOW_DAYS = 182  # "most recent 6 months of data" -- Phase_5 §6
LIVE_WINDOW_DAYS = 30


@dataclass
class DriftCheckResult:
    triggered: bool
    reasons: list[str] = field(default_factory=list)
    feature_drift: dict[str, float] = field(default_factory=dict)
    rolling_sharpe: float | None = None
    new_ml_model: MLModel | None = None


def check_drift_and_recommend_retrain(
    session: Session,
    *,
    model_type: Literal["LightGBM", "TFT-PyTorch"],
    task: Literal["classification", "regression"],
    symbol: str,
    today: date | None = None,
) -> DriftCheckResult:
    today = today or date.today()
    production = session.scalars(
        select(MLModel)
        .where(MLModel.model_type == model_type, MLModel.stage == "Production")
        .order_by(MLModel.created_at.desc())
    ).first()

    if production is None:
        return DriftCheckResult(triggered=False, reasons=["no Production model of this type yet"])

    metrics: dict[str, Any] = production.metrics or {}
    # The Production model's own recorded task takes precedence over the caller's guess -- a
    # retrain must use the same classification/regression framing the model was actually trained
    # with, not whatever the scheduler's caller happened to hardcode.
    task = cast(Literal["classification", "regression"], metrics.get("task", task))
    training_window = metrics.get("training_window")
    if not training_window:
        return DriftCheckResult(
            triggered=False, reasons=["Production model has no recorded training_window"]
        )

    lake_root = get_settings().data_lake_root / "ohlcv_daily"
    reference_df = build_feature_frame(
        symbol,
        date.fromisoformat(training_window["start"]),
        date.fromisoformat(training_window["end"]),
        lake_root=lake_root,
    )
    live_start = today - timedelta(days=LIVE_WINDOW_DAYS)
    live_df = build_feature_frame(symbol, live_start, today, lake_root=lake_root)

    feature_drift = compute_feature_drift(reference_df, live_df, DRIFT_FEATURE_COLUMNS)
    max_drift = max(feature_drift.values()) if feature_drift else 0.0

    live_returns = live_df.select(
        ((pl.col("close") - pl.col("close").shift(1)) / pl.col("close").shift(1)).alias("return")
    )["return"].drop_nulls()
    rolling_sharpe = compute_rolling_sharpe(live_returns)

    reasons = []
    if max_drift > DRIFT_JS_THRESHOLD:
        reasons.append(f"feature drift {max_drift:.4f} exceeds threshold {DRIFT_JS_THRESHOLD}")
    if rolling_sharpe < DRIFT_SHARPE_THRESHOLD:
        reasons.append(
            f"rolling {LIVE_WINDOW_DAYS}-day Sharpe {rolling_sharpe:.2f} below threshold "
            f"{DRIFT_SHARPE_THRESHOLD}"
        )

    if not reasons:
        return DriftCheckResult(
            triggered=False, feature_drift=feature_drift, rolling_sharpe=rolling_sharpe
        )

    new_model = run_training_job(
        session,
        model_type=model_type,
        task=task,
        symbols=[symbol],
        window_start=today - timedelta(days=DRIFT_RETRAIN_WINDOW_DAYS),
        window_end=today,
        trigger_reason="drift_triggered",
    )
    return DriftCheckResult(
        triggered=True,
        reasons=reasons,
        feature_drift=feature_drift,
        rolling_sharpe=rolling_sharpe,
        new_ml_model=new_model,
    )
