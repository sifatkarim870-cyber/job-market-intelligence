# Job Market Intelligence Platform

An explainable-AI job market intelligence platform: a multi-source,
entity-resolved, time-varying dataset of job postings, built for
reproducible research, forecasting, and dashboarding.

**Status:** Foundation stage. The database schema is designed and deployed
(see `job_market_intelligence_db_design.md` / `job_market_intelligence_schema.sql`
in project docs). This repository currently contains project scaffolding
only — no scrapers, database access code, or business logic yet.

---

## Project Overview

The platform ingests job postings from multiple sources (RemoteOK, Indeed,
LinkedIn, Glassdoor, We Work Remotely, government portals, company career
pages), cleans and normalizes them (companies, skills, locations, salaries,
titles), and exposes the result through an API, dashboard, and
research-grade dataset exports — all backed by a PostgreSQL warehouse
designed for 100M+ postings.

This repo currently implements: **Step 3 — Configure the Development
Environment**. It provides the folder structure, environment/config
handling, tooling, and utility scripts every later step builds on top of.

---

## Directory Structure

```
job-market-intel/
├── src/job_market_intel/     # Application source (installable package)
│   ├── common/                # Cross-cutting utilities; base config loader lives here
│   ├── db/                    # DB layer (SQLAlchemy engine/session, pooling) — Step 4
│   ├── scrapers/               # Base scraper framework + per-source scrapers — Step 5+
│   ├── cleaning/                # Standardization pipeline (text, dates, salary, etc.) — Step 8
│   ├── validation/               # Record validation before insert — Step 7
│   ├── normalization/             # Entity resolution: companies, skills, geo, dedup — Step 10b+
│   ├── analytics/                  # EDA + analytics-schema query helpers — Step 28
│   ├── api/                         # FastAPI REST layer + auth wiring — Step 34
│   ├── dashboard/                    # Streamlit/Dash app — Step 29
│   ├── ml/                            # Forecasting models — future phase
│   └── xai/                            # Explainability / provenance reporting — future phase
├── tests/
│   ├── unit/                  # Fast, isolated tests (no DB/network)
│   ├── integration/           # Multi-component tests (e.g. scraper -> test DB)
│   └── fixtures/              # Shared test fixtures/sample payloads
├── scripts/                   # One-off dev utilities (bootstrap, env verification)
├── logs/                      # Log output, split by subsystem (git-ignored contents)
│   ├── scrapers/  ├── database/  ├── api/  ├── scheduler/  └── system/
├── seed/                      # Idempotent reference-data seed scripts — Step 4.5
├── docs/                      # Architecture docs, design doc, schema, diagrams
├── .env.example                # Documented environment variable template
├── .gitignore
├── .pre-commit-config.yaml
├── pyproject.toml              # Project metadata + dependency groups
└── README.md
```

**Why this shape:** each `src/job_market_intel/*` package maps to exactly
one responsibility from the project's build phases. A scraper never
imports from `api/`; `analytics/` never writes to the database directly
(it reads from the `analytics` schema populated by scheduled jobs). This
keeps modules independently testable and lets multiple developers work in
different packages without stepping on each other.

---

## Installation

### 1. Prerequisites

- Python **3.11+**
- [`uv`](https://docs.astral.sh/uv/) (see rationale below) — the bootstrap
  script will offer to install it for you if missing.
- A running PostgreSQL instance with the `job_market_intelligence`
  database already created (Steps 1–2; not part of this repo's setup).

### 2. One-command setup

```bash
./scripts/bootstrap.sh
```

This creates the virtual environment, installs dependencies, copies
`.env.example` to `.env`, installs pre-commit hooks, and runs environment
verification.

### 3. Manual setup (equivalent, step by step)

```bash
# Install uv (skip if already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create the virtual environment and install dependencies
uv venv
uv sync --extra dev --extra test

# Configure environment variables
cp .env.example .env
# then edit .env with real DATABASE_URL, etc.

# Verify everything is wired correctly
uv run python scripts/verify_env.py
```

---

## Environment Setup

All configuration is driven by environment variables, loaded from a local
`.env` file (never committed — see `.gitignore`) or real environment
variables in deployment.

See `.env.example` for the full, documented list. At this stage only the
following are required:

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` \| `staging` \| `production` |
| `LOG_LEVEL` | Root logging verbosity |
| `DATABASE_URL` | Full PostgreSQL DSN |
| `DB_POOL_SIZE` / `DB_POOL_MAX_OVERFLOW` | Base connection pool sizing (tuned further in Step 4) |

Everything else in `.env.example` is a placeholder for **future** steps
and is not yet consumed by any code.

---

## First Run

```bash
uv run python scripts/verify_env.py
```

Expected output: every check passes (`[OK]`), including "Base
configuration loads and validates." If it fails, the error message names
the missing/invalid setting directly.

There is no application to "run" yet beyond this — Step 4 introduces the
first real functionality (the database interface).

---

## Development Guidelines

- **Formatting/linting:** `uv run ruff check .` and `uv run ruff format .`
  (also run automatically via pre-commit).
- **Type checking:** `uv run mypy src`.
- **Tests:** `uv run pytest` (test suite itself is built out in Step 14.5;
  the harness — `pytest` + `pytest-cov` + `tests/` layout — is available
  now).
- **Commits:** install hooks once via `uv run pre-commit install`
  (already done by `bootstrap.sh`); hooks run ruff, mypy, and basic
  hygiene checks before every commit.
- **Branching:** see *Git Configuration* in the architecture notes —
  short-lived `feature/<name>` branches off `main`, merged via PR.
- **Secrets:** never commit `.env` or real credentials. Only
  `.env.example` (placeholders) is tracked.
- **New modules:** add code to the package matching its responsibility
  (see Directory Structure above); don't create new top-level packages
  without updating this README.

---

## Roadmap

See the project workflow document for the full build plan (Steps 1–36
across 8 phases: Foundation, Scraping Framework, Automation, Source
Expansion, Data Quality, Analytics, Production Readiness, Documentation).
This repository will grow in place as each step lands.
