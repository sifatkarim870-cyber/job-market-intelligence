"""Unit tests for job_market_intel.scrapers.glints.config.

Pins the operational contract: the window stays bounded (400 unique jobs
— CI's newest window, mirroring HRGE_MAX_PAGES_PER_RUN's role), the
politeness delay is on by default (a full crawl is ~130k GETs), and
every knob is env-overridable under GLINTS_.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.glints.config import GlintsSettings


class TestDefaults:
    def test_ci_window_is_bounded(self) -> None:
        assert GlintsSettings().max_jobs_per_run == 400

    def test_window_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            GlintsSettings(max_jobs_per_run=0)

    def test_points_at_the_public_sitemap_index(self) -> None:
        assert GlintsSettings().sitemap_index_url == "https://glints.com/sitemap_index.xml"

    def test_politeness_delay_on_by_default(self) -> None:
        assert GlintsSettings().fetch_delay_seconds > 0

    def test_delay_can_be_disabled(self) -> None:
        assert GlintsSettings(fetch_delay_seconds=0.0).fetch_delay_seconds == 0.0


class TestEnvOverrides:
    def test_glints_prefixed_env_overrides(self, monkeypatch) -> None:
        monkeypatch.setenv("GLINTS_MAX_JOBS_PER_RUN", "4000")
        monkeypatch.setenv("GLINTS_FETCH_DELAY_SECONDS", "0")
        settings = GlintsSettings()
        assert settings.max_jobs_per_run == 4000
        assert settings.fetch_delay_seconds == 0.0
