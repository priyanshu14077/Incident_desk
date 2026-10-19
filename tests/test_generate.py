import csv
import json

import pytest

from conftest import SCENARIOS, SEEDS, make_run

FILES = ("logs.jsonl", "metrics.csv", "changes.json", "alert.json", "ground_truth.json")


def read_metrics(run_dir):
    with open(run_dir / "metrics.csv", newline="") as f:
        return list(csv.DictReader(f))


def read_logs(run_dir):
    return [json.loads(line) for line in (run_dir / "logs.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_same_seed_is_byte_identical(scenario, tmp_path):
    a = make_run(scenario, 7, tmp_path / "a")
    b = make_run(scenario, 7, tmp_path / "b")
    for name in FILES:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_different_seeds_differ(scenario, runs):
    assert (runs[(scenario, 1)] / "logs.jsonl").read_bytes() != (runs[(scenario, 2)] / "logs.jsonl").read_bytes()


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("seed", SEEDS)
def test_writes_all_files_covering_60_minutes(scenario, seed, runs):
    run_dir = runs[(scenario, seed)]
    for name in FILES:
        assert (run_dir / name).exists(), name
    minutes = {r["ts"] for r in read_metrics(run_dir)}
    assert len(minutes) == 60
    truth = json.loads((run_dir / "ground_truth.json").read_text())
    assert truth["scenario"] == scenario and truth["seed"] == seed


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_background_noise_present(scenario, runs):
    run_dir = runs[(scenario, 1)]
    details = [c["detail"] for c in json.loads((run_dir / "changes.json").read_text())]
    assert any("search-api" in d for d in details), "unrelated deploy near the incident"
    assert any("inventory v1.8.2 -> v1.8.3" in d for d in details)
    early_errors = [l for l in read_logs(run_dir) if l["level"] == "ERROR" and l["ts"][11:16] < "13:50"]
    assert any("card declined" in l["message"] for l in early_errors), "routine errors before the incident"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_baseline_period_is_healthy(scenario, runs):
    """The first 20 minutes feed the anomaly baseline, so no fault may touch them."""
    for row in read_metrics(runs[(scenario, 1)]):
        if row["ts"][11:16] < "13:50" and row["service"] == "checkout":
            assert float(row["error_rate"]) < 0.02


def test_bad_deploy_pins_payments_pool(runs):
    after = [r for r in read_metrics(runs[("bad-deploy", 1)]) if r["service"] == "payments" and r["ts"][11:16] >= "14:05"]
    assert all(int(r["db_connections"]) <= 6 for r in after)


def test_cert_expiry_errors_only_after_expiry(runs):
    tls = [l for l in read_logs(runs[("cert-expiry", 1)]) if "certificate has expired" in l["message"]]
    assert tls and min(l["ts"][11:19] for l in tls) >= "14:00:00"


def test_noisy_neighbour_saturates_db(runs):
    db = [r for r in read_metrics(runs[("noisy-neighbour", 1)]) if r["service"] == "shopdb" and r["ts"][11:16] >= "14:00"]
    assert all(float(r["cpu_pct"]) > 85 for r in db)
