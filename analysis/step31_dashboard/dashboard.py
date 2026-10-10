"""
Step 31 — Interactive Dashboard
Explainable AI Job Market Intelligence Platform

A local Streamlit app for exploring Neon production data interactively.
Data loading is intentionally NOT duplicated from Step 30 — this imports
load_jobs/load_salaries/load_skills/data_completeness/salary_summary
directly from analysis/step30_eda/run_eda.py, so both tools stay in sync
and any future fix to a query only needs to happen in one place.

Caching: data is cached in-session (st.cache_data) rather than re-queried
on every interaction (every filter change would otherwise re-hit Neon).
Use the "Refresh data" button in the sidebar to force a re-query.

Usage:
    Set NEON_PROD_DATABASE_URL first (never commit its value):

        $env:NEON_PROD_DATABASE_URL = "postgresql://...neon.tech/neondb?"`
            + "sslmode=require&channel_binding=require"

    Then, from the project root:

        uv run streamlit run analysis/step31_dashboard/dashboard.py
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]  # plotly ships no official stubs
import streamlit as st

# Reuse Step 30's tested, ruff/mypy-clean data-loading logic rather than
# duplicate it. Both tools then share one source of truth for what a
# "job", "matched title", or "flagged salary" means.
sys.path.insert(0, str(Path(__file__).parent.parent / "step30_eda"))
from run_eda import (  # type: ignore[import-not-found]  # noqa: E402
    # mypy analyzes imports statically and can't see the sys.path.insert
    # above; this import is only resolvable at runtime. Confirmed working
    # via direct smoke test, not just assumed.
    OUTLIER_WINDOW_DAYS,
    data_completeness,
    get_connection,
    load_jobs,
    load_salaries,
    load_skills,
    salary_summary,
)

st.set_page_config(page_title="Job Market Intel Dashboard", layout="wide")


@st.cache_data(ttl=3600, show_spinner="Querying Neon production...")
def load_all_data() -> dict[str, pd.DataFrame]:
    conn = get_connection()
    data = {
        "jobs": load_jobs(conn),
        "salaries": load_salaries(conn),
        "skills": load_skills(conn),
        "completeness": data_completeness(conn),
    }
    conn.dispose()
    return data


# ---------------------------------------------------------------------------
# Sidebar: refresh control + filters
# ---------------------------------------------------------------------------

st.sidebar.title("Controls")
if st.sidebar.button("Refresh data from Neon", type="primary"):
    load_all_data.clear()
    st.rerun()

try:
    data = load_all_data()
except SystemExit as exc:
    st.error(str(exc))
    st.stop()

jobs = data["jobs"]
salaries = data["salaries"]
skills = data["skills"]
completeness = data["completeness"]

st.sidebar.caption(f"Loaded {len(jobs)} jobs. Cached for up to 1 hour or until refreshed.")

all_sources = sorted(jobs["source_name"].unique().tolist())
selected_sources = st.sidebar.multiselect("Sources", all_sources, default=all_sources)

min_date = pd.to_datetime(jobs["posting_date"]).min().date()
max_date = pd.to_datetime(jobs["posting_date"]).max().date()
date_range = st.sidebar.date_input(
    "Posting date range",
    value=(max(min_date, max_date - timedelta(days=OUTLIER_WINDOW_DAYS)), max_date),
    min_value=min_date,
    max_value=max_date,
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

# Applied to every section below. Filtering by source is a straightforward
# subset; filtering by date only affects the volume-over-time view, since
# collapsing everything else to a narrow date window would make company/
# skill/title breakdowns misleadingly small for no real analytical reason.
jobs_filtered = jobs[jobs["source_name"].isin(selected_sources)]

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

st.title("Job Market Intelligence — Live Dashboard")
st.caption(
    "Reads Neon production directly. Six dimensional columns "
    "(job_category, experience_level, employment_type, education_level, "
    "industry, remote_work_type) are 100% null as of Step 30's EDA — no "
    "breakdown by those is possible yet, and none is attempted here."
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total jobs (filtered)", len(jobs_filtered))
matched_pct = (
    100 * (jobs_filtered["title_classification_status"] == "matched").sum() / len(jobs_filtered)
    if len(jobs_filtered) > 0
    else 0
)
col2.metric("Matched titles", f"{matched_pct:.1f}%")
col3.metric("Distinct companies", jobs_filtered["company_name"].nunique())
skills_coverage = (
    100 * skills["job_id"].nunique() / len(jobs) if len(jobs) > 0 else 0
)
col4.metric("Skills coverage (all jobs)", f"{skills_coverage:.1f}%")

st.warning(
    "Every job in the dataset currently has `job_status = 'active'` — "
    "the pipeline has never flipped a posting to closed/expired. "
    "'Active' here means \"currently tracked,\" not \"confirmed still open.\""
)

with st.expander("Data completeness (click to expand)"):
    st.dataframe(completeness, width='stretch', hide_index=True)
    fully_null = completeness[completeness["null_pct"] == 100.0]["column"].tolist()
    if fully_null:
        st.caption(
            f"{len(fully_null)} column(s) 100% null: " + ", ".join(f"`{c}`" for c in fully_null)
        )

# ---------------------------------------------------------------------------
# Sources and title classification
# ---------------------------------------------------------------------------

st.header("Sources and title classification")
c1, c2 = st.columns(2)

with c1:
    src_counts = (
        jobs_filtered.groupby(["source_name", "job_status"]).size().reset_index(name="count")
    )
    fig = px.bar(
        src_counts, x="source_name", y="count", color="job_status",
        title="Jobs by source and status",
    )
    st.plotly_chart(fig, width='stretch')

with c2:
    class_counts = jobs_filtered["title_classification_status"].value_counts().reset_index()
    class_counts.columns = ["status", "count"]
    fig = px.bar(
        class_counts, x="status", y="count", text="count",
        title="Title classification outcome",
        color="status",
        color_discrete_map={
            "matched": "#4c72b0", "no_match": "#dd8452", "excluded_non_job": "#c44e52",
        },
    )
    st.plotly_chart(fig, width='stretch')

st.caption(
    "`excluded_non_job` currently only catches the literal string \"test\". "
    "`no_match` mixes genuine off-taxonomy jobs with unfiltered scrape noise "
    "(personal names, menu items, template text) — treat it with real "
    "skepticism, not just as a residual category."
)

# ---------------------------------------------------------------------------
# Job families (matched only)
# ---------------------------------------------------------------------------

st.header("Job families")
matched = jobs_filtered[jobs_filtered["title_classification_status"] == "matched"]
top_n_families = st.slider("Show top N families", 5, 30, 15)
family_counts = matched["job_family"].value_counts().head(top_n_families).reset_index()
family_counts.columns = ["job_family", "count"]
fig = px.bar(
    family_counts.sort_values("count"), x="count", y="job_family", orientation="h",
    title=f"Top {top_n_families} job families (matched titles only, n={len(matched)})",
)
st.plotly_chart(fig, width='stretch')

# ---------------------------------------------------------------------------
# Posting volume over time
# ---------------------------------------------------------------------------

st.header("Posting volume over time")
dates_all = pd.to_datetime(jobs_filtered["posting_date"])
cutoff = dates_all.max() - pd.Timedelta(days=OUTLIER_WINDOW_DAYS)
in_range = jobs_filtered[
    (dates_all >= pd.Timestamp(start_date)) & (dates_all <= pd.Timestamp(end_date))
]
outliers = jobs_filtered[dates_all < cutoff]

daily = (
    pd.to_datetime(in_range["posting_date"]).dt.date.value_counts().sort_index().reset_index()
)
daily.columns = ["posting_date", "count"]
fig = px.line(
    daily, x="posting_date", y="count", markers=True, title="Postings per day (selected range)"
)
st.plotly_chart(fig, width='stretch')

if len(outliers) > 0:
    expander_label = (
        f"{len(outliers)} posting(s) older than {OUTLIER_WINDOW_DAYS} days "
        "(outside default range)"
    )
    with st.expander(expander_label):
        outlier_cols = ["job_id", "source_name", "job_title", "posting_date"]
        st.dataframe(
            outliers[outlier_cols].sort_values("posting_date"),
            width='stretch', hide_index=True,
        )

# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

st.header("Companies")
company_search = st.text_input("Search company name (optional)", "")
company_pool = jobs_filtered
if company_search:
    company_pool = company_pool[
        company_pool["company_name"].str.contains(company_search, case=False, na=False)
    ]
top_n_companies = st.slider("Show top N companies", 5, 30, 15)
company_counts = company_pool["company_name"].value_counts().head(top_n_companies).reset_index()
company_counts.columns = ["company_name", "count"]
fig = px.bar(
    company_counts.sort_values("count"), x="count", y="company_name", orientation="h",
    title=f"Top {top_n_companies} companies by posting count",
)
st.plotly_chart(fig, width='stretch')

# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

st.header("Skills")
st.caption(
    f"Only {skills['job_id'].nunique()}/{len(jobs)} jobs "
    f"({skills_coverage:.1f}%) have any extracted skill at all. The "
    "extractor skews toward generic soft skills over hard technical ones "
    "on this data — treat this as a coverage/extraction-method finding, "
    "not a market finding."
)
top_n_skills = st.slider("Show top N skills", 5, 30, 20)
skill_counts = skills["skill_name"].value_counts().head(top_n_skills).reset_index()
skill_counts.columns = ["skill_name", "count"]
fig = px.bar(
    skill_counts.sort_values("count"), x="count", y="skill_name", orientation="h",
    title=f"Top {top_n_skills} extracted skills",
)
st.plotly_chart(fig, width='stretch')

# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------

st.header("Salary")
salary_rows = salary_summary(salaries)
st.caption(
    f"Only {len(salary_rows)}/{len(jobs)} jobs "
    f"({100 * len(salary_rows) / len(jobs):.1f}%) have a disclosed salary — "
    "too small a sample for any distributional claim. Rows below with a "
    "non-empty flag look wrong, not just sparse (see Step 30/27's findings "
    "on RemoteOK's unannotated pay-period data)."
)
st.dataframe(
    salary_rows.sort_values("normalized_annual_min_usd"),
    width='stretch', hide_index=True,
)
