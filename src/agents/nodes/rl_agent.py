"""RL Agent node (AGT-018, PMPT-018/041) -- REL-008 E8.6.

Same DB-write-is-the-deterministic-action reasoning as ml_agent.py: this node trains real PPO/SAC
policies across multiple seeds, rejects (raises) if AGT-018's own design-doc error-handling rule
fires ("reject the run and flag for reward-function redesign" on excessive reward-curve variance
across seeds), evaluates the best-surviving seed via the real VectorBT backtesting engine, logs to
MLflow, and persists a real `ml_models` row -- the LLM is called only for the narrative.
"""

import json
from datetime import date

import mlflow
import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import RLTrainingResult, TradingOSGraphState
from src.core.config import get_settings
from src.core.db import get_session
from src.ml.features.store import build_feature_frame
from src.ml.mlflow_client import get_tracking_uri, sync_mlflow_run_to_ml_models
from src.ml.rl.env import TradingEnv
from src.ml.rl.evaluation import evaluate_policy_backtest
from src.ml.rl.policies import train_policy
from src.ml.rl.stability import assess_seed_stability

PROMPT_SLUG = "rl_agent"
TASK_PROMPT_SLUG = "rl_agent_task"
logger = structlog.get_logger(__name__)


class RLTrainingRejected(Exception):
    """Raised when the seed-stability gate fails -- matches AGT-018's own design-doc rule
    literally: an unstable run is rejected, not silently registered."""


def _generate_narrative(
    *,
    algorithm: str,
    symbols: list[str],
    trigger_reason: str,
    stability_passed: bool,
    reward_variance_cv: float,
    backtest_sharpe: float | None,
) -> str:
    try:
        system_prompt = get_active_prompt(PROMPT_SLUG)
        user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
            algorithm=algorithm,
            symbols_summary=", ".join(symbols),
            trigger_reason=trigger_reason,
            stability_passed=stability_passed,
            reward_variance_cv=round(reward_variance_cv, 4),
            backtest_sharpe=backtest_sharpe,
        )
        response = complete(
            "research",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        parsed = json.loads(extract_json(content))
        return str(parsed["narrative"])
    except Exception as exc:  # noqa: BLE001 - narrative is advisory; never block the loop on it
        logger.warning("rl_agent_narrative_fallback", error=str(exc))
        return (
            f"Trained {algorithm} over {symbols} ({trigger_reason}). "
            f"Stability passed: {stability_passed} (CV={reward_variance_cv:.3f}). "
            f"Backtest Sharpe: {backtest_sharpe}."
        )


def rl_agent_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.rl_training_request is None:
        raise ValueError("rl_agent_node requires state.rl_training_request")
    request = state.rl_training_request

    lake_root = get_settings().data_lake_root / "ohlcv_daily"
    window_start = date.fromisoformat(request.window_start)
    window_end = date.fromisoformat(request.window_end)
    feature_frames = {
        symbol: build_feature_frame(symbol, window_start, window_end, lake_root=lake_root)
        for symbol in request.symbols
    }

    def env_factory() -> TradingEnv:
        return TradingEnv(feature_frames)

    reward_curves: dict[int, list[float]] = {}
    trained_models = {}
    for seed in request.seeds:
        model, curve = train_policy(request.algorithm, env_factory, request.total_timesteps, seed)
        reward_curves[seed] = curve
        trained_models[seed] = model

    stability = assess_seed_stability(reward_curves)
    if not stability.passed:
        raise RLTrainingRejected(
            f"reward variance CV {stability.coefficient_of_variation:.3f} exceeds threshold "
            "-- rejecting run, flagging for reward-function redesign per AGT-018's own rule"
        )

    best_seed = max(
        stability.mean_final_reward_by_seed, key=lambda s: stability.mean_final_reward_by_seed[s]
    )
    best_model = trained_models[best_seed]
    eval_env = env_factory()
    backtest_metrics = evaluate_policy_backtest(best_model, eval_env)

    get_tracking_uri()
    with mlflow.start_run(run_name=f"rl_{request.algorithm}_{'_'.join(request.symbols)}") as run:
        mlflow_run_id = run.info.run_id
        # A real local save of the trained policy (stable-baselines3's own .zip format, the
        # standard way to persist an SB3 model) -- DB-017's artifact_path column is meant to hold
        # a real, loadable artifact location (Phase_11's schema comment: "`.onnx`/`.pkl`
        # location"), not a bare MLflow run URI nothing was actually logged under.
        policy_dir = get_settings().data_lake_root / "ml_artifacts" / mlflow_run_id
        policy_dir.mkdir(parents=True, exist_ok=True)
        policy_path = policy_dir / "policy.zip"
        best_model.save(str(policy_path))

        mlflow.log_params(
            {
                "algorithm": request.algorithm,
                "symbols": ",".join(request.symbols),
                "total_timesteps": request.total_timesteps,
                "seeds": ",".join(str(s) for s in request.seeds),
                "best_seed": best_seed,
            }
        )
        mlflow.log_metrics(
            {
                "reward_variance_cv": stability.coefficient_of_variation,
                "backtest_sharpe": backtest_metrics.sharpe_ratio,
                **{
                    f"mean_final_reward_seed_{s}": v
                    for s, v in stability.mean_final_reward_by_seed.items()
                },
            }
        )
        mlflow.log_artifact(str(policy_path))
        artifact_path = str(policy_path)

    narrative = _generate_narrative(
        algorithm=request.algorithm,
        symbols=request.symbols,
        trigger_reason=request.trigger_reason,
        stability_passed=stability.passed,
        reward_variance_cv=stability.coefficient_of_variation,
        backtest_sharpe=backtest_metrics.sharpe_ratio,
    )

    with get_session() as session:
        ml_model = sync_mlflow_run_to_ml_models(
            session,
            mlflow_run_id=mlflow_run_id,
            name=f"{request.algorithm}-RL_{'_'.join(request.symbols)}",
            model_type=f"{request.algorithm}-RL",
            artifact_path=artifact_path,
            git_commit_hash="unknown",  # RL policies aren't tied to a single training-script hash
            training_data_hash="unknown",
            metrics={
                "reward_variance_cv": stability.coefficient_of_variation,
                "backtest_sharpe": backtest_metrics.sharpe_ratio,
                "training_window": {"start": request.window_start, "end": request.window_end},
                "trigger_reason": request.trigger_reason,
            },
        )
        session.commit()
        ml_model_id = str(ml_model.id)

    return {
        "rl_training_result": RLTrainingResult(
            ml_model_id=ml_model_id,
            mlflow_run_id=mlflow_run_id,
            algorithm=request.algorithm,
            reward_mean_by_seed={str(k): v for k, v in stability.mean_final_reward_by_seed.items()},
            reward_variance_cv=stability.coefficient_of_variation,
            stability_passed=stability.passed,
            backtest_sharpe=backtest_metrics.sharpe_ratio,
            artifact_path=artifact_path,
            narrative=narrative,
        )
    }
