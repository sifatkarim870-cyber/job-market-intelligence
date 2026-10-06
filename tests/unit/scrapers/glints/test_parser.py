"""Unit tests for job_market_intel.scrapers.glints.parser.

The parser's contract is skip-don't-crash: one malformed record must
never take down a whole run (the same contract every other source's
parser tests pin down).
"""

from __future__ import annotations

from job_market_intel.scrapers.glints.parser import GlintsParser

_CANONICAL_URL = "https://glints.com/id/opportunities/jobs/j/11111111-1111-1111-1111-111111111111"


def _entry(**overrides):
    entry = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Engineer",
        "original_url": _CANONICAL_URL,
    }
    entry.update(overrides)
    return entry


class TestParseJobs:
    def test_valid_records_parse(self) -> None:
        jobs = GlintsParser().parse_jobs(
            [
                _entry(),
                _entry(id="22222222-2222-2222-2222-222222222222"),
            ]
        )
        assert [j.source_job_id for j in jobs] == [
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]

    def test_malformed_record_is_skipped_not_raised(self) -> None:
        jobs = GlintsParser().parse_jobs([
            _entry(),
            _entry(title=""),  # fails min_length -> ValidationError -> skipped
            _entry(id="33333333-3333-3333-3333-333333333333"),
        ])
        assert len(jobs) == 2

    def test_record_without_original_url_is_skipped(self) -> None:
        # original_url is injected by the client; an empty one means the
        # payload lost its canonical URL and the record is unusable.
        jobs = GlintsParser().parse_jobs([
            _entry(),
            {"id": "44444444-4444-4444-4444-444444444444", "title": "No URL"},
        ])
        assert len(jobs) == 1

    def test_non_job_record_is_skipped(self) -> None:
        jobs = GlintsParser().parse_jobs([_entry(), {"bogus": True}])
        assert len(jobs) == 1

    def test_empty_batch_is_fine(self) -> None:
        assert GlintsParser().parse_jobs([]) == []
