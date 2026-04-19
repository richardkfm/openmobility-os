# CLAUDE.md — OpenMobility OS Contributor Guide

This file contains binding instructions for all contributors and AI assistants
working on OpenMobility OS. Read it before making changes.

## Project Philosophy

OpenMobility OS is the missing operating system between open mobility data and
political decisions. It is **not** a consumer routing tool. It is a decision,
prioritization, and transparency platform for municipalities, city planners,
local politics, NGOs, journalists, researchers, and citizens.

**Core principles — never violate:**

1. **City-agnostic.** No logic may be hard-wired to Leipzig or any specific
   city, country, or administrative structure. Leipzig is one demo workspace
   among many. Every feature must work for an arbitrary municipality anywhere
   in the world.
2. **API-first and connector-based.** Data enters the system through
   well-defined adapters. Never assume a specific data source layout, schema,
   or vendor in core code.
3. **Transparent scoring.** No black-box recommendations. Every score must
   expose its sources, inputs, calculation formula, and uncertainty level.
4. **Self-hosting first.** Every change must keep `docker compose up` working
   end-to-end. Never introduce runtime dependencies on proprietary SaaS that
   a municipality cannot replace with an open alternative.
5. **Open public layer.** Read access is always public and requires no login.
   Write actions are protected by a shared `ADMIN_TOKEN` in the MVP, and can
   be upgraded to full RBAC later.
6. **Internationalization by default.** Every user-facing string goes through
   Django's `gettext`. Never hardcode German or English copy in templates,
   views, or Python code.

## Architecture Overview

- **Backend:** Django 5 + GeoDjango + PostGIS + Django REST Framework
- **Frontend:** Django templates + Tailwind CSS + HTMX + Alpine.js + MapLibre GL JS
- **Database:** PostgreSQL 16 with PostGIS 3
- **Deployment:** Docker Compose (one web container + one database container)
- **Multi-tenancy:** Path-based URLs (`/<workspace-slug>/...`); a single
  installation hosts N workspaces
- **Auth:** Shared `ADMIN_TOKEN` for write operations. No user management in the MVP.

### Django app boundaries

| App           | Responsibility                                               |
|---------------|--------------------------------------------------------------|
| `workspaces`  | City/municipality entities, goals, districts                 |
| `datasets`    | Data sources and normalized feature sets                     |
| `connectors`  | Pluggable adapters (CSV, GeoJSON, OSM Overpass, stubs, ...)  |
| `measures`    | Rule-based engine + transparent scoring                      |
| `goals`       | Workspace-level policy goals and KPI targets                 |
| `maps`        | GeoJSON API endpoints consumed by MapLibre                   |
| `api`         | Public read-only REST API                                    |

### Path-based multi-tenancy

Never write code that assumes a single workspace exists. Every view that
touches workspace data receives the slug from the URL and scopes all queries
to that workspace. Cross-workspace data leakage is a bug.

## Versioning Policy

We follow [Semantic Versioning 2.0.0](https://semver.org/):

- **MAJOR.MINOR.PATCH**
- **MAJOR** — breaking changes to the public API, data model (requires a
  migration guide), connector interface, or deployment layout.
- **MINOR** — new features, new connectors, new measure rules, new languages,
  new layer kinds.
- **PATCH** — bug fixes, documentation updates, non-breaking refactors.

The current version lives in the `VERSION` file at the repo root. This is
the single source of truth. Django reads it at boot and exposes it under
`/about/` and `/api/v1/meta/`.

**When to bump:**

- Every merge to `main` that changes user-visible behavior must bump the
  version.
- Pre-launch development happens on the `0.x.y` line. `1.0.0` is reserved
  for the first public release.

## Changelog Policy

We maintain `CHANGELOG.md` at the repo root in
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Each release
section uses these subsections as needed:
`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

**Rules:**

- Every pull request **must** add at least one line to the `[Unreleased]`
  section.
- Entries are written from the user's perspective, not the developer's.
  - Good: `Added CSV connector with automatic detection of coordinate columns`
  - Bad: `refactored csv.py to use pandas`
- When cutting a release: move the `[Unreleased]` content under a new version
  heading with an ISO date, then create a fresh empty `[Unreleased]`.
- Breaking changes must be prefixed with `**BREAKING:**` and include a short
  migration note.

## README Policy

`README.md` is the first impression for anyone discovering the project.
It must stay current with:

- A working quickstart — someone cloning today must succeed in under 15 minutes
- A feature list that matches what is actually implemented (mark planned
  connectors as "planned", not "available")
- Screenshots that reflect the current UI, not older versions
- The current list of deployment modes (`public-demo`, `single-city`,
  `multi-city`) and how to switch between them
- A link to `CHANGELOG.md` and a current version badge

**Every pull request that adds or removes a user-facing feature must update
the README in the same commit.**

## Contribution Workflow

1. Create a feature branch from `main`.
2. Make changes. Keep commits small, focused, and self-explanatory.
3. Update `CHANGELOG.md` under the `[Unreleased]` section.
4. Update `README.md` if user-facing behavior changed.
5. Bump `VERSION` if this work warrants a release (see Versioning Policy).
6. Run `docker compose up --build` and manually verify the core flows still work.
7. Run the test suite (`python manage.py test`).
8. Open a pull request. Reference any related issues.

## Code Style

- **Python:** Black + Ruff, line length 100
- **HTML templates:** 2-space indent, one tag per line for readability
- **JavaScript:** no framework — vanilla JS plus Alpine.js and MapLibre only
- **CSS:** Tailwind utility-first. Custom CSS only in
  `backend/static/css/components.css` for things Tailwind cannot express.

## Testing

- `python manage.py test` must pass before every commit.
- New connectors must ship with unit tests using fixture data (no network
  calls in tests).
- New measure rules must have golden-file tests run against seed data.
- UI changes should be manually verified inside Docker, not just unit-tested,
  because templates and the JS layer are not fully covered.

## Things Never to Do

- Never couple core code to a specific city, country, language, or administrative system.
- Never hardcode Overpass queries outside the connector template system.
- Never add runtime dependencies on proprietary APIs (Google Maps, Mapbox
  paid tier, Here, TomTom, ...) without a fully functional free/open fallback.
- Never bypass `gettext` for user-facing strings.
- Never commit API keys, tokens, passwords, or production credentials.
- Never break `docker compose up` without updating the quickstart in the
  same commit.
- Never merge a pull request without updating `CHANGELOG.md`.
- Never add an "only for Leipzig" shortcut, even temporarily.
