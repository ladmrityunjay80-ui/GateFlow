# ML-Based Anomaly Detection

GateFlow ships with two anomaly detection layers:

1. **Rule-based detector** in `gateflow/anomaly.py` — covers error-rate spikes, latency spikes and traffic spikes using hard thresholds.
2. **Statistical ML detector** in `gateflow/ml_anomaly.py` — online Z-score based outlier detection over a rolling window.

## ML detector

`MLAnomalyDetector` keeps a bounded window of recent values and flags a value as anomalous when its Z-score is greater than the configured threshold.

### Example

```python
from gateflow.ml_anomaly import MLAnomalyDetector

detector = MLAnomalyDetector(window_size=60, threshold=3.0)
for latency in latency_stream:
    result = detector.update(latency)
    if result["is_anomaly"]:
        print(f"Anomaly detected: z_score={result['z_score']:.2f}")
```

## Integration roadmap

The ML detector can be enabled in `gateflow/metrics_worker.py` alongside the rule-based detector. Future work includes:

- Persisting the rolling window in Redis so it survives restarts.
- Replacing Z-score with scikit-learn `IsolationForest` or a lightweight auto-encoder.
- Training on historical telemetry stored in Redis streams.
