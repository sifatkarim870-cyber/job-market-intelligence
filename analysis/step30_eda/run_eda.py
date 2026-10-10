"""
Step 30 - Exploratory Data Analysis
Explainable AI Job Market Intelligence Platform

Connects to Neon PRODUCTION (read-only), pulls the current dataset, and
produces:
 - analysis/step30_eda/output/*.png  (chart images)
 - analysis/step30_eda/output/report.md  (narrative report embedding them)

Design decisions this script encodes (confirmed 2026-09-12, do not change
without re-confirming - see analysis/step30_eda/README.md for the full
rationale):

  1. Market-composition charts (company, skills, salary, posting volume)
     include BOTH 'matched' and 'no_match' jobs, with an explicit caveat in
     the report that 'no_match' is a mix of genuine off-taxonomy jobs and
     unfiltered scrape noise (personal names, menus, template text, etc.).
     Only 3/605 rows are currently caught by 'excluded_non_job'.
  2. Normalized-title / job-family charts use ONLY 'matched' jobs, since
     'no_match' rows have no normalized_title_id by definition.
  3. Posting-date outliers are handled generically, not manually
     investigated: any posting_date more than OUTLIER_WINDOW_DAYS before
     the most recent posting_date is excluded from the main time-series
     chart and listed separately in the report as a flagged outlier.
  4. Every dimensional column confirmed 100% null as of 2026-09-12
     (job_category_id, experience_level_id, employment_type_id,
     education_level_id, industry_id, remote_work_type_id) is INTENTIONALLY
     absent from this analysis. Re-run the null-rate check in
     data_completeness() each time before trusting this list - if any of
     these gets populated by a future step, this script will keep silently
     ignoring it until someone notices.

Usage:
    Set the NEON_PROD_DATABASE_URL environment variable first (never commit
    its value):

        $env:NEON_PROD_DATABASE_URL = "postgresql://...neon.tech/neondb?"`
            + "sslmode=require&channel_binding=require"

    Then, from the project root:

        uv run python analysis/step30_eda/run_eda.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import cast

import matplotlib

matplotlib.use("Agg")  # headless: never try to open a GUI window
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

sns.set_theme(style="whitegrid")

OUTPUT_DIR = Path(__file__).parent / "output"
OUTLIER_WINDOW_DAYS = 90


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_connection() -> Engine:
    dsn = os.environ.get("NEON_PROD_DATABASE_URL")
    if not dsn:
        raise SystemExit(
            "NEON_PROD_DATABASE_URL is not set. This script deliberately does "
            "not embed a production credential, since it lives in git. Set "
            "the environment variable and re-run - see README.md."
        )
    # pandas.read_sql wants a SQLAlchemy engine/connection (a raw psycopg
    # connection works but triggers a UserWarning on every call). Force the
    # psycopg3 driver explicitly since that's already this project's
    # standard driver (see design doc / schema notes).
    if dsn.startswith("postgresql://"):
        dsn = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(dsn, connect_args={"connect_timeout": 15})


# ---------------------------------------------------------------------------
# Data loading - one query per concern, kept simple over clever
# ---------------------------------------------------------------------------

def load_jobs(conn: Engine) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT
            j.job_id, j.source_id, s.source_name, j.job_title,
            j.title_classification_status, j.normalized_title_id,
            nt.normalized_title, nt.job_family,
            j.company_id, c.company_name,
            j.location_id, j.job_status, j.posting_date,
            j.first_scraped_at, j.last_scraped_at
        FROM core.jobs j
        JOIN ref.sources s ON s.source_id = j.source_id
        JOIN core.companies c ON c.company_id = j.company_id
        LEFT JOIN ref.normalized_job_titles nt ON nt.normalized_title_id = j.normalized_title_id
        """,
        conn,
    )


def load_salaries(conn: Engine) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT job_id, salary_disclosed, normalized_annual_min_usd,
               normalized_annual_max_usd, is_estimated
        FROM salary.job_salaries
        """,
        conn,
    )


def load_skills(conn: Engine) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT bjs.job_id, sk.skill_name, sc.category_name, bjs.requirement_type
        FROM bridge.job_skills bjs
        JOIN ref.skills sk ON sk.skill_id = bjs.skill_id
        JOIN ref.skill_categories sc ON sc.skill_category_id = sk.skill_category_id
        """,
        conn,
    )


def data_completeness(conn: Engine) -> pd.DataFrame:
    """Null-rate check on every dimensional FK on core.jobs. Re-run this
    every time - do not trust the hardcoded list in the module docstring."""
    query = """
        SELECT
            count(*) AS total_jobs,
            count(*) FILTER (WHERE location_id IS NULL) AS location_id_null,
            count(*) FILTER (WHERE job_category_id IS NULL) AS job_category_id_null,
            count(*) FILTER (WHERE experience_level_id IS NULL) AS experience_level_id_null,
            count(*) FILTER (WHERE employment_type_id IS NULL) AS employment_type_id_null,
            count(*) FILTER (WHERE education_level_id IS NULL) AS education_level_id_null,
            count(*) FILTER (WHERE normalized_title_id IS NULL) AS normalized_title_id_null,
            count(*) FILTER (WHERE industry_id IS NULL) AS industry_id_null,
            count(*) FILTER (WHERE remote_work_type_id IS NULL) AS remote_work_type_id_null
        FROM core.jobs;
    """
    df = pd.read_sql(query, conn)
    # pandas-stubs types df.loc[...] scalar access as a very broad union
    # (str | bytes | date | ... | complex). At runtime this is always a
    # plain int, since it comes from a Postgres count(*). cast() tells
    # mypy to trust that rather than re-deriving it — same pattern as the
    # documented rowcount type: ignore elsewhere in this project.
    total = cast(int, df.loc[0, "total_jobs"])
    long = df.drop(columns=["total_jobs"]).T.reset_index()
    long.columns = ["column", "null_count"]
    long["column"] = long["column"].str.removesuffix("_null")
    long["null_pct"] = (100 * long["null_count"] / total).round(1)
    return long.sort_values("null_pct", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Charts - each returns the filename it wrote, for the report to reference
# ---------------------------------------------------------------------------

def chart_source_status(jobs: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(7, 4))
    counts = jobs.groupby(["source_name", "job_status"]).size().unstack(fill_value=0)
    counts.plot(kind="bar", stacked=True, ax=ax, legend=True)
    ax.set_title("Jobs by source and status")
    ax.set_xlabel("")
    ax.set_ylabel("job count")
    plt.xticks(rotation=0)
    fig.tight_layout()
    path = OUTPUT_DIR / "01_source_status.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name


def chart_title_classification(jobs: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(6, 4))
    counts = jobs["title_classification_status"].value_counts()
    ax.bar(counts.index.tolist(), counts.values.tolist(), color=["#4c72b0", "#dd8452", "#c44e52"])
    ax.set_title("Title classification outcome (all sources)")
    ax.set_ylabel("job count")
    for i, v in enumerate(counts.values):
        ax.text(i, v + 5, str(v), ha="center")
    fig.tight_layout()
    path = OUTPUT_DIR / "02_title_classification.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name


def chart_job_families(jobs: pd.DataFrame, top_n: int = 15) -> str:
    matched = jobs[jobs["title_classification_status"] == "matched"]
    counts = matched["job_family"].value_counts().head(top_n)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(counts.index[::-1].tolist(), counts.values[::-1].tolist(), color="#4c72b0")
    ax.set_title(f"Top {top_n} job families (matched titles only, n={len(matched)})")
    ax.set_xlabel("job count")
    fig.tight_layout()
    path = OUTPUT_DIR / "03_job_families.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name


def chart_posting_volume(jobs: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Returns (chart filename, outlier rows table). Outliers = postings
    more than OUTLIER_WINDOW_DAYS before the most recent posting_date;
    handled generically per confirmed scope, not manually investigated."""
    dates = pd.to_datetime(jobs["posting_date"])
    cutoff = dates.max() - pd.Timedelta(days=OUTLIER_WINDOW_DAYS)
    recent = jobs[dates >= cutoff].copy()
    outliers = jobs[dates < cutoff][
        ["job_id", "source_name", "job_title", "posting_date"]
    ].sort_values("posting_date")

    daily = pd.to_datetime(recent["posting_date"]).dt.date.value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(daily.index.tolist(), daily.values.tolist(), marker="o", markersize=3)
    ax.set_title(
        f"Postings per day, last {OUTLIER_WINDOW_DAYS} days "
        f"({len(outliers)} older outlier row(s) excluded, listed separately)"
    )
    ax.set_ylabel("job count")
    fig.autofmt_xdate()
    fig.tight_layout()
    path = OUTPUT_DIR / "04_posting_volume.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name, outliers


def chart_top_companies(jobs: pd.DataFrame, top_n: int = 15) -> str:
    active = jobs[jobs["job_status"] == "active"]
    counts = active["company_name"].value_counts().head(top_n)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh(counts.index[::-1].tolist(), counts.values[::-1].tolist(), color="#55a868")
    ax.set_title(f"Top {top_n} companies by posting count (all statuses currently 'active')")
    ax.set_xlabel("job count")
    fig.tight_layout()
    path = OUTPUT_DIR / "05_top_companies.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name


def chart_top_skills(skills: pd.DataFrame, jobs_total: int, top_n: int = 20) -> str:
    counts = skills["skill_name"].value_counts().head(top_n)
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.barh(counts.index[::-1].tolist(), counts.values[::-1].tolist(), color="#8172b2")
    coverage_pct = round(100 * skills["job_id"].nunique() / jobs_total, 1)
    ax.set_title(
        f"Top {top_n} extracted skills "
        f"(only {coverage_pct}% of jobs have any extracted skill)"
    )
    ax.set_xlabel("job count")
    fig.tight_layout()
    path = OUTPUT_DIR / "06_top_skills.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path.name


def salary_summary(salaries: pd.DataFrame) -> pd.DataFrame:
    """Returns disclosed-salary rows with a heuristic anomaly flag.

    The flag is deliberately crude (min/max sanity bounds + spread ratio) -
    it exists to make obviously-wrong normalization results visible on
    every run, not to be a rigorous outlier model. A flagged row means
    "look at this before trusting it," not "this is definitely wrong."
    """
    disclosed = salaries[salaries["salary_disclosed"] == True].copy()  # noqa: E712

    def flag(row: pd.Series) -> str:
        a, b = row["normalized_annual_min_usd"], row["normalized_annual_max_usd"]
        if pd.isna(a) or pd.isna(b):
            return "missing normalized value despite salary_disclosed=true"
        if a < 1000:
            return "implausibly low for an annual figure - likely un-annualized rate"
        if a > 0 and (b / a) > 5:
            return f"min/max spread is {b / a:.0f}x - check pay-period/currency conversion"
        return ""

    disclosed["anomaly_flag"] = disclosed.apply(flag, axis=1)
    cols = [
        "job_id", "normalized_annual_min_usd", "normalized_annual_max_usd",
        "is_estimated", "anomaly_flag",
    ]
    return disclosed[cols]


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report(
    jobs: pd.DataFrame,
    salaries: pd.DataFrame,
    skills: pd.DataFrame,
    completeness: pd.DataFrame,
    charts: dict[str, str],
    outliers: pd.DataFrame,
    salary_rows: pd.DataFrame,
) -> str:
    total = len(jobs)
    matched_n = (jobs["title_classification_status"] == "matched").sum()
    no_match_n = (jobs["title_classification_status"] == "no_match").sum()
    excluded_n = (jobs["title_classification_status"] == "excluded_non_job").sum()
    skills_coverage_n = skills["job_id"].nunique()

    lines = []
    lines.append("# Step 30 - Exploratory Data Analysis")
    lines.append("")
    lines.append(
        f"Generated against Neon production. Dataset size at generation time: "
        f"**{total} jobs**."
    )
    lines.append("")
    lines.append(
        "This report includes an honest data-completeness section before any "
        "market-composition claims, because several core dimensional fields "
        "are currently unpopulated and several other fields are populated "
        "for only a small fraction of the dataset. Every chart below is "
        "scoped to what the current data can actually support."
    )
    lines.append("")

    lines.append("## Data completeness")
    lines.append("")
    lines.append("| Column | Null count | Null % |")
    lines.append("|---|---|---|")
    for _, row in completeness.iterrows():
        lines.append(f"| `{row['column']}` | {row['null_count']} | {row['null_pct']}% |")
    lines.append("")
    fully_null = completeness[completeness["null_pct"] == 100.0]["column"].tolist()
    if fully_null:
        cols = ", ".join(f"`{c}`" for c in fully_null)
        lines.append(
            f"**{len(fully_null)} column(s) are 100% null as of this run**: {cols}. "
            "No breakdown by these dimensions appears anywhere below, because "
            "there is no data to break down."
        )
    lines.append("")

    lines.append("## Title classification quality")
    lines.append("")
    lines.append(
        f"`matched`: {matched_n} ({100*matched_n/total:.1f}%) | "
        f"`no_match`: {no_match_n} ({100*no_match_n/total:.1f}%) | "
        f"`excluded_non_job`: {excluded_n} ({100*excluded_n/total:.1f}%)"
    )
    lines.append("")
    lines.append(
        "`excluded_non_job` currently only catches the literal string \"test\". "
        "`no_match` is a mix of genuine jobs outside the current title "
        "taxonomy's scope and unfiltered scrape noise (personal names, menu "
        "items, template text). By agreed scope, company/skill/salary/volume "
        "charts below include both `matched` and `no_match` jobs. Job-family "
        "and normalized-title charts can only use `matched` jobs, since "
        "`no_match` rows have no normalized title by definition."
    )
    lines.append("")
    lines.append(f"![Title classification]({charts['title_classification']})")
    lines.append("")

    lines.append("## Sources and status")
    lines.append("")
    lines.append(
        "Every job in the dataset currently has `job_status = 'active'` - "
        "the pipeline has never flipped a posting to `closed`/`expired`. "
        "This is a known, documented gap; treat 'active' as meaning "
        "\"currently tracked,\" not \"confirmed still open.\""
    )
    lines.append("")
    lines.append(f"![Source and status]({charts['source_status']})")
    lines.append("")

    lines.append("## Job families")
    lines.append("")
    lines.append(f"Matched jobs only (n={matched_n}).")
    lines.append("")
    lines.append(f"![Job families]({charts['job_families']})")
    lines.append("")

    lines.append("## Posting volume over time")
    lines.append("")
    lines.append(
        f"Postings older than {OUTLIER_WINDOW_DAYS} days before the most "
        "recent posting_date are excluded from the chart and listed here "
        "instead, so a small number of old outliers can't distort the "
        "visible trend."
    )
    lines.append("")
    lines.append(f"![Posting volume]({charts['posting_volume']})")
    lines.append("")
    if len(outliers) > 0:
        lines.append(f"**{len(outliers)} outlier posting(s) excluded from the chart above:**")
        lines.append("")
        lines.append("| job_id | source | title | posting_date |")
        lines.append("|---|---|---|---|")
        for _, row in outliers.iterrows():
            lines.append(
                f"| {row['job_id']} | {row['source_name']} | "
                f"{row['job_title']} | {row['posting_date']} |"
            )
    else:
        lines.append(f"No postings older than {OUTLIER_WINDOW_DAYS} days found - nothing excluded.")
    lines.append("")

    lines.append("## Companies")
    lines.append("")
    lines.append(f"![Top companies]({charts['top_companies']})")
    lines.append("")

    lines.append("## Skills")
    lines.append("")
    lines.append(
        f"Only {skills_coverage_n}/{total} jobs ({100*skills_coverage_n/total:.1f}%) have "
        "any extracted skill at all. The extractor is rule-based and, on "
        "this data, skews heavily toward generic soft skills (Communication, "
        "Teamwork, Leadership) over hard technical skills - treat this as a "
        "coverage/extraction-method finding, not a market finding about what "
        "employers actually want."
    )
    lines.append("")
    lines.append(f"![Top skills]({charts['top_skills']})")
    lines.append("")

    lines.append("## Salary")
    lines.append("")
    lines.append(
        f"Only {len(salary_rows)}/{total} jobs ({100*len(salary_rows)/total:.1f}%) have "
        "a disclosed salary - too small a sample to support any distributional "
        "claim (average, median, by-title comparison)."
    )
    lines.append("")
    n_flagged = (salary_rows["anomaly_flag"] != "").sum()
    if n_flagged > 0:
        lines.append(
            f"**{n_flagged} of {len(salary_rows)} disclosed-salary rows look wrong, "
            "not just sparse** - implausible values (e.g. an annual figure "
            "under $1,000, or a >5x spread between min and max), most likely "
            "from Step 27's pay-period/currency normalization rather than "
            "from the source data itself. Flagged rows are marked below; "
            "treat the whole salary section as needing a normalization-logic "
            "review before any real use, not just \"wait for more data.\""
        )
        lines.append("")
    if len(salary_rows) > 0:
        lines.append("| job_id | annual min (USD) | annual max (USD) | estimated | flag |")
        lines.append("|---|---|---|---|---|")
        for _, row in salary_rows.sort_values("normalized_annual_min_usd").iterrows():
            lo_val = row["normalized_annual_min_usd"]
            hi_val = row["normalized_annual_max_usd"]
            lo = "-" if pd.isna(lo_val) else f"{lo_val:.0f}"
            hi = "-" if pd.isna(hi_val) else f"{hi_val:.0f}"
            flag = row["anomaly_flag"] or ""
            lines.append(f"| {row['job_id']} | {lo} | {hi} | {row['is_estimated']} | {flag} |")
    lines.append("")

    lines.append("## Caveats for any downstream use of this report")
    lines.append("")
    lines.append(
        f"- Dataset size ({total} jobs) is small; all findings are preliminary "
        "and directional, not statistically robust."
    )
    lines.append(
        "- `job_status` never leaves `active` - no lifecycle/duration analysis "
        "is possible yet."
    )
    lines.append(
        "- Six dimensional FK columns are 100% null (see completeness table) - "
        "no breakdown by category, experience level, employment type, "
        "education level, industry, or remote-work-type is possible yet."
    )
    lines.append(
        "- Salary figures rest on a small sample (see flagged rows above) - "
        "some values likely reflect a normalization bug (pay-period/currency "
        "conversion), not just limited disclosure. Skill figures rest on a "
        "small, extraction-limited subset of the data."
    )
    lines.append(
        "- `no_match` jobs are included in several charts per agreed scope, "
        "but this bucket mixes real off-taxonomy jobs with unfiltered scrape "
        "noise."
    )
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log("Connecting to Neon production...")
    conn = get_connection()
    log("Connected. Loading data...")

    jobs = load_jobs(conn)
    salaries = load_salaries(conn)
    skills = load_skills(conn)
    completeness = data_completeness(conn)
    conn.dispose()
    log(f"Loaded {len(jobs)} jobs, {len(salaries)} salary rows, {len(skills)} skill rows.")

    log("Generating charts...")
    charts = {}
    charts["source_status"] = chart_source_status(jobs)
    charts["title_classification"] = chart_title_classification(jobs)
    charts["job_families"] = chart_job_families(jobs)
    charts["posting_volume"], outliers = chart_posting_volume(jobs)
    charts["top_companies"] = chart_top_companies(jobs)
    charts["top_skills"] = chart_top_skills(skills, jobs_total=len(jobs))

    salary_rows = salary_summary(salaries)

    log("Writing report.md...")
    report = build_report(jobs, salaries, skills, completeness, charts, outliers, salary_rows)
    (OUTPUT_DIR / "report.md").write_text(report, encoding="utf-8")

    log(f"Done. Output in {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
