# Step 30 — Exploratory Data Analysis

Reads Neon **production** data (read-only) and produces a data-completeness
assessment plus a scoped EDA report. Two ways to run it: a fixed script that
regenerates everything from scratch, and a notebook for follow-up questions
the fixed report doesn't answer.

## Setup

Add the new dependencies as an optional extra (run once, from the project root):

```powershell
uv add --optional eda pandas matplotlib seaborn jupyter notebook
uv sync --extra dev --extra test --extra eda
```

Set the connection string as an environment variable for the current
PowerShell session (do not commit this value anywhere):

```powershell
$env:NEON_PROD_DATABASE_URL = "postgresql://neondb_owner:...@ep-damp-band-b35ije4h.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
```

## Run the fixed report

```powershell
uv run python analysis/step30_eda/run_eda.py
```

Writes `analysis/step30_eda/output/report.md` plus six `.png` chart files.
The `output/` folder is regenerated each run — safe to delete between runs.

## Run the interactive notebook

```powershell
uv run jupyter notebook analysis/step30_eda/step30_eda.ipynb
```

The notebook imports functions from `run_eda.py` directly rather than
duplicating logic, so the two never drift apart. Use it to drill into
specific job families, sources, or skills beyond what the fixed report
covers.

## Design decisions this deliverable encodes

Confirmed 2026-09-12, against real production data (605 jobs at the time):

1. **Market-composition charts include both `matched` and `no_match` jobs**,
   with an explicit caveat in the report. `no_match` (32.7% of the dataset
   at generation time) is a real mix of genuine off-taxonomy jobs and
   unfiltered scrape noise — `excluded_non_job` currently only catches the
   literal string "test" (3/605 rows). This was a deliberate scope choice
   for completeness over cleanliness, not a claim that `no_match` is clean.
2. **Job-family and normalized-title charts use `matched` only**, since
   `no_match` rows have no `normalized_title_id` by definition.
3. **Posting-date outliers are handled generically** (see
   `OUTLIER_WINDOW_DAYS` in `run_eda.py`, default 90): anything older than
   the window is excluded from the time-series chart and listed in a
   separate table in the report, rather than manually investigated case by
   case.
4. **No breakdown by job category, experience level, employment type,
   education level, industry, or remote-work-type** — all six were
   confirmed 100% null against real production data on 2026-09-12.
   `data_completeness()` re-checks this on every run; if a future step
   populates any of these, the report's completeness table will show it,
   but the charts themselves won't automatically start using the new
   column — that would need a deliberate follow-up change.
5. **No salary distribution chart.** Only ~3% of jobs have a disclosed
   salary at this data volume — a chart would imply more statistical
   weight than ~20 data points can support. Raw values are listed in the
   report as a table instead.

## Known limitations of this report itself

- Every run reflects a snapshot of production at that moment; re-run before
  trusting numbers if meaningful time has passed since the last scrape cycle.
- Chart styling is intentionally plain (no branding/theming work done) —
  this is an internal analysis artifact, not a publication figure.
- `job_status` is `active` for 100% of rows as of 2026-09-12 (the
  known "postings never flip to closed" gap) — no lifecycle or
  time-to-fill analysis is attempted here.
