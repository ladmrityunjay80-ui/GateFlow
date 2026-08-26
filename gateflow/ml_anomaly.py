from __future__ import annotations

import logging
import os
import sys
from collections import deque
from typing import Any

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .config import get_settings
from .ml_model import load_model, predict

logger = logging.getLogger("gateflow.ml_anomaly")


class MLAnomalyDetector:
    """Anomaly detector that uses a persisted scikit-learn model when available,
    otherwise falls back to a rolling Z-score.
    """

    def __init__(self, window_size: int = 60, threshold: float = 3.0) -> None:
        self._window: deque[float] = deque(maxlen=window_size)
        self.threshold = threshold
        self._model = None
        self._model_checked = False

    def _get_model(self) -> Any | None:
        if not self._model_checked:
            settings = get_settings()
            self._model = load_model(settings.ml_model_path)
            self._model_checked = True
        return self._model

    def _mean(self) -> float:
        return sum(self._window) / len(self._window)

    def _std(self, mean: float) -> float:
        if len(self._window) < 2:
            return 0.0
        variance = sum((x - mean) ** 2 for x in self._window) / len(self._window)
        return variance**0.5

    def update(self, value: float) -> dict[str, Any]:
        """Ingest a new value and return whether it is anomalous."""
        model = self._get_model()
        if model is not None:
            result = predict(model, value)
            self._window.append(value)
            if result["is_anomaly"]:
                logger.info("ml_anomaly_detected", extra={"value": value, "score": result["score"]})
            return {"is_anomaly": result["is_anomaly"], "score": result["score"], "model": True}

        if len(self._window) < 2:
            self._window.append(value)
            return {"is_anomaly": False, "z_score": 0.0}

        mean = self._mean()
        std = self._std(mean)
        if std > 0:
            z_score = (value - mean) / std
        elif value == mean:
            z_score = 0.0
        else:
            z_score = float("inf") if value > mean else float("-inf")
        is_anomaly = abs(z_score) > self.threshold

        if is_anomaly:
            logger.info(
                "ml_anomaly_detected",
                extra={"value": value, "mean": mean, "std": std, "z_score": z_score},
            )

        self._window.append(value)
        return {"is_anomaly": is_anomaly, "z_score": z_score, "mean": mean, "std": std}

    def current_stats(self) -> dict[str, Any]:
        if not self._window:
            return {"count": 0, "mean": 0.0, "std": 0.0}
        mean = self._mean()
        std = self._std(mean)
        return {"count": len(self._window), "mean": mean, "std": std}
