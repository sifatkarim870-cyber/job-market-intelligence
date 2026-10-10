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

#: Measured on HR.ge's CI run of 2026-10-10 (run 38082775985), which committed
#: 100 rows every ~3.4 minutes against Neon.
#:
#: Recorded as named constants with their provenance so a future throughput
#: change is a visible test failure rather than a silent timeout, and so the
#: resetting of max_pages_per_run from 40 to 7 has a stated reason.
SECONDS_PER_PERSISTED_ROW = 2.04

#: hrge's timeout in config/sources.json. Keep in sync.
CI_STEP_SECONDS = 45 * 60

#: List-phase walk, cleaning, validation, session bookkeeping, uv startup.
SETUP_SECONDS = 60


class TestDefaults:
    def test_page_size_matches_server_cap(self) -> None:
        assert HRGeSettings().page_size == 100

    def test_rows_per_run_fit_inside_the_ci_step(self) -> None:
        """The CI step is 45 minutes, and the board's full 3,560 postings cost
        ~121 minutes at the rates measured on 2026-10-10 (~1.2 s per detail
        request plus ~2.04 s per persisted row over the WAN).

        So the default is deliberately a turnover-sized slice, not the whole
        board. A local full backfill restores the old coverage with
        HRGE_MAX_PAGES_PER_RUN=40.
        """
        rows = HRGeSettings().max_pages_per_run * HRGeSettings().page_size
        budget_seconds = (
            HRGeSettings().detail_budget_seconds
            + rows * SECONDS_PER_PERSISTED_ROW
            + SETUP_SECONDS
        )
        assert budget_seconds < CI_STEP_SECONDS, (
            f"{rows} rows projects to {budget_seconds / 60:.0f} min, "
            f"over the {CI_STEP_SECONDS / 60:.0f}-min CI step"
        )

    def test_pages_are_walked_newest_first(self) -> None:
        """A truncated run must cover the postings most likely to have changed,
        which is the only reason cutting the row count is safe at all."""
        import inspect

        from job_market_intel.scrapers.hrge import client as client_module

        source = inspect.getsource(client_module.HRGeClient._fetch_all_pages)
        assert "range(settings.max_pages_per_run)" in source

    def test_full_corpus_is_coverable_with_an_override(self) -> None:
        """40 x 100 > the 3,596 active vacancies observed live, restored by env."""
        full = HRGeSettings(max_pages_per_run=40)
        assert full.max_pages_per_run * full.page_size >= 3596

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
