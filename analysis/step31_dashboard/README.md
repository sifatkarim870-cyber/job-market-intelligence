# Step 31 — Interactive Dashboard

A local Streamlit app for exploring Neon production data interactively —
filter by source and date range, search companies, adjust top-N sliders,
all without re-running a script and re-reading a static report each time.

## Why Streamlit over Dash

Faster to build and simpler to maintain for a solo research tool. Dash
gives more layout/callback control, which would matter if this grows into
something multi-user or more heavily customized later — not needed yet.

## Setup

This reuses `analysis/step30_eda/run_eda.py` directly for data loading
(no duplicated queries — one source of truth for what a "job," "matched
title," or "flagged salary" means). **Step 30 must already be set up**
(its `eda` extra installed) before this will run.

Add the dashboard-specific dependencies:

```powershell
uv add --optional dashboard streamlit plotly
uv sync --extra dev --extra test --extra eda --extra dashboard
```

Set the connection string for the session (never commit its value):

```powershell
$env:NEON_PROD_DATABASE_URL = "postgresql://neondb_owner:...@ep-damp-band-b35ije4h.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
```

## Run it

```powershell
uv run streamlit run analysis\step31_dashboard\dashboard.py
```

Opens in your browser automatically (usually `http://localhost:8501`).
Press Ctrl+C in the terminal to stop it.

## Caching and refresh

Data is cached for up to 1 hour per session (`st.cache_data(ttl=3600)`) so
adjusting filters/sliders doesn't re-query Neon on every interaction. Use
the **"Refresh data from Neon"** button in the sidebar to force a fresh
pull — useful since GitHub Actions scrapes new jobs every ~12 hours.

## What's shown, and what deliberately isn't

Same real-data constraints as Step 30 apply here — this dashboard doesn't
try to show anything the data can't actually support:

- No breakdown by job category, experience level, employment type,
  education level, industry, or remote-work-type — all six confirmed 100%
  null as of Step 30's EDA.
- No salary distribution chart — sample too small; shown as a flagged
  table instead (same anomaly-flagging logic as Step 30, imported directly
  from `run_eda.salary_summary`).
- The date-range filter only affects the posting-volume chart. Applying it
  to every section would make company/skill/title breakdowns misleadingly
  small for no analytical benefit — those stay filtered by source only.
- Postings older than `OUTLIER_WINDOW_DAYS` (90 days, same constant as
  Step 30) are excluded from the default date range and the trend chart,
  listed separately in a collapsible section instead.

## Known limitations

- Single-user, local-only. No auth, no deployment story — this is an
  exploration tool for you, not a shared dashboard.
- The `run_eda` import only resolves at runtime via a `sys.path` insert
  (see the comment in `dashboard.py`) — `mypy` can't verify it statically,
  hence the scoped `# type: ignore` there. Confirmed working via direct
  smoke test before shipping, not just assumed.
