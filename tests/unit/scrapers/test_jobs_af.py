"""Unit tests for the Jobs.af scraper.

Each test pins a fact measured on the live site on 2026-10-18. The two that
would each have broken the source silently:

  1. **``addressCountry`` is the name ``"Afghanistan"``, not the ISO code
     ``"AF"``** -- the same shape as Vagas.com.br's ``"Brasil"``. An unmapped
     name resolves to no country and the row collapses onto the global-remote
     location. That is a *silent* loss, so it has its own test.

  2. **``datePosted`` carries milliseconds and a truncated offset** --
     ``"2026-10-17 10:48:27.175+00"``. ``+00`` has no minutes, so this is not
     ISO 8601: ``datetime.fromisoformat`` rejects it and a strict parser returns
     **no dates for any posting**. The parser takes the leading ``YYYY-MM-DD``
     by regex instead.

Also pinned: no ``identifier`` (so the URL slug is the key), no ``baseSalary``,
and **no working pager** -- ``/public/job/page/2`` is HTTP 404 and all 12
postings sit on the homepage.

Run with:  uv run pytest tests/unit/scrapers/test_jobs_af.py -q
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from job_market_intel.cleaning.jobs_af_cleaner import (
    JobsAfCleaner,
    _map_country,
    _map_employment_type,
)
from job_market_intel.scrapers.jobs_af.client import JobsAfClient, _is_posting_slug
from job_market_intel.scrapers.jobs_af.config import JobsAfSettings
from job_market_intel.scrapers.jobs_af.exceptions import (
    JobsAfParseError,
    JobsAfResponseError,
)
from job_market_intel.scrapers.jobs_af.parser import (
    JobsAfParser,
    _extract_location,
    _parse_date,
)

#: Trimmed verbatim from a live detail page fetched 2026-10-18
#: (/public/job/assistant-branch-manager-31).
POSTING = {
    "@context": "http://schema.org",
    "@type": "JobPosting",
    "title": "Assistant Branch Manager (Kunduz Branch)",
    "description": "Responsible for assisting with the direction and administration "
    "of branch operations, supervising staff and ensuring compliance with policy.",
    # THE trap: milliseconds, and an offset with no minutes. Not ISO 8601.
    "datePosted": "2026-10-17 10:48:27.175+00",
    "validThrough": "2026-10-30 00:00:00+00",
    "directApply": True,
    "employmentType": "FULL_TIME",
    "hiringOrganization": {
        "@type": "Organization",
        "name": "Afghanistan Internatinal Bank (AIB)",
        "logo": "http://jobs.af/storage/logos/aib.png",
    },
    "jobLocation": {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
            # THE other trap: a country NAME, not the ISO code.
            "addressCountry": "Afghanistan",
        },
    },
}


def detail_html(posting: dict | None = None) -> str:
    body = POSTING if posting is None else posting
    return (
        f'<html><head><script type="application/ld+json">{json.dumps(body)}</script>'
        "</head><body></body></html>"
    )


# ====================================================================== links


class TestListingLinks:
    def test_the_measured_href_form_is_relative(self) -> None:
        """Measured: 12 relative, 0 absolute."""
        from job_market_intel.scrapers.jobs_af.client import _JOB_LINK

        html = '<a href="/public/job/assistant-branch-manager-31">x</a>'
        assert [m.group(1) for m in _JOB_LINK.finditer(html)] == [
            "/public/job/assistant-branch-manager-31"
        ]

    def test_absolute_form_is_accepted_too(self) -> None:
        from job_market_intel.scrapers.jobs_af.client import _JOB_LINK

        html = '<a href="https://jobs.af/public/job/cashier-270">x</a>'
        assert [m.group(1) for m in _JOB_LINK.finditer(html)] == ["/public/job/cashier-270"]

    def test_a_slug_with_a_chrome_word_is_still_a_posting(self) -> None:
        """Whole-segment matching only -- a substring test would lose this."""
        assert _is_posting_slug("branch-manager-kunduz-branch-16") is True

    def test_chrome_and_numeric_slugs_are_not_postings(self) -> None:
        for not_a_posting in ("page", "search", "270", ""):
            assert _is_posting_slug(not_a_posting) is False

    def test_the_listing_is_the_homepage(self) -> None:
        """/public/job/page/2 is 404 and ?page=2 adds nothing."""
        client = JobsAfClient(JobsAfSettings())
        assert client.listing_url(1) == "https://jobs.af/"

    def test_empty_discovery_raises(self) -> None:
        client = JobsAfClient(JobsAfSettings())
        client._fetch = lambda url: "<html><body>nothing</body></html>"  # type: ignore[method-assign]
        with pytest.raises(JobsAfResponseError, match="markup changed"):
            client.discover_detail_paths()


# ====================================================================== dates


class TestDates:
    def test_the_millisecond_truncated_offset_shape(self) -> None:
        """THE trap. datetime.fromisoformat would reject this outright."""
        assert _parse_date("2026-10-17 10:48:27.175+00") == date(2026, 10, 17)

    def test_the_valid_through_shape(self) -> None:
        assert _parse_date("2026-10-30 00:00:00+00") == date(2026, 10, 30)

    @pytest.mark.parametrize("raw", ["2026-11-07", "2026-11-07T00:00:00", "2026-11-07T12:56:18"])
    def test_other_shapes_still_work(self, raw: str) -> None:
        assert _parse_date(raw) == date(2026, 11, 7)

    @pytest.mark.parametrize("raw", [None, "", "null", "not a date"])
    def test_junk_is_none(self, raw) -> None:
        assert _parse_date(raw) is None

    def test_the_tail_is_ignored_entirely(self) -> None:
        """Why the regex exists, stated as behaviour rather than folklore.

        ``datetime.fromisoformat`` only became lenient about fractional seconds
        and short timezone offsets in 3.11, so whether it accepts this board's
        timestamp depends on the interpreter. The parser must not depend on that,
        so it takes the leading calendar date and ignores whatever follows --
        which also means a future change to the timestamp tail cannot break it.
        """
        assert _parse_date("2026-10-17") == date(2026, 10, 17)
        assert _parse_date("2026-10-17 anything at all follows") == date(2026, 10, 17)


# ==================================================================== location


class TestLocation:
    def test_country_arrives_as_a_name(self) -> None:
        label, country = _extract_location(POSTING)
        assert country == "Afghanistan"
        assert label == "Afghanistan"


class TestCountryNormalization:
    def test_the_name_is_normalized_to_the_iso_code(self) -> None:
        assert _map_country("Afghanistan") == "AF"

    def test_an_iso_code_passes_through(self) -> None:
        assert _map_country("AF") == "AF"

    def test_an_unmapped_name_is_none_rather_than_a_guess(self) -> None:
        assert _map_country("Wakanda") is None
        assert _map_country(None) is None


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = JobsAfParser().parse(
            "assistant-branch-manager-31",
            detail_html(),
            url="https://jobs.af/public/job/assistant-branch-manager-31",
        )
        assert job.source_job_id == "assistant-branch-manager-31"
        assert job.title == "Assistant Branch Manager (Kunduz Branch)"
        assert job.company_name == "Afghanistan Internatinal Bank (AIB)"
        assert job.company_logo_url is not None
        assert job.employment_type == "FULL_TIME"
        assert job.posted_date == date(2026, 10, 17)
        assert job.closing_date == date(2026, 10, 30)

    def test_both_dates_survive_the_non_iso_format(self) -> None:
        """If either were lost the rows would look undated for no reason."""
        job = JobsAfParser().parse("x", detail_html())
        assert job.posted_date is not None and job.closing_date is not None

    def test_the_slug_is_the_key_because_there_is_no_identifier(self) -> None:
        job = JobsAfParser().parse("assistant-branch-manager-31", detail_html())
        assert job.raw["has_identifier"] is False

    def test_no_salary_is_recorded_rather_than_assumed(self) -> None:
        job = JobsAfParser().parse("x", detail_html())
        assert job.raw["has_base_salary"] is False

    def test_direct_apply_is_recorded_not_mapped(self) -> None:
        job = JobsAfParser().parse("x", detail_html())
        assert job.raw["direct_apply"] is True

    def test_the_raw_timestamp_is_kept_for_audit(self) -> None:
        job = JobsAfParser().parse("x", detail_html())
        assert job.raw["date_posted_raw"] == "2026-10-17 10:48:27.175+00"

    def test_no_title_raises(self) -> None:
        with pytest.raises(JobsAfParseError, match="no title"):
            JobsAfParser().parse("x", detail_html({}))

    def test_parse_many_collects_failures(self) -> None:
        records = [{"job_id": "a", "html": detail_html()}, {"job_id": "b", "html": detail_html({})}]
        jobs, issues = JobsAfParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["a"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return (
            JobsAfParser()
            .parse(
                "assistant-branch-manager-31",
                detail_html(),
                url="https://jobs.af/public/job/assistant-branch-manager-31",
            )
            .model_copy(update=kw)
        )

    def test_the_country_reaches_storage_as_an_iso_code(self) -> None:
        """Without this the row resolves to no country and collapses."""
        payload = JobsAfCleaner().clean_job(self._job()).raw_payload
        assert payload["country_iso"] == "AF"
        assert payload["country_raw"] == "Afghanistan"

    def test_no_salary_is_ever_claimed(self) -> None:
        cleaned = JobsAfCleaner().clean_job(self._job())
        assert cleaned.salary_min is None
        assert cleaned.salary_disclosed is False
        assert cleaned.raw_payload["salary_published"] is False

    def test_employment_type_is_mapped(self) -> None:
        assert JobsAfCleaner().clean_job(self._job()).employment_type_code == "full_time"

    def test_country_only_location_is_kept(self) -> None:
        job = self._job(location=None)
        assert JobsAfCleaner().clean_job(job).location_cleaned == "AF"

    def test_both_dates_survive_cleaning(self) -> None:
        cleaned = JobsAfCleaner().clean_job(self._job())
        assert cleaned.posting_date is not None and cleaned.closing_date is not None

    def test_closing_is_not_before_posting(self) -> None:
        cleaned = JobsAfCleaner().clean_job(self._job())
        assert cleaned.closing_date >= cleaned.posting_date

    def test_language_is_recorded_as_english(self) -> None:
        assert JobsAfCleaner().clean_job(self._job()).raw_payload["language"] == "en"


class TestEmploymentMapping:
    def test_full_time_maps(self) -> None:
        assert _map_employment_type("FULL_TIME") == "full_time"

    def test_a_list_is_also_accepted(self) -> None:
        """Angola Emprego sends a list; both shapes must survive a normaliser."""
        assert _map_employment_type(["FULL_TIME"]) == "full_time"

    def test_unknown_is_none(self) -> None:
        assert _map_employment_type("NEW") is None
        assert _map_employment_type(None) is None


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 12, posting: dict | None = None):
        from job_market_intel.validation.jobs_af_validator import JobsAfBatchValidator

        parser = JobsAfParser()
        raw = [{"job_id": f"slug-{i}", "html": detail_html(posting)} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return JobsAfBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_salary_is_not_in_the_census(self) -> None:
        """The board publishes none, so a check would be a permanent failure."""
        assert "salary" not in self._report().missing_field_rates

    def test_missing_dates_are_censused(self) -> None:
        payload = {k: v for k, v in POSTING.items() if k not in ("datePosted", "validThrough")}
        report = self._report(posting=payload)
        assert report.missing_field_rates.get("posted_date") == 1.0
        assert report.missing_field_rates.get("closing_date") == 1.0

    def test_a_thin_batch_does_fail(self) -> None:
        assert not self._report(n=2).passed


# ==================================================================== settings


class TestSettings:
    def test_defaults(self) -> None:
        s = JobsAfSettings()
        assert s.base_url == "https://jobs.af"
        assert s.listing_path == "/"
        assert s.max_pages == 1

    def test_overrides_are_honoured(self) -> None:
        assert JobsAfSettings(max_jobs_per_run=10).max_jobs_per_run == 10

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            JobsAfSettings(inter_request_delay_seconds=-1.0)
