# Contributing to OpenMobility OS

Thank you for your interest in contributing! OpenMobility OS is a free,
open-source platform for municipal mobility decision-making. We welcome
contributions from planners, developers, data enthusiasts, and municipalities
worldwide.

Read [CLAUDE.md](CLAUDE.md) before you start — it contains the binding
project philosophy and all governance rules.

---

## Quick Start for Contributors

```bash
git clone https://github.com/richardkfm/openmobility-os.git
cd openmobility-os
cp .env.example .env          # edit ADMIN_TOKEN and SECRET_KEY
docker compose up --build
```

Visit `http://localhost:8000`. You should see the platform with three demo
workspaces (Leipzig, Musterstadt, Muster-Landkreis).

---

## Types of Contributions

### Bug Reports

Open an issue using the **Bug report** template. Include:
- Exact steps to reproduce
- Expected vs. actual behavior
- Your deployment setup (Docker version, OS, `VERSION` file contents)

### Feature Requests

Open an issue using the **Feature request** template. Describe:
- The use case (which municipality, which planner workflow)
- Why the current platform doesn't solve it
- Rough idea of what the feature would look like

### New Connector Proposals

Each new connector brings a new class of open data sources into the platform.
Use the **New connector proposal** template. Before starting:
- Check the existing stubs in `backend/connectors/stubs.py`
- Read `backend/connectors/base.py` — the interface every connector must implement
- Include sample data (or a public URL) for testing

### Code Changes

1. Fork the repository and create a feature branch from `main`
2. Make your changes (keep commits small and focused)
3. Update `CHANGELOG.md` under `[Unreleased]` (see [CLAUDE.md](CLAUDE.md))
4. Update `README.md` if user-facing behavior changed
5. Bump `VERSION` if warranted (see versioning rules in [CLAUDE.md](CLAUDE.md))
6. Run `docker compose up --build` and verify core flows still work
7. Run the test suite: `python manage.py test`
8. Open a pull request using the **Pull request** template

---

## What Makes a Good Pull Request

- **One logical change per PR.** Don't bundle a bug fix with a new feature.
- **City-agnostic.** Nothing hard-wired to Leipzig, Germany, or any single
  administrative structure. See CLAUDE.md principle 1.
- **Tests included.** New connectors need unit tests with fixture data
  (no live network calls). New measure rules need golden-file tests.
- **i18n respected.** Every new user-facing string goes through
  `{% trans %}` / `gettext_lazy`. No hardcoded copy.
- **CHANGELOG updated.** Every PR must add at least one line to `[Unreleased]`.

---

## Development Setup (without Docker)

```bash
# Requires Python 3.12+, PostgreSQL 16 + PostGIS 3, GDAL

python -m venv venv
source venv/bin/activate    # bash / zsh / sh
# fish:        source venv/bin/activate.fish
# csh / tcsh:  source venv/bin/activate.csh
# PowerShell:  venv\Scripts\Activate.ps1
pip install -r requirements.txt

export DJANGO_SETTINGS_MODULE=config.settings.development
export PYTHONPATH=$(pwd)/backend

cd backend
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

---

## Project Structure

```
backend/
  config/         Django settings, URLs, WSGI
  workspaces/     City/municipality models and views
  datasets/       DataSource and NormalizedFeatureSet models
  connectors/     Pluggable data adapters
  measures/       Rule engine and transparent scoring
  goals/          Workspace-level policy goals
  maps/           GeoJSON API for MapLibre
  api/            Public read-only REST API
  templates/      Django HTML templates
  static/         Pre-compiled CSS + JS
  locale/         Translation files (de, en)

config/workspaces/  YAML seed configs per workspace
docker/             Dockerfile, entrypoint.sh
```

---

## Code Style

- **Python:** Black + Ruff, line length 100
- **HTML templates:** 2-space indent, one element per line
- **JavaScript:** Vanilla JS + Alpine.js + MapLibre only — no npm, no bundler
- **CSS:** Tailwind utility-first; custom CSS only in `backend/static/css/components.css`

---

## Questions

Open a [discussion](https://github.com/richardkfm/openmobility-os/discussions)
or tag your issue with `question`. We're happy to help.
