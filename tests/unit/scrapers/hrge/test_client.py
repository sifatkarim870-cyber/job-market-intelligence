"""Tests for HR.ge's detail-phase budget and progress logging.

The detail phase is one HTTP request per posting, so it - not the list phase -
decides whether a run finishes. The list phase walks 3,560 ids in 36 seconds;
the detail phase is what blew the 20-minute step, and it used to log nothing at
all, so a 19-minute silent stall looked exactly like a hang.

No HTTP mocking here. The two private methods that touch the network are
patched with counting stubs, which makes what these tests are actually about
directly observable: how many times each is called.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from job_market_intel.scrapers.hrge.client import HRGeClient
from job_market_intel.scrapers.hrge.config import HRGeSettings
from job_market_intel.scrapers.hrge.exceptions import HRGeResponseError

PAGES = 20
PER_PAGE = 100
TOTAL = PAGES * PER_PAGE


@contextmanager
def patched_client(settings: HRGeSettings | None = None):
    """Run with `_fetch_list_page` / `_fetch_detail` replaced by counters."""
    calls = {"list": 0, "detail": 0}

    def fake_list_page(self, start: int) -> tuple[list[dict], int | None]:
        calls["list"] += 1
        items = [
            {"announcementId": start + i, "name": f"J{start + i}"} for i in range(PER_PAGE)
        ]
        return items, TOTAL

    def fake_detail(self, announcement_id: object) -> dict | None:
        calls["detail"] += 1
        return {"description": f"detail for {announcement_id}"}

    original_list = HRGeClient._fetch_list_page
    original_detail = HRGeClient._fetch_detail
    HRGeClient._fetch_list_page = fake_list_page  # type: ignore[assignment]
    HRGeClient._fetch_detail = fake_detail  # type: ignore[assignment]
    try:
        yield HRGeClient(settings) if settings else HRGeClient(), calls
    finally:
        HRGeClient._fetch_list_page = original_list  # type: ignore[assignment]
        HRGeClient._fetch_detail = original_detail  # type: ignore[assignment]


def run(settings: HRGeSettings) -> tuple[list[dict], dict[str, int]]:
    """One run against the counting stubs; returns (jobs, call counts)."""
    with patched_client(settings) as (client, calls):
        jobs = client.fetch_raw_jobs()
    return jobs, calls


def test_caps_detail_requests_and_returns_every_id():
    """1,000 ids listed, but only `max_details_per_run` get a detail request.

    A budget of 10 against 2,000 ids is the same shape as the real incident:
    3,560 ids listed in 36 s, then a detail request per posting that ran past the
    20-minute step with no log output at all.
    """
    jobs, calls = run(
        HRGeSettings(max_pages_per_run=PAGES, max_details_per_run=10)
    )

    # Every id is returned: a skipped detail costs the description, not the row.
    assert len(jobs) == TOTAL
    assert calls["list"] == PAGES
    assert calls["detail"] == 10, f"expected 10 detail requests, made {calls['detail']}"


def test_rows_without_a_detail_still_carry_their_list_data():
    jobs, _ = run(HRGeSettings(max_pages_per_run=PAGES, max_details_per_run=1))

    assert len(jobs) == TOTAL
    enriched = [j for j in jobs if "description" in j]
    assert len(enriched) == 1, "only the first row should gain a description"
    # The rest must keep their list-entry fields, not come back empty.
    assert jobs[1]["name"] == "J1"
    assert jobs[1]["announcementId"] == 1


def test_budget_of_zero_means_list_only():
    jobs, calls = run(HRGeSettings(max_pages_per_run=PAGES, max_details_per_run=0))

    assert len(jobs) == TOTAL
    assert calls["detail"] == 0


def test_budget_larger_than_corpus_means_all_get_details():
    jobs, calls = run(
        HRGeSettings(max_pages_per_run=PAGES, max_details_per_run=TOTAL * 10)
    )

    assert calls["detail"] == TOTAL
    assert all("description" in j for j in jobs)


def test_default_budget_fits_the_ci_step_timeout():
    """The default must comfortably hold the 20-minute Scrape (HTML) step."""
    settings = HRGeSettings()
    # Conservative ceiling: even half a second per posting including the
    # politeness delay must not reach the step timeout.
    assert settings.max_details_per_run * 0.5 / 60 < 20, (
        f"{settings.max_details_per_run} details at 0.5 s each is "
        f"{settings.max_details_per_run * 0.5 / 60:.0f} min, over the 20-min step"
    )


def test_detail_fetch_is_de_duplicated_per_id():
    """De-dup happens before the detail phase, so a re-seen id costs one request."""
    calls = {"detail": 0}

    def fake_detail(self, announcement_id: object) -> dict | None:
        calls["detail"] += 1
        return {"description": "work"}

    def one_page_of_duplicates(self, start: int) -> tuple[list[dict], int | None]:
        return (
            [
                {"announcementId": 1, "name": "Job 1"},
                {"announcementId": 1, "name": "Job 1 again"},
                {"announcementId": 2, "name": "Job 2"},
            ],
            3,
        )

    original_list = HRGeClient._fetch_list_page
    original_detail = HRGeClient._fetch_detail
    HRGeClient._fetch_list_page = one_page_of_duplicates  # type: ignore[assignment]
    HRGeClient._fetch_detail = fake_detail  # type: ignore[assignment]
    try:
        jobs = HRGeClient(
            HRGeSettings(max_pages_per_run=1, max_details_per_run=9999)
        ).fetch_raw_jobs()
    finally:
        HRGeClient._fetch_list_page = original_list  # type: ignore[assignment]
        HRGeClient._fetch_detail = original_detail  # type: ignore[assignment]

    assert len(jobs) == 2
    assert calls["detail"] == 2


def test_empty_listing_still_raises():
    def no_items(self, start: int) -> tuple[list[dict], int | None]:
        return [], 0

    original_list = HRGeClient._fetch_list_page
    HRGeClient._fetch_list_page = no_items  # type: ignore[assignment]
    try:
        with pytest.raises(HRGeResponseError):
            HRGeClient(HRGeSettings(max_pages_per_run=1)).fetch_raw_jobs()
    finally:
        HRGeClient._fetch_list_page = original_list  # type: ignore[assignment]


def test_progress_is_logged_during_the_detail_phase():
    """The absence of any progress line is what made this bug take this long.

    The run logged 'listed so far: 3560' and then nothing for 19 minutes, so a
    timeout and a hang were indistinguishable from the log alone.
    """
    # loguru writes to its own sinks and bypasses stdlib logging, so caplog sees
    # nothing. Capture through loguru itself instead.

    from job_market_intel.scrapers.hrge import client as client_module

    messages: list[str] = []
    original_logger = client_module.logger

    class CapturingLogger:
        def info(self, message: str, *args, **kwargs) -> None:
            messages.append(message.format(*args) if args else message)

        def warning(self, message: str, *args, **kwargs) -> None:
            messages.append(message.format(*args) if args else message)

    client_module.logger = CapturingLogger()
    try:
        run(HRGeSettings(max_pages_per_run=PAGES, max_details_per_run=250))
    finally:
        client_module.logger = original_logger

    progress = [m for m in messages if "detail fetch" in m]
    assert progress, f"expected progress lines, saw: {messages[-3:]}"
    assert "250" in progress[-1], progress[-1]
    assert "elapsed" in progress[-1]


def test_the_skipped_detail_count_is_logged():
    """Seeing '2,000 unique, details merged for 250' is what told us the budget
    was binding -- without it, a capped run and a full run look identical."""
    from job_market_intel.scrapers.hrge import client as client_module

    messages: list[str] = []
    original_logger = client_module.logger

    class CapturingLogger:
        def info(self, message: str, *args, **kwargs) -> None:
            messages.append(message.format(*args) if args else message)

        def warning(self, message: str, *args, **kwargs) -> None:
            pass

    client_module.logger = CapturingLogger()
    try:
        run(HRGeSettings(max_pages_per_run=PAGES, max_details_per_run=250))
    finally:
        client_module.logger = original_logger

    capped = [m for m in messages if "only fetching details for the newest" in m]
    assert capped, f"expected a capping log line, saw: {messages[:3]}"
    assert "2000" in capped[0] and "250" in capped[0]
