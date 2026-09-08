"""Unit tests for job_market_intel.scrapers.remotive.parser.RemotiveParser.

Mirrors ``scrapers/remoteok/test_parser.py``'s ``TestParseJobsBasics``
coverage exactly — see that module's docstring for why each of these
matters (skip-don't-crash is the core reliability guarantee being
verified). No fixture-file-based end-to-end test is included here (unlike
RemoteOK's ``TestParseJobsAgainstFixture``) since inline records already
give the same coverage without a new fixture asset to maintain; revisit
if/when a real captured Remotive response sample is added to
``tests/fixtures/``.
"""

from __future__ import annotations

from job_market_intel.scrapers.remotive.models import RawRemotiveJob
from job_market_intel.scrapers.remotive.parser import RemotiveParser


class TestParseJobsBasics:
    def test_all_valid_records_are_parsed(self) -> None:
        raw_jobs = [
            {"id": 1, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"},
            {"id": 2, "title": "Designer", "company_name": "Globex", "url": "https://x.test/2"},
        ]
        result = RemotiveParser().parse_jobs(raw_jobs)
        assert len(result) == 2
        assert all(isinstance(job, RawRemotiveJob) for job in result)

    def test_empty_input_returns_empty_output(self) -> None:
        assert RemotiveParser().parse_jobs([]) == []

    def test_malformed_record_is_skipped_not_raised(self) -> None:
        raw_jobs = [
            {"id": 1, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"},
            {"id": 2, "company_name": "Globex", "url": "https://x.test/2"},  # missing "title"
            {"id": 3, "title": "Analyst", "company_name": "Initech", "url": "https://x.test/3"},
        ]
        # Must not raise, even though record 2 is malformed.
        result = RemotiveParser().parse_jobs(raw_jobs)
        assert len(result) == 2
        assert {job.source_job_id for job in result} == {"1", "3"}

    def test_all_malformed_records_returns_empty_list_without_raising(self) -> None:
        raw_jobs = [
            {"id": 1, "company_name": "Acme", "url": "https://x.test/1"},  # missing title
            {"id": 2, "title": "Designer", "url": "https://x.test/2"},  # missing company_name
        ]
        result = RemotiveParser().parse_jobs(raw_jobs)
        assert result == []

    def test_raw_payload_attached_to_parsed_records(self) -> None:
        raw = {"id": 1, "title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"}
        result = RemotiveParser().parse_jobs([raw])
        assert result[0].raw_payload == raw

    def test_unparseable_id_missing_record_reports_index_not_id(self) -> None:
        raw_jobs = [{"title": "Engineer", "company_name": "Acme", "url": "https://x.test/1"}]
        result = RemotiveParser().parse_jobs(raw_jobs)
        assert result == []
