"""Unit tests for job_market_intel.scrapers.hrge.config.

Pins the operational contract: page size can never exceed the server's
documented cap of 100 (HTTP 400 "Max 100 items are allowed per
request"), the vacancy type id stays 1 (types 2/3 are tenders and
trainings, not jobs), and every knob is env-overridable under HRGE_.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.hrge.config import HRGeSettings


class TestDefaults:
    def test_page_size_matches_server_cap(self) -> None:
        assert HRGeSettings().page_size == 100

    def test_full_corpus_is_covered_by_max_pages(self) -> None:
        # 40 pages x 100 > the 3,596 active vacancies observed live.
        assert HRGeSettings().max_pages_per_run * HRGeSettings().page_size >= 3596

    def test_fetches_vacancies_only(self) -> None:
        assert HRGeSettings().announcement_type_id == 1

    def test_asks_the_site_for_english(self) -> None:
        assert "en" in HRGeSettings().accept_language

    def test_details_on_by_default(self) -> None:
        assert HRGeSettings().fetch_details is True

    def test_page_size_above_server_cap_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            HRGeSettings(page_size=101)


class TestEnvOverrides:
    def test_hrge_prefixed_env_overrides(self, monkeypatch) -> None:
        monkeypatch.setenv("HRGE_MAX_PAGES_PER_RUN", "4")
        monkeypatch.setenv("HRGE_FETCH_DETAILS", "false")
        settings = HRGeSettings()
        assert settings.max_pages_per_run == 4
        assert settings.fetch_details is False
