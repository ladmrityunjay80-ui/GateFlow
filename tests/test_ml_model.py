from __future__ import annotations

from pathlib import Path

import pytest

from gateflow.ml_model import HAS_SKLEARN, load_model, predict, train_and_save


def test_load_model_missing_path():
    assert load_model("/non/existent/path.joblib") is None


def test_load_model_empty_path():
    assert load_model("") is None


def test_predict_without_sklearn_or_model():
    result = predict(None, 42.0)
    assert result == {"is_anomaly": False, "score": 0.0}


@pytest.mark.skipif(HAS_SKLEARN, reason="tests fallback when sklearn is absent")
def test_train_and_save_raises_without_sklearn():
    with pytest.raises(RuntimeError, match="scikit-learn is not installed"):
        train_and_save([1.0, 2.0, 3.0], "/tmp/model.joblib")


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn is not installed")
def test_train_and_predict_with_sklearn(tmp_path: Path):
    path = tmp_path / "anomaly.joblib"
    train_and_save([1.0, 2.0, 3.0, 2.5, 1.5, 100.0], str(path), contamination=0.15)
    model = load_model(str(path))
    assert model is not None
    result = predict(model, 2.0)
    assert "is_anomaly" in result
    assert "score" in result
    outlier = predict(model, 999.0)
    assert outlier["is_anomaly"] is True
