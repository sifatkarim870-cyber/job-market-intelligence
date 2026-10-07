"""Unit tests for IrantalentParser — skip-don't-crash contract.

The request loop is covered live (probes r5-r10, 2026-10-07); these
tests pin the parser's behavior on the malformed records a live feed
produces: identity loss and non-object payloads skip with a warning,
valid rows (both language modes) come through.
"""

from __future__ import annotations

from job_market_intel.scrapers.irantalent.models import RawIrantalentJob
from job_market_intel.scrapers.irantalent.parser import IrantalentParser

from .test_models import ANON_PAYLOAD, ANON_URL, PAYLOAD, URL


def _raw(payload, url: str = URL) -> dict:
    return {"url": url, "payload": payload}


def test_valid_records_parse() -> None:
    parsed = IrantalentParser().parse_jobs([_raw(PAYLOAD), _raw(ANON_PAYLOAD, ANON_URL)])
    assert [job.source_job_id for job in parsed] == ["184579", "184576"]
    assert all(isinstance(job, RawIrantalentJob) for job in parsed)


def test_non_dict_payload_is_skipped_not_raised() -> None:
    parsed = IrantalentParser().parse_jobs([_raw(None), _raw(PAYLOAD), _raw("html wall")])
    # One bad record must never take down the run (the jobinja 76%
    # skip-rate morning made this contract vivid).
    assert [job.source_job_id for job in parsed] == ["184579"]


def test_identity_loss_is_skipped() -> None:
    parsed = IrantalentParser().parse_jobs(
        [_raw({**PAYLOAD, "id": None}), _raw({**PAYLOAD, "title": "", "title_farsi": None})]
    )
    assert parsed == []


def test_missing_url_is_skipped() -> None:
    # from_payload rejects an empty original_url; the parser reports it
    # under the record index (no URL to identify it with).
    parsed = IrantalentParser().parse_jobs([{"url": "", "payload": PAYLOAD}])
    assert parsed == []


def test_all_bad_batch_returns_empty_list() -> None:
    assert IrantalentParser().parse_jobs([]) == []
