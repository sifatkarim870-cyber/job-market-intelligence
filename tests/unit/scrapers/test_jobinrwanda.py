"""Unit tests for the Job in Rwanda scraper.

Each test pins a fact measured on the live site on 2026-10-18. The one that
matters most is a trap of **omission**:

  1. **The site publishes no posting date at all.** Of six detail pages
     inspected, four carry no date and the two that do carry only a
     **deadline**, in prose ("The deadline for submission of applications is
     19 October 2026"). A parser that took the first date on the page would
     write a closing date into ``posting_date`` on every row that had one,
     asserting a recency the site never claims. ``posted_date`` is therefore
     ``None`` on every row, and only deadline wording becomes ``closing_date``.
  2. **The site publishes no company field.** The employer appears only in the
     posting prose, so ``company_name`` stays "Unknown employer".
  3. **The title is in ``<title>``, not in an ``h1``** -- and there is no ``h1``
     at all on the detail page. Measured: ``<title>`` is
     ``"Accountant | Job in Rwanda"``.
  4. **``.field--name-body`` is site boilerplate**, not the posting. Left in, it
     would make "Click on the APPLY button..." the description of every row.
  5. **The homepage *is* the listing**: ``/jobs`` is HTTP 404, ``?page=2`` adds
     nothing, and all **199** postings are on one page.

Run with:  uv run pytest tests/unit/scrapers/test_jobinrwanda.py -q
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from bs4 import BeautifulSoup

from job_market_intel.cleaning.jobinrwanda_cleaner import JobInRwandaCleaner
from job_market_intel.scrapers.jobinrwanda.client import _JOB_LINK, JobInRwandaClient
from job_market_intel.scrapers.jobinrwanda.config import JobInRwandaSettings
from job_market_intel.scrapers.jobinrwanda.exceptions import (
    JobInRwandaParseError,
    JobInRwandaResponseError,
)
from job_market_intel.scrapers.jobinrwanda.parser import (
    _BOILERPLATE,
    JobInRwandaParser,
    _extract_deadline,
    _extract_title,
    parse_detail,
)

#: Trimmed from a live detail page fetched 2026-10-18 (/job/accountant-172).
DETAIL = DETAIL_TEMPLATE = """<!DOCTYPE html><html><head>
<title>Accountant | Job in Rwanda</title></head>
<body>
<div class="node node--type-job node--view-mode-full">
  <div class="node__content clearfix text-formatted field field--name-body
               field--type-text-with-summary field--label-hidden field__item">
    <p>JOB VACANCY ANNOUNCEMENT The Management of RATWA SACCO HUYE informs all
    qualified and competent candidates that is recruiting for the following
    position : ACCOUNTANT (Head Quarters) (1) Responsibilities &amp; tasks :
    Under the supervision and guidance of the Head of Finance &amp; Administration
    to work diligently on the assigned tasks on time and to produce results.</p>
    <p>ACCO HUYE - Head Office. The deadline for submission of applications is
    __DEADLINE__ at 5:00 PM. Only shortlisted candidates will be contacted.</p>
    <div class="field--name-body">Click on the APPLY button to send your
    application documents: Your application will be routed to the hiring manager.</div>
  </div>
</div>
</body></html>"""

#: The deadline is 30 days out rather than a fixed date: the cleaner
#: drops a deadline that is no longer open, so a hard-coded one expires
#: and takes the test with it. This fixture rotted that way on
#: 20 October 2026.
DETAIL = DETAIL_TEMPLATE.replace(
    "__DEADLINE__",
    (date.today() + timedelta(days=30)).strftime("%d %B %Y"),
)


#: A page with no deadline at all (4 of 6 measured).
NO_DEADLINE = """<html><head><title>Accounting Intern | Job in Rwanda</title></head>
<body><div class="node__content">
<p>JOB VACANCY ANNOUNCEMENT. We are looking for an accounting intern to support
the finance team in Kigali. Responsibilities include supporting monthly closes.</p>
</div></body></html>"""

#: A page with a bare date that is NOT called a deadline.
BARE_DATE = """<html><head><title>Rwanda Contracts Coordinator | Job in Rwanda</title></head>
<body><div class="node__content">
<p>About One Acre Fund, founded in 2006. This role is open to citizens or
permanent residents of Rwanda. Reference number 25 November 2026 in our system
for tracking purposes only.</p>
</div></body></html>"""


# ====================================================================== links


class TestListingLinks:
    def test_link_regex_takes_the_slug(self) -> None:
        html = '<a href="/job/accountant-172">Accountant</a>'
        assert [m.group(1) for m in _JOB_LINK.finditer(html)] == ["/job/accountant-172"]

    def test_both_href_forms_are_accepted(self) -> None:
        """Measured on THIS board: 199 relative, 0 absolute.

        Angola Emprego was the opposite and a relative-only pattern there
        matched nothing on a board serving 15 postings a page. Both spellings
        are accepted rather than betting on one.
        """
        slug = "/job/accountant-172"
        for prefix in ("", "https://www.jobinrwanda.com"):
            assert [m.group(1) for m in _JOB_LINK.finditer(f'<a href="{prefix}{slug}">x</a>')] == [
                slug
            ]

    def test_non_job_paths_are_ignored(self) -> None:
        html = (
            '<a href="/">Home</a>'
            '<a href="/jobs">Jobs</a>'
            '<a href="/employer/one-acre-fund">Employer</a>'
            '<a href="/node/12">Node</a>'
        )
        assert list(_JOB_LINK.finditer(html)) == []

    def test_the_listing_is_the_homepage(self) -> None:
        """/jobs is HTTP 404 and ?page=2 adds nothing."""
        client = JobInRwandaClient(JobInRwandaSettings())
        assert client.listing_url(1) == "https://www.jobinrwanda.com/"

    def test_empty_discovery_raises_rather_than_returning_nothing(self) -> None:
        client = JobInRwandaClient(JobInRwandaSettings())
        client._fetch = lambda url: "<html><body>nothing</body></html>"  # type: ignore[method-assign]
        with pytest.raises(JobInRwandaResponseError, match="markup changed"):
            client.discover_detail_paths()


# ====================================================================== title


class TestTitle:
    def test_the_site_suffix_is_stripped(self) -> None:
        soup = BeautifulSoup(DETAIL, "html.parser")
        assert _extract_title(soup) == "Accountant"

    def test_a_long_title_keeps_all_of_its_words(self) -> None:
        raw = (
            "Invitation for Expressions of Interest (EoI) for Provision of "
            "Project Management Consultancy Services | Job in Rwanda"
        )
        soup = BeautifulSoup(f"<html><head><title>{raw}</title></head></html>", "html.parser")
        assert _extract_title(soup) == (
            "Invitation for Expressions of Interest (EoI) for Provision of "
            "Project Management Consultancy Services"
        )

    def test_a_title_without_the_suffix_is_kept_whole(self) -> None:
        soup = BeautifulSoup(
            "<html><head><title>Some Other Page</title></head></html>", "html.parser"
        )
        assert _extract_title(soup) == "Some Other Page"

    def test_no_title_element_is_none(self) -> None:
        assert _extract_title(BeautifulSoup("<html><body>x</body></html>", "html.parser")) is None


# ================================================================== deadlines


class TestDeadlineExtraction:
    """THE trap: the site has no posting date, only deadlines."""

    def test_a_deadline_phrase_yields_a_closing_date(self) -> None:
        date, phrase = _extract_deadline(
            "The deadline for submission of applications is 19 October 2026 at 5:00 PM."
        )
        assert date is not None and date.isoformat() == "2026-10-19"
        assert phrase is not None and "deadline" in phrase.lower()

    @pytest.mark.parametrize(
        "text",
        [
            "Application deadline Sunday 25 October 2026 - places filled on a rolling basis",
            "Application Deadline 28 November 2026 .",
            "closing date: 3 March 2027",
        ],
    )
    def test_other_deadline_wordings(self, text: str) -> None:
        date, _ = _extract_deadline(text)
        assert date is not None

    def test_a_page_with_no_deadline_yields_none(self) -> None:
        assert _extract_deadline(NO_DEADLINE.split("<body>")[1]) == (None, None)

    def test_a_bare_date_not_called_a_deadline_is_not_read(self) -> None:
        """A long date alone is not evidence of a deadline.

        Storing it would invent a closing date the page never stated.
        """
        date, phrase = _extract_deadline(BARE_DATE.split("<body>")[1])
        assert date is None
        assert phrase is None


class TestPostedDateIsAlwaysNone:
    def test_parsing_never_invents_a_posting_date(self) -> None:
        """Even when the page carries a date, ``posted_date`` stays None."""
        job = parse_detail("accountant-172", DETAIL)
        assert job.posted_date is None
        assert job.closing_date is not None


# ================================================================= boilerplate


class TestBoilerplate:
    def test_the_apply_button_block_is_removed(self) -> None:
        job = parse_detail("accountant-172", DETAIL)
        assert job.description is not None
        assert "Click on the APPLY button" not in job.description

    def test_the_real_body_survives(self) -> None:
        job = parse_detail("accountant-172", DETAIL)
        assert "RATWA SACCO HUYE" in (job.description or "")
        assert "ACCOUNTANT" in (job.description or "")

    def test_the_boilerplate_pattern_matches_the_measured_sentence(self) -> None:
        assert _BOILERPLATE.search(
            "text Click on the APPLY button to send your application documents: more"
        )


# ====================================================================== parser


class TestParser:
    def test_a_full_page_is_parsed(self) -> None:
        job = JobInRwandaParser().parse(
            "accountant-172", DETAIL, url="https://www.jobinrwanda.com/job/accountant-172"
        )
        assert job.source_job_id == "accountant-172"
        assert job.title == "Accountant"
        assert job.posted_date is None
        assert job.closing_date is not None
        assert job.raw["page_bytes"] == len(DETAIL)
        assert job.raw["title_tag"] == "Accountant | Job in Rwanda"

    def test_the_deadline_phrase_is_preserved_for_audit(self) -> None:
        job = parse_detail("accountant-172", DETAIL)
        assert "deadline" in (job.raw["deadline_phrase"] or "").lower()

    def test_company_is_unknown_because_no_field_exists(self) -> None:
        job = parse_detail("accountant-172", DETAIL)
        assert job.company_name == "Unknown employer"

    def test_no_title_raises(self) -> None:
        with pytest.raises(JobInRwandaParseError, match="no title"):
            parse_detail("x", "<html><body>no title here</body></html>")

    def test_parse_many_collects_failures_rather_than_raising(self) -> None:
        records = [
            {"job_id": "a", "html": DETAIL},
            {"job_id": "b", "html": "<html><body>x</body></html>"},
        ]
        jobs, issues = JobInRwandaParser().parse_many(records)
        assert [j.source_job_id for j in jobs] == ["a"]
        assert len(issues) == 1


# ====================================================================== cleaner


class TestCleaner:
    def _job(self, **kw):
        return parse_detail(
            "accountant-172", DETAIL, url="https://www.jobinrwanda.com/job/accountant-172"
        ).model_copy(update=kw)

    def test_posting_date_is_none_on_the_cleaned_row(self) -> None:
        assert JobInRwandaCleaner().clean_job(self._job()).posting_date is None

    def test_closing_date_survives_cleaning(self) -> None:
        cleaned = JobInRwandaCleaner().clean_job(self._job())
        assert cleaned.closing_date is not None

    def test_employer_is_unknown_and_says_why(self) -> None:
        cleaned = JobInRwandaCleaner().clean_job(self._job())
        assert cleaned.company_name == "Unknown employer"
        assert cleaned.raw_payload["has_company_field"] is False

    def test_no_salary_is_ever_claimed(self) -> None:
        cleaned = JobInRwandaCleaner().clean_job(self._job())
        assert cleaned.salary_min is None
        assert cleaned.salary_disclosed is False
        assert cleaned.raw_payload["salary_published"] is False

    def test_skills_are_empty_because_the_board_has_none(self) -> None:
        assert JobInRwandaCleaner().clean_job(self._job()).skills == []

    def test_location_is_named_so_the_resolver_can_reach_the_fallback(self) -> None:
        """A NULL here gives location_id = NULL, not a country.

        ``resolve_and_cache_location`` returns ``None`` straight away when
        ``raw_location_text`` is ``None`` -- it never consults
        ``SOURCE_HOME_COUNTRY``. The first live run produced 150 rows with
        ``location_id IS NULL``: no country *and* no global-remote flag, which
        is worse than either.
        """
        cleaned = JobInRwandaCleaner().clean_job(self._job())
        assert cleaned.location_cleaned == "Rwanda"

    def test_posting_date_is_none_so_the_repository_supplies_its_partition_key(self) -> None:
        """``core.jobs`` is RANGE partitioned on posting_date (NOT NULL).

        So the repository stamps ``date.today()`` for every one of these rows.
        The cleaner must not pretend to know a publication date; it must also
        not pretend the run date is one.
        """
        assert JobInRwandaCleaner().clean_job(self._job()).posting_date is None
        assert JobInRwandaCleaner().clean_job(self._job()).raw_payload["has_posting_date"] is False

    def test_language_is_recorded_as_english(self) -> None:
        assert JobInRwandaCleaner().clean_job(self._job()).raw_payload["language"] == "en"

    def test_quality_score_ignores_absent_by_design_signals(self) -> None:
        """Employer, posting date and salary are structurally absent here.

        Counting them would give every row the same depressed score and make
        the number useless for ranking this source.
        """
        s = JobInRwandaCleaner().clean_job(self._job()).data_quality_score
        assert s == 1.0


class TestExpiredDeadline:
    """A past deadline cannot be stored, and must not be.

    ``job_repository.save_cleaned_job`` defaults a NULL ``posting_date`` to
    ``date.today()``. This board publishes no posting date, so every row would
    claim to have been posted today -- and a deadline of 5 October on a run
    dated 17 October then sits *before* that fabricated date and trips
    ``ck_jobs_closing_after_posting``. It cost 1 of 40 postings on the first
    live run.
    """

    def _expired(self):
        from datetime import date, timedelta

        return parse_detail(
            "sales-manager-20",
            DETAIL,
            url="https://www.jobinrwanda.com/job/sales-manager-20",
        ).model_copy(update={"closing_date": date.today() - timedelta(days=12)})

    def test_an_expired_deadline_is_not_stored_as_a_closing_date(self) -> None:
        cleaned = JobInRwandaCleaner().clean_job(self._expired())
        assert cleaned.closing_date is None

    def test_but_the_phrase_is_kept_so_nothing_is_lost(self) -> None:
        cleaned = JobInRwandaCleaner().clean_job(self._expired())
        assert cleaned.raw_payload["deadline_expired"] is True
        assert cleaned.raw_payload["deadline_phrase"]

    def test_a_future_deadline_is_stored_normally(self) -> None:
        from datetime import date, timedelta

        job = parse_detail(
            "future", DETAIL, url="https://www.jobinrwanda.com/job/future"
        ).model_copy(update={"closing_date": date.today() + timedelta(days=30)})
        cleaned = JobInRwandaCleaner().clean_job(job)
        assert cleaned.closing_date is not None
        assert cleaned.raw_payload["deadline_expired"] is False

    def test_the_quality_score_reflects_the_stored_not_the_stated_date(self) -> None:
        expired = JobInRwandaCleaner().clean_job(self._expired())
        assert expired.data_quality_score < 1.0


# ==================================================================== validator


class TestValidator:
    def _report(self, n: int = 120, html: str = DETAIL):
        from job_market_intel.validation.jobinrwanda_validator import (
            JobInRwandaBatchValidator,
        )

        parser = JobInRwandaParser()
        raw = [{"job_id": f"slug-{i}", "html": html} for i in range(n)]
        parsed = [parser.parse(r["job_id"], r["html"]) for r in raw]
        return JobInRwandaBatchValidator().validate(raw, parsed)

    def test_a_full_batch_passes(self) -> None:
        assert self._report().passed

    def test_posted_date_is_not_in_the_census(self) -> None:
        """The board publishes none, so a check would be a permanent failure."""
        assert "posted_date" not in self._report().missing_field_rates

    def test_an_empty_description_is_censused(self) -> None:
        report = self._report(
            html="<html><head><title>X | Job in Rwanda</title></head>"
            "<body><div class='node__content'></div></body></html>"
        )
        assert report.missing_field_rates.get("description") == 1.0

    def test_a_thin_batch_does_fail(self) -> None:
        assert not self._report(n=5).passed


# ==================================================================== settings


class TestSettings:
    def test_defaults(self) -> None:
        s = JobInRwandaSettings()
        assert s.base_url == "https://www.jobinrwanda.com"
        assert s.listing_path == "/"
        assert s.max_pages == 1

    def test_overrides_are_honoured(self) -> None:
        s = JobInRwandaSettings(max_jobs_per_run=40)
        assert s.max_jobs_per_run == 40

    def test_settings_reject_nonsense_bounds(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            JobInRwandaSettings(inter_request_delay_seconds=-1.0)
