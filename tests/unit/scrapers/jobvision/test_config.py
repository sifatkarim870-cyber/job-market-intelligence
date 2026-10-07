"""Unit tests for job_market_intel.scrapers.jobvision.config.

Pins the defaults that make a Jobvision run work out of the box (open
sitemap + open detail API, no keys) and the ``JOBVISION_`` environment
overrides — same contracts every other source's config tests pin.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_market_intel.scrapers.jobvision.config import JobvisionSettings
from job_market_intel.validation.jobvision_validator import JobvisionValidationSettings


class TestDefaults:
    def test_endpoints_need_no_auth(self) -> None:
        settings = JobvisionSettings()
        # Discovery: the open sitemap (robots.txt-permitted).
        assert settings.sitemap_url == "https://jobvision.ir/sitemap/jobposts.xml"
        # Detail: the unauthenticated JSON API the SSR page embeds.
        assert settings.detail_api_url == (
            "https://candidateapi.jobvision.ir/api/v1/JobPost/Detail"
        )
        assert settings.web_base_url == "https://jobvision.ir"

    def test_window_and_pacing(self) -> None:
        settings = JobvisionSettings()
        # 400 = the CI cap every other source uses; 0.15s politeness
        # between the ~8 KB detail calls.
        assert settings.max_jobs_per_run == 400
        assert settings.fetch_delay_seconds == pytest.approx(0.15)

    def test_sitemap_timeout_is_generous_for_27mb(self) -> None:
        # Documented deviation: the sitemap is a single 27 MB document
        # over a slow cross-border route (other sources use 25s).
        assert JobvisionSettings().request_timeout_seconds == pytest.approx(90.0)

    def test_retry_defaults(self) -> None:
        settings = JobvisionSettings()
        assert settings.max_retry_attempts == 4
        assert settings.retry_initial_wait_seconds == pytest.approx(1.0)
        assert settings.retry_max_wait_seconds == pytest.approx(30.0)

    def test_browser_user_agent(self) -> None:
        assert "Mozilla/5.0" in JobvisionSettings().user_agent

    def test_window_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            JobvisionSettings(max_jobs_per_run=0)


class TestEnvOverrides:
    def test_prefix_is_jobvision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JOBVISION_MAX_JOBS_PER_RUN", "7")
        monkeypatch.setenv("JOBVISION_FETCH_DELAY_SECONDS", "0.5")
        settings = JobvisionSettings()
        assert settings.max_jobs_per_run == 7
        assert settings.fetch_delay_seconds == pytest.approx(0.5)

    def test_sitemap_and_api_urls_are_overridable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JOBVISION_SITEMAP_URL", "https://example.invalid/jobs.xml")
        monkeypatch.setenv(
            "JOBVISION_DETAIL_API_URL", "https://example.invalid/api/JobPost/Detail"
        )
        settings = JobvisionSettings()
        assert settings.sitemap_url == "https://example.invalid/jobs.xml"
        assert settings.detail_api_url == "https://example.invalid/api/JobPost/Detail"


class TestValidationSettings:
    def test_defaults_are_sane(self) -> None:
        settings = JobvisionValidationSettings()
        assert settings.min_expected_jobs == 100
        assert settings.max_skip_rate == pytest.approx(0.10)

    def test_env_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JOBVISION_VALIDATION_MIN_EXPECTED_JOBS", "3")
        assert JobvisionValidationSettings().min_expected_jobs == 3
