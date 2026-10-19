# IncidentDesk: M0 → M1 checklist

> **Status 2026-10-20:** 0.1–0.5 and all of M1 are built and `make test` passes (59 tests). Still yours, because each one needs your Groq key or your judgement:
> 1. Create `.env` from `.env.example` with your `GROQ_API_KEY`
> 2. Run `make check-groq`, then copy the real limits into `incidentdesk/config.py` and set the "Limits read on" date
> 3. Run `make web`, ask "what time is it in Tokyo?", and read the Events tab (0.5)
> 4. Do the 0.6 experiments
> 5. Do the 1.11 human eval: `make data-all`, then solve each scenario from the tool output alone
> 6. Make your first commit

You write the code. Tick each box as you go. Ask for a review at the two **STOP** points.

Versions checked on 2026-10-20: `google-adk 2.12.0` and `litellm 1.106.0`, both importing on Python 3.12. ADK 2.x is new, so many tutorials online still show 1.x code. When an example and the installed package disagree, trust the installed package (`python -c "import inspect, google.adk.agents as a; help(a.LlmAgent)"`).

---

## M0: Setup and a first agent on Groq

**Goal:** a call from ADK reaches Groq through LiteLlm, and you can see every step of the agent loop.

### 0.1 Repo
- [ ] `git init`
- [ ] `.gitignore` with: `.env`, `.venv/`, `data/`, `__pycache__/`, `.pytest_cache/`
- [ ] `.env.example` (committed) containing only `GROQ_API_KEY=`

### 0.2 Python environment
Your system Python is 3.14. Pin 3.12, because older versions are the ones ADK and LiteLLM are tested on.
- [ ] `uv init --bare` (creates only `pyproject.toml`)
- [ ] `uv python pin 3.12`
- [ ] `uv add google-adk==2.12.0 litellm==1.106.0 pydantic python-dotenv` (TR-1 requires exact pins; `uv.lock` pins everything else)
- [ ] `uv add --dev pytest`
- [ ] Check it works: `uv run python -c "from google.adk.models.lite_llm import LiteLlm; print('ok')"`

### 0.3 Groq key, tested without ADK first
Start with the raw API so you know what LiteLlm does for you later.
- [ ] Create a key at console.groq.com → API Keys, and put it in `.env`
- [ ] List the models: `curl -s https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY" | python3 -m json.tool`
  - Learn: Groq exposes an **OpenAI-compatible** API. LiteLlm sends `groq/<model-id>` there.
- [ ] Choose a FAST model (small, good at tool calling) and a SMART model (larger), and check both appear in that list
- [ ] Choose a FALLBACK model (Design rule 4: the model to switch to after repeated 429s)

### 0.4 `incidentdesk/config.py`
Settings only, no logic.
- [ ] `FAST_MODEL`, `SMART_MODEL` and `FALLBACK_MODEL` as `"groq/<id>"` strings
- [ ] Your real limits from console.groq.com/settings/limits: RPM, RPD, TPM and TPD for each model, with the date you read them in a comment
- [ ] TR-4 values: temperature 0.1 for specialists and commander, 0.5 for comms; max_tokens 800 / 1500 / 400
- [ ] Retry policy: backoffs `(5, 15, 45)`, `STAGGER_SECONDS = 3`, `COMMANDER_TIMEOUT_S = 90`, `TOOL_OUTPUT_TOKEN_CAP = 1500`
- [ ] Write this down: is the FAST model's TPM below 6,000? If so, M2 needs staggered starts (Design rule 3).

### 0.5 Hello agent
- [ ] `incidentdesk/__init__.py` containing `from . import agent`
- [ ] `incidentdesk/agent.py`:
  - a plain function `get_time(city: str) -> dict` with a real docstring and type hints (fake data is fine)
  - `root_agent = LlmAgent(name=..., model=LiteLlm(model=FAST_MODEL), instruction=..., tools=[get_time])`
  - imports: `from google.adk.agents import LlmAgent`, `from google.adk.models.lite_llm import LiteLlm`
- [ ] From the **repo root**, run `uv run adk web`, open http://localhost:8000 and pick `incidentdesk`
  - ADK walks up from the agent folder to find `.env`, so a `.env` in the repo root is picked up
- [ ] Ask it "what time is it in Tokyo?", then open the **Events** tab and find:
  1. the model's `functionCall` (ADK built that tool schema from your docstring and type hints)
  2. the `functionResponse` (ADK ran your Python, not the model)
  3. the final text
- [ ] Count the LLM calls: one question that uses the tool takes **2 calls**. That is the PRD's budget of "≤ 2 calls per specialist".
- [ ] Also try the terminal: `uv run adk run incidentdesk`

### 0.6 Experiments
Break it on purpose. Each one teaches something you'll need in M2.
- [ ] Delete the docstring. Does the model still call the tool correctly?
- [ ] Ask something that doesn't need the tool. Does it skip the call?
- [ ] Set temperature and max_tokens through `generate_content_config` (you'll need this for TR-4)
- [ ] Add `output_key="answer"`, then check the **State** tab in `adk web`. That is the mechanism the evidence board uses in ADK mode (TR-7).
- [ ] Put in a bad model ID and read the error. You'll see this message again whenever Groq retires a model.

### 0.7 Close M0
- [ ] Exit check: Groq works from ADK via LiteLlm; Git ≥ 2.48 (you have 2.54); Docker running; limits recorded in `config.py`
- [ ] Commit
- [ ] **STOP → say "review M0"**

---

## M1: ShopCo data generator and tools

**Goal:** fake telemetry that is deterministic and noisy, plus read-only tools that shrink it into summaries a small model can reason over. No LLM is involved in M1.

The key idea: **the LLM is only as good as what your tools return.** If you can't find the root cause by calling your own tools, a small model can't either.

### 1.1 Design on paper first (about 30 min)
- [ ] Time window: 60 minutes, e.g. 13:30–14:30 on a fixed date. The faults sit at 13:55 to 14:05, so there are about 25 healthy minutes before them to use as a baseline.
- [ ] Services: `checkout`, `payments`, `inventory`, plus one shared database
- [ ] Output folder `data/<scenario>-seed<n>/` holds:
  - `logs.jsonl`: `ts, service, level, message` (add `upstream` when one service calls another)
  - `metrics.csv`: one row per minute per service: `ts, service, latency_p95_ms, error_rate, cpu_pct, db_connections, db_cpu_pct`
  - `changes.json`: a list of `{ts, type: deploy|config|job|cert, service, detail}`
  - `alert.json`: `{service, symptom, start}` (FR-2)
  - `ground_truth.json`: hidden; **no tool may ever read it**

### 1.2 `incidentdesk/schemas.py` (part 1)
- [ ] An `Evidence` model: `source`, `ts`, `detail`
- [ ] A `Finding` model: `agent`, `summary`, `evidence: list[Evidence]`, `confidence` limited to 0–1 (use `Field(ge=0, le=1)`)
- [ ] Load the example from PRD p.5 into `Finding` to prove the schema matches
- (`Report` waits until M2.)

### 1.3 `generate.py`: framework
- [ ] CLI: `--scenario`, `--seed`, `--out`
- [ ] **Determinism (TR-11):** create one `random.Random(seed)` and pass it everywhere. Never use the module-level `random.*` and never use `datetime.now()`.
- [ ] Healthy traffic: per-minute metrics as baseline plus Gaussian noise; logs that are mostly INFO

### 1.4 Background noise (TR-12), present in every scenario
- [ ] Routine WARNs (e.g. a slow GC pause, a cache miss retried)
- [ ] An unrelated deploy that causes nothing (e.g. inventory v1.8.3 at 13:40)
- [ ] A harmless config change
- [ ] A few scattered ERRORs that aren't the incident

The aim is that the agents must tell the cause apart from the noise, not just find the only error in the data.

### 1.5 `scenarios/`: one definition per scenario (data, not if-statements in the generator)
- [ ] **bad-deploy:** a deploy at 14:02:10 takes payments from v2.4.0 to v2.4.1, with a config detail that shrinks the DB pool. From about 14:05, payments `db_connections` stays pinned at its max, payments logs show "connection pool exhausted", checkout logs show upstream payments timeouts, and the checkout error rate is about 14%.
- [ ] **cert-expiry:** a cert event says inventory's TLS cert expires at about 14:00. Checkout logs show TLS handshake failures when calling inventory. *Trap:* inventory's own metrics look healthy.
- [ ] **noisy-neighbour:** a scheduled batch job starts at 13:55 on the shared DB. `db_cpu_pct` climbs above 90%, and checkout logs show query timeouts. *Trap:* the unrelated deploy looks like a suspect.
- [ ] Every scenario fires a checkout alert, so the alert alone doesn't give the answer away

### 1.6 `ground_truth.json`, designed for the scorer you'll write in M4
- [ ] `{scenario, root_cause, service, trigger_ts, must_mention: [...], expected_action}`
  - e.g. `must_mention: ["v2.4.1", "connection pool"]`, `expected_action: "rollback"`

### 1.7 `runbooks/`: you write these in Markdown
- [ ] `rollback.md`, `cert-renewal.md`, `batch-jobs.md`, each with a short `##` section per step. `read_runbook` returns these sections.

### 1.8 `incidentdesk/tools.py`: the part the LLM actually sees
Rules for every tool:
- Plain types in the signature (`str` for times like `"14:05"`), because the model fills these arguments in
- The docstring is written **for the model**: what the tool does, the argument formats, what it returns
- Returns a JSON-serializable `dict`
- Output capped near 1,500 tokens (estimate as `len(json) / 4`) and truncated with a note when larger
- A bad input returns a helpful error dict instead of raising (the model reads it and can try again)
- The data folder comes from one setting (e.g. env var `INCIDENTDESK_DATA_DIR`), not from a tool argument

- [ ] `error_summary(service, start, end)`: ERROR counts per minute, plus the top 5 messages with count and first_seen. Normalize messages (strip IDs and numbers) so repeats of the same error group together.
- [ ] `metric_anomalies(service, start, end)`: build a baseline band (mean ± k·std) from the healthy minutes. For each metric that leaves the band, return when it first left, the baseline value and the peak, **sorted by first breach** (that order answers "what went abnormal first").
- [ ] `list_changes(start, end)`: every change type in the window, sorted by time
- [ ] `read_runbook(topic)`: match the topic loosely to a runbook. For an unknown topic, return the list of valid topics.

### 1.9 `tests/` (TR-13; no network, no Groq)
- [ ] Generator: the same seed gives byte-identical files (compare hashes); different seeds give different files; all 5 files exist for each scenario
- [ ] Each fault is visible (e.g. bad-deploy: payments `db_connections` at max after 14:05) and the noise is present
- [ ] Each tool, run on data generated into a pytest `tmp_path` fixture: the right top error and first_seen, the right first breach, window filtering that excludes edge cases, the token cap enforced, the unknown-topic path of `read_runbook`

### 1.10 `Makefile`
- [ ] `make data SCENARIO=bad-deploy SEED=7`
- [ ] `make test`

### 1.11 Close M1
- [ ] Exit check: `uv run pytest` passes, and all 3 scenarios generate deterministically with noise
- [ ] **Human eval:** for each scenario, call the four tools yourself from `uv run python`, and from their output alone write the root cause in one sentence. Then compare with `ground_truth.json`. If you can't solve a scenario, the agents won't either, so fix the data or the tools before starting M2.
- [ ] Commit
- [ ] **STOP → say "review M1"**
