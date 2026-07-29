"""REL-008 E8.2: LightGBM tabular classification/regression training (Phase_5 §2), with an
Optuna hyperparameter sweep and real MLflow experiment logging (params, metrics, feature
importance).
"""

from typing import Any, Literal, cast

import lightgbm as lgb
import mlflow
import numpy as np
import optuna
import polars as pl
from sklearn.metrics import mean_absolute_error, roc_auc_score

from src.ml.features.store import FEATURE_COLUMNS
from src.ml.training.baselines import buy_and_hold_return, momentum_baseline_accuracy
from src.ml.training.dataset import build_labels, chronological_split
from src.ml.training.types import TrainingRunOutcome

optuna.logging.set_verbosity(optuna.logging.WARNING)


def _objective(
    trial: optuna.Trial,
    task: Literal["classification", "regression"],
    train_x: pl.DataFrame,
    train_y: pl.Series,
    valid_x: pl.DataFrame,
    valid_y: pl.Series,
) -> float:
    params: dict[str, Any] = {
        "num_leaves": trial.suggest_int("num_leaves", 7, 63),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 30),
        "n_estimators": 100,
        "verbosity": -1,
    }
    model_cls = lgb.LGBMClassifier if task == "classification" else lgb.LGBMRegressor
    model = model_cls(**params)
    model.fit(train_x.to_pandas(), train_y.to_pandas())
    preds = np.asarray(model.predict(valid_x.to_pandas()))

    if task == "classification":
        valid_y_np = valid_y.to_pandas().to_numpy()
        return float(np.mean(preds == valid_y_np))  # accuracy, maximize

    mae = float(mean_absolute_error(valid_y.to_pandas(), preds))
    return -mae  # Optuna maximizes; negate MAE so "less error" scores higher


def train_lightgbm(
    *,
    symbol: str,
    feature_df: pl.DataFrame,
    task: Literal["classification", "regression"],
    n_optuna_trials: int = 20,
) -> TrainingRunOutcome:
    labeled = build_labels(feature_df, task)
    train_df, valid_df, test_df = chronological_split(labeled)

    train_x, train_y = train_df.select(FEATURE_COLUMNS), train_df["label"]
    valid_x, valid_y = valid_df.select(FEATURE_COLUMNS), valid_df["label"]
    test_x, test_y = test_df.select(FEATURE_COLUMNS), test_df["label"]

    study = optuna.create_study(direction="maximize")
    study.optimize(
        lambda trial: _objective(trial, task, train_x, train_y, valid_x, valid_y),
        n_trials=n_optuna_trials,
    )
    best_params: dict[str, Any] = {**study.best_params, "n_estimators": 100, "verbosity": -1}

    # Refit on train+valid combined with the best hyperparameters, held-out test split only used
    # for final unbiased evaluation -- standard practice, and matches "no K-fold" without wasting
    # the valid split's signal on the final model.
    fit_x = pl.concat([train_x, valid_x]).to_pandas()
    fit_y = pl.concat([train_y.to_frame(), valid_y.to_frame()])["label"].to_pandas()
    model_cls = lgb.LGBMClassifier if task == "classification" else lgb.LGBMRegressor
    final_model = model_cls(**best_params)
    final_model.fit(fit_x, fit_y)

    metrics: dict[str, float] = {}
    baseline_comparison: dict[str, float] = {}
    test_preds = np.asarray(final_model.predict(test_x.to_pandas()))

    if task == "classification":
        test_y_np = test_y.to_pandas().to_numpy()
        accuracy = float(np.mean(test_preds == test_y_np))
        metrics["test_accuracy"] = accuracy
        try:
            proba = np.asarray(
                cast(lgb.LGBMClassifier, final_model).predict_proba(test_x.to_pandas())
            )[:, 1]
            metrics["test_auc"] = float(roc_auc_score(test_y_np, proba))
        except ValueError:
            # A single-class test split (all-up or all-down) makes AUC undefined -- an honest gap
            # of this small a real dataset. Omitted rather than stored as NaN: NaN isn't valid
            # JSON, and this dict gets persisted into ml_models.metrics JSONB downstream.
            pass
        baseline_comparison["model_accuracy"] = accuracy
        baseline_comparison["baseline_momentum_accuracy"] = momentum_baseline_accuracy(test_df)
    else:
        mae = float(mean_absolute_error(test_y.to_pandas(), test_preds))
        directional_accuracy = float(
            np.mean((test_preds > 0) == (test_y.to_pandas().to_numpy() > 0))
        )
        metrics["test_mae"] = mae
        metrics["test_directional_accuracy"] = directional_accuracy
        baseline_comparison["model_mae"] = mae
        baseline_comparison["baseline_buy_and_hold_return"] = buy_and_hold_return(test_df)

    with mlflow.start_run(run_name=f"lightgbm_{task}_{symbol}") as run:
        mlflow.log_params({**best_params, "symbol": symbol, "task": task})
        mlflow.log_metrics(metrics)
        importances = dict(
            zip(FEATURE_COLUMNS, [float(v) for v in final_model.feature_importances_], strict=True)
        )
        mlflow.log_dict(importances, "feature_importance.json")
        mlflow.lightgbm.log_model(final_model, name="model")
        mlflow_run_id = run.info.run_id

    return TrainingRunOutcome(
        mlflow_run_id=mlflow_run_id,
        model=final_model,
        metrics=metrics,
        baseline_comparison=baseline_comparison,
        feature_columns=FEATURE_COLUMNS,
    )
