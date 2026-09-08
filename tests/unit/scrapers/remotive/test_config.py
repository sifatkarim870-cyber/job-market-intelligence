"""Unit tests for job_market_intel.scrapers.remotive.config.RemotiveSettings.

Mirrors ``scrapers/remoteok/test_config.py``'s coverage and rationale
exactly — see that module's docstring for why each of these matters.
"""

from __future__ import annotations

import pytest

from job_market_intel.scrapers.remotive.config import RemotiveSettings


class TestRemotiveSettingsDefaults:
    def test_default_api_url(self) -> None:
        assert RemotiveSettings().api_url == "https://remotive.com/api/remote-jobs"

    def test_default_timeout(self) -> None:
        assert RemotiveSettings().request_timeout_seconds == 15.0

    def test_default_retry_settings(self) -> None:
        settings = RemotiveSettings()
        assert settings.max_retry_attempts == 4
        assert settings.retry_initial_wait_seconds == 1.0
        assert settings.retry_max_wait_seconds == 30.0

    def test_default_user_agent_is_non_empty_and_identifying(self) -> None:
        assert RemotiveSettings().user_agent
        assert len(RemotiveSettings().user_agent) > 5

    def test_default_max_requests_per_day(self) -> None:
        assert RemotiveSettings().max_requests_per_day == 4


class TestRemotiveSettingsOverrides:
    def test_constructor_kwargs_override_defaults(self) -> None:
        settings = RemotiveSettings(request_timeout_seconds=99.0, max_retry_attempts=10)
        assert settings.request_timeout_seconds == 99.0
        assert settings.max_retry_attempts == 10

    def test_environment_variable_with_prefix_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REMOTIVE_REQUEST_TIMEOUT_SECONDS", "42.5")
        settings = RemotiveSettings()
        assert settings.request_timeout_seconds == 42.5

    def test_unprefixed_environment_variable_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without the REMOTIVE_ prefix, this must NOT be picked up — this
        # is what keeps every scraper's settings from colliding with each
        # other in the environment.
        monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "999.0")
        settings = RemotiveSettings()
        assert settings.request_timeout_seconds == 15.0
