"""Manual entry point to run the RemoteOK scraper and see the results.

This script exists so you can confirm the scraper works by running one
command and reading the output — you do not need to write any code or use
pytest to try this out. It does NOT touch the database and does NOT clean
or normalize the data; it only fetches and validates, per Step 5's scope.

Run it from the project root with:

    python scripts/run_remoteok_scraper.py

What you should see:
    - Log lines in the terminal describing the fetch and parse steps.
    - A final summary printed to the terminal: how many jobs were fetched,
      how many parsed successfully, and a preview of the first few jobs.
    - A log file created at logs/job_market_intel.log with the same
      information plus more detail.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.common.logger import configure_logging
from job_market_intel.scrapers.remoteok import RemoteOKClient, RemoteOKError, RemoteOKParser, RemoteOKSettings


def main() -> int:
    """Run the RemoteOK scraper end-to-end and print a human-readable summary.

    Returns:
        Process exit code: ``0`` on success, ``1`` if the scrape failed.
    """
    configure_logging(log_dir="logs", console_level="INFO", file_level="DEBUG")

    settings = RemoteOKSettings()
    client = RemoteOKClient(settings=settings)
    parser = RemoteOKParser()

    logger.info("Starting manual RemoteOK scraper run.")

    try:
        raw_jobs = client.fetch_raw_jobs()
    except RemoteOKError as exc:
        logger.error("RemoteOK scraper run failed: {}", exc)
        return 1

    parsed_jobs = parser.parse_jobs(raw_jobs)

    print()
    print("=" * 70)
    print("REMOTEOK SCRAPER — MANUAL RUN SUMMARY")
    print("=" * 70)
    print(f"Raw job records fetched: {len(raw_jobs)}")
    print(f"Successfully parsed:     {len(parsed_jobs)}")
    print(f"Skipped (malformed):     {len(raw_jobs) - len(parsed_jobs)}")
    print()
    print("Preview of the first 5 parsed jobs:")
    print("-" * 70)
    for job in parsed_jobs[:5]:
        print(f"  [{job.source_job_id}] {job.job_title} @ {job.company_name}")
        print(f"      location: {job.location_raw or '(not specified)'}")
        print(f"      salary:   {job.salary_min or '?'} - {job.salary_max or '?'} USD")
        print(f"      url:      {job.original_url}")
        print()
    print("=" * 70)
    print("Full details are in logs/job_market_intel.log")
    print("=" * 70)

    logger.info("Manual RemoteOK scraper run finished successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
