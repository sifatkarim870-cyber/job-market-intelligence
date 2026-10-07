"""Unit tests for job_market_intel.scrapers.irantalent.config.

Pins the defaults that make an Irantalent run work out of the box (one
open POST endpoint, no keys) and the ``IRANTALENT_`` environment
overrides — same contracts every other source's config tests pin.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.irantalent.config import IrantalentSettings
from job_market_intel.validation.irantalent_validator import IrantalentValidationSettings


class TestDefaults:
    def test_endpoint_needs_no_auth(self) -> None:
        settings = IrantalentSettings()
        # Discovery AND data: the open search endpoint (bare UA +
        # JSON content-type passed r7's header-independence probe).
        assert settings.api_search_url == (
            "https://api.irantalent.com/api/v1/employer/position/search"
        )
        assert settings.web_base_url == "https://www.irantalent.com"

    def test_window_and_pacing(self) -> None:
        settings = IrantalentSettings()
        # 400 = the CI cap every other source uses (14 search pages);
        # 0.25s politeness between page POSTs — the same morning's
        # Jobinja WAF lesson, but cheap here (63 pages per full sweep).
        assert settings.max_jobs_per_run == 400
        assert settings.fetch_delay_seconds == pytest.approx(0.25)

    def test_cursor_starts_at_the_newest_page(self) -> None:
        # Rows are date-descending, so page 1 = the newest window CI
        # wants; a chunked backfill raises it.
        assert IrantalentSettings().start_page == 1

    def test_timeout_fits_half_megabyte_pages(self) -> None:
        # No 27 MB sitemap here: each page is ~450 KB and answered in
        # well under a second during recon.
        assert IrantalentSettings().request_timeout_seconds == pytest.approx(40.0)

    def test_retry_defaults(self) -> None:
        settings = IrantalentSettings()
        assert settings.max_retry_attempts == 4
        assert settings.retry_initial_wait_seconds == pytest.approx(1.0)
        assert settings.retry_max_wait_seconds == pytest.approx(30.0)

    def test_browser_user_agent(self) -> None:
        assert "Mozilla/5.0" in IrantalentSettings().user_agent

    def test_window_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            IrantalentSettings(max_jobs_per_run=0)

    def test_start_page_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            IrantalentSettings(start_page=0)


class TestEnvOverrides:
    def test_prefix_is_irantalent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IRANTALENT_MAX_JOBS_PER_RUN", "7")
        monkeypatch.setenv("IRANTALENT_FETCH_DELAY_SECONDS", "0.5")
        monkeypatch.setenv("IRANTALENT_START_PAGE", "15")
        settings = IrantalentSettings()
        assert settings.max_jobs_per_run == 7
        assert settings.fetch_delay_seconds == pytest.approx(0.5)
        assert settings.start_page == 15

    def test_urls_are_overridable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IRANTALENT_API_SEARCH_URL", "https://example.invalid/search")
        monkeypatch.setenv("IRANTALENT_WEB_BASE_URL", "https://example.invalid")
        settings = IrantalentSettings()
        assert settings.api_search_url == "https://example.invalid/search"
        assert settings.web_base_url == "https://example.invalid"


class TestValidationSettings:
    def test_defaults_are_sane(self) -> None:
        settings = IrantalentValidationSettings()
        # 100 floors a healthy 400-row CI run while still passing a
        # thin backfill tail (the whole live corpus is ~1,872 rows).
        assert settings.min_expected_jobs == 100
        assert settings.max_skip_rate == pytest.approx(0.10)

    def test_env_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IRANTALENT_VALIDATION_MIN_EXPECTED_JOBS", "3")
        assert IrantalentValidationSettings().min_expected_jobs == 3
