"""Unit tests for job_market_intel.scheduler.config.SchedulerSettings.

What these tests verify, and why each matters:
    - The default interval is 12 hours with zero configuration, matching
      the current build plan for Step 12.
    - Settings can be overridden via SCHEDULER_-prefixed environment
      variables, matching the project's existing configuration pattern.
    - An unprefixed variable is ignored, keeping this settings class from
      colliding with any other SCRAPE_INTERVAL_HOURS-shaped variable that
      might exist in the environment.
"""

from __future__ import annotations

import pytest

from job_market_intel.scheduler.config import SchedulerSettings


class TestSchedulerSettingsDefaults:
    def test_default_scrape_interval_is_twelve_hours(self) -> None:
        assert SchedulerSettings().scrape_interval_hours == 12.0

    def test_default_indeed_scrape_interval_is_twelve_hours(self) -> None:
        assert SchedulerSettings().indeed_scrape_interval_hours == 12.0

    def test_default_runs_immediately_on_start(self) -> None:
        assert SchedulerSettings().run_immediately_on_start is True

    def test_default_misfire_grace_time_is_one_hour(self) -> None:
        assert SchedulerSettings().misfire_grace_time_seconds == 3600

    def test_default_coalesces_missed_runs(self) -> None:
        assert SchedulerSettings().coalesce_missed_runs is True

    def test_zero_or_negative_interval_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            SchedulerSettings(scrape_interval_hours=0)
        with pytest.raises(ValueError):
            SchedulerSettings(scrape_interval_hours=-1)

    def test_zero_or_negative_indeed_interval_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            SchedulerSettings(indeed_scrape_interval_hours=0)
        with pytest.raises(ValueError):
            SchedulerSettings(indeed_scrape_interval_hours=-1)


class TestSchedulerSettingsOverrides:
    def test_constructor_kwargs_override_defaults(self) -> None:
        settings = SchedulerSettings(scrape_interval_hours=6, run_immediately_on_start=False)
        assert settings.scrape_interval_hours == 6
        assert settings.run_immediately_on_start is False

    def test_environment_variable_with_prefix_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SCHEDULER_SCRAPE_INTERVAL_HOURS", "6")
        settings = SchedulerSettings()
        assert settings.scrape_interval_hours == 6.0

    def test_indeed_environment_variable_with_prefix_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SCHEDULER_INDEED_SCRAPE_INTERVAL_HOURS", "8")
        settings = SchedulerSettings()
        assert settings.indeed_scrape_interval_hours == 8.0

    def test_unprefixed_environment_variable_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SCRAPE_INTERVAL_HOURS", "999")
        settings = SchedulerSettings()
        assert settings.scrape_interval_hours == 12.0
