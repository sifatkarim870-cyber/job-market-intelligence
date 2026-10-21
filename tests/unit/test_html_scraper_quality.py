"""The quality gate must reject navigation, not real postings.

On 2026-10-21 the sweep stored 578 rows from auto-generated configs and called
them a success. 499 of them were the site's own navigation or news: see
``/job-search/operations-jobs``, ``/jobs/today/``, ``/blog/...``. The gate added
afterwards rejects those. These tests pin both directions -- a gate that rejects
everything would look just as green.

Run with:  uv run pytest tests/unit/test_html_scraper_quality.py -q
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from job_market_intel.validation.html_scraper_quality import reject_reason

DESCRIPTION = "We are hiring a senior engineer. " * 10


@pytest.mark.parametrize(
    ("url", "title", "reason_fragment"),
    [
        # Category pages that mention "job" in the path.
        (
            "https://shine.com/job-search/operations-jobs",
            "Operations jobs in India",
            "section path",
        ),
        (
            "https://ikman.lk/en/ads/sri-lanka/driver-jobs",
            "Driver jobs",
            "category path",
        ),
        (
            "https://jobwebkenya.com/job-tag/career/",
            'Jobs tagged "career"',
            "section path",
        ),
        # News and advice, which several newspaper sources produced.
        (
            "https://burkina24.com/2026/10/21/autonomisation-des-femmes/",
            "Autonomisation des femmes",
            "news article",
        ),
        (
            "https://www.acbar.org/en/site-highlight/securing-slopes",
            "Menu",
            "section path",
        ),
        # Nav furniture.
        ("https://camhr.com/a/job", "Home", "listing page"),
        ("https://jobnet.dk/hjaelp-og-support", "Menu", "no job keyword"),
        ("https://zhipin.com/gongsi/job/abc.html", "安全验证", "navigation title"),
        # A bare listing page is not a posting.
        ("https://jobs.example.com/jobs/", "Jobs", "listing page"),
        ("https://jobtiger.bg/obiavi-za-rabota", "Работа - JobTiger", "listing page"),
        # General classifieds with no job vocabulary at all.
        (
            "https://willhaben.at/iad/kaufen-und-verkaufen/marktplatz/taschen-koffer/handtaschen-3484",
            "Handtaschen | willhaben",
            "no job keyword",
        ),
    ],
)
def test_navigation_is_rejected(url: str, title: str, reason_fragment: str) -> None:
    reason = reject_reason(url, title, DESCRIPTION, site_host=urlparse(url).netloc)
    assert reason is not None, f"{url} should have been rejected"
    assert reason_fragment in reason, reason


def test_link_to_another_site_is_rejected() -> None:
    """The board is not a directory: a link to linkedin is not a posting."""
    reason = reject_reason(
        "https://www.linkedin.com/company/jobthai",
        "JobThai",
        DESCRIPTION,
        site_host="jobthai.com",
    )
    assert reason is not None
    assert "offsite link" in reason


@pytest.mark.parametrize(
    "url",
    [
        "https://mustakbil.com/jobs/job/1436023",
        "https://praca.by/vacancy/744451/",
        "https://www.posao.hr/oglasi/mesar-m-z/1235449/",
        "https://www.prace.cz/nabidka/affd26e6-ba41-4a13-a947-9665192e9311/",
        "https://www.hellojob.az/vakansiya/satis-meslehetcisi-14815708-17107625",
        "https://jobwebghana.com/jobs/head-legal-reputable-company/",
        "https://www.emploidakar.com/offre-demploi/mmbc-dakar-cdi-receptionniste/",
    ],
)
def test_real_detail_urls_are_kept(url: str) -> None:
    assert reject_reason(url, "Senior Engineer", DESCRIPTION) is None


def test_missing_description_is_rejected() -> None:
    """A page with no body is a nav link even when the URL looks right."""
    reason = reject_reason("https://example.com/jobs/senior-engineer-12345", "Senior Engineer", "")
    assert reason is not None
    assert "no job description" in reason


def test_long_title_ending_in_jobs_is_kept() -> None:
    """skill.jobs puts the board name in og:title; that is not a category page.

    The first version of the category rule rejected all six real skill.jobs
    postings because their title ends with "| Skill Jobs".
    """
    assert (
        reject_reason(
            "https://skill.jobs/jobs/tele-sales-intern-female-lxhBGqsY",
            "Tele Sales Intern at Skill Jobs | 104, Shukrabad, Dhanmondi, "
            "Mirpur Road, Dhaka-1207 | Skill Jobs",
            DESCRIPTION,
        )
        is None
    )


def test_offsite_link_is_rejected() -> None:
    """A board's posting lives on its own host; off-site links are its nav.

    This used to allow any non-social off-site host in case a board linked to
    an ATS. bne.cl used that to store Chilean subsidy pages from sence.gob.cl.
    """
    reason = reject_reason(
        "https://jobs.lever.co/acme/1234",
        "Senior Engineer",
        DESCRIPTION,
        site_host="acme.com",
    )
    assert reason is not None
    assert "offsite link" in reason
