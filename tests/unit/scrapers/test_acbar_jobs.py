"""Unit tests for the ACBAR jobs scraper.

Each test pins a fact measured on the live site on 2026-10-18. The one that
matters most is a trap of *contamination*:

  1. **The body container holds other postings' dates.**
     ``.acbar-jd__body`` is 4680 characters and contains **six** ISO dates that
     belong to *different* jobs, inside a ``.acbar-jd__related`` carousel. The
     tell was that the same ten dates came back from two *different* posting
     pages. A naive "first date in the body" extraction therefore assigns a
     deadline from an unrelated job, and the description ends up with six
     strangers spliced into it. The related block is removed first; **zero**
     dates remain afterwards.

  2. **``Salary`` is prose, not a figure.** Measured: ``"As Per Organization"``,
     ``"As per scale"``, ``"Negotiable"``. Storing any of them would invent a
     number.

  3. **``Nationality`` is not a country.** It reads ``"Afghan"`` / ``"National"``
     and describes who may apply. Deriving the country from it would read the
     wrong field.

  4. **There is no company field** -- the employer is prose only.

Also pinned: ``?page=`` is the pager while ``/en/site-page/2`` is HTTP 404
(chrome, not pager), and hrefs are absolute.

Run with:  uv run pytest tests/unit/scrapers/test_acbar_jobs.py -q
"""

from __future__ import annotations

from datetime import date

import pytest
from bs4 import BeautifulSoup

from job_market_intel.cleaning.acbar_jobs_cleaner import AcbarJobsCleaner, _map_employment_type
from job_market_intel.scrapers.acbar_jobs.client import _JOB_LINK, AcbarJobsClient
from job_market_intel.scrapers.acbar_jobs.config import AcbarJobsSettings
from job_market_intel.scrapers.acbar_jobs.exceptions import (
    AcbarJobsParseError,
    AcbarJobsResponseError,
)
from job_market_intel.scrapers.acbar_jobs.parser import (
    AcbarJobsParser,
    _parse_date,
    extract_body,
    extract_info_rows,
    extract_title,
    parse_detail,
)

#: Trimmed from a live detail page fetched 2026-10-18
#: (/en/jobs/details/146202/pedagogy-trainer). The related-jobs carousel and its
#: six foreign dates are the trap, so they are reproduced faithfully.
DETAIL = """<!DOCTYPE html><html><head>
<title>ACBAR: Pedagogy Trainer</title></head><body>
<h1>Pedagogy Trainer</h1>
<div class="acbar-jd__hero-meta">
  <dl class="acbar-jd__info-table">
    <div class="acbar-jd__info-row"><dt class="acbar-jd__info-term">Type</dt>
      <dd class="acbar-jd__info-desc">Full Time</dd></div>
    <div class="acbar-jd__info-row"><dt class="acbar-jd__info-term">Location</dt>
      <dd class="acbar-jd__info-desc">Baghlan - Pull-e-Khumri</dd></div>
    <div class="acbar-jd__info-row"><dt class="acbar-jd__info-term">Category</dt>
      <dd class="acbar-jd__info-desc">Education, Training</dd></div>
    <div class="acbar-jd__info-row"><dt class="acbar-jd__info-term">Published</dt>
      <dd class="acbar-jd__info-desc" dir="ltr">2026-10-14</dd></div>
    <div class="acbar-jd__info-row"><dt class="acbar-jd__info-term">Nationality</dt>
      <dd class="acbar-jd__info-desc">Afghan</dd></div>
    <div class="acbar-jd__info-row"><dt class="acbar-jd__info-term">Gender</dt>
      <dd class="acbar-jd__info-desc">Female</dd></div>
    <div class="acbar-jd__info-row"><dt class="acbar-jd__info-term">Salary</dt>
      <dd class="acbar-jd__info-desc">As Per Organization</dd></div>
    <div class="acbar-jd__info-row"><dt class="acbar-jd__info-term">Contract Duration</dt>
      <dd class="acbar-jd__info-desc">Project Based</dd></div>
    <div class="acbar-jd__info-row"><dt class="acbar-jd__info-term">Vacancy Number</dt>
      <dd class="acbar-jd__info-desc">(05-PG-SDCO)</dd></div>
    <div class="acbar-jd__info-row"><dt class="acbar-jd__info-term">No of Job</dt>
      <dd class="acbar-jd__info-desc">2</dd></div>
  </dl>
  <div class="acbar-jd__info-text">Education</div>
  <p class="acbar-jd__info-text-value">Bachelor's degree</p>
  <div class="acbar-jd__deadline-banner">
    <p class="acbar-jd__deadline-label">Deadline</p>
    <p class="acbar-jd__deadline-value">2026-10-24</p>
  </div>
</div>
<div class="acbar-jd__body">
  <div class="acbar-jd__rich">About the Company About SDCO Support Development Capacity
  Organization (SDCO) is a non-governmental, non-political, and non-profit
  organization established in 2012 working to support vulnerable communities.</div>
  <div class="acbar-jd__related acbar-jd__no-print">
    <div class="acbar-jd-carousel__slide"><p>Laboratory dispensing technician
    INTERSOS Full Time Oruzgan 2026-10-22 2 days ago</p></div>
    <div class="acbar-jd-carousel__slide"><p>Head of Information Technology
    e&amp; Afghanistan Full Time Kabul 2026-10-28 2 days ago</p></div>
    <div class="acbar-jd-carousel__slide"><p>Senior Project Coordinator
    War Child Canada Full Time Kabul 2026-10-22 2 days ago</p></div>
    <div class="acbar-jd-carousel__slide"><p>Hygiene Promoter INTERSOS
    Full Time Helmand 2026-10-21 2 days ago</p></div>
  </div>
</div>
</body></html>"""


# ====================================================================== links


class TestListingLinks:
    def test_the_measured_href_form_is_absolute(self) -> None:
        """Measured: 20 absolute, 0 relative."""
        html = '<a href="https://www.acbar.org/en/jobs/details/146202/pedagogy-trainer">x</a>'
        found = {m.group(2): m.group(1) for m in _JOB_LINK.finditer(html)}
        assert found == {"146202": "/en/jobs/details/146202/pedagogy-trainer"}

    def test_relative_form_is_accepted_too(self) -> None:
        html = '<a href="/en/jobs/details/146205/wash-field-engineer">x</a>'
        assert [m.group(2) for m in _JOB_LINK.finditer(html)] == ["146205"]

    def test_the_numeric_id_is_the_key(self) -> None:
        html = '<a href="/en/jobs/details/146202/pedagogy-trainer">x</a>'
        assert [m.group(2) for m in _JOB_LINK.finditer(html)] == ["146202"]

    def test_pagination_uses_page_and_not_the_chrome_path(self) -> None:
        """?page=N is the pager. /en/site-page/2 is HTTP 404 -- that is chrome."""
        client = AcbarJobsClient(AcbarJobsSettings())
        assert client.listing_url(1) == "https://www.acbar.org/en/jobs"
        assert client.listing_url(2) == "https://www.acbar.org/en/jobs?page=2"
        assert "site-page" not in client.listing_url(2)

    def test_empty_discovery_raises(self) -> None:
        client = AcbarJobsClient(AcbarJobsSettings(max_pages=1))
        client._fetch = lambda url: "<html><body>nothing</body></html>"  # type: ignore[method-assign]
        with pytest.raises(AcbarJobsResponseError, match="markup changed"):
            client.discover_detail_paths()


# ====================================================================== dates


class TestDates:
    def test_iso(self) -> None:
        assert _parse_date("2026-10-14") == date(2026, 10, 14)

    @pytest.mark.parametrize("raw", [None, "", "not a date"])
    def test_junk_is_none(self, raw) -> None:
        assert _parse_date(raw) is None


# ============================================================ the body trap


class TestBodyExcludesOtherPostings:
    """THE trap. Foreign dates must not survive into the body."""

    def test_the_fixture_really_contains_foreign_dates(self) -> None:
        """Guards the guard: without this the test below could pass vacuously."""
        soup = BeautifulSoup(DETAIL, "html.parser")
        body_with_sidebar = soup.select_one(".acbar-jd__body").get_text(" ", strip=True)
        assert body_with_sidebar.count("2026-10-") >= 4, (
            "the fixture must contain the related-jobs dates for this test to mean anything"
        )

    def test_no_foreign_date_survives_extraction(self) -> None:
        body = extract_body(BeautifulSoup(DETAIL, "html.parser"))
        assert "2026-10-" not in body
        assert "2 days ago" not in body

    def test_the_parser_records_the_count_for_audit(self) -> None:
        job = parse_detail("146202", DETAIL)
        assert job.raw["dates_left_in_body"] == 0

    def test_the_real_description_survives(self) -> None:
        body = extract_body(BeautifulSoup(DETAIL, "html.parser"))
        assert "SDCO" in body
        assert "non-profit" in body

    def test_related_slides_are_gone(self) -> None:
        body = extract_body(BeautifulSoup(DETAIL, "html.parser"))
        for stranger in ("INTERSOS", "War Child", "e& Afghanistan"):
            assert stranger not in body


# ================================================================= info rows


class TestInfoRows:
    def test_every_measured_key_is_read(self) -> None:
        info = extract_info_rows(BeautifulSoup(DETAIL, "html.parser"))
        assert info["type"] == "Full Time"
        assert info["location"] == "Baghlan - Pull-e-Khumri"
        assert info["category"] == "Education, Training"
        assert info["published"] == "2026-10-14"
        assert info["nationality"] == "Afghan"
        assert info["gender"] == "Female"
        assert info["salary"] == "As Per Organization"
        assert info["contract duration"] == "Project Based"
        assert info["vacancy number"] == "(05-PG-SDCO)"
        assert info["no of job"] == "2"

    def test_the_second_pair_shape_is_read_too(self) -> None:
        """Education uses info-text/info-text-value, not the <dl> shape."""
        info = extract_info_rows(BeautifulSoup(DETAIL, "html.parser"))
        assert info["education"] == "Bachelor's degree"


class TestTitle:
    def test_h1_wins(self) -> None:
        assert extract_title(BeautifulSoup(DETAIL, "html.parser")) == "Pedagogy Trainer"

    def test_title_tag_is_the_fallback_and_stripped(self) -> None:
        html = "<html><head><title>ACBAR: Wash Field Engineer</title></head><body></body></html>"
        assert extract_title(BeautifulSoup(html, "html.parser")) == "Wash Field Engineer"

    def test_no_title_anywhere_is_none(self) -> None:
        assert extract_title(BeautifulSoup("<html><body>x</body></html>", "html.parser")) is None


# ====================================================================== parser


class TestParser:
    def test_a_full_posting_is_parsed(self) -> None:
        job = parse_detail(
            "146202", DETAIL, url="https://www.acbar.org/en/jobs/details/146202/pedagogy-trainer"
        )
        assert job.source_job_id == "146202"
        assert job.title == "Pedagogy Trainer"
        assert job.employment_type == "Full Time"
        assert job.industry == "Education, Training"
        assert job.location == "Baghlan - Pull-e-Khumri"
        assert job.posted_date == date(2026, 10, 14)
        assert job.closing_date == date(2026, 10, 24)

    def test_the_salary_prose_is_kept_verbatim(self) -> None:
        job = parse_detail("146202", DETAIL)
        assert job.salary_text == "As Per Organization"

    def test_the_raw_model_has_no_salary_numbers_to_store(self) -> None:
        """There is nothing to store: the board publishes prose, not a figure.

        Asserting the *absence* of the fields rather than their value is the
        point -- it means a future "improvement" that adds them has to be
        deliberate.
        """
        job = parse_detail("146202", DETAIL)
        assert not hasattr(job, "salary_min")
        assert not hasattr(job, "salary_max")

    def test_company_is_unknown_because_no_field_exists(self) -> None:
        assert parse_detail("146202", DETAIL).company_name == "Unknown employer"

    def test_no_title_raises(self) -> None:
        with pytest.raises(AcbarJobsParseError, match="no title"):
            parse_detail("x", "<html><body>no h1</body></html>")

    def test_parse_many_collects_failures(self) -> None:
        records = [
            {"job_id": "1", "html": DETAIL},
            {"job_id": "2", "html": "<html><body>x</body></html>"},
        ]
        jobs, issues = AcbarJobsParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["1"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return parse_detail(
            "146202", DETAIL, url="https://www.acbar.org/en/jobs/details/146202/pedagogy-trainer"
        ).model_copy(update=kw)

    def test_prose_salary_is_never_stored_as_a_number(self) -> None:
        cleaned = AcbarJobsCleaner().clean_job(self._job())
        assert cleaned.salary_min is None
        assert cleaned.salary_max is None
        assert cleaned.salary_disclosed is False

    def test_the_prose_is_kept_for_audit(self) -> None:
        cleaned = AcbarJobsCleaner().clean_job(self._job())
        assert cleaned.raw_payload["salary_text"] == "As Per Organization"
        assert cleaned.raw_payload["salary_published"] is False

    def test_full_time_maps_to_full_time(self) -> None:
        assert AcbarJobsCleaner().clean_job(self._job()).employment_type_code == "full_time"

    def test_nationality_is_recorded_but_not_used_as_the_country(self) -> None:
        """'Afghan' describes who may apply, not where the job is."""
        payload = AcbarJobsCleaner().clean_job(self._job()).raw_payload
        assert payload["nationality"] == "Afghan"

    def test_posting_and_closing_dates_survive(self) -> None:
        cleaned = AcbarJobsCleaner().clean_job(self._job())
        assert cleaned.posting_date is not None
        assert cleaned.closing_date is not None

    def test_closing_is_not_before_posting(self) -> None:
        """The schema enforces it; a reversed pair would lose the row."""
        cleaned = AcbarJobsCleaner().clean_job(self._job())
        assert cleaned.closing_date >= cleaned.posting_date

    def test_location_is_kept(self) -> None:
        assert (
            AcbarJobsCleaner().clean_job(self._job()).location_cleaned == "Baghlan - Pull-e-Khumri"
        )

    def test_the_whole_info_table_is_preserved(self) -> None:
        info = AcbarJobsCleaner().clean_job(self._job()).raw_payload["info_table"]
        assert info["vacancy number"] == "(05-PG-SDCO)"


class TestEmploymentMapping:
    def test_full_time_with_a_space_maps(self) -> None:
        """ACBAR writes 'Full Time'; schema.org writes FULL_TIME."""
        assert _map_employment_type("Full Time") == "full_time"

    def test_unknown_is_none(self) -> None:
        assert _map_employment_type("Something Else") is None
        assert _map_employment_type(None) is None


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 20, html: str = DETAIL):
        from job_market_intel.validation.acbar_jobs_validator import (
            AcbarJobsBatchValidator,
        )

        parser = AcbarJobsParser()
        raw = [{"job_id": str(146200 + i), "html": html} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return AcbarJobsBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_salary_is_not_in_the_census(self) -> None:
        """Every posting states prose, so a check would be a permanent failure."""
        assert "salary" not in self._report().missing_field_rates

    def test_a_thin_batch_does_fail(self) -> None:
        assert not self._report(n=3).passed


# ==================================================================== settings


class TestSettings:
    def test_defaults(self) -> None:
        s = AcbarJobsSettings()
        assert s.base_url == "https://www.acbar.org"
        assert s.listing_path == "/en/jobs"

    def test_overrides_are_honoured(self) -> None:
        s = AcbarJobsSettings(max_pages=3, max_jobs_per_run=25)
        assert (s.max_pages, s.max_jobs_per_run) == (3, 25)

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AcbarJobsSettings(inter_request_delay_seconds=-1.0)
