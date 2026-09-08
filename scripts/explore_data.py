"""Exploratory analysis script for the Job Market Intelligence Platform database.

Performs statistical analysis over the ingested PostgreSQL data:
  - Row counts across core tables
  - Summary statistics for salary distribution (mean, std, percentiles)
  - Job description word count statistics
  - Data quality score distribution
  - Top hiring employers
  - Scraping session audit metrics
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from job_market_intel.db.session import get_session


def main() -> None:
    print("=" * 70)
    print("EXPLAINABLE AI JOB MARKET INTELLIGENCE PLATFORM")
    print("PostgreSQL Database — Exploratory Data Analysis Report")
    print("=" * 70)

    with get_session() as session:
        # 1. Row counts across main schemas
        table_counts = {}
        tables = [
            ("core", "jobs"),
            ("core", "companies"),
            ("core", "job_descriptions"),
            ("salary", "job_salaries"),
            ("ops", "scraping_sessions"),
            ("ref", "sources"),
            ("ref", "skills"),
        ]
        for schema, tbl in tables:
            count = session.execute(text(f"SELECT count(*) FROM {schema}.{tbl}")).scalar()
            table_counts[f"{schema}.{tbl}"] = count

        print("\n📊 TABLE ROW COUNTS:")
        print("-" * 50)
        for tbl_name, count in table_counts.items():
            print(f"  {tbl_name:<30} {count:>8,}")

        # 2. Company Summary
        companies_df = pd.read_sql(
            text(
                "SELECT c.company_name, count(j.job_id) as active_postings "
                "FROM core.companies c "
                "JOIN core.jobs j ON j.company_id = c.company_id "
                "GROUP BY c.company_name "
                "ORDER BY active_postings DESC LIMIT 10"
            ),
            con=session.connection(),
        )

        print("\n🏢 TOP 10 EMPLOYERS BY ACTIVE POSTINGS:")
        print("-" * 50)
        print(companies_df.to_string(index=False))

        # 3. Salary Distribution Analysis
        salary_df = pd.read_sql(
            text(
                "SELECT salary_min, salary_max, salary_disclosed "
                "FROM salary.job_salaries "
                "WHERE salary_disclosed = TRUE"
            ),
            con=session.connection(),
        )

        print("\n💵 SALARY STATISTICAL SUMMARY (USD Annualized):")
        print("-" * 50)
        total_jobs = table_counts["core.jobs"]
        disclosed_jobs = len(salary_df)
        disclosure_rate = (disclosed_jobs / total_jobs * 100) if total_jobs else 0.0
        print(
            f"  Salary Disclosure Rate: {disclosure_rate:.1f}% "
            f"({disclosed_jobs}/{total_jobs} jobs)"
        )

        if not salary_df.empty:
            stats_min = salary_df["salary_min"].describe()
            stats_max = salary_df["salary_max"].describe()
            summary_table = pd.DataFrame({"Salary Min ($)": stats_min, "Salary Max ($)": stats_max})
            print(summary_table.to_string())

        # 4. Job Description Text Metrics
        desc_df = pd.read_sql(
            text("SELECT word_count FROM core.job_descriptions WHERE word_count IS NOT NULL"),
            con=session.connection(),
        )
        print("\n📝 JOB DESCRIPTION WORD COUNT METRICS:")
        print("-" * 50)
        if not desc_df.empty:
            desc_stats = desc_df["word_count"].describe()
            print(desc_stats.to_frame(name="Word Count Summary").to_string())

        # 5. Data Quality Score Distribution
        quality_df = pd.read_sql(
            text("SELECT data_quality_score FROM core.jobs WHERE data_quality_score IS NOT NULL"),
            con=session.connection(),
        )
        print("\n⭐ DATA QUALITY SCORE DISTRIBUTION:")
        print("-" * 50)
        if not quality_df.empty:
            quality_stats = quality_df["data_quality_score"].describe()
            print(quality_stats.to_frame(name="Quality Score").to_string())

        # 6. Scraping Session Audit
        sessions_df = pd.read_sql(
            text(
                "SELECT session_id, started_at, finished_at, status, "
                "jobs_found, jobs_new, jobs_updated "
                "FROM ops.scraping_sessions ORDER BY session_id DESC LIMIT 5"
            ),
            con=session.connection(),
        )
        print("\n⏱️ RECENT SCRAPING SESSIONS (ops.scraping_sessions):")
        print("-" * 50)
        print(sessions_df.to_string(index=False))

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
