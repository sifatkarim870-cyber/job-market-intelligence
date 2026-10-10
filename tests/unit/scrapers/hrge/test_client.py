"""Tests for HR.ge's detail-phase budgets and progress logging.

The detail phase is one HTTP request per posting, so it - not the list phase -
decides whether a run finishes. The list phase walks 3,560 ids in 36 seconds;
the detail phase is what blew the 20-minute step, and it used to log nothing at
all, so a 19-minute silent stall looked exactly like a hang.

Two budgets gate it, and the second one exists because the first was not enough:
`max_details_per_run` is a count, `detail_budget_seconds` is a wall clock. A
count of 900 measured 1.18 s per detail in CI, so the phase alone consumed
17m45s of a 20-minute step and the run was killed before persisting anything -
four times the latency the count was sized around.

No HTTP mocking here. The two private methods that touch the network are
replaced with counting stubs, which makes what these tests are actually about
directly observable: how many times each is called, and how long the loop runs.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

import pytest

from job_market_intel.scrapers.hrge.client import HRGeClient
from job_market_intel.scrapers.hrge.config import HRGeSettings
from job_market_intel.scrapers.hrge.exceptions import HRGeResponseError

PAGES = 20
PER_PAGE = 100
TOTAL = PAGES * PER_PAGE


class CapturingLogger:
    """Stands in for the module's loguru logger.

    loguru writes to its own sinks and bypasses stdlib logging, so caplog sees
    none of it. Substitute the object the module resolves and collect the
    formatted messages directly.
    """

    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def _record(self, message: str, args: tuple) -> None:
        self._sink.append(message.format(*args) if args else message)

    def info(self, message: str, *args, **kwargs) -> None:
        self._record(message, args)

    def warning(self, message: str, *args, **kwargs) -> None:
        self._record(message, args)

    def debug(self, message: str, *args, **kwargs) -> None:
        pass

    def error(self, message: str, *args, **kwargs) -> None:
        self._record(message, args)


@contextmanager
def patched_network(settings: HRGeSettings | None = None, **stub_kwargs):
    """Patch the two network methods; yield (client, counts, log_messages).

    ``client`` is built with ``settings``, so the test's own budgets are what
    apply. ``detail_stub`` defaults to a fast stub that returns instantly; a test
    can supply a slow one to make the wall-clock deadline bind.
    """
    from job_market_intel.scrapers.hrge import client as client_module

    detail_stub = stub_kwargs.pop("detail_stub", None)
    detail_delay = stub_kwargs.pop("detail_delay", 0.0)
    counts = {"list": 0, "detail": 0}
    messages: list[str] = []
    stub = detail_stub or (lambda _self, announcement_id: {"description": "work"})

    def fake_list_page(self, start: int) -> tuple[list[dict], int | None]:
        counts["list"] += 1
        items = [
            {"announcementId": start + i, "name": f"J{start + i}"} for i in range(PER_PAGE)
        ]
        return items, TOTAL

    def fake_detail(self, announcement_id: object) -> dict | None:
        counts["detail"] += 1
        if detail_delay:
            time.sleep(detail_delay)
        return stub(self, announcement_id)

    original_list = HRGeClient._fetch_list_page
    original_detail = HRGeClient._fetch_detail
    original_logger = client_module.logger
    HRGeClient._fetch_list_page = fake_list_page  # type: ignore[assignment]
    HRGeClient._fetch_detail = fake_detail  # type: ignore[assignment]
    client_module.logger = CapturingLogger(messages)
    try:
        yield HRGeClient(settings), counts, messages
    finally:
        HRGeClient._fetch_list_page = original_list  # type: ignore[assignment]
        HRGeClient._fetch_detail = original_detail  # type: ignore[assignment]
        client_module.logger = original_logger


def run(
    settings: HRGeSettings, **stub_kwargs
) -> tuple[list[dict], dict[str, int], list[str]]:
    """One run against the patched network; returns (jobs, counts, log messages)."""
    with patched_network(settings, **stub_kwargs) as (client, counts, messages):
        jobs = client.fetch_raw_jobs()
    return jobs, counts, messages


def test_count_budget_caps_requests_and_returns_every_id():
    """1,000 ids listed, but only `max_details_per_run` get a detail request."""
    jobs, counts, _ = run(
        HRGeSettings(max_pages_per_run=PAGES, max_details_per_run=10)
    )

    # Every id is returned: a skipped detail costs the description, not the row.
    assert len(jobs) == TOTAL
    assert counts["list"] == PAGES
    assert counts["detail"] == 10, f"expected 10 detail requests, made {counts['detail']}"


def test_rows_past_the_budget_still_carry_their_list_data():
    jobs, counts, _ = run(
        HRGeSettings(max_pages_per_run=PAGES, max_details_per_run=1)
    )

    assert len(jobs) == TOTAL
    enriched = [j for j in jobs if "description" in j]
    assert len(enriched) == 1, "only the first row should gain a description"
    # The rest must keep their list-entry fields, not come back empty.
    assert jobs[1]["name"] == "J1"
    assert jobs[1]["announcementId"] == 1
    assert counts["detail"] == 1


def test_budget_of_zero_means_list_only():
    jobs, counts, _ = run(
        HRGeSettings(max_pages_per_run=PAGES, max_details_per_run=0)
    )

    assert len(jobs) == TOTAL
    assert counts["detail"] == 0
    assert all("description" not in j for j in jobs)


def test_budget_larger_than_corpus_means_all_get_details():
    jobs, counts, _ = run(
        HRGeSettings(
            max_pages_per_run=PAGES,
            max_details_per_run=TOTAL * 10,
            detail_fetch_delay_seconds=0.0,
        )
    )

    assert counts["detail"] == TOTAL
    assert all("description" in j for j in jobs)


def test_default_deadline_is_a_real_fraction_of_the_ci_step():
    """The 20-minute Scrape (HTML) step must hold the detail phase with room left
    for cleaning, validation and persistence."""
    settings = HRGeSettings()
    assert settings.detail_budget_seconds < 20 * 60 * 0.75, (
        f"{settings.detail_budget_seconds}s leaves too little of a 20-min step"
    )


def test_wall_clock_deadline_binds_under_slow_network():
    """The reason detail_budget_seconds exists.

    Sized as a count, 900 details measured 1.18 s each against the live API, so
    the phase alone consumed 17m45s and the run was killed before persisting
    anything. A deadline is immune to that variance.
    """
    deadline_seconds = 5.0
    jobs, counts, messages = run(
        HRGeSettings(
            max_pages_per_run=PAGES,
            max_details_per_run=TOTAL,  # count does NOT bind here
            detail_budget_seconds=deadline_seconds,
            detail_fetch_delay_seconds=0.0,
        ),
        detail_delay=0.01,  # 100ms each -> ~500 requests in the budget
    )

    assert counts["detail"] < TOTAL, "the deadline should have cut the loop short"
    assert counts["detail"] > 0
    # All rows still returned, most with list data only.
    assert len(jobs) == TOTAL
    assert sum(1 for j in jobs if "description" in j) == counts["detail"]

    hit = [m for m in messages if "detail budget of" in m]
    assert hit, f"expected a deadline line, saw: {messages[-3:]}"
    assert "reached at" in hit[0]


def test_deadline_of_zero_disables_it():
    """Otherwise a zero would cut the loop before the first request."""
    jobs, counts, _ = run(
        HRGeSettings(
            max_pages_per_run=PAGES,
            max_details_per_run=TOTAL,
            detail_budget_seconds=0.0,
            detail_fetch_delay_seconds=0.0,
        )
    )

    assert counts["detail"] == TOTAL
    assert all("description" in j for j in jobs)


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
            HRGeSettings(
                max_pages_per_run=1,
                max_details_per_run=9999,
                detail_fetch_delay_seconds=0.0,
            )
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
    _, _, messages = run(
        HRGeSettings(
            max_pages_per_run=PAGES,
            max_details_per_run=250,
            detail_fetch_delay_seconds=0.0,
        )
    )

    progress = [m for m in messages if "detail fetch" in m]
    assert progress, f"expected progress lines, saw: {messages[-3:]}"
    assert "250" in progress[-1]
    assert "elapsed" in progress[-1]

    merged = [m for m in messages if "details merged for" in m]
    assert merged, messages[-3:]
    assert "2000 unique" in merged[0]
    assert "merged for 250" in merged[0]
    assert any("stopped at" in m for m in messages), messages[-3:]
