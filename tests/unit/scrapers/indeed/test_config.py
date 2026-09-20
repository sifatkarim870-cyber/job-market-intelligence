"""Unit tests for job_market_intel.scrapers.indeed.config.IndeedSettings.

Mirrors tests/unit/scrapers/remoteok/test_config.py's structure and
rationale: confirm the scraper works out-of-the-box with no .env entries,
and that INDEED_-prefixed overrides (and only those) take effect.
"""

from __future__ import annotations

import pytest

from job_market_intel.scrapers.indeed.config import IndeedSettings


class TestIndeedSettingsDefaults:
    def test_default_base_url(self) -> None:
        assert IndeedSettings().base_url == "https://www.indeed.com"

    def test_default_headless_is_false(self) -> None:
        # Confirmed decision (see config.py's docstring): headless mode is
        # itself a fingerprinting signal, so the default favors a visible
        # session over speed/convenience.
        assert IndeedSettings().headless is False

    def test_default_pacing_window(self) -> None:
        settings = IndeedSettings()
        assert settings.page_action_min_wait_seconds == 4.0
        assert settings.page_action_max_wait_seconds == 9.0
        assert settings.page_action_min_wait_seconds < settings.page_action_max_wait_seconds

    def test_default_session_caps(self) -> None:
        settings = IndeedSettings()
        assert settings.max_search_pages_per_session == 5
        assert settings.max_detail_pages_per_session == 60
        assert settings.max_consecutive_failures == 3

    def test_default_long_pause_window(self) -> None:
        settings = IndeedSettings()
        assert settings.long_pause_min_seconds < settings.long_pause_max_seconds
        assert settings.long_pause_every_n_pages == 5

    def test_default_user_agent_is_non_empty_and_identifying(self) -> None:
        assert IndeedSettings().request_user_agent
        assert "Mozilla" in IndeedSettings().request_user_agent


class TestIndeedSettingsOverrides:
    def test_constructor_kwargs_override_defaults(self) -> None:
        settings = IndeedSettings(max_search_pages_per_session=2, headless=True)
        assert settings.max_search_pages_per_session == 2
        assert settings.headless is True

    def test_environment_variable_with_prefix_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INDEED_MAX_SEARCH_PAGES_PER_SESSION", "9")
        settings = IndeedSettings()
        assert settings.max_search_pages_per_session == 9

    def test_unprefixed_environment_variable_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAX_SEARCH_PAGES_PER_SESSION", "999")
        settings = IndeedSettings()
        assert settings.max_search_pages_per_session == 5
