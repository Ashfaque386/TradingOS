"""REL-008 E8.6: `/ml/*` API surface (API-061..067 + a new /predict endpoint, see the REL-008
plan's "decisions made without asking" for why /predict was added beyond the numbered list --
E8.3's exit criterion requires serving a real inference request, and no such endpoint exists in
Phase_10_API_Design.md's numbered list).

`/train` and `/rl/train` dispatch a detached `threading.Thread` running the relevant small graph
(src/agents/ml_graph.py), mirroring src/api/routers/agents.py::trigger_research()'s own reasoning
(LightGBM/PyTorch/Optuna all release the GIL during their C/C++-heavy compute, so a background
thread doesn't stall the app the way a pure-Python long loop would; a detached daemon thread also
isn't tracked by Starlette's graceful-shutdown sequence, matching the existing precedent).

`/promote` is the ONLY path that ever sets `stage="Production"` -- REL-008's confirmed decision
that promotion is always human/role-gated, never autonomous, even after a drift-triggered retrain.
"""

import threading
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel
from sqlalchemy import select

from src.agents.ml_graph import build_rl_training_graph, build_supervised_training_graph
from src.agents.state import MLTrainingRequest, RLTrainingRequest, TradingOSGraphState
from src.api.deps import require_role
from src.core.audit import write_audit_entry
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_RISK_MANAGER,
    ROLE_SYSTEM_ADMINISTRATOR,
)
from src.data.datalake.query import DataLake
from src.ml.features.store import FEATURE_COLUMNS, build_feature_frame
from src.ml.serving.onnx_runtime_service import load_onnx_session, run_inference
from src.models.agent import AgentLog, AgentRun
from src.models.ml import MLModel
from src.models.user import User

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])
logger = structlog.get_logger(__name__)

_can_train = require_role(ROLE_SYSTEM_ADMINISTRATOR)
_can_promote = require_role(ROLE_PORTFOLIO_MANAGER, ROLE_SYSTEM_ADMINISTRATOR)
_can_read = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, ROLE_READ_ONLY_AUDITOR
)


# --- response models -------------------------------------------------------------------------


class ModelResponse(BaseModel):
    id: uuid.UUID
    name: str
    model_type: str
    stage: str
    mlflow_run_id: str
    artifact_path: str
    created_at: datetime


def _to_response(row: MLModel) -> ModelResponse:
    return ModelResponse(
        id=row.id,
        name=row.name,
        model_type=row.model_type,
        stage=row.stage,
        mlflow_run_id=row.mlflow_run_id,
        artifact_path=row.artifact_path,
        created_at=row.created_at,
    )


class TrainPayload(BaseModel):
    model_type: str
    task: str
    symbols: list[str]
    window_start: date
    window_end: date


class TrainResponse(BaseModel):
    run_id: uuid.UUID


class RLTrainPayload(BaseModel):
    algorithm: str
    symbols: list[str]
    window_start: date
    window_end: date
    total_timesteps: int = 5000
    seeds: list[int] = [1, 2, 3]


class PromotePayload(BaseModel):
    pass


class PredictPayload(BaseModel):
    symbol: str
    as_of_date: date


class PredictResponse(BaseModel):
    prediction: float
    used_fallback: bool
    latency_ms: float
    model_id: uuid.UUID
    stage: str


class RLEnvironmentResponse(BaseModel):
    symbols: list[str]
    observation_dim: int
    action_dim: int


# --- dispatch helpers --------------------------------------------------------------------------


def _execute_graph_run(
    graph: CompiledStateGraph,  # type: ignore[type-arg]
    state: TradingOSGraphState,
    *,
    run_id: uuid.UUID,
) -> None:
    """A leaner counterpart to agents.py's `_execute_graph_run` -- this graph's consumers poll
    `GET /ml/models/{id}` for the result rather than watching the live Redis log stream the main
    dashboard graph feeds, so this only needs to close out one AgentRun row, not per-node ones."""
    started_at = datetime.now(UTC)
    try:
        final_state = graph.invoke(state)
        with get_session() as session:
            root = session.get(AgentRun, run_id)
            if root is not None:
                root.status = "Completed"
                root.ended_at = datetime.now(UTC)
                ml_result = final_state.get("ml_training_result")
                rl_result = final_state.get("rl_training_result")
                verdict = final_state.get("model_evaluation_verdict")
                root.output_state = {
                    "ml_training_result": ml_result.model_dump() if ml_result else None,
                    "rl_training_result": rl_result.model_dump() if rl_result else None,
                    "model_evaluation_verdict": verdict.model_dump() if verdict else None,
                }
                session.commit()
    except Exception as exc:  # noqa: BLE001 -- must always close out the run row, even on failure
        logger.warning("ml_graph_run_failed", run_id=str(run_id), error=str(exc))
        with get_session() as session:
            root = session.get(AgentRun, run_id)
            if root is not None:
                root.status = "Failed"
                root.ended_at = datetime.now(UTC)
                session.add(
                    AgentLog(
                        agent_run_id=run_id,
                        log_level="ERROR",
                        message=str(exc),
                        created_at=started_at,
                    )
                )
                session.commit()


def _dispatch(
    graph: CompiledStateGraph,  # type: ignore[type-arg]
    state: TradingOSGraphState,
    *,
    agent_name: str,
) -> uuid.UUID:
    started_at = datetime.now(UTC)
    with get_session() as session:
        root = AgentRun(
            graph_thread_id=state.thread_id,
            agent_name=agent_name,
            status="Running",
            started_at=started_at,
        )
        session.add(root)
        session.commit()
        run_id = root.id

    threading.Thread(
        target=_execute_graph_run,
        kwargs={"graph": graph, "state": state, "run_id": run_id},
        daemon=True,
    ).start()
    return run_id


# --- routes --------------------------------------------------------------------------------


@router.get("/models", response_model=list[ModelResponse])
def list_models(_user: User = Depends(_can_read)) -> list[ModelResponse]:
    with get_session() as session:
        rows = session.scalars(select(MLModel).order_by(MLModel.created_at.desc()))
        return [_to_response(r) for r in rows]


@router.get("/models/{model_id}", response_model=ModelResponse)
def get_model(model_id: uuid.UUID, _user: User = Depends(_can_read)) -> ModelResponse:
    with get_session() as session:
        row = session.get(MLModel, model_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Model not found")
        return _to_response(row)


@router.post("/models/train", response_model=TrainResponse, status_code=202)
def train_model(body: TrainPayload, _user: User = Depends(_can_train)) -> TrainResponse:
    thread_id = str(uuid.uuid4())
    state = TradingOSGraphState(
        thread_id=thread_id,
        ml_training_request=MLTrainingRequest(
            model_type=body.model_type,  # type: ignore[arg-type]
            task=body.task,  # type: ignore[arg-type]
            symbols=body.symbols,
            window_start=body.window_start.isoformat(),
            window_end=body.window_end.isoformat(),
            trigger_reason="manual",
        ),
    )
    run_id = _dispatch(build_supervised_training_graph(), state, agent_name="ml_agent")
    return TrainResponse(run_id=run_id)


@router.get("/models/{model_id}/metrics")
def get_model_metrics(model_id: uuid.UUID, _user: User = Depends(_can_read)) -> dict[str, Any]:
    with get_session() as session:
        row = session.get(MLModel, model_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Model not found")
        return row.metrics or {}


@router.post("/models/{model_id}/promote", response_model=ModelResponse)
def promote_model(
    model_id: uuid.UUID, _body: PromotePayload, user: User = Depends(_can_promote)
) -> ModelResponse:
    """The ONLY path that ever sets stage="Production" -- always a real, human-role-gated call,
    never automatic, including after a drift-triggered retrain (REL-008's confirmed decision)."""
    with get_session() as session:
        candidate = session.get(MLModel, model_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Model not found")
        if candidate.stage == "Production":
            raise HTTPException(status_code=400, detail="Model is already in Production")

        prior_production = session.scalars(
            select(MLModel).where(
                MLModel.model_type == candidate.model_type, MLModel.stage == "Production"
            )
        ).all()
        for row in prior_production:
            row.stage = "Archived"

        candidate.stage = "Production"

        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action="ML_MODEL_PROMOTED",
            entity_type="MLModel",
            entity_id=candidate.id,
            before_state={"stage": "Staging"},
            after_state={
                "stage": "Production",
                "archived_model_ids": [str(r.id) for r in prior_production],
            },
        )
        session.commit()
        return _to_response(candidate)


@router.get("/rl/environments", response_model=list[RLEnvironmentResponse])
def list_rl_environments(_user: User = Depends(_can_read)) -> list[RLEnvironmentResponse]:
    """Returns the real, small, in-code TradingEnv configuration -- honestly one real environment
    spec built over every currently-ingested symbol, not a fabricated list."""
    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    symbols = lake.list_symbols()
    n_symbols = len(symbols)
    obs_dim = 1 + n_symbols + n_symbols * len(FEATURE_COLUMNS)
    return [RLEnvironmentResponse(symbols=symbols, observation_dim=obs_dim, action_dim=n_symbols)]


@router.post("/rl/train", response_model=TrainResponse, status_code=202)
def train_rl(body: RLTrainPayload, _user: User = Depends(_can_train)) -> TrainResponse:
    thread_id = str(uuid.uuid4())
    state = TradingOSGraphState(
        thread_id=thread_id,
        rl_training_request=RLTrainingRequest(
            algorithm=body.algorithm,  # type: ignore[arg-type]
            symbols=body.symbols,
            window_start=body.window_start.isoformat(),
            window_end=body.window_end.isoformat(),
            total_timesteps=body.total_timesteps,
            seeds=body.seeds,
            trigger_reason="manual",
        ),
    )
    run_id = _dispatch(build_rl_training_graph(), state, agent_name="rl_agent")
    return TrainResponse(run_id=run_id)


@router.post("/models/{model_id}/predict", response_model=PredictResponse)
def predict(
    model_id: uuid.UUID, body: PredictPayload, _user: User = Depends(_can_read)
) -> PredictResponse:
    with get_session() as session:
        model_row = session.get(MLModel, model_id)
        if model_row is None:
            raise HTTPException(status_code=404, detail="Model not found")
        artifact_path = model_row.artifact_path
        stage = model_row.stage
        model_type = model_row.model_type

    if model_type not in ("LightGBM", "TFT-PyTorch"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"/predict serves single-value LightGBM/TFT predictions only -- {model_type} "
                "policies output portfolio weights, consumed via the RL backtest evaluation "
                "path, not a stateless point prediction."
            ),
        )

    lake_root = get_settings().data_lake_root / "ohlcv_daily"
    # A window ending at as_of_date, wide enough to cover the longest warm-up window
    # build_feature_frame() needs (26 trading days for the slowest MACD/EMA component).
    window_start = body.as_of_date.replace(year=body.as_of_date.year - 1)
    feature_df = build_feature_frame(
        body.symbol, window_start, body.as_of_date, lake_root=lake_root
    )
    if feature_df.height == 0:
        raise HTTPException(
            status_code=400,
            detail=f"No feature data available for {body.symbol} as of {body.as_of_date}",
        )
    row = feature_df.filter(feature_df["date"] == body.as_of_date)
    if row.height == 0:
        row = feature_df.tail(1)  # fall back to the most recent available trading day
    feature_vector = {col: float(row[col][0]) for col in FEATURE_COLUMNS}

    task: Literal["classification", "regression"] = (
        "classification" if "test_accuracy" in (model_row.metrics or {}) else "regression"
    )
    session_ort = load_onnx_session(artifact_path)
    outcome = run_inference(session_ort, feature_vector, FEATURE_COLUMNS, task)

    return PredictResponse(
        prediction=outcome.prediction,
        used_fallback=outcome.used_fallback,
        latency_ms=outcome.latency_seconds * 1000,
        model_id=model_id,
        stage=stage,
    )
