"""Unit tests for job_market_intel.scrapers.remoteok.config.RemoteOKSettings.

What these tests verify, and why each matters:
    - Sensible defaults apply with zero configuration — the scraper must
      work out-of-the-box with no .env entries at all, as documented.
    - Settings can be overridden via environment variables using the
      REMOTEOK_ prefix, matching the project's existing configuration
      pattern (this is how you'd override a value on your real machine).
    - Settings can also be overridden directly via constructor kwargs,
      which is how the test suite itself configures fast retry timings
      for the client tests elsewhere in this suite.
"""

from __future__ import annotations

import pytest

from job_market_intel.scrapers.remoteok.config import RemoteOKSettings


class TestRemoteOKSettingsDefaults:
    def test_default_api_url(self) -> None:
        assert RemoteOKSettings().api_url == "https://remoteok.com/api"

    def test_default_timeout(self) -> None:
        assert RemoteOKSettings().request_timeout_seconds == 15.0

    def test_default_retry_settings(self) -> None:
        settings = RemoteOKSettings()
        assert settings.max_retry_attempts == 4
        assert settings.retry_initial_wait_seconds == 1.0
        assert settings.retry_max_wait_seconds == 30.0

    def test_default_user_agent_is_non_empty_and_identifying(self) -> None:
        # Not pinned to an exact string (that's an implementation detail),
        # just confirming it's set to something real rather than blank —
        # sending no User-Agent at all was the gotcha we're guarding against.
        assert RemoteOKSettings().user_agent
        assert len(RemoteOKSettings().user_agent) > 5


class TestRemoteOKSettingsOverrides:
    def test_constructor_kwargs_override_defaults(self) -> None:
        settings = RemoteOKSettings(request_timeout_seconds=99.0, max_retry_attempts=10)
        assert settings.request_timeout_seconds == 99.0
        assert settings.max_retry_attempts == 10

    def test_environment_variable_with_prefix_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REMOTEOK_REQUEST_TIMEOUT_SECONDS", "42.5")
        settings = RemoteOKSettings()
        assert settings.request_timeout_seconds == 42.5

    def test_unprefixed_environment_variable_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Without the REMOTEOK_ prefix, this must NOT be picked up — this
        # is what keeps every scraper's settings from colliding with each
        # other in the environment.
        monkeypatch.setenv("REQUEST_TIMEOUT_SECONDS", "999.0")
        settings = RemoteOKSettings()
        assert settings.request_timeout_seconds == 15.0
