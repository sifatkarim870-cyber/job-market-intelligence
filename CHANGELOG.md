# Changelog

All notable changes to this project are documented here.

## [Unreleased] - 2026-10-15

### Fixed

- **Built In rows lost their country.** `builtin` was missing from
  `SOURCE_HOME_COUNTRY`, so 9 of 40 live rows landed on the collapsed
  global-remote row with no country -- on a board that only ever posts in the
  US. Added, and `scripts/reresolve_home_country.py` repointed them. All four
  boards added in this cycle are now 40/40, 40/40, 10/10 and 40/40 on
  `country_code` with zero false `is_global_remote` rows; the one remaining
  global-remote row is a Wellfound posting that genuinely says "Anywhere in the
  World". `wellfound` is deliberately **not** in the map: its postings span the
  US, UK, DE, FR, NL, ES, IE and IN.

### Added

- **Built In scraper** (`builtin`) - the US tech and startup board, pairing with
  Wellfound to cover the segment the corpus had none of. US-only in practice:
  every posting sampled carried
  `applicantLocationRequirements: {"@type": "Country", "name": "USA"}`. Rich per
  posting: 2-6k characters of description, posting *and* closing dates, and up
  to 46 benefits (`"Offers 401(K)"`, `"Provides adoption assistance"`). A live
  40-posting run produced 40/40 descriptions (979-2182 words), 40/40 posting and
  closing dates, 31/40 disclosed salaries, and `data_quality_score` 0.86-1.00.

  **The one trap: the `JobPosting` node is not at the top level of the JSON-LD.**
  Built In emits an ~8.8 KB document shaped
  `{"@context": ..., "@graph": [ ... ]}`. A parser that checks `json["@type"]`
  finds nothing and reports an empty board on a site serving every field -- the
  first probe did exactly that and reported "no JobPosting on any detail page"
  on all six postings it fetched. `extract_posting` walks the whole document.

  Four more shapes, all measured over 24 postings:

  * `geo` is a **sibling of** `address` on the `Place` node, not a child. Reading
    `address["geo"]` returns nothing on every posting, silently -- caught by a
    live run reporting 0 of 8 rows with coordinates, after a first attempt that
    had confidently documented the wrong path.
  * `industry` is a **list on 21 of 24** postings and a bare string on 3, so a
    scalar-typed field rejects three quarters of the board.
  * `jobLocation` is a bare `Place` on 19 of 24 and a list on the other 5.
  * `hiringOrganization.logo` is an `ImageObject` dict (`{"url": ...}`), not a
    URL string.

  robots.txt disallows `/search/` and `/jobs*?search=`, so discovery is
  facet-based and never keyword-based; `Allow: /jobs*?page=` permits the
  pagination because it is the longer, governing match. Listing pages yield
  20-27 distinct links (182 over 8 pages, pager to 1000).

  `jobLocationType` is `"TELECOMMUTE"` on remote roles, the only explicit remote
  flag on this board -- but `core.jobs.remote_work_type_id` is populated solely
  by the location resolver, and `CleanedJob` has no remote field, so the flag
  currently rides in `raw_payload` and is **not persisted**. Wiring it properly
  means adding a field to `CleanedJob` and teaching the repository about it,
  which touches every source and is a separate change.

- **Wellfound scraper** (`wellfound`) - the startup and tech job board, filling
  a segment the corpus had none of. No key, no proxy, no captcha. It is the
  **best salary source in the corpus**: 6 of 6 postings sampled carried an
  explicit `minValue`/`maxValue` in a named currency with a period, where most
  boards carry a figure on only some rows. A live 40-posting run produced 40/40
  descriptions (311-1474 words), 40/40 salary rows, 40/40 posting dates,
  `data_quality_score` 1.00 throughout, 14 distinct employers, and 39/40 rows
  with a resolved `country_code`.

  Discovery works **only** through `/location/<country>` and
  `/role/l/<role>/<country>`. `/jobs` returns HTTP 200, renders a `page=N`
  pager, and then ignores the parameter -- pages 1 through 11 each returned the
  identical 43 job ids and zero new ones (measured 2026-10-14). Walking it
  would spend the entire request budget re-reading page 1 while appearing to
  make progress, so only the working paths are walked, and the client now stops
  any listing after repeated empty pages so that failure mode cannot return.

  Two traps worth recording: `identifier` is a schema.org `PropertyValue` whose
  `name` is the *company* and whose `value` is the id -- and that value is
  sometimes `"<id>-<slug>"` rather than a bare id. And
  `hiringOrganization.location` is the company's offices while `jobLocation` is
  where the job is; on the sampled Checkr role they differed (Denver and San
  Francisco as offices, San Francisco as the job), so conflating them would put
  every job at a company in its head office.

  `robots.txt` is served as `Content-Type: text/html` despite being real
  plain-text robots content. Its `User-agent: *` rules disallow `/_jobs/`,
  `/*?after_sign_in=*` and `/*?inFrame=*`; this scraper uses `/location/`,
  `/role/` and `/jobs/<id>-<slug>`, and `/jobs/` is a different path from the
  disallowed `/_jobs/`.

- **USAJOBS scraper** (`usajobs`) - the US federal government's job board, the
  single largest US employer by headcount and the answer to a corpus that had
  no United States rows at all from any federal source. Free data.gov key, no
  proxy, no captcha, no per-agreement registration.

  Unusually rich structured fields: every posting carries the employing bureau,
  department and sub-agency, the pay grade and job series, the salary band with
  its pay interval, publication and closing dates, and a structured location
  with city, state and coordinates. Of those, the salary band, dates,
  organisation hierarchy and city/state **do** persist; the pay grade, job
  series and coordinates do **not**, because the schema has no columns for them
  and `raw_payload` is not persisted. Adding those columns would change the
  shard contract for all 22 sources and is a separate change.

  Costs one API request per 50 postings plus one job page per posting, because
  **there is no position detail endpoint** - `/api/v2/position/{id}` and four
  other spellings all return 404, and `PositionFormattedDescription` is a marker
  object rather than text. The full duties and requirements therefore come from
  the public page's `page-section` blocks (~30k chars) rather than its JSON-LD
  `description` (~400 chars). Ships disabled in `config/sources.json` until the
  key is in the Actions env.

### Fixed

- **Four pipelines could never report a failed batch.** `jobbank`,
  `arbeitnow`, `greenhouse` and `usajobs` read
  `getattr(report, "validation_passed", True)` from the validation report.
  `BatchValidationReport` has no attribute of that name - the field is `passed`
  - so the `getattr` fallback silently swallowed the `AttributeError` and every
  run reported `validation_passed=True`. `scheduler/jobs.py` gates on that field,
  so a degraded or empty fetch could not raise anything downstream. The other 18
  pipelines already read `.passed`; these four now match.
- **42 government jobs claimed to be open to the entire world.** `usajobs`
  (US) and `jobbank` (CA) are national government boards but were missing from
  `SOURCE_HOME_COUNTRY`, so the country fallback never ran for them. Every
  Job Bank row (location `"All of Canada"`) and 2 USAJOBS rows (location
  `"Multiple Locations"`) collapsed onto one shared `ref.locations` row with
  `is_global_remote = True` and no country. That is a factual claim about the
  job, not a statement about the parser - exactly what that map's docstring
  says it exists to prevent. Both sources are now 40/40 and 10/10 on
  `country_code`, with 0 global-remote rows.
- **A cached location alias could pin a job to a wrong country forever.**
  `resolve_and_cache_location` returned a `core.location_aliases` hit without
  re-matching, so the bad resolutions above were cached and every later scrape
  re-applied them. The alias cannot simply be deleted or updated: the table is
  `UNIQUE(raw_location_text, source_id)` and the runtime role holds only
  `SELECT` and `INSERT` on it. The resolver now bypasses an alias that asserts
  a worldwide opening for a single-country board, resolves fresh, and leaves the
  dead row in place. `scripts/reresolve_home_country.py` (new, dry-run by
  default) repoints the 42 already-affected jobs.

  The three bypassed alias rows remain in `core.location_aliases` pointing at
  the wrong location, so that audit trail disagrees with `core.jobs` for those
  entries until a privileged cleanup. Documented in the resolver.
- **A short final listing page lost its jobs.** The Wellfound client treated a
  page with fewer than five links as the tail and broke out *before* collecting
  it, discarding the last page of every listing walked. Caught by a test; the
  links are now collected first and the walk stops after.
- **`get_or_create_location` silently lost rows on a concurrent insert.** The
  first CI run of USAJOBS lost one row in twenty:

  ```
  failed to persist USAJOBS job 26-CB-13082116-DH: Transaction block failed
  and was rolled back: (psycopg.errors.UniqueViolation) duplicate key value
  violates unique constraint "locations_pkey"
  ```

  It is a check-then-insert, so two sessions that both find nothing both
  insert. The per-row savepoint in each pipeline kept the other nineteen rows,
  but the failed row was simply gone -- silently, on every run, forever. It
  never reproduced locally because a single sequential writer cannot race
  itself.

  Now the INSERT runs inside `session.begin_nested()`, and on `IntegrityError`
  the code re-reads the row the winner committed. A full `session.rollback()`
  would have been wrong here: the pipeline calls this from inside
  `transaction(session)` -- a savepoint per job row -- so a full rollback
  discards the job row too and loses two rows instead of one. Six integration
  tests cover it, and they were checked to fail against both the unfixed code
  and the plausible-but-wrong full-rollback variant.

  **Root cause of the collision: identified, not yet fixed.** Identity
  sequences do not agree with seeded ids on the CI database. Measured
  2026-10-15 on `job_market_intelligence_test`: every reference table's ids
  start in the thousands (countries 1393..1450, cities 2251..2340) while its
  identity sequence sits at 57,147 / 92,357, because the seeder upserts on
  every integration-test run and each run advances the sequence. A CI database
  seeded with explicit ids but a sequence still near 1 will hand out a
  `location_id` that already exists, which is exactly a `locations_pkey`
  violation. The laptop's sequences are all far *ahead*, which is why the same
  code never collides there -- the same laptop-versus-CI asymmetry that hid
  this in the first place. The remedy is to resync every identity column to
  `max(id)` as part of seeding; that is a separate change and is not in here.

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
  `jmi-translate-hf`). Confirmed 2026-10-13 that `jmi-translate-hf` owns the
  daily schedule, so `nllb-translate` is an unscheduled duplicate. It is left
  in place rather than deleted: it holds a UI-attached HF secret that cannot
  be read back or migrated programmatically, and deleting a working kernel is
  not reversible. De-scheduling or removing it is a manual UI step.
  Two near-identical names is plausibly how the stale-token copy went unnoticed
  in the first place, so this is worth doing deliberately.
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