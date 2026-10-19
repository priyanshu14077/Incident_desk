import json
import random
from pathlib import Path

import pytest

import generate

SCENARIOS = ("bad-deploy", "cert-expiry", "noisy-neighbour")
SEEDS = (1, 2, 3)


def make_run(scenario: str, seed: int, out: Path) -> Path:
    return generate.write_run(generate.Run(generate.load_scenario(scenario), seed, random.Random(seed)), out)


@pytest.fixture(scope="session")
def runs(tmp_path_factory) -> dict[tuple[str, int], Path]:
    """Every scenario x seed, generated once per test session."""
    out = tmp_path_factory.mktemp("data")
    return {(s, seed): make_run(s, seed, out) for s in SCENARIOS for seed in SEEDS}


@pytest.fixture
def use_run(monkeypatch, runs):
    """Point the tools at one generated run."""

    def _use(scenario: str, seed: int = 1) -> Path:
        run_dir = runs[(scenario, seed)]
        monkeypatch.setenv("INCIDENTDESK_DATA_DIR", str(run_dir))
        return run_dir

    return _use


def scenario_def(name: str) -> dict:
    return json.loads((generate.config.SCENARIO_DIR / f"{name}.json").read_text())
