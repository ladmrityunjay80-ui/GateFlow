from __future__ import annotations

import logging
import os
from typing import Any

try:
    import joblib
    from sklearn.ensemble import IsolationForest

    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

logger = logging.getLogger("gateflow.ml_model")


def load_model(path: str) -> Any | None:
    """Load a persisted scikit-learn model. Return None if ML deps or file are missing."""
    if not HAS_SKLEARN or not path:
        return None
    if not os.path.exists(path):
        logger.warning("ml_model_missing", extra={"path": path})
        return None
    try:
        return joblib.load(path)
    except Exception as exc:
        logger.warning("ml_model_load_failed", extra={"path": path, "error": str(exc)})
        return None


def predict(model: Any, value: float) -> dict[str, Any]:
    """Score a single value with the loaded model.

    Returns is_anomaly=True when the model predicts an outlier (IsolationForest
    predict == -1) and a positive anomaly score based on score_samples.
    """
    if not HAS_SKLEARN or model is None:
        return {"is_anomaly": False, "score": 0.0}
    try:
        x = [[value]]
        pred = int(model.predict(x)[0])
        score = -float(model.score_samples(x)[0])
        return {"is_anomaly": pred == -1, "score": score}
    except Exception as exc:
        logger.warning("ml_model_predict_failed", extra={"error": str(exc)})
        return {"is_anomaly": False, "score": 0.0}


def train_and_save(values: list[float], path: str, contamination: float = 0.1) -> None:
    """Train an IsolationForest on a list of values and persist with joblib."""
    if not HAS_SKLEARN:
        raise RuntimeError("scikit-learn is not installed; install with 'pip install -e .[ml]'")
    if len(values) < 2:
        raise ValueError("need at least 2 values to train a model")

    import numpy as np

    x = np.array(values, dtype=float).reshape(-1, 1)
    model = IsolationForest(contamination=contamination, random_state=42)
    model.fit(x)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    joblib.dump(model, path)
