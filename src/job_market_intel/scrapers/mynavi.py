"""Discovery for Mynavi's new-grad site (job.mynavi.jp).

The site publishes no listing of postings. Its search (`/27/pc/search/...`)
is a query-string application, and robots.txt answers every such URL with
``Disallow: /*?`` under ``User-agent: *``; the company directory that the
site's own front page offers is the same query-string search. What is left
are the two sitemaps Mynavi publishes for crawlers:

* ``sitemap_2027_corp_employment.xml`` -- 32,000+ company pages at
  ``/27/pc/search/corp<id>/employment.html``, each listing that company's
  recruitment courses (the postings) with title, location and a blurb;
* ``sitemap_2027_corp.xml`` -- the same companies' profile pages.

Each course links to a detail page that is reachable WITHOUT a query string
(``/27/pc/search/corp<id>/recruiting_course<courseId>/recruiting_course.html``)
and carries the full posting: course name, 配属職種 (the work description),
雇用形態, 勤務地, 初任給 and 最終更新日. So discovery walks the sitemap, reads
the courses off a company page, and hands the course URLs to the generic
client, which fetches and parses them with the site config's selectors.

robots.txt also sets ``Crawl-delay: 120`` for ``User-agent: *``, which the
site config honours, so a run covers a dozen ads rather than the whole
sitemap. To keep successive runs from re-reading the same companies, the
walk starts at an offset derived from the current UTC hour.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from loguru import logger

from job_market_intel.scrapers.html_scraper.client import HtmlScraperClient
from job_market_intel.scrapers.html_scraper.exceptions import (
    HtmlScraperFetchError,
    HtmlScraperResponseError,
)

#: New-grad years in preference order. Mynavi re-issues the sitemaps yearly; the
#: newest one with entries is the one worth walking.
SITEMAP_YEARS: tuple[int, ...] = (2028, 2027)

SITEMAP_URL = "https://job.mynavi.jp/sitemap_{year}_corp_employment.xml"

_COMPANY_RE = re.compile(r"/corp\d+/employment\.html$")
_COURSE_LINK_RE = re.compile(r"corpId=(\d+)&(?:amp;)?recruitingCourseId=(\d+)")
_COURSE_PATH = "/pc/search/corp{corp}/recruiting_course{course}/recruiting_course.html"


class MynaviClient(HtmlScraperClient):
    """Sitemap -> company course list -> course detail pages."""

    def _sitemap_companies(self, year: int) -> list[str]:
        """Company employment URLs from one year's sitemap."""
        url = SITEMAP_URL.format(year=year)
        try:
            body = self._get(url)
        except HtmlScraperFetchError as exc:
            logger.warning("mynavi sitemap {} failed: {}", url, exc)
            return []
        companies = [
            loc.strip()
            for loc in re.findall(r"<loc>([^<]+)</loc>", body)
            if _COMPANY_RE.search(loc.strip())
        ]
        if not companies:
            logger.warning("mynavi sitemap {} has no company URLs", url)
        return companies

    def _year_is_live(self, company_url: str) -> bool:
        """True when a company page answers directly instead of redirecting.

        A sitemap can be published before its recruiting cycle opens: the 2028
        company pages currently answer 302 to
        ``/28/pc/corpinfo/displayPrevRecruitingCourseList/index?corpId=...`` (a
        query URL robots disallows) and their courses live under the 2027
        prefix instead. Only a cycle that serves its own ``employment.html``
        has course pages at the matching prefix.
        """
        try:
            response = self._session.get(
                company_url,
                timeout=self._site_config.request_timeout_seconds,
                allow_redirects=False,
            )
        except Exception as exc:  # requests.RequestException, plus odd adapter errors
            logger.warning("mynavi company probe {} failed: {}", company_url, exc)
            return False
        return response.status_code < 400 and not response.is_redirect

    def _company_pages(self) -> tuple[str, list[str]] | None:
        """URL prefix and company pages of the newest live recruiting cycle."""
        for year in SITEMAP_YEARS:
            companies = self._sitemap_companies(year)
            if not companies:
                continue
            if not self._year_is_live(companies[0]):
                logger.info("mynavi {} is not serving its own company pages yet", year)
                continue
            prefix = companies[0].split("/pc/search/")[0]
            logger.info("mynavi {}: {} company page(s) under {}", year, len(companies), prefix)
            return prefix, companies
        return None

    def _course_links(self, html: str, prefix: str) -> list[dict]:
        """Course detail URLs listed on one company's employment page.

        ``prefix`` is the year segment of the company URL ("/27"), because the
        course lives under the same year as the company that lists it.
        """
        courses: list[dict] = []
        seen: set[str] = set()
        for corp, course in _COURSE_LINK_RE.findall(html or ""):
            url = prefix + _COURSE_PATH.format(corp=corp, course=course)
            if url in seen:
                continue
            seen.add(url)
            courses.append({"url": url, "title": ""})
        return courses

    def discover_detail_paths(
        self, max_jobs: int | None = None
    ) -> tuple[list[dict], dict[str, str]]:
        budget = max_jobs or self._site_config.max_jobs_per_run
        cycle = self._company_pages()
        if cycle is None:
            raise HtmlScraperResponseError(
                "mynavi sitemaps yielded no live company pages; "
                "the sitemap format may have changed."
            )
        prefix, companies = cycle

        # Rotate the window so a daily run does not keep re-reading the first
        # companies of a 32,000-entry sitemap. Company pages are cheap to skip:
        # a few carry no courses at all.
        now = datetime.now(UTC)
        start = ((now.toordinal() * 24 + now.hour) * budget) % len(companies)
        ordered = companies[start:] + companies[:start]
        company_budget = max(3, budget * 2)

        jobs: list[dict] = []
        failures: dict[str, str] = {}
        fetched = 0
        for company_url in ordered:
            if len(jobs) >= budget or fetched >= company_budget:
                break
            try:
                html = self._get(company_url)
            except HtmlScraperFetchError as exc:
                failures[company_url] = str(exc)
                logger.warning("mynavi company page {} failed: {}", company_url, exc)
                continue
            fetched += 1
            for course in self._course_links(html, prefix):
                if len(jobs) >= budget:
                    break
                jobs.append(course)
            time.sleep(self._site_config.inter_request_delay_seconds)

        logger.info("mynavi: {} course(s) from {} company page(s)", len(jobs), fetched)
        return jobs, failures
