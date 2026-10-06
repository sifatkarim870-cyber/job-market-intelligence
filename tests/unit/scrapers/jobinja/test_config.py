"""Unit tests for job_market_intel.scrapers.jobinja.config.

Pins the operational contract: the window stays bounded (400 unique
jobs — CI's newest window, mirroring GLINTS_MAX_JOBS_PER_RUN's role),
``start_page`` defaults to 1 (the newest listing window; backfills
raise it), the politeness delay is on by default, and every knob is
env-overridable under JOBINGJA_.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.jobinja.config import JobinjaSettings


class TestDefaults:
    def test_ci_window_is_bounded(self) -> None:
        assert JobinjaSettings().max_jobs_per_run == 400

    def test_window_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            JobinjaSettings(max_jobs_per_run=0)

    def test_points_at_the_public_listing(self) -> None:
        assert JobinjaSettings().listing_url_template == "https://jobinja.ir/jobs?page={page}"

    def test_start_page_is_the_newest_window(self) -> None:
        settings = JobinjaSettings()
        assert settings.start_page == 1
        assert settings.listing_url_template.format(page=settings.start_page) == (
            "https://jobinja.ir/jobs?page=1"
        )

    def test_start_page_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            JobinjaSettings(start_page=0)

    def test_politeness_delay_on_by_default(self) -> None:
        assert JobinjaSettings().fetch_delay_seconds > 0

    def test_delay_can_be_disabled(self) -> None:
        assert JobinjaSettings(fetch_delay_seconds=0.0).fetch_delay_seconds == 0.0


class TestEnvOverrides:
    def test_jobinja_prefixed_env_overrides(self, monkeypatch) -> None:
        monkeypatch.setenv("JOBINGJA_MAX_JOBS_PER_RUN", "2000")
        monkeypatch.setenv("JOBINGJA_START_PAGE", "900")
        monkeypatch.setenv("JOBINGJA_FETCH_DELAY_SECONDS", "0")
        settings = JobinjaSettings()
        assert settings.max_jobs_per_run == 2000
        assert settings.start_page == 900
        assert settings.fetch_delay_seconds == 0.0
