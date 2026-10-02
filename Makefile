define HELP
make [TARGET]

TARGET
    pyenv                      Create the Python virtual environment (pyenv)
    install                    Sync Python deps from requirements.txt
    upgrade                    Recompile requirements.txt from requirements.in
    pre-commit                 Install pre-commit hooks
    check                      Lint + format check (ruff; no fixes — CI parity)
    ruff                       Autofix imports + format (ruff)
    test / tests               Run the test suite (offline: fake LLM, no network, no DB)
    test-last-fail             Re-run the tests that failed last time
    rig                        Run campaigns against LLM_BASE_URL (CAMPAIGNS=3 RUN=runs/latest RIGSPEC=rigs/...)
    demo                       Run campaigns offline with the deterministic fake LLM (RUN=runs/demo)
    floor                      Lab-floor API + legacy page on :$$FLOOR_PORT for RUN (default runs/latest)
    ui-install                 Install the lab UI's Node dependencies (ui/, Node >= 20)
    ui                         The lab UI (Next.js) on :$$UI_PORT; needs make floor running
    ui-check                   Lint, typecheck, test and build the lab UI (CI parity)
    replay                     Build a self-contained replay page for RUN
    labd                       Run the lab continuously until its goal; pings on goal, data needs, stalls (EVERY=3600)
    knowledge                  What the lab knows across runs: the PI's brief (RIGSPEC=rigs/...; JSON=1 for the graph)
    calibrate                  Lab self-calibration benchmark (planted-truth hypotheses, ~3 min)
    protocols                  Promotion-protocol benchmark (ratchet vs gates, ~4 min)
    collect                    Poll bike-share GBFS availability every 5 min into data/gbfs (SYSTEM=chi|bkn)
    ingest                     Download and aggregate bike-share trip months into data/bikeshare (SYSTEM=chi|bkn)
    censor                     Reduce collected GBFS snapshots to the station-day censoring table (SYSTEM=chi|bkn)
    lock-month                 Lock champion + baseline forecasts for month L+2 (SYSTEM, RUN or CHAMPION=k1,k2)
    score-month                Score a locked month once published (SYSTEM, MONTH=yyyymm)
    clean                      Remove caches and __pycache__ dirs

See README.md for setup.
endef
export HELP

help:
	@echo "$$HELP"


# Auto-load .env so LLM_BASE_URL, REASONING_MODEL, etc. are visible to all targets.
ifneq (,$(wildcard .env))
    include .env
    export
endif


# ---------------------- Python ----------------------

PYTHON_VERSION  = 3.11
PYENV_NAME      = nightshift

FLOOR_PORT     ?= 18765
UI_PORT        ?= 18088
RUN            ?= runs/latest
CAMPAIGNS      ?= 3
SYSTEM         ?= chi
RIGSPEC        ?=

# Repo root on the import path for `python -m ...` (top-level packages, no install step).
export PYTHONPATH := $(CURDIR)

# Explicit env prefix so uv / pip work even when pyenv shims aren't active
# in the non-interactive Make shell (same as lab-foundry).
VENV_PREFIX = $(shell pyenv prefix $(PYENV_NAME) 2>/dev/null)
VENV_PYTHON = $(VENV_PREFIX)/bin/python
UV          = VIRTUAL_ENV=$(VENV_PREFIX) uv

pyenv: # Create the Python virtualenv (pyenv). Idempotent.
	pyenv install -s $(PYTHON_VERSION)
	@pyenv virtualenvs --bare | grep -qx "$(PYENV_NAME)" \
		|| pyenv virtualenv $(PYTHON_VERSION) $(PYENV_NAME)
	pyenv local $(PYENV_NAME)
	# Make expands every recipe line before running the first, so $(VENV_PYTHON) would be empty on a fresh
	# machine; resolve the prefix in the shell after the virtualenv exists.
	"$$(pyenv prefix $(PYENV_NAME))/bin/python" -m pip install --upgrade pip
	"$$(pyenv prefix $(PYENV_NAME))/bin/python" -m pip install uv

upgrade:
	$(UV) pip compile -U requirements.in -o requirements.txt

install:
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(UV) pip sync requirements.txt

pre-commit:
	pre-commit install

.PHONY: check ruff test tests test-last-fail rig demo floor replay calibrate protocols labd reply requests events knowledge collect ingest censor lock-month score-month ui-install ui ui-check clean

# Non-mutating lint + format check — mirrors the CI `lint` job. Use `make ruff` to autofix.
check:
	ruff check .
	ruff format --check .

ruff:
	ruff check --select I --fix
	ruff format

# ---------------------- Tests ----------------------
# Fully offline: the end-to-end tests drive the whole rig with harness/fake_llm.py.
test tests:
	$(VENV_PYTHON) -m pytest --cov

test-last-fail:
	$(VENV_PYTHON) -m pytest --lf

# ---------------------- The lab ----------------------

rig:
	$(VENV_PYTHON) -m ops.nightshift run --campaigns $(CAMPAIGNS) --root $(RUN) $(if $(RIGSPEC),--rigspec $(RIGSPEC))

demo:
	$(VENV_PYTHON) -m ops.nightshift run --fake-llm --no-knowledge --campaigns 2 --root $(if $(filter runs/latest,$(RUN)),runs/demo,$(RUN)) $(if $(RIGSPEC),--rigspec $(RIGSPEC))

floor:
	$(VENV_PYTHON) -m ops.nightshift floor serve $(RUN) --port $(FLOOR_PORT)

replay:
	$(VENV_PYTHON) -m ops.nightshift floor build $(RUN) $(RUN)/replay.html

labd:
	$(VENV_PYTHON) -m ops.labd --rigspec rigs/bikeshare-lab.json --every $(or $(EVERY),3600)

reply:
	$(VENV_PYTHON) -m ops.nightshift reply --rigspec $(or $(RIGSPEC),rigs/bikeshare-lab.json) $(if $(REQUEST),--request $(REQUEST)) "$(MSG)"

requests:
	$(VENV_PYTHON) -m ops.nightshift requests --rigspec $(or $(RIGSPEC),rigs/bikeshare-lab.json) $(if $(ALL),--all)

events:
	$(VENV_PYTHON) -m ops.events_ingest --system $(or $(SYSTEM),chi)

knowledge:
	$(VENV_PYTHON) -m ops.nightshift knowledge $(if $(RIGSPEC),--rigspec $(RIGSPEC)) $(if $(JSON),--json) $(if $(IMPORT),--import $(IMPORT))

calibrate:
	$(VENV_PYTHON) -m eval.lab_calibration

protocols:
	$(VENV_PYTHON) -m eval.promotion_protocols

ingest:
	$(VENV_PYTHON) -m ops.bikeshare_ingest --system $(SYSTEM)

lock-month:
	$(VENV_PYTHON) -m ops.prospective lock --system $(SYSTEM) $(if $(CHAMPION),--champion $(CHAMPION),--run $(RUN))

score-month:
	$(VENV_PYTHON) -m ops.prospective score --system $(SYSTEM) --month $(MONTH)

censor:
	$(VENV_PYTHON) -m ops.gbfs_reduce --system $(SYSTEM)

collect:
	$(VENV_PYTHON) -m ops.gbfs_collect --system $(SYSTEM) --every 300

ui-install:
	cd ui && npm ci

ui:
	cd ui && NIGHTSHIFT_FLOOR_API=http://127.0.0.1:$(FLOOR_PORT) npx next dev -p $(UI_PORT)

ui-check:
	cd ui && npm run lint && npx tsc --noEmit && npm test && npm run build

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
