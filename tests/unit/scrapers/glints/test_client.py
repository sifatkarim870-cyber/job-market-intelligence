"""Unit tests for GlintsClient discovery — skip-known URL selection.

The client's request loop is covered live (smoke + DB runs, 2026-10-07);
these tests pin the *selection* logic, which is pure once sitemap
fetching is stubbed: exclusion of already-known uuids, locale-pair
preference, and the empty-selection contract (corpus covered vs.
discovery broken).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

import pytest

from job_market_intel.scrapers.glints.client import GlintsClient
from job_market_intel.scrapers.glints.config import GlintsSettings
from job_market_intel.scrapers.glints.exceptions import GlintsResponseError

UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
UUID_C = "33333333-3333-4333-8333-333333333333"

SITEMAP_1 = "https://glints.com/sitemap_job_id_1.xml"
SITEMAP_2 = "https://glints.com/sitemap_job_id_2.xml"


def _sitemap_xml(*urls: str) -> str:
    return "<urlset>" + "".join(f"<loc>{u}</loc>" for u in urls) + "</urlset>"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> GlintsClient:
    """A client whose sitemap index and XML fetches are stubbed.

    One family, two sitemaps: #1 holds job A (listed under both the
    ``/id/`` local and ``/en/`` locale URLs — a duplicate pair) and job
    B; #2 holds job C. Newest-first order is preserved by dict order.
    """
    client = GlintsClient(settings=GlintsSettings(max_jobs_per_run=10))
    sitemaps = {
        SITEMAP_1: _sitemap_xml(
            f"https://glints.com/id/jobs/{UUID_A}",
            f"https://glints.com/en/jobs/{UUID_A}",
            f"https://glints.com/id/jobs/{UUID_B}",
        ),
        SITEMAP_2: _sitemap_xml(f"https://glints.com/id/jobs/{UUID_C}"),
    }
    monkeypatch.setattr(
        client,
        "_fetch_job_sitemap_families",
        lambda: OrderedDict({"sitemap_job_id": [SITEMAP_1, SITEMAP_2]}),
    )
    monkeypatch.setattr(client, "_request_text", lambda url, what: sitemaps[url])
    return client


class TestSelectJobUrls:
    def test_without_exclusion_selects_everything_preferring_local_locale(
        self, client: GlintsClient
    ) -> None:
        selected = dict(client._select_job_urls())

        assert set(selected) == {UUID_A, UUID_B, UUID_C}
        # A appears twice in the sitemap (local + /en/); the local wins.
        assert selected[UUID_A] == f"https://glints.com/id/jobs/{UUID_A}"

    def test_known_uuids_are_excluded_and_walk_continues_deeper(
        self, client: GlintsClient
    ) -> None:
        selected = dict(client._select_job_urls(exclude_ids={UUID_A, UUID_B}))

        # A and B dropped at sitemap-parse time; the walk continues into
        # sitemap #2 for the next unseen job instead of stopping early.
        assert set(selected) == {UUID_C}
        assert selected[UUID_C] == f"https://glints.com/id/jobs/{UUID_C}"

    def test_excluding_everything_returns_empty_not_an_error(
        self, client: GlintsClient
    ) -> None:
        assert client._select_job_urls(exclude_ids={UUID_A, UUID_B, UUID_C}) == []


class TestFetchRawJobsContract:
    @pytest.fixture
    def dry_client(self, monkeypatch: pytest.MonkeyPatch) -> GlintsClient:
        return GlintsClient(settings=GlintsSettings(max_jobs_per_run=10))

    def test_exclusion_is_passed_to_selection(
        self,
        dry_client: GlintsClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: dict[str, Any] = {}

        def fake_select(*, exclude_ids: set[str] | None = None) -> list[tuple[str, str]]:
            seen["exclude_ids"] = exclude_ids
            return [(UUID_A, f"https://glints.com/id/jobs/{UUID_A}")]

        monkeypatch.setattr(dry_client, "_select_job_urls", fake_select)
        monkeypatch.setattr(
            dry_client,
            "_fetch_job",
            lambda uuid, url: {"id": uuid},
        )

        jobs = dry_client.fetch_raw_jobs(exclude_ids={UUID_B})

        assert seen["exclude_ids"] == {UUID_B}
        assert len(jobs) == 1

    def test_empty_selection_with_exclusion_returns_empty(
        self,
        dry_client: GlintsClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Corpus fully covered: no unseen jobs — a successful no-op.
        monkeypatch.setattr(
            dry_client, "_select_job_urls", lambda **kwargs: []
        )

        assert dry_client.fetch_raw_jobs(exclude_ids={UUID_A}) == []

    def test_empty_selection_without_exclusion_raises(
        self,
        dry_client: GlintsClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No exclusion means a fresh scrape; an empty result there is a
        # broken index / unreachable site, not "nothing new".
        monkeypatch.setattr(
            dry_client, "_select_job_urls", lambda **kwargs: []
        )

        with pytest.raises(GlintsResponseError):
            dry_client.fetch_raw_jobs()
