"""Unit tests for job_market_intel.scrapers.weworkremotely.config.WWRSettings.

Mirrors ``scrapers/remoteok/test_config.py``'s structure and reasoning
exactly — see that module's docstring for what each test category
verifies and why it matters. Same coverage, WWR's own defaults and
``WWR_`` prefix.
"""

from __future__ import annotations

import pytest

from job_market_intel.scrapers.weworkremotely.config import WWRSettings


class TestWWRSettingsDefaults:
    def test_default_feed_url(self) -> None:
        assert WWRSettings().feed_url == "https://weworkremotely.com/remote-jobs.rss"

    def test_default_timeout(self) -> None:
        assert WWRSettings().request_timeout_seconds == 15.0

    def test_default_retry_settings(self) -> None:
        settings = WWRSettings()
        assert settings.max_retry_attempts == 4
        assert settings.retry_initial_wait_seconds == 1.0
        assert settings.retry_max_wait_seconds == 30.0

    def test_default_user_agent_is_non_empty_and_identifying(self) -> None:
        # Not pinned to an exact string (that's an implementation detail),
        # just confirming it's set to something real rather than blank.
        assert WWRSettings().user_agent
        assert len(WWRSettings().user_agent) > 5


class TestWWRSettingsOverrides:
    def test_constructor_kwargs_override_defaults(self) -> None:
        settings = WWRSettings(request_timeout_seconds=99.0, max_retry_attempts=10)
        assert settings.request_timeout_seconds == 99.0
        assert settings.max_retry_attempts == 10

    def test_environment_variable_with_prefix_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WWR_REQUEST_TIMEOUT_SECONDS", "42.5")
        settings = WWRSettings()
        assert settings.request_timeout_seconds == 42.5

    def test_unprefixed_environment_variable_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without the WWR_ prefix, this must NOT be picked up — this is
        # what keeps every scraper's settings from colliding with each
        # other in the environment.
        monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "999.0")
        settings = WWRSettings()
        assert settings.request_timeout_seconds == 15.0
