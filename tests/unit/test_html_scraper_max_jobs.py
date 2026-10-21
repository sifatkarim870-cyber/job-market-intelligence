"""The generic HTML runner must actually honour ``--max-jobs``.

Found 2026-10-21: ``scripts/run_html_scraper.py`` parsed ``--max-jobs`` and then
never passed it anywhere. ``HtmlScraperPipeline.run`` had no such parameter, so
every "fetch 2 postings" probe silently fetched up to ``max_jobs_per_run`` (60)
detail pages. On jobwebghana.com that turned a 6-second check into a run that
never finished, which is how the cap was noticed.

The test pins the plumbing: the value reaches the client, and the pipeline does
not quietly substitute the site default.

Run with:  uv run pytest tests/unit/test_html_scraper_max_jobs.py -q
"""

from __future__ import annotations

from job_market_intel.scrapers.html_scraper.config import SiteConfig
from job_market_intel.scrapers.html_scraper.pipeline import HtmlScraperPipeline


class _RecordingClient:
    def __init__(self) -> None:
        self.seen: list[int | None] = []

    def fetch_raw_jobs(self, max_jobs: int | None = None):
        self.seen.append(max_jobs)
        return [], {}


def _site_config() -> SiteConfig:
    return SiteConfig(
        source_code="unit_test",
        source_name="Unit test board",
        country="Nowhere",
        base_url="https://example.invalid",
        max_jobs_per_run=60,
    )


def test_max_jobs_reaches_the_client() -> None:
    client = _RecordingClient()
    pipeline = HtmlScraperPipeline(
        source_code="unit_test",
        site_config=_site_config(),
        client=client,  # type: ignore[arg-type]
    )

    result = pipeline.run(store_db=False, max_jobs=3)

    assert client.seen == [3]
    assert result.raw_count == 0


def test_omitting_max_jobs_delegates_to_the_site_default() -> None:
    client = _RecordingClient()
    pipeline = HtmlScraperPipeline(
        source_code="unit_test",
        site_config=_site_config(),
        client=client,  # type: ignore[arg-type]
    )

    pipeline.run(store_db=False)

    assert client.seen == [None]
