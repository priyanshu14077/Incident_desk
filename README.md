# IncidentDesk

A demo of multi-agent orchestration: when a synthetic ShopCo outage fires, three specialist agents investigate in parallel and an Incident Commander writes a root-cause report. Built on Google ADK with Groq models via LiteLlm, and Scion for the multi-container mode. All data is synthetic.

See `CHECKLIST.md` for build progress and the PRD PDF for the full spec.

```bash
uv sync
cp .env.example .env        # add GROQ_API_KEY
make check-groq             # model IDs + real rate limits
make data SCENARIO=bad-deploy SEED=7
make test
make web                    # http://localhost:8000
```
