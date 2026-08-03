"""Unit tests for job_market_intel.scrapers.remoteok.parser.RemoteOKParser.

What these tests verify, and why each matters:
    - A batch of fully valid records all parse successfully.
    - A single malformed record is skipped and logged, WITHOUT taking down
      the rest of the batch — this is the core reliability guarantee of
      Step 5 ("one bad record must never crash the whole run").
    - The realistic fixture file (mixed valid/invalid/edge-case records,
      matching what RemoteOK's live feed actually looks like) produces
      exactly the expected valid/skipped counts.
    - raw_payload is correctly attached to every successfully parsed record.
"""

from __future__ import annotations

import json
from pathlib import Path

from job_market_intel.scrapers.remoteok.models import RawRemoteOKJob
from job_market_intel.scrapers.remoteok.parser import RemoteOKParser

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "remoteok" / "sample_response.json"


class TestParseJobsBasics:
    def test_all_valid_records_are_parsed(self) -> None:
        raw_jobs = [
            {"id": "1", "position": "Engineer", "company": "Acme", "url": "https://x.test/1"},
            {"id": "2", "position": "Designer", "company": "Globex", "url": "https://x.test/2"},
        ]
        result = RemoteOKParser().parse_jobs(raw_jobs)
        assert len(result) == 2
        assert all(isinstance(job, RawRemoteOKJob) for job in result)

    def test_empty_input_returns_empty_output(self) -> None:
        assert RemoteOKParser().parse_jobs([]) == []

    def test_malformed_record_is_skipped_not_raised(self) -> None:
        raw_jobs = [
            {"id": "1", "position": "Engineer", "company": "Acme", "url": "https://x.test/1"},
            {"id": "2", "company": "Globex", "url": "https://x.test/2"},  # missing required "position"
            {"id": "3", "position": "Analyst", "company": "Initech", "url": "https://x.test/3"},
        ]
        # Must not raise, even though record 2 is malformed.
        result = RemoteOKParser().parse_jobs(raw_jobs)
        assert len(result) == 2
        assert {job.source_job_id for job in result} == {"1", "3"}

    def test_all_malformed_records_returns_empty_list_without_raising(self) -> None:
        raw_jobs = [
            {"id": "1", "company": "Acme", "url": "https://x.test/1"},  # missing position
            {"id": "2", "position": "Designer", "url": "https://x.test/2"},  # missing company
        ]
        result = RemoteOKParser().parse_jobs(raw_jobs)
        assert result == []

    def test_raw_payload_attached_to_parsed_records(self) -> None:
        raw = {"id": "1", "position": "Engineer", "company": "Acme", "url": "https://x.test/1"}
        result = RemoteOKParser().parse_jobs([raw])
        assert result[0].raw_payload == raw


class TestParseJobsAgainstFixture:
    """End-to-end check against a realistic RemoteOK response sample.

    The fixture (tests/fixtures/remoteok/sample_response.json) contains,
    by design:
        - 1 non-job metadata entry (already stripped by client.py in real
          usage; this parser-level test feeds job records only, matching
          what the parser actually receives).
        - 3 records that should parse successfully (one complete, one
          missing several optional fields, one with an unparseable date
          that should still succeed with posting_date=None).
        - 2 records that should be skipped: one missing the required
          "position" field, one with empty-string required fields.
    """

    def _load_fixture_job_records(self) -> list[dict]:
        with FIXTURE_PATH.open(encoding="utf-8") as f:
            all_entries = json.load(f)
        # Mirror what RemoteOKClient.fetch_raw_jobs() does: drop the
        # leading non-job metadata entry (no "id" field) before handing
        # records to the parser.
        return [entry for entry in all_entries if "id" in entry]

    def test_fixture_produces_expected_valid_and_skipped_counts(self) -> None:
        job_records = self._load_fixture_job_records()
        assert len(job_records) == 5, "Fixture should contain 5 job-shaped entries (after metadata removed)"

        result = RemoteOKParser().parse_jobs(job_records)

        assert len(result) == 3
        assert {job.source_job_id for job in result} == {"1000001", "1000002", "1000003"}

    def test_fixture_record_with_malformed_date_still_parses(self) -> None:
        job_records = self._load_fixture_job_records()
        result = RemoteOKParser().parse_jobs(job_records)
        job_with_bad_date = next(job for job in result if job.source_job_id == "1000003")
        assert job_with_bad_date.posting_date is None

    def test_fixture_record_missing_title_is_skipped(self) -> None:
        job_records = self._load_fixture_job_records()
        result = RemoteOKParser().parse_jobs(job_records)
        parsed_ids = {job.source_job_id for job in result}
        assert "1000004" not in parsed_ids

    def test_fixture_record_with_empty_required_fields_is_skipped(self) -> None:
        job_records = self._load_fixture_job_records()
        result = RemoteOKParser().parse_jobs(job_records)
        parsed_ids = {job.source_job_id for job in result}
        assert "1000005" not in parsed_ids
