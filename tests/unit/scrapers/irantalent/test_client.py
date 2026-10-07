"""Unit tests for IrantalentClient — cursor walk and record contracts.

The request loop is covered live (probes r5-r10, 2026-10-07); these
tests pin the logic that is pure once ``_post_page`` is stubbed:

* window fill across search pages (30 rows/page, dedup by id,
  ``start_page`` honored, empty ``data`` list ends the cursor);
* the empty-selection contract (past ``start_page`` vs. broken
  envelope — both loud, never a silent no-op);
* ``_job_url``'s locale/id/slug rules;
* ``_post_page``'s shape-change behavior (non-JSON propagates).
"""

from __future__ import annotations

from typing import Any

import pytest

from job_market_intel.scrapers.irantalent.client import IrantalentClient
from job_market_intel.scrapers.irantalent.config import IrantalentSettings
from job_market_intel.scrapers.irantalent.exceptions import (
    IrantalentFetchError,
    IrantalentResponseError,
)


def _row(job_id: int, *, slug: str = "some-job", language: str = "fa") -> dict:
    return {"id": job_id, "slug": slug, "language": language}


def _page(*rows: dict) -> dict:
    return {"current_page": 1, "data": list(rows), "total": 1872}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> IrantalentClient:
    """A client whose page POSTs are stubbed (window 10, no pacing)."""
    client = IrantalentClient(
        settings=IrantalentSettings(max_jobs_per_run=10, fetch_delay_seconds=0)
    )
    pages = {
        1: _page(*[_row(i) for i in range(1, 4)]),  # 3 rows
        2: _page(*[_row(i) for i in range(3, 6)]),  # 6 unique after dedup (3 repeats)
        3: _page(*[_row(i) for i in range(6, 11)]),  # fills past the window of 10
        4: _page(),  # end of cursor
    }
    monkeypatch.setattr(client, "_post_page", lambda page: pages[page])
    return client


class TestSelectRows:
    def test_walks_pages_until_window_fills_with_dedup(self, client: IrantalentClient) -> None:
        rows = client._select_rows()
        # Pages 1-3 yield 10 unique ids (3..5 repeat across the
        # boundary and collapse); the window stops the walk.
        assert [row["id"] for row in rows] == list(range(1, 11))
        assert len({row["id"] for row in rows}) == len(rows)

    def test_window_cap_stops_the_walk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        capped = IrantalentClient(
            settings=IrantalentSettings(max_jobs_per_run=2, fetch_delay_seconds=0)
        )
        pages = {1: _page(*[_row(i) for i in range(1, 5)])}
        monkeypatch.setattr(capped, "_post_page", lambda page: pages[page])

        assert [row["id"] for row in capped._select_rows()] == [1, 2]

    def test_empty_data_list_ends_the_cursor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Whole-cursor read: pages 1-2 have rows, page 3 is the
        # verified HTTP-200 ``data: []`` tail — a successful end, not
        # an error, as long as something was selected.
        partial = IrantalentClient(
            settings=IrantalentSettings(max_jobs_per_run=10, fetch_delay_seconds=0)
        )
        pages = {1: _page(_row(1)), 2: _page(), 3: _page(_row(999))}
        monkeypatch.setattr(partial, "_post_page", lambda page: pages[page])

        assert [row["id"] for row in partial._select_rows()] == [1]

    def test_start_page_is_honored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[int] = []

        def fake_post(page: int) -> dict:
            seen.append(page)
            return _page(_row(page)) if page < 3 else _page()

        deep = IrantalentClient(
            settings=IrantalentSettings(start_page=2, max_jobs_per_run=10, fetch_delay_seconds=0)
        )
        monkeypatch.setattr(deep, "_post_page", fake_post)
        deep._select_rows()
        assert seen == [2, 3]  # backfill chunk starts where configured

    def test_non_dict_rows_are_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        messy = IrantalentClient(
            settings=IrantalentSettings(max_jobs_per_run=10, fetch_delay_seconds=0)
        )
        monkeypatch.setattr(
            messy,
            "_post_page",
            lambda page: {"data": ["junk", _row(7), None]} if page == 1 else {"data": []},
        )
        assert [row["id"] for row in messy._select_rows()] == [7]

    def test_envelope_without_data_list_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Shape change (or a block page wearing a JSON content type):
        # fail loudly instead of walking an empty cursor forever.
        monkeypatch.setattr(client := _dry_client(), "_post_page", lambda page: {"total": 1872})
        with pytest.raises(IrantalentResponseError, match="data list"):
            client._select_rows()


def _dry_client(**overrides: Any) -> IrantalentClient:
    defaults: dict[str, Any] = {"max_jobs_per_run": 10, "fetch_delay_seconds": 0}
    defaults.update(overrides)
    return IrantalentClient(settings=IrantalentSettings(**defaults))


class TestJobUrl:
    def test_english_language_gets_the_en_locale(self) -> None:
        url = _dry_client()._job_url(_row(9, slug="customer-success", language="en"))
        assert url == "https://www.irantalent.com/en/job/customer-success/9"

    def test_fa_and_multi_get_the_fa_locale(self) -> None:
        assert _dry_client()._job_url(_row(9, language="fa")) == (
            "https://www.irantalent.com/fa/job/some-job/9"
        )
        assert _dry_client()._job_url(_row(9, language="multi")) == (
            "https://www.irantalent.com/fa/job/some-job/9"
        )

    def test_missing_id_or_slug_is_unusable(self) -> None:
        assert _dry_client()._job_url({"slug": "x", "language": "en"}) is None
        assert _dry_client()._job_url({"id": 5, "language": "en"}) is None
        assert _dry_client()._job_url({"id": 5, "slug": "", "language": "en"}) is None


class TestFetchRawJobsContract:
    def test_happy_path_builds_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dry = _dry_client()
        monkeypatch.setattr(
            dry, "_select_rows", lambda: [_row(1, slug="first"), _row(2, slug="second")]
        )
        jobs = dry.fetch_raw_jobs()
        assert jobs == [
            {"url": "https://www.irantalent.com/fa/job/first/1", "payload": _row(1, slug="first")},
            {
                "url": "https://www.irantalent.com/fa/job/second/2",
                "payload": _row(2, slug="second"),
            },
        ]

    def test_zero_rows_raises_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No skip-known here — an empty selection means past
        # start_page / format change / block, never "nothing new".
        dry = _dry_client()
        monkeypatch.setattr(dry, "_select_rows", lambda: [])
        with pytest.raises(IrantalentResponseError, match="zero job rows"):
            dry.fetch_raw_jobs()

    def test_all_rows_missing_identity_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dry = _dry_client()
        monkeypatch.setattr(dry, "_select_rows", lambda: [{"language": "en"}])
        with pytest.raises(IrantalentResponseError, match="zero usable"):
            dry.fetch_raw_jobs()

    def test_partially_unusable_rows_are_dropped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dry = _dry_client()
        monkeypatch.setattr(dry, "_select_rows", lambda: [{"language": "en"}, _row(5, slug="good")])
        jobs = dry.fetch_raw_jobs()
        assert len(jobs) == 1
        assert jobs[0]["payload"]["id"] == 5


class TestPostPage:
    def test_non_json_body_raises_not_skips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A shape change (or bot wall) affects every page — propagating
        # fails the run loudly instead of silently skipping rows.
        client = _dry_client()

        class _Html:
            def json(self) -> Any:
                raise ValueError("Expecting value")

        monkeypatch.setattr(client, "_post", lambda body, what: _Html())
        with pytest.raises(IrantalentFetchError, match="non-JSON"):
            client._post_page(1)

    def test_non_object_json_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _dry_client()

        class _List:
            def json(self) -> Any:
                return [1, 2, 3]

        monkeypatch.setattr(client, "_post", lambda body, what: _List())
        with pytest.raises(IrantalentFetchError, match="non-object"):
            client._post_page(1)

    def test_object_json_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _dry_client()
        envelope = {"current_page": 1, "data": [_row(1)], "total": 1872}

        class _Ok:
            def json(self) -> Any:
                return envelope

        monkeypatch.setattr(client, "_post", lambda body, what: _Ok())
        assert client._post_page(1) is envelope
