# RemoteOK Scraper — Documentation

**Part of:** Explainable AI Job Market Intelligence Platform
**Build step:** Step 5 (Phase 2, "Scraping Framework")
**Package location:** `src/job_market_intel/scrapers/remoteok/`
**Status:** Implemented, tested (123/123 tests passing, unit + integration), verified against the live RemoteOK API.

---

## 1. Purpose and scope

This scraper fetches job postings from RemoteOK and hands back a list of validated, typed Python objects — one per job posting. It is the **first** of what will eventually be seven-plus source scrapers (RemoteOK, We Work Remotely, Remotive, Indeed, LinkedIn/equivalent, Glassdoor, government portals, company career pages).

**What this scraper does:**
- Fetches the current job listing feed from RemoteOK
- Validates every field on every record
- Skips and logs individual malformed records without failing the whole run
- Returns a list of `RawRemoteOKJob` objects

**What this scraper deliberately does NOT do** (by design, per the project's step-scoped build plan):
- Clean or normalize text (HTML stripping, encoding fixes, whitespace normalization) — that's Step 8
- Resolve company name variants to a canonical company — that's Step 23
- Extract skills from free text — that's Step 24
- Normalize salary/currency — that's Step 25
- Resolve locations to `ref.locations` — that's Step 26
- Write anything to the database — that's Step 9 and beyond

Keeping this boundary strict is what makes each step independently testable and lets later steps improve without needing to touch this one.

---

## 2. Why a JSON API instead of HTML scraping

The original plan (per the project's technology stack) assumed HTML scraping with BeautifulSoup/Playwright. During planning, we discovered RemoteOK exposes its listings as a public JSON feed at `https://remoteok.com/api`. This changed the design for the better:

| HTML scraping (original assumption) | JSON API (what was actually built) |
|---|---|
| Requires CSS selectors, breaks when RemoteOK redesigns their site | No selectors — structured data, resilient to visual redesigns |
| Requires pagination logic across multiple page loads | Single request returns the current full listing set |
| Slower (many page loads), higher chance of being blocked | One fast request to a documented-by-convention endpoint |
| BeautifulSoup/Playwright required | Neither needed for this source |

BeautifulSoup and Playwright remain in the project's dependency stack for future sources that don't offer a JSON feed (e.g. most company career pages).

---

## 3. Architecture

### 3.1 Folder structure

```
job-market-intel/
├── src/job_market_intel/
│   ├── common/                       # shared, source-agnostic infrastructure
│   │   ├── http_client.py            # HTTP GET wrapper; transient/permanent error split
│   │   ├── retry.py                  # Tenacity-based retry policy builder
│   │   └── logger.py                 # Loguru configuration (console + rotating file)
│   │
│   └── scrapers/
│       └── remoteok/                 # everything RemoteOK-specific lives here
│           ├── __init__.py           # public exports
│           ├── client.py             # talks to RemoteOK's API, returns raw dicts
│           ├── parser.py             # validates raw dicts into RawRemoteOKJob objects
│           ├── models.py             # RawRemoteOKJob (Pydantic model)
│           ├── exceptions.py         # RemoteOKError, RemoteOKFetchError, RemoteOKResponseError
│           └── config.py             # RemoteOKSettings (env-driven configuration)
│
├── scripts/
│   └── run_remoteok_scraper.py       # manual entry point — fetch, parse, print a summary
│
├── tests/
│   ├── fixtures/remoteok/
│   │   └── sample_response.json      # realistic mock RemoteOK response
│   └── unit/
│       ├── common/                   # tests for http_client.py, retry.py, logger.py
│       └── scrapers/remoteok/        # tests for client.py, parser.py, models.py, config.py
│
└── docs/
    └── remoteok_scraper.md           # this file
```

### 3.2 Why `common/` holds only three files

Three things are true for *any* scraper this platform will ever add, regardless of source: it needs to make HTTP requests, it needs a retry policy for transient failures, and it needs consistent logging. Those three concerns — and only those — live in `common/`. Everything else (parsing logic, field definitions, source-specific error types, source-specific settings) stays inside `scrapers/remoteok/` until a second scraper exists and genuine shared patterns can be observed, rather than guessed at in advance. This follows YAGNI deliberately: no generic `BaseScraper` class or plugin framework has been built, because only one scraper exists so far and premature abstraction would be guessing at requirements that haven't appeared yet.

### 3.3 Component responsibilities

| Component | Responsibility |
|---|---|
| `common/http_client.py` | Makes the HTTP GET request; classifies failures into `TransientHTTPError` (worth retrying: network errors, timeouts, 5xx) vs. `PermanentHTTPError` (not worth retrying: 4xx, invalid JSON body) |
| `common/retry.py` | Wraps a function call in Tenacity's retry logic — exponential backoff, configurable max attempts, logs a warning before each retry |
| `common/logger.py` | One-time Loguru configuration: colored console output + rotating file sink under `logs/` |
| `scrapers/remoteok/client.py` | Fetches the feed via `common/http_client.py` + `common/retry.py`; strips RemoteOK's non-job metadata entry; raises `RemoteOKFetchError` / `RemoteOKResponseError` on failure |
| `scrapers/remoteok/parser.py` | Validates each raw dict via `models.py`; skips and logs malformed records individually |
| `scrapers/remoteok/models.py` | `RawRemoteOKJob` — the typed, validated shape of one job record, in RemoteOK's own field naming |
| `scrapers/remoteok/exceptions.py` | `RemoteOKError` (base), `RemoteOKFetchError` (whole-feed failure), `RemoteOKResponseError` (response wasn't a usable job list) |
| `scrapers/remoteok/config.py` | `RemoteOKSettings` — API URL, timeouts, retry limits, all overridable via `REMOTEOK_`-prefixed environment variables |

---

## 4. Workflow

1. `RemoteOKSettings` loads configuration (API URL, timeout, retry limits) from environment variables / `.env`, falling back to sensible defaults.
2. `RemoteOKClient.fetch_raw_jobs()` calls `common/http_client.fetch_json()`, wrapped in `common/retry.call_with_retry()`.
3. On a transient failure (network error, timeout, 5xx), the retry policy waits (exponential backoff) and tries again, up to `max_retry_attempts` times, logging a warning before each retry.
4. On success, the response is checked: it must be a JSON list containing at least one entry with an `id` field (a genuine job record). RemoteOK's feed always includes one non-job metadata/legal-notice entry as its first element — this is filtered out based on the absence of an `id` field, which every real job record has.
5. `RemoteOKParser.parse_jobs()` validates each remaining raw dict against `RawRemoteOKJob`. A record missing a required field (job title, company name, RemoteOK's own ID, or the posting URL) is logged and skipped — it does not stop the rest of the batch from being processed.
6. The caller receives a list of `RawRemoteOKJob` objects — validated, typed, ready for the next pipeline stage (cleaning, in Step 8).

Every step above logs what happened: request sent, response received, retry triggered, records skipped, final counts.

---

## 5. Parsing strategy and RemoteOK-specific data quirks

Since the source is JSON, "parsing" here means **validation and shaping**, not tag-hunting. Key decisions:

- **Required vs. optional fields**: `id`, `position` (job title), `company`, and `url` are required — a record missing any of these can't be traced back to its source or meaningfully used, so it's skipped. Everything else (`tags`, `location`, `salary_min`/`salary_max`, `company_logo`, `apply_url`, `description`) is optional, since RemoteOK frequently omits them — a missing salary is a valid, expected state (matching how the database schema itself treats undisclosed salary), not an error.
- **The metadata-entry quirk**: RemoteOK's feed's first array element is not a job at all — it's a legal/attribution notice object with no `id` field. `client.py` filters based on that field's absence rather than assuming a fixed array position, so this remains correct even if RemoteOK ever moves that entry.
- **Date parsing**: RemoteOK's `date` field is typically ISO-8601. The parser accepts that format (including a trailing `Z`), attaches UTC if the parsed value is naive, and — critically — returns `None` rather than raising if the date is malformed or missing. A missing posting date is recoverable downstream (it can fall back to `first_scraped_at`); a missing title or URL is not. This asymmetry is deliberate.
- **Raw payload preservation**: every successfully parsed record retains a complete, unmodified copy of RemoteOK's original dict in `raw_payload`, mirroring the platform's broader design principle (`jobs.raw_html_ref` in the schema) of never discarding original source data, even after it's been parsed into typed fields.
- **Text is captured as-is**: encoding artifacts (e.g. `EspaÃ±ol` instead of `Español`) and raw HTML entities (`&amp;`) observed in live data are captured verbatim, not fixed here. Cleaning text is explicitly Step 8's job — this scraper's only job is faithful capture plus structural validation.

---

## 6. Configuration reference

All settings are optional overrides via environment variables prefixed `REMOTEOK_` (or a `.env` file), with working defaults out of the box:

| Variable | Default | Purpose |
|---|---|---|
| `REMOTEOK_API_URL` | `https://remoteok.com/api` | The feed endpoint |
| `REMOTEOK_REQUEST_TIMEOUT_SECONDS` | `15.0` | Max wait per HTTP request |
| `REMOTEOK_MAX_RETRY_ATTEMPTS` | `4` | Total attempts (including the first) before giving up on a transient failure |
| `REMOTEOK_RETRY_INITIAL_WAIT_SECONDS` | `1.0` | Wait before the first retry |
| `REMOTEOK_RETRY_MAX_WAIT_SECONDS` | `30.0` | Ceiling on exponential backoff wait time |
| `REMOTEOK_USER_AGENT` | `JobMarketIntelligencePlatform-Research/1.0 (...)` | Identifying header sent with every request |

---

## 7. Testing

Full suite: `uv run pytest` (from the project root). As of this writing: **123 tests passing** across the whole project, of which the RemoteOK-specific suite contributes:

- `tests/unit/scrapers/remoteok/test_models.py` — field requirements, optional-field defaults, date parsing edge cases, raw payload preservation
- `tests/unit/scrapers/remoteok/test_parser.py` — skip-malformed-records behavior, an end-to-end pass against a realistic fixture file
- `tests/unit/scrapers/remoteok/test_client.py` — metadata-entry filtering, retry integration, all three failure modes (transient/permanent/malformed-response)
- `tests/unit/scrapers/remoteok/test_config.py` — default values, environment variable overrides, prefix isolation
- `tests/unit/common/test_http_client.py`, `test_retry.py`, `test_logger.py` — the shared infrastructure these depend on

All RemoteOK tests are fully mocked at the HTTP boundary — none make a real network call, so the suite runs in under a second and never depends on RemoteOK's server being up.

**Manual, real-network verification**: `uv run python scripts/run_remoteok_scraper.py` — fetches the live feed and prints a human-readable summary. Last confirmed run: 100/100 records fetched and parsed successfully.

---

## 8. Assumptions

- RemoteOK's JSON feed continues to return the full current listing set in a single response (no pagination). If RemoteOK introduces pagination in the future, `client.py` would need a follow-up-page loop added.
- RemoteOK's feed continues to include exactly one non-job metadata entry, identifiable by the absence of an `id` field.
- RemoteOK's `date` field continues to be ISO-8601 formatted (or absent) — no other date format has been observed or is currently handled.
- A single HTTP request completes within `REMOTEOK_REQUEST_TIMEOUT_SECONDS` (default 15s) under normal network conditions.

## 9. Limitations

- **No official RemoteOK API documentation exists.** The feed's shape is inferred from observed live responses, not a documented contract. `client.py` and `parser.py` are written defensively (never assuming a field is present, always allowing individual records to fail independently) specifically because of this uncertainty.
- **Text is not cleaned.** HTML tags, HTML entities, and character-encoding artifacts are captured as-is; this is intentional (Step 8's responsibility) but means `RawRemoteOKJob` objects are not yet suitable for direct display or NLP processing.
- **No persistence.** This scraper does not write to the database. Running it repeatedly does not deduplicate against previous runs — that begins in Step 9 (storage) and Step 10 (duplicate detection).
- **Single source only.** Company name variants, location strings, and job titles are not yet normalized or compared across sources — that's Phase 4/5 of the overall build plan.
- **No built-in rate limiting / politeness delay.** A single fetch is lightweight, but if this scraper is later called very frequently by the scheduler (Step 12), consider adding a minimum-interval guard — RemoteOK has no published rate limit, so this is a "be a good citizen" concern rather than a functional necessity today.

## 10. Future improvements

- Add pagination support if RemoteOK's feed shape changes to require it.
- Add a lightweight "feed size sanity check" (e.g. alert if the fetched job count drops by more than some threshold vs. the last run) — useful operational signal that the feed's shape changed unexpectedly, once the scheduler (Step 13) is in place.
- Split logging output by category to match the `logs/api/`, `logs/database/`, `logs/scrapers/`, `logs/scheduler/`, `logs/system/` folder structure already present in the project scaffold, rather than the current single flat `logs/job_market_intel.log` file. (Noted as a Step 14 configuration-management item, not urgent today.)
- Once a second scraper exists (We Work Remotely, per the workflow's Phase 4), revisit `common/` for any genuinely shared parsing patterns that emerge — but not before, per YAGNI.

---

## 11. Where this fits in the overall build plan

This scraper is Step 5 of the project's phased workflow. It depends on Step 4.5 (reference data seeding) only insofar as *later* steps (cleaning, normalization) will map its raw output onto those controlled vocabularies — this scraper itself has no direct dependency on seeded data. It is a direct prerequisite for:
- **Step 7** (validate scraped data) — largely already satisfied by this scraper's own field-level validation
- **Step 8** (data cleaning pipeline) — consumes `RawRemoteOKJob` objects
- **Step 9** (store in PostgreSQL) — will persist cleaned records into `core.jobs`
- **Step 10a** (same-source duplicate detection) — will use `content_hash` comparison once records reach the database
