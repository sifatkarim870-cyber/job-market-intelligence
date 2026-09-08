"""Unit tests for job_market_intel.normalization.config.DedupSettings.

Mirrors scrapers/*/test_config.py's structure and reasoning — see those
modules' docstrings for what each test category verifies and why it
matters. Same coverage pattern, dedup's own default and ``DEDUP_`` prefix.
"""

from __future__ import annotations

import pytest

from job_market_intel.normalization.config import DedupSettings, get_dedup_settings


class TestDedupSettingsDefaults:
    def test_default_posting_date_window_days(self) -> None:
        assert DedupSettings().posting_date_window_days == 3

    def test_get_dedup_settings_returns_defaults(self) -> None:
        assert get_dedup_settings().posting_date_window_days == 3


class TestDedupSettingsOverrides:
    def test_constructor_kwarg_overrides_default(self) -> None:
        settings = DedupSettings(posting_date_window_days=7)
        assert settings.posting_date_window_days == 7

    def test_environment_variable_with_prefix_overrides_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEDUP_POSTING_DATE_WINDOW_DAYS", "10")
        settings = DedupSettings()
        assert settings.posting_date_window_days == 10

    def test_unprefixed_environment_variable_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("POSTING_DATE_WINDOW_DAYS", "999")
        settings = DedupSettings()
        assert settings.posting_date_window_days == 3

    def test_zero_is_a_valid_window(self) -> None:
        # ge=0 constraint -- same-day-only matching is a legitimate,
        # maximally conservative configuration, not an error.
        assert DedupSettings(posting_date_window_days=0).posting_date_window_days == 0

    def test_negative_window_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            DedupSettings(posting_date_window_days=-1)
