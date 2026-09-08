"""Unit tests for job_market_intel.scrapers.weworkremotely.parser.WWRParser.

What these tests verify, and why each matters (mirrors
``scrapers/remoteok/test_parser.py``'s reasoning exactly):
    - A batch of fully valid records all parse successfully.
    - A single malformed record is skipped and logged, WITHOUT taking
      down the rest of the batch.
    - raw_payload is correctly attached to every successfully parsed
      record.

Uses inline dicts (WWRClient's raw dict shape) rather than a fixture
file — realistic XML-to-dict extraction is already thoroughly covered by
``test_client.py``, so a second fixture asset here would just duplicate
that coverage without testing anything new about the parser itself.
"""

from __future__ import annotations

from job_market_intel.scrapers.weworkremotely.models import RawWWRJob
from job_market_intel.scrapers.weworkremotely.parser import WWRParser


def _raw(**overrides: object) -> dict:
    defaults: dict[str, object] = {
        "title": "Acme Corp: Engineer",
        "guid": "https://weworkremotely.com/remote-jobs/acme-corp-engineer",
        "link": "https://weworkremotely.com/remote-jobs/acme-corp-engineer",
        "region": "Anywhere in the World",
        "country": None,
        "state": None,
        "skills": "python, django",
        "category": "Programming",
        "type": "Full-Time",
        "description": "<p>Do engineering things.</p>",
        "pubdate": "Tue, 25 Aug 2026 07:31:11 +0000",
        "expires_at": "Thu, 24 Sep 2026 07:31:11 +0000",
        "media_content_url": None,
    }
    defaults.update(overrides)
    return defaults


class TestParseJobsBasics:
    def test_all_valid_records_are_parsed(self) -> None:
        raw_jobs = [
            _raw(guid="https://weworkremotely.com/remote-jobs/job-one"),
            _raw(
                title="Globex: Designer",
                guid="https://weworkremotely.com/remote-jobs/job-two",
                link="https://weworkremotely.com/remote-jobs/job-two",
            ),
        ]
        result = WWRParser().parse_jobs(raw_jobs)
        assert len(result) == 2
        assert all(isinstance(job, RawWWRJob) for job in result)

    def test_empty_input_returns_empty_output(self) -> None:
        assert WWRParser().parse_jobs([]) == []

    def test_malformed_record_is_skipped_not_raised(self) -> None:
        raw_jobs = [
            _raw(guid="https://weworkremotely.com/remote-jobs/job-one"),
            _raw(title="No Separator Here", guid="https://weworkremotely.com/remote-jobs/job-two"),
            _raw(
                title="Initech: Analyst",
                guid="https://weworkremotely.com/remote-jobs/job-three",
                link="https://weworkremotely.com/remote-jobs/job-three",
            ),
        ]
        # Must not raise, even though the second record's title has no
        # "Company: Title" separator.
        result = WWRParser().parse_jobs(raw_jobs)
        assert len(result) == 2
        assert {job.source_job_id for job in result} == {"job-one", "job-three"}

    def test_all_malformed_records_returns_empty_list_without_raising(self) -> None:
        raw_jobs = [
            _raw(title="No Separator One", guid="https://weworkremotely.com/remote-jobs/job-one"),
            _raw(guid=None),  # missing identity entirely
        ]
        result = WWRParser().parse_jobs(raw_jobs)
        assert result == []

    def test_raw_payload_attached_to_parsed_records(self) -> None:
        raw = _raw()
        result = WWRParser().parse_jobs([raw])
        assert result[0].raw_payload == raw

    def test_missing_guid_record_is_skipped(self) -> None:
        raw_jobs = [
            _raw(guid="https://weworkremotely.com/remote-jobs/job-one"),
            _raw(guid=None),
        ]
        result = WWRParser().parse_jobs(raw_jobs)
        assert len(result) == 1
        assert result[0].source_job_id == "job-one"
