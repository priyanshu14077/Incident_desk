"""Read-only investigation tools over one generated ShopCo run.

Plain Python does the heavy lifting (filter, group, compare against a baseline)
and returns a compact dict, so the model never reads raw telemetry (Design
rule 1). Docstrings are written for the model: ADK turns them, plus the type
hints, into the tool schema the model sees.

Which run is read: $INCIDENTDESK_DATA_DIR, or else the newest folder in data/.
Nothing here reads ground_truth.json.
"""

import csv
import json
import os
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from . import config

SERVICES = ("checkout", "payments", "inventory", "shopdb")
METRICS = ("latency_p95_ms", "error_rate", "cpu_pct", "db_connections")
BASELINE_MINUTES = 20  # the first 20 minutes of a run are the healthy reference
RUNBOOK_TOPICS = {
    "rollback": ("rollback", "roll back", "revert", "deploy", "release", "version"),
    "cert-renewal": ("cert", "tls", "ssl", "x509", "renew"),
    "batch-jobs": ("batch", "job", "schedule", "cron", "database", "db", "cpu", "noisy"),
}
# Minimum band half-width, so tiny healthy noise never counts as an anomaly.
BAND_FLOOR = {"latency_p95_ms": 40, "error_rate": 0.01, "cpu_pct": 10, "db_connections": 4}

_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")


# --- helpers ------------------------------------------------------------------


def data_dir() -> Path:
    env = os.environ.get(config.DATA_DIR_ENV)
    if env:
        return Path(env)
    runs = [p for p in config.DATA_ROOT.glob("*/") if (p / "logs.jsonl").exists()]
    if not runs:
        raise FileNotFoundError("no generated run found; run `make data` first")
    return max(runs, key=lambda p: p.stat().st_mtime)


def _clock(ts: str) -> str:
    """'2026-11-16T14:05:12Z' -> '14:05:12'."""
    return ts[11:19]


def _parse_window(start: str, end: str) -> tuple[str, str] | dict:
    bounds = []
    for name, value in (("start", start), ("end", end)):
        m = _TIME.match(value.strip())
        if not m:
            return {"error": f"{name}={value!r} is not a time; use 24h 'HH:MM', e.g. '14:05'"}
        bounds.append(f"{m[1]}:{m[2]}:{m[3] or '00'}")
    lo, hi = bounds
    if lo > hi:
        return {"error": f"start {start} is after end {end}"}
    # Make the end inclusive of its whole minute when given as HH:MM.
    if len(end.strip()) == 5:
        hi = hi[:6] + "59"
    return lo, hi


def _check_service(service: str, allow_all: bool = True) -> str | dict:
    s = service.strip().lower()
    if s in SERVICES or (allow_all and s == "all"):
        return s
    return {"error": f"unknown service {service!r}", "valid": [*SERVICES, "all"] if allow_all else list(SERVICES)}


def _cap(result: dict) -> dict:
    """Shrink the longest list until the JSON fits the token cap (~4 chars/token)."""
    limit = config.TOOL_OUTPUT_TOKEN_CAP * 4
    while len(json.dumps(result)) > limit:
        lists = [k for k, v in result.items() if isinstance(v, list) and len(v) > 1]
        if not lists:
            break
        key = max(lists, key=lambda k: len(json.dumps(result[k])))
        result[key] = result[key][: len(result[key]) // 2]
        result["truncated"] = True
    return result


def _normalise(message: str) -> str:
    """Group repeats of the same error: replace ids and numbers with placeholders."""
    message = re.sub(r"\b[0-9a-f]{6,}\b", "<id>", message)
    return re.sub(r"\b\d+\b", "<n>", message)


def _load_logs(run: Path) -> list[dict]:
    with open(run / "logs.jsonl") as f:
        return [json.loads(line) for line in f]


def _load_metrics(run: Path) -> list[dict]:
    with open(run / "metrics.csv", newline="") as f:
        return [{**r, **{m: float(r[m]) for m in METRICS}} for r in csv.DictReader(f)]


def _episode(service: str, metric: str, mean: float, points: list, i: int, j: int) -> dict:
    """Describe points[i:j], a run of minutes outside the band."""
    peak_t, peak_v = max(points[i:j], key=lambda p: abs(p[1] - mean))
    if not mean:
        change = f"+{peak_v:g}"
    elif peak_v >= mean:
        change = f"x{peak_v / mean:.1f}"
    else:
        change = f"-{(1 - peak_v / mean) * 100:.0f}%"
    return {
        "service": service,
        "metric": metric,
        "baseline": round(mean, 4),
        "first_breach": points[i][0][:5],
        "peak": peak_v,
        "peak_at": peak_t[:5],
        "change": change,
        "recovered_at": points[j][0][:5] if j < len(points) else None,
    }


# --- tools --------------------------------------------------------------------


def error_summary(service: str, start: str, end: str) -> dict:
    """Summarise ERROR and WARN log lines for a service in a time window.

    Use this to find which errors spiked, in which service, and since when.

    Args:
        service: One of "checkout", "payments", "inventory", "shopdb", or "all".
        start: Window start, 24h "HH:MM" (e.g. "13:45").
        end: Window end, 24h "HH:MM" (e.g. "14:30"), inclusive.

    Returns:
        errors_per_minute: ERROR count for each minute that had errors.
        top_errors: up to 5 distinct error messages (ids replaced by <id>,
            numbers by <n>) with count, first_seen, last_seen, service, and the
            upstream service the error was about, if any.
        top_warnings: up to 3 distinct warnings in the same shape.
        Note that some errors happen all the time (e.g. declined cards): compare
        first_seen with the incident start before blaming one.
    """
    window = _parse_window(start, end)
    if isinstance(window, dict):
        return window
    svc = _check_service(service)
    if isinstance(svc, dict):
        return svc
    lo, hi = window

    per_minute: Counter[str] = Counter()
    groups: dict[tuple, dict] = {}
    for line in _load_logs(data_dir()):
        clock = _clock(line["ts"])
        if not (lo <= clock <= hi) or (svc != "all" and line["service"] != svc):
            continue
        if line["level"] not in ("ERROR", "WARN"):
            continue
        if line["level"] == "ERROR":
            per_minute[clock[:5]] += 1
        key = (line["level"], line["service"], _normalise(line["message"]), line.get("upstream"))
        g = groups.setdefault(key, {"count": 0, "first_seen": clock, "last_seen": clock})
        g["count"] += 1
        g["last_seen"] = max(g["last_seen"], clock)

    def top(level: str, n: int) -> list[dict]:
        rows = [
            {"message": msg, "service": service, "upstream": upstream, **g}
            for (lvl, service, msg, upstream), g in groups.items()
            if lvl == level
        ]
        for r in rows:
            if r["upstream"] is None:
                del r["upstream"]
        return sorted(rows, key=lambda r: -r["count"])[:n]

    return _cap({
        "service": svc,
        "window": f"{lo[:5]}-{hi[:5]}",
        "total_errors": sum(per_minute.values()),
        "top_errors": top("ERROR", 5),
        "top_warnings": top("WARN", 3),
        "errors_per_minute": [{"minute": m, "errors": c} for m, c in sorted(per_minute.items())],
    })


def metric_anomalies(service: str, start: str, end: str) -> dict:
    """Find metrics that left their healthy baseline band in a time window.

    Use this to see which signals went abnormal, and which went abnormal first.
    Metrics: latency_p95_ms, error_rate (0-1), cpu_pct, db_connections. The
    "shopdb" service is the shared database used by all three app services.

    Args:
        service: One of "checkout", "payments", "inventory", "shopdb", or "all".
        start: Window start, 24h "HH:MM" (e.g. "13:45").
        end: Window end, 24h "HH:MM" (e.g. "14:30"), inclusive.

    Returns:
        baseline_window: the healthy reference period the bands come from.
        anomalies: one entry per episode (2+ consecutive minutes outside the
            band), sorted by first_breach, earliest first. Each has service,
            metric, baseline (healthy mean), first_breach, peak, peak_at,
            change ("x5.2" or "-72%"), and recovered_at ("HH:MM", or null if
            still abnormal at the end of the window). A short episode that
            recovered is usually noise.
    """
    window = _parse_window(start, end)
    if isinstance(window, dict):
        return window
    svc = _check_service(service)
    if isinstance(svc, dict):
        return svc
    lo, hi = window

    series: dict[tuple, list[tuple[str, float]]] = defaultdict(list)
    for row in _load_metrics(data_dir()):
        if svc == "all" or row["service"] == svc:
            for m in METRICS:
                series[(row["service"], m)].append((_clock(row["ts"]), row[m]))

    anomalies = []
    baseline_window = None
    for (service_name, metric), points in series.items():
        points.sort()
        reference = [v for _, v in points[:BASELINE_MINUTES]]
        baseline_window = f"{points[0][0][:5]}-{points[BASELINE_MINUTES - 1][0][:5]}"
        mean = statistics.fmean(reference)
        half = max(4 * statistics.pstdev(reference), 0.3 * mean, BAND_FLOOR[metric])

        in_window = [(t, v) for t, v in points if lo <= t <= hi]
        outside = [abs(v - mean) > half for _, v in in_window] + [False]
        i = 0
        while i < len(in_window):
            if not outside[i]:
                i += 1
                continue
            j = i
            while outside[j]:
                j += 1
            if j - i >= 2:
                anomalies.append(_episode(service_name, metric, mean, in_window, i, j))
            i = j

    anomalies.sort(key=lambda a: (a["first_breach"], a["service"], a["metric"]))
    return _cap({
        "service": svc,
        "window": f"{lo[:5]}-{hi[:5]}",
        "baseline_window": baseline_window,
        "anomalies": anomalies,
    })


def list_changes(start: str, end: str) -> dict:
    """List every change recorded in a time window, oldest first.

    Use this to answer "what changed shortly before the incident?". Changes
    include deploys, config changes, scheduled jobs and certificate events,
    for any service (including ones not involved in the incident).

    Args:
        start: Window start, 24h "HH:MM" (e.g. "13:30").
        end: Window end, 24h "HH:MM" (e.g. "14:10"), inclusive.

    Returns:
        changes: each with ts ("HH:MM:SS"), type (deploy, config, job, cert),
            service, and detail.
    """
    window = _parse_window(start, end)
    if isinstance(window, dict):
        return window
    lo, hi = window

    changes = json.loads((data_dir() / "changes.json").read_text())
    picked = [
        {**c, "ts": _clock(c["ts"])}
        for c in sorted(changes, key=lambda c: c["ts"])
        if lo <= _clock(c["ts"]) <= hi
    ]
    return _cap({"window": f"{lo[:5]}-{hi[:5]}", "count": len(picked), "changes": picked})


def read_runbook(topic: str) -> dict:
    """Read the ShopCo runbook for a remediation topic.

    Args:
        topic: What needs fixing, e.g. "rollback", "certificate renewal", or
            "batch job rescheduling". Loose wording is fine.

    Returns:
        The runbook's name and its Markdown content, or the list of valid
        topics if nothing matches.
    """
    words = topic.strip().lower()
    for name, keywords in RUNBOOK_TOPICS.items():
        if name in words or any(k in words for k in keywords):
            content = (config.RUNBOOK_DIR / f"{name}.md").read_text()
            return _cap({"runbook": name, "content": content})
    return {"error": f"no runbook matches {topic!r}", "valid_topics": list(RUNBOOK_TOPICS)}
