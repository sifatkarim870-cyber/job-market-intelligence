"""Unit tests for job_market_intel.scrapers.reed.config.ReedSettings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.reed.config import ReedSettings


class TestApiKeyIsRequired:
    """api_key has no default, unlike every field on every other source's
    settings class -- see config.py's module docstring for why."""

    def test_constructing_without_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REED_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            ReedSettings(_env_file=None)

    def test_constructing_with_api_key_succeeds(self) -> None:
        settings = ReedSettings(api_key="test-key-123")
        assert settings.api_key == "test-key-123"


class TestDefaults:
    def test_results_per_page_defaults_to_100(self) -> None:
        assert ReedSettings(api_key="k").results_per_page == 100

    def test_results_per_page_cannot_exceed_reed_documented_maximum(self) -> None:
        with pytest.raises(ValidationError):
            ReedSettings(api_key="k", results_per_page=101)

    def test_search_and_details_urls_have_sane_defaults(self) -> None:
        settings = ReedSettings(api_key="k")
        assert settings.search_url == "https://www.reed.co.uk/api/1.0/search"
        assert settings.details_url == "https://www.reed.co.uk/api/1.0/jobs"
