"""Unit tests for job_market_intel.scrapers.reed.parser.ReedParser."""

from __future__ import annotations

from job_market_intel.scrapers.reed.parser import ReedParser

VALID_SEARCH = {
    "jobId": 1,
    "employerName": "Acme",
    "jobTitle": "Engineer",
    "jobUrl": "https://reed.example/1",
}


class TestParseJobs:
    def test_valid_record_is_parsed(self) -> None:
        parser = ReedParser()
        result = parser.parse_jobs([{"search": VALID_SEARCH, "details": None}])
        assert len(result) == 1
        assert result[0].source_job_id == "1"

    def test_empty_input_returns_empty_list(self) -> None:
        parser = ReedParser()
        assert parser.parse_jobs([]) == []

    def test_record_missing_required_field_is_skipped_not_raised(self) -> None:
        parser = ReedParser()
        broken = {"search": {"jobId": 2, "employerName": "Acme"}, "details": None}  # no jobTitle
        result = parser.parse_jobs([broken])
        assert result == []

    def test_one_bad_record_does_not_block_the_rest_of_the_batch(self) -> None:
        parser = ReedParser()
        broken = {"search": {"jobId": 2}, "details": None}
        good = {"search": VALID_SEARCH, "details": None}
        result = parser.parse_jobs([broken, good])
        assert len(result) == 1
        assert result[0].source_job_id == "1"

    def test_missing_search_key_is_treated_as_empty_and_skipped(self) -> None:
        parser = ReedParser()
        result = parser.parse_jobs([{"details": None}])
        assert result == []
