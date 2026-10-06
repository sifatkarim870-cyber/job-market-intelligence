"""Unit tests for job_market_intel.scrapers.hrge.parser.

The parser's contract is skip-don't-crash: one malformed record must
never take down a whole run (the same contract every other source's
parser tests pin down).
"""

from __future__ import annotations

from job_market_intel.scrapers.hrge.parser import HRGeParser


def _entry(**overrides):
    entry = {"announcementId": 1, "title": "Engineer", "customerName": "Acme"}
    entry.update(overrides)
    return entry


class TestParseJobs:
    def test_valid_records_parse(self) -> None:
        jobs = HRGeParser().parse_jobs([_entry(), _entry(announcementId=2)])
        assert [j.source_job_id for j in jobs] == ["1", "2"]

    def test_malformed_record_is_skipped_not_raised(self) -> None:
        jobs = HRGeParser().parse_jobs([
            _entry(),
            _entry(title=""),  # fails min_length -> ValidationError -> skipped
            _entry(announcementId=3),
        ])
        assert [j.source_job_id for j in jobs] == ["1", "3"]

    def test_non_dict_record_is_skipped(self) -> None:
        jobs = HRGeParser().parse_jobs([_entry(), {"bogus": True}])
        assert len(jobs) == 1

    def test_empty_batch_is_fine(self) -> None:
        assert HRGeParser().parse_jobs([]) == []
