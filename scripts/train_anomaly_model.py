#!/usr/bin/env python3
"""Train an anomaly model from a CSV/TSV or JSONL value stream.

Examples:
    python scripts/train_anomaly_model.py --values 1.0 2.0 3.0 100.0 --output models/anomaly.joblib
    python scripts/train_anomaly_model.py --csv metrics.csv --column value --output models/anomaly.joblib
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from gateflow.ml_model import train_and_save  # noqa: E402


def _read_values(path: Path, column: str | None = None) -> list[float]:
    values: list[float] = []
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        with path.open() as f:
            for line in f:
                data = json.loads(line)
                raw = data if column is None else data[column]
                values.append(float(raw))
    elif suffix in (".csv", ".tsv"):
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open(newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            if column is None:
                raise ValueError("--column is required for CSV/TSV input")
            for row in reader:
                values.append(float(row[column]))
    else:
        raise ValueError(f"unsupported file format: {suffix}")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="Train an anomaly detection model")
    parser.add_argument("--values", type=float, nargs="*", help="Numeric values to train on")
    parser.add_argument("--csv", type=Path, help="Path to a CSV or TSV file")
    parser.add_argument("--column", type=str, help="Column name for CSV/TSV/JSONL value")
    parser.add_argument("--contamination", type=float, default=0.1, help="IsolationForest contamination")
    parser.add_argument("--output", type=Path, default=Path("models/anomaly.joblib"), help="Output model file (joblib)")
    args = parser.parse_args()

    if args.csv:
        values = _read_values(args.csv, args.column)
    elif args.values:
        values = args.values
    else:
        values = [1.0, 2.0, 3.0, 100.0]
        print("No training data supplied; using demo values:", values, file=sys.stderr)

    train_and_save(values, str(args.output), contamination=args.contamination)
    print(f"Trained model on {len(values)} values and saved to {args.output}")


if __name__ == "__main__":
    main()
