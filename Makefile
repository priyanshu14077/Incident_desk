SCENARIO ?= bad-deploy
SEED ?= 7
SCENARIOS := bad-deploy cert-expiry noisy-neighbour

.PHONY: data data-all test web check-groq clean

data:  ## make data SCENARIO=bad-deploy SEED=7
	uv run python generate.py --scenario $(SCENARIO) --seed $(SEED)

data-all:
	@for s in $(SCENARIOS); do for seed in 1 2 3; do uv run python generate.py --scenario $$s --seed $$seed; done; done

test:
	uv run pytest -q

web:  ## ADK dev UI on http://localhost:8000 (tools read the newest run in data/)
	uv run adk web

check-groq:  ## confirm model IDs and read real rate limits (3 tiny requests)
	uv run python scripts/check_groq.py

clean:
	rm -rf data
