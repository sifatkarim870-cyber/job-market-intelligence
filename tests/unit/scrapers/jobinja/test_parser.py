"""Unit tests for job_market_intel.scrapers.jobinja.parser.

The parser's contract is skip-don't-crash: one malformed record (a page
without JSON-LD, a lost URL) must never take down a whole run — the
same contract every other source's parser tests pin down.
"""

from __future__ import annotations

from job_market_intel.scrapers.jobinja.parser import JobinjaParser

_URL_A = "https://jobinja.ir/companies/acme/jobs/aaaa/first"
_URL_B = "https://jobinja.ir/companies/acme/jobs/bbbb/second"

_PAGE = (
    '<html><script type="application/ld+json">'
    '{"@type": "JobPosting", "identifier": {"value": "11111"},'
    ' "title": "مهندس نرم‌افزار", "datePosted": "2026-10-01",'
    ' "hiringOrganization": {"name": "Acme"},'
    ' "jobLocation": {"address": {"addressCountry": {"name": "IR"}}}'
    "}</script></html>"
)


def _entry(**overrides) -> dict:
    entry = {"url": _URL_A, "html": _PAGE}
    entry.update(overrides)
    return entry


class TestParseJobs:
    def test_valid_records_parse(self) -> None:
        jobs = JobinjaParser().parse_jobs(
            [
                _entry(),
                _entry(
                    url=_URL_B,
                    html=_PAGE.replace("11111", "22222"),
                ),
            ]
        )
        assert [j.source_job_id for j in jobs] == ["11111", "22222"]

    def test_page_without_job_posting_is_skipped_not_raised(self) -> None:
        jobs = JobinjaParser().parse_jobs([
            _entry(),
            {"url": _URL_B, "html": "<html><body>maintenance</body></html>"},
        ])
        assert len(jobs) == 1

    def test_page_without_ldjson_is_skipped(self) -> None:
        jobs = JobinjaParser().parse_jobs([_entry(html="<html>no structured data</html>")])
        assert jobs == []

    def test_missing_url_is_skipped(self) -> None:
        # original_url is injected by the client; an empty one means
        # the payload lost its canonical URL and the record is unusable.
        jobs = JobinjaParser().parse_jobs([_entry(), {"html": _PAGE}])
        assert len(jobs) == 1

    def test_empty_batch_is_fine(self) -> None:
        assert JobinjaParser().parse_jobs([]) == []
