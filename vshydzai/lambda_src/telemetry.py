"""CloudWatch Embedded Metric Format; no synchronous metrics API calls."""

import json
import math
import os
import time

APPLICATION_RELEASE = "2026-10-13-baseline-2"


def emit(component, metrics, *, dimensions=None, units=None):
    values = {name: float(value) for name, value in metrics.items()}
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("Metric values must be finite")
    labels = {"Environment": os.environ.get("ENVIRONMENT", "local"), "Component": component}
    labels.update(dimensions or {})
    document = {
        # Diagnostic field only: keep metric dimensions stable between builds.
        "ApplicationRelease": APPLICATION_RELEASE,
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "WebHealth", "Dimensions": [list(labels)],
                "Metrics": [{"Name": name, "Unit": (units or {}).get(name, "Count")}
                            for name in values],
            }],
        }, **labels, **values,
    }
    print(json.dumps(document, allow_nan=False))


def timed(component, operation, action):
    start = time.perf_counter()
    try:
        return action()
    finally:
        name = f"DynamoDB{operation}Ms"
        emit(component, {name: (time.perf_counter() - start) * 1000},
             units={name: "Milliseconds"})


def memory_snapshot(component):
    """Linux peak RSS of the Python process; full runtime memory is also in REPORT logs."""
    try:
        import resource
    except ImportError:
        return
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    allocated_mb = int(os.environ.get("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", "256"))
    emit(component, {"MemoryUsedMB": rss_mb, "MemoryUtilizationPercent": rss_mb / allocated_mb * 100},
         units={"MemoryUsedMB": "Megabytes", "MemoryUtilizationPercent": "Percent"})
