# Machine Learning Anomaly Detection

GateFlow can run a statistical Z-score detector by default, or a persisted
scikit-learn model when `GATEFLOW_ML_MODEL_PATH` is set.

## Training a model

Install the optional ML dependencies:

```bash
pip install -e ".[ml]"
```

Train from a list of values or a CSV:

```bash
python scripts/train_anomaly_model.py \
  --csv telemetry.csv \
  --column latency_ms \
  --contamination 0.05 \
  --output models/anomaly.joblib
```

`contamination` is the expected fraction of outliers in the training data. The
output is a `joblib`-pickled scikit-learn `IsolationForest`.

## Running with a model

Set the path in your environment:

```bash
export GATEFLOW_ML_MODEL_PATH=$(pwd)/models/anomaly.joblib
export GATEFLOW_ML_ANOMALY_ENABLED=true
```

`MLAnomalyDetector.update(value)` will use the model when it is available and
fall back to the Z-score detector otherwise.

## Model lifecycle

1. Export historical metrics to a CSV/JSONL.
2. Train with `scripts/train_anomaly_model.py`.
3. Store the model in object storage or a ConfigMap/PVC.
4. GateFlow loads the model at runtime and uses it for online scoring.
5. Periodically retrain on new data and roll the model out by updating
   `GATEFLOW_ML_MODEL_PATH`.
