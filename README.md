# Job Market Intelligence Platform

An explainable-AI job market intelligence platform: a multi-source,
entity-resolved, time-varying dataset of job postings, built for reproducible
research, forecasting, and dashboarding.

**Status:** the data layer is built and running. 20 scrapers, a deployed
PostgreSQL warehouse, a full normalization/entity-resolution pipeline, and a
published analysis-ready corpus. The model/serving layer (API, forecasting,
XAI) has not been started — see *Roadmap*.

---

## What this produces

A research-grade corpus of ~116,000 job postings across 19 job boards, with
every posting normalized to a canonical entity (company, location, salary,
skills, occupation) and translated into English. It is published as
denormalized Parquet shards on Hugging Face at ~692 bytes/row and as full
`pg_dump` archives.

## Architecture in one picture

```
GitHub Actions (cron)                 Kaggle GPU        Laptop (nightly 03:20)
─────────────────────                 ──────────        ─────────────────────
scrape_api   (14 src, 6h)  ─┐
scrape_html  (5 src, 12h)  ─┤
scrape_browser (Indeed, off)┘
                          ▼
  ephemeral Postgres ──► Parse→Validate→Clean→Store ──► HF shards ─┐
  (destroyed each run)                                              │
                                                                    ▼
  LOCAL POSTGRES ◄── merge ◄── run_corpus_sync.cmd ◄── pull ◄── HF ◄┘
   (system of record)  └──► export full snapshot ──► HF

  Kaggle: nllb on shards ──► translations overlay dataset ──► apply to local
```

**Why the database lives on a laptop.** Neon Free refuses writes past 1 GB, and
the corpus grows ~29 MB/day. Rather than buy capacity, the system is split by
write pattern: Postgres keeps the small, indexed relational slice; Parquet
shards carry the analysis-ready rows at 7x lower storage. CI therefore scrapes
into a **throwaway container** seeded from a Hugging Face reference snapshot,
publishes shards, and destroys the container — losing a CI database costs
nothing. The laptop's Postgres is the system of record; HF is the transport.

**Merge before export, always.** `export_corpus_to_hf.py` rebuilds `shards/`
from the database of record and deletes anything it did not just write, so an
unmerged CI row is destroyed by the very push meant to publish it.
`run_corpus_sync.cmd` enforces pull → merge → export in that order.

## The identity rule

Every join, merge, dedupe and upsert keys on the **natural key**
`(source_code, source_job_id)` — never `job_id`. `job_id` is a per-database
identity sequence, so local job 12345 and Neon job 12345 are unrelated
postings. Keying on `job_id` silently deleted 38 real rows from the published
corpus before it was caught.

## Per-source pipeline

Every scraper follows the same six stages, all under
`src/job_market_intel/scrapers/<source>/`:

| Stage | File | Role |
|---|---|---|
| Fetch | `client.py` | HTTP/browser retrieval, retry/backoff, rate limiting |
| Parse | `parser.py` | raw payload → Pydantic models |
| Validate | `validation/<src>_validator.py` | batch sanity gates (min records, max skip rate) |
| Clean | `cleaning/<src>_cleaner.py` | HTML strip, encoding fixes, salary/location extraction → `CleanedJob` |
| Store | `db/job_repository.py` | upsert with SHA-256 change detection |
| Resolve | `normalization/*` | company, geo, salary — inline at insert |

`CleanedJob` is the source-agnostic contract all 19 payloads funnel into, which
is why adding a source is mechanical rather than architectural.

**Three fetch patterns.** API (14 sources, JSON over HTTP); HTML (5, requests +
BeautifulSoup); browser (Indeed, seleniumbase undetected-Chrome — currently
disabled, as shared CI runner IPs get blocked).

## The database

`SQL_Code/job_market_intelligence_schema.sql` — 47 tables across 9 schemas.

`core` (jobs partitioned monthly by `posting_date`, descriptions, companies,
aliases) · `ref` (17 lookup tables) · `bridge` (job↔skills/benefits/languages) ·
`salary` (current + append-only history + FX rates) · `ops` (sessions, logs,
failures, query queues) · `audit` (append-only status and field-change history)
· `analytics` (facts, daily skill demand, active-jobs view) · `auth` ·
`system`.

Design decisions and their rationale are in
`DesignPrompt/job_market_intelligence_db_design.md`.

Access is centralised in `db/`: nothing outside that package may call
`create_engine()` or open a raw connection. See `docs/DATABASE_INTERFACE.md`.

## Normalization — the research value

All six stages are conservative by design: they **propose**, a human approves.
Nothing auto-merges entities or invents taxonomy terms.

| Stage | Strategy |
|---|---|
| Dedup | title+company+date-window cross-source match → `is_duplicate_of` |
| Company resolution | pg_trgm similarity → alias candidates for `review_company_aliases.py` |
| Skill extraction | keyword scan against the curated 434-skill vocabulary |
| Salary standardization | pay period × currency → USD annual |
| Geographic resolution | split `"Berlin, Germany · Remote"` → resolved `ref.locations` |
| Title classification | local embeddings → 2,046-title taxonomy, plus a `excluded_non_job` deny-list |

Translation is local (NLLB-200): titles on CPU in CI, descriptions on Kaggle
GPU, published as an additive overlay. No hosted LLM API, so no per-row cost.

Provenance is recorded on every derived row (`confidence_score`, `extracted_by`,
`classified_by`, `translated_by`) — that is what makes the dataset defensible in
an explainability audit.

## Layout

```
job-market-intel/
├── src/job_market_intel/     # installable package
│   ├── common/               # config, logging, HTTP, retry
│   ├── db/                   # engine/session/transaction/repositories
│   ├── scrapers/<source>/    # 20 scrapers, 7 files each
│   ├── cleaning/             # per-source cleaners + shared text utils
│   ├── validation/           # per-source validators
│   ├── normalization/        # entity resolution + extraction
│   ├── corpus/               # Parquet shard export to Hugging Face
│   ├── scheduler/            # APScheduler orchestration
│   └── analytics/ api/ dashboard/ ml/ xai/    # not yet implemented
├── tests/                    # unit/ + integration/ + workflow/
├── scripts/                  # dev + batch + corpus-sync tooling
├── seed/                     # 17 idempotent reference-data seeders
├── migrations/               # 13 applied schema migrations
├── analysis/                 # step30 EDA, step31 Streamlit dashboard
├── diagnostics/              # read-only scoping queries (gitignored)
├── docs/                     # interface guide, CI/DB runbook
└── config/sources.json       # THE source registry — CI builds its matrix from this
```

## Setup

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv venv
uv sync --extra dev --extra test
cp .env.example .env          # then fill in DATABASE_URL, REED_API_KEY, HF token
uv run python scripts/verify_env.py
```

PostgreSQL 16+ must be running with the schema applied
(`SQL_Code/job_market_intelligence_schema.sql`) and reference data seeded
(`python -m seed.run_all`).

## Daily commands

```bash
# the single most useful command — must print "HF agrees"
uv run python scripts/verify_local_hf_parity.py

# full nightly cycle: pull -> merge -> export
scripts/run_corpus_sync.cmd

# health
uv run python scripts/check_sources_registry.py    # "registry consistent"
uv run pytest tests -q --no-cov
uv run ruff check . && uv run ruff format .
```

## Adding a source

1. Create `src/job_market_intel/scrapers/<name>/` (client, config, models,
   parser, pipeline, exceptions).
2. Add `cleaning/<name>_cleaner.py` and `validation/<name>_validator.py`.
3. Add a line to `config/sources.json` — `code` **must** equal
   `ref.sources.source_code`, because the corpus exporter filters on it.
4. `uv run python scripts/register_source.py <name>` — registers locally *and*
   on HF; the HF copy is required or CI cannot run the source.
5. `scripts/run_<name>_scraper.py`, then the test suite.

`tests/README.md` has the long form. `scripts/check_sources_registry.py`
catches the classic failure — built, seeded, working locally, but on no cron.

## Secrets

Never commit `.env` or credentials. Needed at runtime: `DATABASE_URL`
(and `LOCAL_DATABASE_URL` / `NEON_DATABASE_URL` where applicable),
`REED_API_KEY`, `INDEED_PROXY_*`, and a Hugging Face **write** token — supply it
via `HF_TOKEN` in CI, or `CORPUS_HF_TOKEN` / `CORPUS_HF_TOKEN_FILE` locally.

> **Rotating the HF token requires four coordinated updates**: the local
> `Hugging_Face_token.txt`, the `HF_TOKEN` GitHub secret, the Kaggle creds
> dataset, and any local `.env`. Miss the GitHub one and every workflow 401s
> while still reporting success, because the shard exporter is deliberately
> fail-open. Rotate them all, then verify with a real run.

## Roadmap

Data layer complete. Not yet started:

- **API** (FastAPI read layer over the warehouse)
- **Forecasting / ML** (`ml/` is an empty package)
- **Explainability reporting** (`xai/` is an empty package)
- **CI quality gate** — pre-commit runs locally, but there is no workflow that
  runs lint/tests or the parity check on push. This is the highest-value
  remaining piece: a bad merge key or broken publish path is currently found
  by a human weeks later.
- **Source coverage** — 11 of 325 probed job-board targets are built; all 11
  came from the free-API tier. The 134 HTML-tier and 101 browser-tier targets
  are untouched. See `job_sites_by_country_SCRAPEABILITY.xlsx`.