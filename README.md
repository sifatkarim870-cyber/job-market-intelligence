# Job Market Intelligence Platform

An explainable-AI job market intelligence platform: a multi-source,
entity-resolved, time-varying dataset of job postings, built for reproducible
research, forecasting, and dashboarding.

**Status:** the data layer is built and running. **286 registered sources
(233 enabled)**, **279,859 postings** from **255 boards with data**, a deployed
PostgreSQL warehouse, a normalization/entity-resolution pipeline, and a
published analysis-ready corpus. The model/serving layer (API, forecasting,
XAI) has not been started — see *Roadmap*.

---

## What this produces

A research corpus of **279,859 job postings** across **255 boards** (286
registered, 233 enabled), published as denormalized Parquet shards on Hugging
Face and as full `pg_dump` archives. English descriptions: 88.8%.
Title-classified: 247,301 attempted (182,171 matched, 65.1%). Skills: 71.6%.
Salary amount: 34.0%, USD-normalized: 26.3%. Location resolved: 97.0%. The
full, generated table is in [`reports/current_metrics.md`](reports/current_metrics.md);
run `python scripts/publish_metrics.py` to refresh it.

**The dataset is not globally representative.** Persian is 29.0% of rows and
20.5% have no country; employer identity is unresolved for 17.2%. See the
[dataset card](docs/DATASET_CARD.md) before using it for cross-country claims.

## Architecture in one picture

```
GitHub Actions (cron)                 Kaggle GPU        Laptop (nightly 03:20)
─────────────────────                 ──────────        ─────────────────────
scrape_api   (48 src, 6h)   ─┐
scrape_html  (166 src, 12h) ─┤
scrape_browser (19 src, 24h)┘
                          ▼
  ephemeral Postgres ──► Parse→Validate→Clean→Store ──► HF shards ─┐
  (destroyed each run)                                              │
                                                                     ▼
  LOCAL POSTGRES ◄── merge ◄── run_corpus_sync.cmd ◄── pull ◄── HF ◄┘
   (system of record)  └──► export full snapshot ──► HF

  Kaggle: nllb on shards ──► translations overlay dataset ──► apply to local
```

**Why the database lives on a laptop.** The corpus grows ~29 MB/day, far more
than a free hosted Postgres would hold. Rather than buy capacity, the system is
split by write pattern: Postgres keeps the small, indexed relational slice;
Parquet shards carry the analysis-ready rows at a fraction of the storage. CI
therefore scrapes into a **throwaway container** seeded from a Hugging Face
reference snapshot, publishes shards, and destroys the container — losing a CI
database costs nothing. The laptop's Postgres is the system of record; HF is
the transport.

**Merge before export, always.** `export_corpus_to_hf.py` rebuilds `shards/`
from the database of record and deletes anything it did not just write, so an
unmerged CI row is destroyed by the very push meant to publish it.
`run_corpus_sync.cmd` enforces pull → merge → export in that order.

## The identity rule

Every join, merge, dedupe and upsert keys on the **natural key**
`(source_code, source_job_id, posting_date)` when `posting_date_source =
'source'` — never `job_id`. `job_id` is a per-database identity sequence, so
local job 12345 and CI job 12345 are unrelated postings. Keying on `job_id`
silently deleted 38 real rows from the published corpus before it was caught.

A `posting_date_source = 'scrape_fallback'` date is **not** identity: it is the
scrape date substituted when the publisher omitted one, so it changes on every
run. Those rows are matched on `(source_code, source_job_id)` and keep their
original stored date. Time-series analyses must filter on `posting_date_source
= 'source'`. The 2026-11-08 labelling pass relabelled 26,843 pre-existing
fallback rows and collapsed the 3,488 rows the old fallback had duplicated, but
undated boards keep producing more: **78,704 rows (28.1%)** currently carry the
`scrape_fallback` label.

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

`CleanedJob` is the source-agnostic contract all payloads funnel into, which is
why adding a source is mechanical rather than architectural. The package holds
**92 bespoke scraper packages** plus the generic HTML and browser engines,
driven by **95 `run_*scraper*.py` runner scripts**.

**Three fetch patterns.** API (51 registered / 48 enabled, JSON over HTTP); HTML
(202 registered / 166 enabled, mostly the generic config-driven engine, backed
by 165 site JSON configs); browser (33 registered / 19 enabled;
SeleniumBase/Playwright, 32 site configs).

## The database

`../SQL_Code/job_market_intelligence_schema.sql` — 9 schemas and ~124
base relations/partitions.

`core` (jobs monthly range-partitioned by `posting_date` — 61 partitions,
2024-08 through 2029-07, plus a default partition — descriptions, companies,
aliases) · `ref`
(17 lookup tables) · `bridge` (5 job↔skill/benefit/language association tables)
· `salary` (current salaries + append-only history + a currency-rate table) ·
`ops` (sessions, logs, failures, query queues) · `audit` (append-only status and
field-change history) · `analytics` (facts, daily skill demand, active-jobs view)
· `auth` · `system`.

`core.jobs` also carries **`posting_date_source`**: `source` when the publisher
supplied the date, `scrape_fallback` when the first scrape date was substituted.
78,704 rows are fallbacks; time-series queries must filter on `source`.

Design decisions and their rationale are in
`../DesignPrompt/job_market_intelligence_db_design.md`.

Runtime scraper access goes through `db/`; batch and corpus-sync scripts use
their own SQLAlchemy connections by design (they must run without the app
settings). See `docs/DATABASE_INTERFACE.md`.

## Normalization — the research value

All six stages are conservative by design: they **propose**, a human approves.
Nothing auto-merges entities or invents taxonomy terms.

| Stage | Strategy | Measured coverage |
|---|---|---:|
| Dedup | title+company+date-window cross-source match → `is_duplicate_of` | 31 flagged cross-source; 0 same-source groups |
| Company resolution | pg_trgm similarity → alias candidates; never auto-merged | 82.8% real employer; 17.2% sentinel |
| Skill extraction | regex against a 434-term taxonomy over title + description | 71.6% |
| Salary standardization | pay period × 21 static currency rates → USD annual | 26.3% (77.3% of disclosed amounts) |
| Geographic resolution | split `"Berlin, Germany · Remote"` → `ref.locations` | 97.0% |
| Title classification | local embeddings → a 2,046-title taxonomy, plus deny-list | 247,301 attempted; 65.1% matched |

Translation is local (NLLB-200): descriptions on Kaggle GPU, published as an
additive overlay; titles were backfilled locally. No hosted LLM API, so no
per-row cost.

Provenance is **partial**: `title_classified_by` is written for the title runs,
but `translated_by` is NULL for 261,771 of 279,859 rows (93.5%; the older
backfills did not stamp it), and FX normalization uses a static in-code rate
table (`_USD_CONVERSION_RATES`) rather than the (currently empty)
`salary.currency_exchange_rates` table, so no per-row `fx_date` is stored. The
dataset card states these gaps; it does not claim full provenance.

## Layout

```
job-market-intel/
├── src/job_market_intel/     # installable package
│   ├── common/               # config, logging, HTTP, retry
│   ├── db/                   # engine/session/transaction/repositories
│   ├── scrapers/<source>/    # 92 bespoke packages + 2 generic engines
│   ├── cleaning/             # per-source cleaners + shared text utils
│   ├── validation/           # per-source validators
│   ├── normalization/        # entity resolution + extraction
│   ├── corpus/               # Parquet shard export to Hugging Face
│   ├── scheduler/            # APScheduler orchestration
│   └── analytics/ api/ dashboard/ ml/ xai/    # not yet implemented
├── tests/                    # 244 files, ~3,940 test functions
├── scripts/                  # 95 source runners + batch, corpus-sync, metrics
├── seed/                     # 21 idempotent reference-data seeders
├── migrations/               # 13 applied schema migrations
├── analysis/                 # step30 EDA, step31 Streamlit dashboard
├── diagnostics/              # read-only scoping queries (gitignored)
├── reports/                  # generated coverage/metrics snapshots
├── docs/                     # interface guide, dataset card, CI/DB runbook
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

PostgreSQL **18+** must be running with the schema applied
(`../SQL_Code/job_market_intelligence_schema.sql`) or the migration chain, and
reference data seeded (`python -m seed.run_all`). The identity-on-partitioned-
table feature in `core.jobs` requires 17+, but CI and the laptop use 18.

## Daily commands

```bash
# the single most useful command — must print "HF agrees"
uv run python scripts/verify_local_hf_parity.py

# full nightly cycle: pull -> merge -> export
scripts/run_corpus_sync.cmd

# health
uv run python scripts/check_sources_registry.py    # "registry consistent"
uv run python scripts/publish_metrics.py           # refresh reports/current_metrics.md
uv run pytest tests -q --no-cov
uv run ruff check . && uv run ruff format .
```

## Adding a source

1. Create `src/job_market_intel/scrapers/<name>/` (client, config, models,
   parser, pipeline, exceptions), or add a `sites/<name>.json` config if a
   generic HTML/browser engine already fits.
2. Add `cleaning/<name>_cleaner.py` and `validation/<name>_validator.py`.
3. Add a line to `config/sources.json` — `code` **must** equal
   `ref.sources.source_code`, because the corpus exporter filters on it.
4. `uv run python scripts/register_source.py <name>` — registers locally *and*
   on HF; the HF copy is required or CI cannot run the source.
5. `scripts/run_<name>_scraper.py`, then the test suite.

`tests/README.md` has the long form. `scripts/check_sources_registry.py`
catches the classic failure — built, seeded, working locally, but on no cron.

## Secrets

Never commit `.env` or credentials. Needed at runtime: `DATABASE_URL`,
`REED_API_KEY`, `INDEED_PROXY_*`, and a Hugging Face **write** token — supply it
via `HF_TOKEN` in CI, or `CORPUS_HF_TOKEN` / `CORPUS_HF_TOKEN_FILE` locally.

> **Rotating the HF token requires four coordinated updates**: the local
> `Hugging_Face_token.txt`, the `HF_TOKEN` GitHub secret, the Kaggle creds
> dataset, and any local `.env`. Miss the GitHub one and every workflow 401s
> while still reporting success, because the shard exporter is deliberately
> fail-open. Rotate them all, then verify with a real run.

## Roadmap

The data layer is operational. Not yet started:

- **API** (FastAPI read layer over the warehouse)
- **Forecasting / ML** (`ml/` is an empty package)
- **Explainability reporting** (`xai/` is an empty package)
- **Normalization depth** — skills 71.6%, salary USD 26.3%, employer 82.8% are
  the honest ceilings of the current extractors/rates, not missing runs. The
  dataset card lists each limitation.
- **Source coverage** — 286 registered sources (233 enabled); 255 have rows and
  31 registered sources currently have zero (built but blocked in CI, or
  awaiting a key). **53 registered sources are disabled**, almost all against a
  datacenter-IP wall (Cloudflare/captcha) that a residential proxy would clear;
  the single 621-site master workbook in
  `../../job_sites_uniform_master.xlsx` remains the target list, and
  `docs/source_registration_list.md` + `docs/backlog_disposition_2026-11-12.md`
  carry the measured per-site reasons.
- **Quality gate** — `quality.yml` runs ruff, pytest and the env-consistency
  test on push/PR. The nightly parity check is still local (`run_corpus_sync`),
  not CI.

**Recent activity.** Since 2026-11-08 the November 2026 source push has grown
the registry from 163 to 286 sources (+123; enabled 131 → 233) and the corpus
from 174,422 to 279,859 rows (+105,437), clearing the 188-row backlog sweep. Two
boards landed on 2026-11-20 — Emploi.ci (Côte d'Ivoire) and JobNet (Myanmar),
both API sources, with new MMK and XOF FX rates. New boards span China, Japan,
Russia, Vietnam, Mozambique, Taiwan, Slovenia, Luxembourg, Tanzania, Norway,
Nepal, Thailand, Croatia, North Macedonia, South Korea, Uruguay, Canada,
Bangladesh, Pakistan, Nigeria and Portugal, among others. The system-map/runbook
HTML in the parent folder is a **historical snapshot**;
`reports/current_metrics.md` is the live source of truth.

## License

Code is **MIT** (see [`LICENSE`](LICENSE)); the published dataset is
**CC-BY-4.0** (see [`docs/DATA_LICENSE.md`](docs/DATA_LICENSE.md)). The
Hugging Face dataset card repeats the data license and the limitations above.
The repository was previously marked “Proprietary” while being public; that
contradiction is resolved here.