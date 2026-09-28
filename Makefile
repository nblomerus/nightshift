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
    floor                      Live lab-floor dashboard on :$$FLOOR_PORT for RUN (default runs/latest)
    replay                     Build a self-contained replay page for RUN
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

FLOOR_PORT     ?= 8765
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

.PHONY: check ruff test tests test-last-fail rig demo floor replay calibrate protocols collect ingest censor lock-month score-month clean

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
	$(VENV_PYTHON) -m ops.nightshift run --fake-llm --campaigns 2 --root $(if $(filter runs/latest,$(RUN)),runs/demo,$(RUN)) $(if $(RIGSPEC),--rigspec $(RIGSPEC))

floor:
	$(VENV_PYTHON) -m ops.nightshift floor serve $(RUN) --port $(FLOOR_PORT)

replay:
	$(VENV_PYTHON) -m ops.nightshift floor build $(RUN) $(RUN)/replay.html

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

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
