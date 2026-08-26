#!/usr/bin/env python3
"""Retrain the anomaly model from recent request telemetry.

This script reads the Redis metrics stream (or an optional JSONL file) and
retrains the IsolationForest model on request latency values.  It is intended
for cron / CI driven retraining.

Examples:
    python scripts/retrain_anomaly_model.py --output models/anomaly.joblib
    python scripts/retrain_anomaly_model.py --jsonl metrics.jsonl --field duration_ms
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from gateflow.config import get_settings  # noqa: E402
from gateflow.constants import RedisKeys  # noqa: E402
from gateflow.ml_model import train_and_save  # noqa: E402


async def _read_stream(redis_client, since_ms: int, field: str) -> list[float]:
    """Read metrics from the Redis stream that are newer than since_ms."""
    values: list[float] = []
    start_id = f"{since_ms}-0"
    while True:
        chunk = await redis_client.xrange(
            RedisKeys.METRICS_STREAM,
            min=start_id,
            max="+",
            count=1000,
        )
        if not chunk:
            break
        for msg_id, data in chunk:
            try:
                raw = data.get(field, "0")
                values.append(float(raw))
            except (ValueError, TypeError):
                continue
            start_id = msg_id
        if len(chunk) < 1000:
            break
    return values


def _read_jsonl(path: Path, field: str) -> list[float]:
    values: list[float] = []
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            raw = data if field is None else data.get(field)
            if raw is not None:
                with contextlib.suppress(ValueError, TypeError):
                    values.append(float(raw))
    return values


async def _fetch_values(args: argparse.Namespace) -> list[float]:
    if args.jsonl:
        return _read_jsonl(args.jsonl, args.field)

    import redis.asyncio as redis

    settings = get_settings()
    client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        since = datetime.now(UTC) - timedelta(hours=args.hours)
        since_ms = int(since.timestamp() * 1000)
        return await _read_stream(client, since_ms, args.field)
    finally:
        await client.aclose()  # type: ignore[attr-defined]


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrain the anomaly model from recent telemetry")
    parser.add_argument("--output", type=Path, default=Path("models/anomaly.joblib"))
    parser.add_argument("--hours", type=float, default=24.0, help="Lookback window in hours when reading Redis")
    parser.add_argument("--field", type=str, default="duration_ms", help="Numeric field to train on")
    parser.add_argument("--jsonl", type=Path, help="JSONL file of telemetry (skips Redis)")
    parser.add_argument("--contamination", type=float, default=0.1)
    args = parser.parse_args()

    import anyio

    values = anyio.run(_fetch_values, args)

    if len(values) < 2:
        print(f"Not enough samples to retrain (found {len(values)}).", file=sys.stderr)
        sys.exit(1)

    train_and_save(values, str(args.output), contamination=args.contamination)
    print(f"Retrained anomaly model on {len(values)} samples and saved to {args.output}")


if __name__ == "__main__":
    main()
