# Conventions (follows lab-foundry)

Nightshift deliberately follows the **lab-foundry project structure and pyenv workflow** so the two repos feel the same
to work in.

| Area | Convention |
|---|---|
| Layout | Runs as an application, not an installable package. Top-level domain packages (`agents/`, `harness/`, `state/`, `science/`, `judges/`, `api/`, `ops/`, `eval/`) are importable from the repo root. No `src/`, no `pip install -e`. |
| Python | 3.11 via **pyenv**: `make pyenv` installs 3.11, creates the `nightshift` virtualenv, writes `.python-version` (`pyenv local`), and installs uv. |
| Dependencies | Declared in `requirements.in`, pinned in `requirements.txt` with `make upgrade` (uv pip compile). Install with `make install` (uv pip sync). Never `pip install` ad hoc. |
| Version | The canonical version lives in `version`. **Bump it on every PR**; CI fails if it did not increase. |
| Lint / format | ruff **0.15.14** (same pin in CI and `.pre-commit-config.yaml`), line length 122, rules E, F, UP, B, SIM, I. `make check` = CI parity (no fixes); `make ruff` autofixes. |
| Tests | `make test` (pytest, `pythonpath = ["."]`, pytest-timeout 120 s, coverage floor 75 % in CI). Tests are **offline**: the end-to-end tests drive the rig with `harness/fake_llm.py`. |
| Makefile | `make help` lists every target; `.env` is auto-loaded; `PYTHONPATH` is set to the repo root; targets call `$(VENV_PYTHON)` explicitly so they work without active pyenv shims. |
| CI | `.github/workflows/ci.yml`: lint job (ruff check, ruff format --check, version-increment check on PRs), then test job. |
