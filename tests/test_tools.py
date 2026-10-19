import json

import pytest

from conftest import SCENARIOS, SEEDS, scenario_def
from incidentdesk import config, tools

CAP_CHARS = config.TOOL_OUTPUT_TOKEN_CAP * 4


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("seed", SEEDS)
def test_error_summary_top_error_is_the_planted_one(scenario, seed, use_run):
    use_run(scenario, seed)
    planted = [e for e in scenario_def(scenario)["log_effects"] if e["level"] == "ERROR"]
    result = tools.error_summary("all", "13:30", "14:30")
    top = result["top_errors"][0]
    assert any(top["service"] == e["service"] and top["first_seen"] >= e["start"] for e in planted)
    assert len(json.dumps(result)) <= CAP_CHARS


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("seed", SEEDS)
def test_metric_anomalies_planted_effects_are_single_ongoing_episodes(scenario, seed, use_run):
    use_run(scenario, seed)
    result = tools.metric_anomalies("all", "13:30", "14:30")
    for effect in scenario_def(scenario)["metric_effects"]:
        episodes = [
            a for a in result["anomalies"]
            if (a["service"], a["metric"]) == (effect["service"], effect["metric"]) and a["first_breach"] >= effect["start"]
        ]
        assert len(episodes) == 1, (effect, episodes)
        assert episodes[0]["recovered_at"] is None
    firsts = [a["first_breach"] for a in result["anomalies"]]
    assert firsts == sorted(firsts)


def test_metric_anomalies_noise_spike_recovers(use_run):
    use_run("bad-deploy")
    spikes = [a for a in tools.metric_anomalies("inventory", "13:30", "14:30")["anomalies"] if a["metric"] == "cpu_pct"]
    assert spikes and all(a["recovered_at"] for a in spikes)


def test_metric_anomalies_filters_by_service(use_run):
    use_run("noisy-neighbour")
    result = tools.metric_anomalies("shopdb", "13:30", "14:30")
    assert {a["service"] for a in result["anomalies"]} == {"shopdb"}
    assert result["anomalies"][0]["first_breach"] == "13:55"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_list_changes_includes_planted_change(scenario, use_run):
    use_run(scenario)
    planted = scenario_def(scenario)["changes"][0]
    result = tools.list_changes("13:30", "14:10")
    assert any(c["ts"] == planted["ts"] and c["service"] == planted["service"] for c in result["changes"])
    assert [c["ts"] for c in result["changes"]] == sorted(c["ts"] for c in result["changes"])


def test_list_changes_window_is_inclusive_and_filters(use_run):
    use_run("bad-deploy")
    assert tools.list_changes("14:10", "14:30")["count"] == 0
    assert any(c["ts"] == "14:02:10" for c in tools.list_changes("14:02", "14:02")["changes"])


@pytest.mark.parametrize(
    "call",
    [
        lambda: tools.error_summary("billing", "13:30", "14:30"),
        lambda: tools.error_summary("all", "2pm", "14:30"),
        lambda: tools.metric_anomalies("all", "14:30", "13:30"),
        lambda: tools.list_changes("13:30", "25:00"),
    ],
)
def test_bad_input_returns_error_not_exception(call, use_run):
    use_run("bad-deploy")
    assert "error" in call()


@pytest.mark.parametrize(
    "topic, runbook",
    [
        ("roll back the payments deploy", "rollback"),
        ("renew TLS certificate", "cert-renewal"),
        ("reschedule batch job", "batch-jobs"),
    ],
)
def test_read_runbook_matches_loose_topics(topic, runbook):
    result = tools.read_runbook(topic)
    assert result["runbook"] == runbook
    assert result["content"].startswith("# Runbook")


def test_read_runbook_unknown_topic_lists_valid_ones():
    result = tools.read_runbook("make coffee")
    assert "error" in result and set(result["valid_topics"]) == {"rollback", "cert-renewal", "batch-jobs"}


def test_cap_truncates_long_lists():
    big = {"items": [{"message": "x" * 100}] * 500}
    capped = tools._cap(big)
    assert capped["truncated"] and len(json.dumps(capped)) <= CAP_CHARS


def test_tools_never_need_ground_truth(use_run):
    run_dir = use_run("cert-expiry", 3)
    truth = run_dir / "ground_truth.json"
    saved = truth.read_bytes()
    truth.unlink()
    try:
        tools.error_summary("all", "13:30", "14:30")
        tools.metric_anomalies("all", "13:30", "14:30")
        tools.list_changes("13:30", "14:30")
    finally:
        truth.write_bytes(saved)


def test_data_dir_defaults_to_newest_run(monkeypatch, tmp_path):
    monkeypatch.delenv(config.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path)
    for name in ("old", "new"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "logs.jsonl").write_text("")
    import os
    os.utime(tmp_path / "old", (0, 0))
    assert tools.data_dir().name == "new"
