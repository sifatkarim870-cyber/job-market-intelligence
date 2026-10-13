# Changelog

All notable changes to this project are documented here.

## [Unreleased] - 2026-10-13

### Fixed

- **Kaggle `jmi-translate-hf` was silently dead.** The scheduled translation
  kernel had been running against a stale HF write token (`hf_Ctte…`, rotated
  away months earlier) mounted from `mskarim870/jmi-translate-hf-creds`, so
  every overlay upload 401'd. Separately its `docker_image` was the public
  `kaggle-images/python` build rather than the pinned `kaggle-private-byod`
  image, whose torch has no CUDA — every `translate_shard()` raised
  `module 'torch._C' has no attribute '_cuda_setDevice'`. Result: 0 rows
  translated, 0-byte overlay, and `"stage": "done"` with exit code 0. Fixed all
  three: token rotated, `docker_image` pinned to the BYOD image, and the kernel
  now aborts non-zero on `device_count() == 0`.
- **Kaggle kernel failed silently on upload failure and on zero progress.**
  `main()` returned 0 unconditionally. It now returns 1 when the final overlay
  upload fails, and when a run scanned rows but produced neither a translation
  nor a GPU chunk.
- **No HF token preflight in the translation kernel.** A bad token is now
  detected via `whoami()` in the first seconds, before the GPU pass, instead of
  after the full budget is spent and every produced row is discarded at upload.
- **Live Neon production password in plaintext.** `diagnostics/run_diagnostics.py`
  carried a hard-coded production DSN as `DEFAULT_DSN` so it would "just run".
  It now requires `NEON_PROD_URL` and exits 2 with instructions if unset.
- **Stale Hugging Face dataset card.** `README.md` described the retired Neon
  architecture, a `shards_local/` layout and `part-0.parquet` paths that no
  longer exist, a sources table missing 4 sources, and a `remote_work_type`
  column that is not in the shard schema. Rewritten against the actual repo.
- **Stale `RESTORE.md`** — presented `neon_full.dump` as the nightly artifact
  (it is `corpus_full.dump`; the Neon dump is historical) and did not mention
  that the laptop is the database of record and a single point of failure.
- **Removed orphan `export_report.json`** from the corpus dataset. No code in the
  repo generated it, nothing referenced it, and its stale contents (105,906
  rows / 18 shards / 69.86 MiB) contradicted the actual corpus (116,497 rows /
  19 shards / ~407 MiB).
- **`README.md` and `CHANGELOG.md` badly out of date.** The README described the
  repo as "scaffolding only — no scrapers, database access code, or business
  logic yet" at "Step 3", which was ~2 months and 19 scrapers out of date.
  Rewritten to describe the system as built.

### Verified

- GitHub Actions: 5/5 workflows active; all 4 failures in the last 40 runs are
  confined to the 2026-10-11 Neon→ephemeral-container migration window.
- Corpus integrity: summed Parquet row counts across all 19 shards = 116,497,
  exactly matching the published snapshot claim.
- HF token round-trip against the Kaggle-mounted creds dataset confirmed equal.

### Known issues (unchanged, still open)

- No CI quality gate. pre-commit is local-only; no workflow runs lint, tests or
  `verify_local_hf_parity.py` on push. Highest-value remaining work.
- The laptop's PostgreSQL is the system of record and nothing monitors whether
  its nightly sync still runs. HF would drift ahead silently.
- Two Kaggle GPU kernels with near-identical names (`nllb-translate`,
  `jmi-translate-hf`). Confirm exactly one owns the schedule and de-schedule
  the other, or the same class of silent failure recurs.
- `ref.sources.is_active` duplicates `config/sources.json`; `activate_sources.py`
  keeps them in step, but they can drift.
- Indeed is `enabled: false`; `scrape_browser.yml` builds an empty matrix. Its
  193 rows are historical and will not grow. Re-enabling needs a dedicated
  runner.
- GitHub cron fires 3–6 hours late (queueing on GitHub's side, not fixable
  in-repo).
- `.env.example` uses `JOBINGJA_` / `JOB51_` prefixes, which are cosmetically
  wrong but match `env_prefix` in the code exactly. Left as-is: renaming would
  break existing `.env` files for no functional gain.

## [0.1.0] - 2026-08-02

### Added
- Database schema design and PostgreSQL implementation: 9 schemas, ~38 tables, monthly range partitioning on core.jobs, materialized analytics views (Steps 1-2).
- Python project scaffold: uv-managed environment, pyproject.toml with optional dependency groups, base configuration loader (Step 3).
- Database interface layer: SQLAlchemy engine/session management, connection pooling, transaction helpers, generic repository pattern (Step 4).
- Reference data seeding system: 16 idempotent seed modules covering all ref.* controlled-vocabulary tables (Step 4.5).
- RemoteOK scraper: JSON API client with retry/backoff, field validation and parsing, structured logging (Step 5).
- Full test suite: 123 tests passing (unit tests for the RemoteOK scraper and shared HTTP/retry/logging infrastructure; integration tests for the database and seeding layers against a live PostgreSQL instance).

### Fixed
- Consolidated project structure into a single root (DataBase/job-market-intel); resolved import-path mismatches between early scratch-folder code and the real job_market_intel package layout; added missing dependencies (sqlalchemy, psycopg, passlib) that were previously untracked in pyproject.toml.