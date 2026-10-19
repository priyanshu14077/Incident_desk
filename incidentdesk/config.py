"""Settings for IncidentDesk: models, Groq free-tier limits, retry policy, paths.

Model IDs live here so a retired Groq model is a one-line change (Design rule 6).
"""

from pathlib import Path

# --- Models (LiteLLM "provider/model-id" strings) -----------------------------
# Confirm each ID with `uv run python scripts/check_groq.py`.
# The PRD's Llama 3.x examples were retired by Groq before 2026-10-20.
FAST_MODEL = "groq/openai/gpt-oss-20b"  # specialists, comms
SMART_MODEL = "groq/openai/gpt-oss-120b"  # commander
FALLBACK_MODEL = "groq/qwen/qwen3.8-27b"  # used after repeated 429s

# gpt-oss models return their reasoning, ADK echoes it back in the history, and
# Groq then rejects the next request ("reasoning_content is unsupported").
# Pass to every LiteLlm(...) so Groq leaves the reasoning out.
GROQ_EXTRA_ARGS = {"extra_body": {"include_reasoning": False}}

# --- Groq free-tier limits, per model ------------------------------------------
# rpd and tpm read from Groq's x-ratelimit-* headers by scripts/check_groq.py
# on 2026-10-20. rpm and tpd are not in the headers: rpm is Groq's published
# free-tier default, tpd unknown (check console.groq.com/settings/limits).
GROQ_LIMITS = {
    FAST_MODEL: {"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": None},
    SMART_MODEL: {"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": None},
    FALLBACK_MODEL: {"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": None},
}

# Three specialists burst ~2,000 input tokens each at once (Design rule 3).
PARALLEL_BURST_TOKENS = 6_000
STAGGER_SECONDS = 3
STAGGER_SPECIALISTS = GROQ_LIMITS[FAST_MODEL]["tpm"] <= PARALLEL_BURST_TOKENS

# --- Generation settings (TR-4) ------------------------------------------------
SPECIALIST_TEMPERATURE = 0.1
COMMANDER_TEMPERATURE = 0.1
COMMS_TEMPERATURE = 0.5

SPECIALIST_MAX_TOKENS = 800
COMMANDER_MAX_TOKENS = 1_500
COMMS_MAX_TOKENS = 400

# --- Retry policy (Design rule 4) ----------------------------------------------
RETRY_BACKOFF_SECONDS = (5, 15, 45)  # then switch to FALLBACK_MODEL

# --- Orchestration --------------------------------------------------------------
COMMANDER_TIMEOUT_S = 90  # FR-5
TOOL_OUTPUT_TOKEN_CAP = 1_500  # Design rule 1

# --- Paths ------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data"
RUNBOOK_DIR = REPO_ROOT / "runbooks"
SCENARIO_DIR = REPO_ROOT / "scenarios"
DATA_DIR_ENV = "INCIDENTDESK_DATA_DIR"
