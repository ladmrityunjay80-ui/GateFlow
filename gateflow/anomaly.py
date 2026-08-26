from __future__ import annotations

import logging
import statistics
import time
from collections import defaultdict, deque
from typing import Any

logger = logging.getLogger("gateflow.anomaly")


class AnomalyDetector:
    """Lightweight streaming anomaly detector for the telemetry channel.

    Maintains a rolling window of latency/error samples per route and per API
    key. Flags three classes of anomalies:

    - **error_rate_spike**: share of 5xx responses in the window exceeds the
      configured threshold.
    - **latency_spike**: p95 latency in the window exceeds the threshold.
    - **traffic_spike**: request count in the current minute is > Nx the
      average of the previous minutes.
    """

    def __init__(
        self,
        window_size: int = 100,
        error_rate_threshold: float = 0.25,
        latency_threshold_ms: float = 1000.0,
        traffic_multiplier: float = 5.0,
    ) -> None:
        self.window_size = window_size
        self.error_rate_threshold = error_rate_threshold
        self.latency_threshold_ms = latency_threshold_ms
        self.traffic_multiplier = traffic_multiplier

        self._samples: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=window_size)
        )
        self._traffic_minute: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"current_minute": 0, "current_minute_count": 0, "counts": deque(maxlen=5)}
        )

    def _group_key(self, metric: dict[str, Any]) -> str:
        return f"{metric.get('route', 'unknown')}:{metric.get('api_key', 'unknown')}"

    def check(self, metric: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate a single telemetry metric and return detected anomalies."""
        now = time.time()
        try:
            status_code = int(metric.get("status_code", 0))
            duration_ms = float(metric.get("duration_ms", 0.0))
        except (TypeError, ValueError):
            return []

        group = self._group_key(metric)
        samples = self._samples[group]

        anomaly: dict[str, Any] = {
            "timestamp": now,
            "group": group,
            "route": metric.get("route", "unknown"),
            "api_key": metric.get("api_key", "unknown"),
        }
        found: list[dict[str, Any]] = []

        samples.append({"status_code": status_code, "duration_ms": duration_ms, "ts": now})

        if len(samples) >= 10:
            error_rate = sum(1 for s in samples if 500 <= s["status_code"] < 600) / len(samples)
            if error_rate > self.error_rate_threshold:
                found.append({**anomaly, "type": "error_rate_spike", "value": error_rate})

            latencies = [s["duration_ms"] for s in samples]
            p95 = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0
            if p95 > self.latency_threshold_ms:
                found.append({**anomaly, "type": "latency_spike", "value": p95})

            mean = statistics.mean(latencies)
            stdev = statistics.stdev(latencies) if len(latencies) > 1 else 0.0
            if duration_ms > mean + 3 * stdev and stdev > 0:
                found.append({**anomaly, "type": "outlier_latency", "value": duration_ms})

        minute = int(now) // 60
        traffic = self._traffic_minute[group]
        if traffic["current_minute"] != minute:
            traffic["counts"].append(traffic["current_minute_count"])
            traffic["current_minute"] = minute
            traffic["current_minute_count"] = 0

        traffic["current_minute_count"] += 1
        if len(traffic["counts"]) >= 2:
            avg = statistics.mean(traffic["counts"])
            if avg > 0 and traffic["current_minute_count"] > avg * self.traffic_multiplier:
                found.append(
                    {
                        **anomaly,
                        "type": "traffic_spike",
                        "value": traffic["current_minute_count"],
                        "expected": avg,
                    }
                )

        for a in found:
            logger.warning("anomaly_detected", extra=a)

        return found
