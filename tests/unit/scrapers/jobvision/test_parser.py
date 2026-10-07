"""Unit tests for job_market_intel.scrapers.jobvision.parser.

Skip-don't-crash: one malformed record must never take down the run —
same contract every other source's parser tests pin.
"""

from __future__ import annotations

from job_market_intel.scrapers.jobvision.parser import JobvisionParser


def _raw(payload, url: str = "https://jobvision.ir/jobs/1/x") -> dict:
    return {"url": url, "payload": payload}


class TestParseJobs:
    def test_valid_records_parse(self) -> None:
        records = [
            _raw({"id": 1, "title": "کارمند حسابداری"}),
            _raw({"id": 2, "title": "کارشناس فروش"}),
        ]
        jobs = JobvisionParser().parse_jobs(records)
        assert len(jobs) == 2
        assert {j.source_job_id for j in jobs} == {"1", "2"}

    def test_empty_batch_is_empty(self) -> None:
        assert JobvisionParser().parse_jobs([]) == []

    def test_payload_none_is_skipped(self) -> None:
        jobs = JobvisionParser().parse_jobs([_raw(None), _raw({"id": 3, "title": "x"})])
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "3"

    def test_missing_url_is_skipped(self) -> None:
        # original_url non-empty is required: the canonical URL is what
        # we store and re-visit; a record without it is unusable.
        jobs = JobvisionParser().parse_jobs(
            [{"url": "", "payload": {"id": 1, "title": "x"}}]
        )
        assert jobs == []

    def test_identityless_payload_is_skipped(self) -> None:
        jobs = JobvisionParser().parse_jobs(
            [
                _raw({"title": "بدون شناسه"}),
                _raw({"id": 5, "title": ""}),
                _raw({"id": 6, "title": "سالم"}),
            ]
        )
        assert len(jobs) == 1
        assert jobs[0].source_job_id == "6"

    def test_bad_records_never_raise(self) -> None:
        # A whole batch of garbage must produce zero jobs, not an error.
        garbage = [
            _raw(None),
            _raw([]),
            _raw({"id": 1}),  # no title
            {"url": None, "payload": {"id": 2, "title": "x"}},  # url None → ""
        ]
        assert JobvisionParser().parse_jobs(garbage) == []
