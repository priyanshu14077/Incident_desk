"""Generate 60 minutes of synthetic ShopCo telemetry with one planted fault.

    uv run python generate.py --scenario bad-deploy --seed 7

Writes <out>/<scenario>-seed<seed>/ containing logs.jsonl, metrics.csv,
changes.json, alert.json and ground_truth.json. The same scenario and seed
always produce byte-identical files (TR-11). Every run carries the same kinds
of background noise, so the fault is never the only thing going on (TR-12).
"""

import argparse
import csv
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from incidentdesk import config

DATE = "2026-11-16"
WINDOW_START = datetime.fromisoformat(f"{DATE}T13:30:00")
WINDOW_MINUTES = 60

METRICS = ("latency_p95_ms", "error_rate", "cpu_pct", "db_connections")

# Healthy (mean, std) per service and metric. shopdb is the shared database;
# its latency is query p95 and db_connections is total open connections.
BASELINES = {
    "checkout": {"latency_p95_ms": (180, 12), "error_rate": (0.004, 0.0015), "cpu_pct": (35, 3), "db_connections": (20, 2)},
    "payments": {"latency_p95_ms": (120, 9), "error_rate": (0.002, 0.001), "cpu_pct": (30, 3), "db_connections": (18, 2)},
    "inventory": {"latency_p95_ms": (60, 5), "error_rate": (0.001, 0.0005), "cpu_pct": (25, 2.5), "db_connections": (10, 1.5)},
    "shopdb": {"latency_p95_ms": (15, 1.5), "error_rate": (0.0, 0.0), "cpu_pct": (40, 3), "db_connections": (48, 3)},
}
SERVICES = tuple(BASELINES)
APP_SERVICES = ("checkout", "payments", "inventory")

INFO_MESSAGES = {
    "checkout": ["order {id} placed", "cart {id} updated", "checkout session {id} started"],
    "payments": ["payment {id} authorised", "refund {id} processed", "payment {id} captured"],
    "inventory": ["stock reserved for order {id}", "stock level synced for sku {n}", "reservation {id} released"],
}

# Background noise present in every scenario.
NOISE_WARNINGS = [
    ("checkout", "GC pause {n}ms"),
    ("payments", "GC pause {n}ms"),
    ("inventory", "cache miss for sku {n}, retrying from primary"),
    ("checkout", "recommendations call slow ({ms}ms), serving cached results"),
]
NOISE_ERRORS = [
    ("payments", 0.5, "card declined by issuer (code 51) for payment {id}"),
    ("checkout", 0.25, "invalid coupon code supplied for cart {id}"),
    ("inventory", 0.1, "sku {n} not found in catalogue"),
]


@dataclass
class Run:
    scenario: dict
    seed: int
    rng: random.Random


def minute_ts(minute: int, second: int = 0) -> datetime:
    return WINDOW_START + timedelta(minutes=minute, seconds=second)


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_to_minute(hhmm: str) -> int:
    t = datetime.fromisoformat(f"{DATE}T{hhmm}")
    return int((t - WINDOW_START).total_seconds() // 60)


def fill(template: str, rng: random.Random) -> str:
    return template.format(
        id=f"{rng.getrandbits(24):06x}",
        n=rng.randint(100, 999),
        ms=rng.randint(1500, 2600),
    )


def load_scenario(name: str) -> dict:
    path = config.SCENARIO_DIR / f"{name}.json"
    if not path.exists():
        known = sorted(p.stem for p in config.SCENARIO_DIR.glob("*.json"))
        raise SystemExit(f"unknown scenario {name!r}; known: {', '.join(known)}")
    return json.loads(path.read_text())


def generate_metrics(run: Run) -> list[dict]:
    rng = run.rng
    effects = run.scenario["metric_effects"]

    # Harmless 3-minute inventory CPU spike that recovers (noise). It sits after
    # the 20-minute baseline period so it doesn't distort the healthy reference.
    spike_start = rng.randint(21, 24)

    rows = []
    for minute in range(WINDOW_MINUTES):
        for service in SERVICES:
            row = {"ts": iso(minute_ts(minute)), "service": service}
            for metric in METRICS:
                mean, std = BASELINES[service][metric]
                value = rng.gauss(mean, std)
                if service == "inventory" and metric == "cpu_pct" and spike_start <= minute < spike_start + 3:
                    value += rng.uniform(25, 35)
                for e in effects:
                    if e["service"] != service or e["metric"] != metric:
                        continue
                    elapsed = minute - clock_to_minute(e["start"])
                    if elapsed < 0:
                        continue
                    frac = min(1.0, (elapsed + 1) / e["ramp_min"])
                    target = e["target"] + rng.gauss(0, abs(e["target"]) * 0.03)
                    # Move toward the target and damp the healthy noise as we go.
                    value = mean + (value - mean) * (1 - 0.8 * frac) + (target - mean) * frac
                row[metric] = round_metric(metric, value)
            rows.append(row)
    return rows


def round_metric(metric: str, value: float):
    value = max(0.0, value)
    if metric == "error_rate":
        return round(min(1.0, value), 4)
    if metric == "cpu_pct":
        return round(min(100.0, value), 1)
    return int(round(value))


def generate_logs(run: Run) -> list[dict]:
    rng = run.rng
    lines = []

    def emit(minute: int, service: str, level: str, message: str, upstream: str | None = None):
        line = {"ts": iso(minute_ts(minute, rng.randint(0, 59))), "service": service, "level": level, "message": message}
        if upstream:
            line["upstream"] = upstream
        lines.append(line)

    for minute in range(WINDOW_MINUTES):
        for service in APP_SERVICES:
            for _ in range(rng.randint(6, 10)):
                emit(minute, service, "INFO", fill(rng.choice(INFO_MESSAGES[service]), rng))
        for service, template in NOISE_WARNINGS:
            if rng.random() < 0.12:
                emit(minute, service, "WARN", fill(template, rng))
        for service, prob, template in NOISE_ERRORS:
            if rng.random() < prob:
                emit(minute, service, "ERROR", fill(template, rng))

    for e in run.scenario["log_effects"]:
        start = clock_to_minute(e["start"])
        end = clock_to_minute(e["end"]) if e.get("end") else WINDOW_MINUTES
        lo, hi = e["per_min"]
        for minute in range(start, end):
            for _ in range(rng.randint(lo, hi)):
                emit(minute, e["service"], e["level"], fill(e["message"], rng), e.get("upstream"))

    lines.sort(key=lambda l: (l["ts"], l["service"], l["level"], l["message"]))
    return lines


def generate_changes(run: Run) -> list[dict]:
    rng = run.rng

    def at(lo: str, hi: str) -> str:
        span = (clock_to_minute(hi) - clock_to_minute(lo)) * 60
        ts = datetime.fromisoformat(f"{DATE}T{lo}") + timedelta(seconds=rng.randint(0, span))
        return iso(ts)

    noise = [
        {"ts": at("13:33", "13:36"), "type": "job", "service": "inventory",
         "detail": "scheduled job cache-warmer started (expected runtime 2 min)"},
        {"ts": at("13:38", "13:44"), "type": "deploy", "service": "inventory",
         "detail": "deploy inventory v1.8.2 -> v1.8.3 (release notes: logging format tweak)"},
        {"ts": at("13:46", "13:50"), "type": "config", "service": "checkout",
         "detail": "feature flag recommendations_v2 rollout 10% -> 25%"},
        {"ts": at("13:49", "13:53"), "type": "cert", "service": "payments",
         "detail": "TLS certificate for payments.shopco.internal renewed (valid until 2027-02-14)"},
        {"ts": at("13:58", "14:04"), "type": "deploy", "service": "search-api",
         "detail": "deploy search-api v5.2.0 -> v5.2.1 (release notes: ranking model refresh)"},
    ]
    planted = [{**c, "ts": iso(datetime.fromisoformat(f"{DATE}T{c['ts']}"))} for c in run.scenario["changes"]]
    return sorted(noise + planted, key=lambda c: (c["ts"], c["service"]))


def write_run(run: Run, out_root: Path) -> Path:
    run_dir = out_root / f"{run.scenario['name']}-seed{run.seed}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Order matters: each generator consumes the shared RNG in turn.
    metrics = generate_metrics(run)
    logs = generate_logs(run)
    changes = generate_changes(run)

    with open(run_dir / "metrics.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ts", "service", *METRICS], lineterminator="\n")
        writer.writeheader()
        writer.writerows(metrics)
    with open(run_dir / "logs.jsonl", "w") as f:
        for line in logs:
            f.write(json.dumps(line) + "\n")

    def dump(name: str, obj) -> None:
        (run_dir / name).write_text(json.dumps(obj, indent=2) + "\n")

    dump("changes.json", changes)
    dump("alert.json", {"date": DATE, **run.scenario["alert"]})
    dump("ground_truth.json", {"scenario": run.scenario["name"], "seed": run.seed, **run.scenario["ground_truth"]})
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=config.DATA_ROOT, help="parent folder for the run folder")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    run_dir = write_run(Run(scenario, args.seed, random.Random(args.seed)), args.out)
    print(run_dir)


if __name__ == "__main__":
    main()
