from __future__ import annotations

from gateflow.ml_anomaly import MLAnomalyDetector


def test_ml_anomaly_flags_spike():
    detector = MLAnomalyDetector(window_size=10, threshold=2.0)
    for _ in range(10):
        result = detector.update(1.0)
        assert not result["is_anomaly"]

    spike = detector.update(100.0)
    assert spike["is_anomaly"]
    assert spike["z_score"] > 0


def test_ml_anomaly_stats():
    detector = MLAnomalyDetector(window_size=5)
    for i in range(5):
        detector.update(float(i))
    stats = detector.current_stats()
    assert stats["count"] == 5
    assert stats["mean"] == 2.0
