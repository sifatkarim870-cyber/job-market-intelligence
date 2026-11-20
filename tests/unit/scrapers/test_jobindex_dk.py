"""Unit tests for the Jobindex (Denmark, jobindex.dk) scraper.

Pinned measured facts (2026-11-20, live site):

  * ``robots.txt`` has a generic ``User-agent: *`` group and **no**
    ``Crawl-delay``; it disallows ``page=``/``sort=``/``jobage=`` search URLs,
    every ``/c?`` link and ``/jobannonce/korrektur|embed/``. The surfaces this
    scraper uses (``/jobsoegning``, ``/jobsoegning/<area>``,
    ``/sitemap/area.gz``, ``/vis-job/<tid>``, ``/jobannonce/<tid>/<slug>``)
    are allowed.
  * ``/sitemap/area.gz`` is a ``<urlset>`` of 759 ``/jobsoegning/<area>``
    pages; ``googleforjobs.gz`` is an EMPTY ``<urlset>`` even as Googlebot.
  * Each listing page embeds ``var Stash = {...}`` with
    ``["jobsearch/result_app/list"]["storeData"]["searchResponse"]["results"]``
    holding ``tid``, ``headline``, ``companytext``, ``firstdate``, ``lastdate``,
    ``apply_deadline``, ``salary``, ``home_workplace``, ``area``, ``addresses``,
    ``listlogo_url`` and the rendered ``html`` snippet.
  * Ad ids look like ``h1716213`` (human) or ``r14107185`` (robot feed); the
    regex ``[A-Za-z]?\\d{4,}`` rejects prose anchors such as
    ``/jobannonce/reportage``.
  * ``/jobannonce/<tid>/<slug>`` carries the full body in
    ``section.jobtext-jobad__body`` and a sidebar card
    (``Div.jobtext-sidebar-card`` -> ``<dl><dt>Label:</dt><dd>value</dd>``)
    with ``Ansættelsestype``/``Hjemmearbejde``/``Ugentlig arbejdstid``.
  * ``/vis-job/<tid>`` is an employer-paid teaser (~530-695 chars) in
    ``div.PaidJob-inner``; its ``<link rel="canonical">`` either points at a
    ``/jobannonce/`` page or at itself. A wrong/missing slug returns HTTP 200
    with no body, so only the slug from the snippet or the canonical link is
    used.
  * ``salary`` was ``null`` on all 116 sampled listing rows.
"""

from __future__ import annotations

import gzip
import json
from datetime import date, datetime

import pytest

from job_market_intel.scrapers.jobindex_dk import (
    JobIndexClient,
    JobIndexParseError,
    JobIndexParser,
    JobIndexPipeline,
    JobIndexResponseError,
    JobIndexSettings,
    RawJobIndexJob,
    canonical_url,
    extract_stash,
    jobannonce_path,
    listing_results,
)
from job_market_intel.scrapers.jobindex_dk.parser import (
    HOME_COUNTRY,
    build_location,
    detect_remote,
    map_employment_type,
    parse_date,
)

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _listing_page(rows: list[dict]) -> str:
    payload = {
        "jobsearch/result_app/list": {
            "storeData": {
                "searchResponse": {
                    "results": rows,
                    "hitcount": 18829,
                    "total_pages": 942,
                    "max_page": 50,
                    "page_size": 20,
                }
            }
        }
    }
    return "<html><body><script>var Stash = " + json.dumps(payload) + ";</script></body></html>"


def _row(
    tid: str,
    *,
    headline: str = "",
    company: str = "",
    firstdate: str | None = "2026-11-20",
    lastdate: str | None = None,
    apply_deadline: str | None = None,
    salary: object = None,
    home_workplace: bool = False,
    area: str | None = None,
    addresses: list | None = None,
    link_slug: str | None = None,
    listlogo_url: str | None = None,
) -> dict:
    row: dict = {
        "tid": tid,
        "headline": headline,
        "companytext": company,
        "firstdate": firstdate,
        "lastdate": lastdate,
        "apply_deadline": apply_deadline,
        "salary": salary,
        "home_workplace": home_workplace,
        "area": area,
        "addresses": addresses or [],
        "listlogo_url": listlogo_url,
        "html": "",
    }
    if link_slug:
        # The site escapes the slashes inside the inline snippet.
        row["html"] = f'<a href="\\/jobannonce\\/{tid}\\/{link_slug}">x</a>'
    return row


FULL_BODY_HTML = """<!DOCTYPE html><html><body>
<article class="jobtext-jobad">
  <header class="jobtext-jobad__header">
    <h1>Uddannet jordemoder eller sygeplejerske med ultralydserfaring</h1>
    <div class="jobtext-jobad__metadata">
      <div class="jobtext-jobad__metadata-item">
        <svg class="svg-icon"><title>Virksomhed:</title></svg> Klinik Hedegaard
      </div>
      <div class="jobtext-jobad__metadata-item">
        <svg class="svg-icon"><title>Lokation:</title></svg> K&oslash;benhavn K
      </div>
    </div>
  </header>
  <section class="jobtext-jobad__body">
    <p>Er du jordemoder eller sygeplejerske med ultralydserfaring?</p>
    <p>Klinik Hedegaard er en gyn&aelig;kologisk speciall&aelig;geklinik i
       K&oslash;benhavn med et stort og varieret patientflow.</p>
  </section>
</article>
<div class="jobtext-sidebar-card">
  <h3>Vigtige datoer</h3>
  <dl>
    <dt class="jobtext-sidebar-card__dt">Indrykket:</dt>
    <dd class="jobtext-sidebar-card__dd"><time datetime="2026-11-20">20. november 2026</time></dd>
    <dt class="jobtext-sidebar-card__dt">Ans&oslash;gningsfrist:</dt>
    <dd class="jobtext-sidebar-card__dd"><time datetime="2026-11-30">30. november 2026</time></dd>
  </dl>
</div>
<div class="jobtext-sidebar-card">
  <h3>Virksomheden tilbyder</h3>
  <dl>
    <dt class="jobtext-sidebar-card__dt">Ans&aelig;ttelsestype:</dt>
    <dd class="jobtext-sidebar-card__dd">Fastans&aelig;ttelse</dd>
    <dt class="jobtext-sidebar-card__dt">Hjemmearbejde:</dt>
    <dd class="jobtext-sidebar-card__dd">Tilbydes ikke</dd>
    <dt class="jobtext-sidebar-card__dt">Ugentlig arbejdstid:</dt>
    <dd class="jobtext-sidebar-card__dd">Fuldtid, Deltid (30&ndash;37 timer)</dd>
  </dl>
</div>
</body></html>"""

TEASER_HTML = """<!DOCTYPE html><html><head>
<link rel="canonical" href="https://www.jobindex.dk/vis-job/h1718527">
</head><body>
<div class="jobsearch-result">
  <div class="jix-toolbar-top">
    <div class="jix-toolbar-top__company">Dynatest A/S</div>
  </div>
  <div class="PaidJob-inner">
    <h4>Lead Technician (v&aelig;rkf&oslash;rer) til Production &amp; Service</h4>
    <div class="jobad-element-area"><span class="jix_robotjob--area">Ballerup</span></div>
    <p>Vil du have b&aring;de skruetr&aelig;kkeren og det daglige overblik i h&aelig;nderne?</p>
    <p>Du deltager aktivt i produktion, montage, test og service.</p>
  </div>
</div>
</body></html>"""

TEASER_WITH_CANONICAL_HTML = """<!DOCTYPE html><html><head>
<link href="https://www.jobindex.dk/jobannonce/h1718526/student-assistant" rel="canonical">
</head><body>
<div class="jobsearch-result"><h4>Student Assistant</h4></div>
</body></html>"""

TEASER_NO_AREA_HTML = """<!DOCTYPE html><html><head>
<link rel="canonical" href="https://www.jobindex.dk/vis-job/h1717721">
</head><body>
<div class="jobsearch-result">
  <div class="jix-toolbar-top"><div class="jix-toolbar-top__company">M&amp;J Recycling</div></div>
  <div class="PaidJob-inner">
    <h4>Area Sales Manager</h4>
    <p>Would you like to take ownership of your own sales territory?</p>
  </div>
</div>
</body></html>"""

CUSTOM_LAYOUT_HTML = """<!DOCTYPE html><html><body>
<main>
  <div class="container-xl"><div class="row">
    <div class="col-lg-7 pt-4 pt-lg-0 pe-lg-5 jobcontent">
      <section class="read-more-container"><div class="read-more">
        <p>Har du solid erfaring med pension og sundhed?</p>
        <p>Som Client Leader i Aons nysalgsteam f&aring;r du ansvaret for ny forretning.</p>
        <a class="btn" href="/c?x">Ans&oslash;g</a>
        <span>L&aelig;s mere</span>
      </div></section>
    </div>
  </div></div>
</main>
</body></html>"""

EMPLOYER_LAYOUT_HTML = """<!DOCTYPE html><html><body>
<div id="job" class="container-fluid job-content">
  <div class="container"><div class="row">
    <div class="col-md-12 txt job-box">
      <h1>Student Assistant for Portfolio &amp; Project Excellence</h1>
      <div>Br&oslash;ndby</div>
      <p>Do you want to help bring clarity, structure and better ways of working?</p>
      <h2>About the role</h2>
      <p>At Force Technology, we are technology specialists.</p>
      <div class="jix-info">
        <p><b>Ans&aelig;ttelsestype:</b> Student job</p>
        <p class="mb-0"><b>Hjemmearbejde:</b> Not disclosed</p>
        <p><b>Ugentlig arbejdstid:</b> Part-time (15&ndash;20 hours)</p>
      </div>
      <div class="jix_onlineapplication_button">Apply</div>
    </div>
  </div></div>
</div>
</body></html>"""

JOBTEXT_LAYOUT_HTML = """<!DOCTYPE html><html><body>
<div class="col-lg-6 offset-lg-1 jobtext mb-5">
  <p>Vil du v&aelig;re med til at skabe v&aelig;rdi for kunderne i AP Pension?</p>
  <h2>Om jobbet</h2>
  <p>Som pensionsr&aring;dgiver bliver du en del af et engageret og fagligt dygtigt team.</p>
  <div class="jix-info">
    <p><b>Ans&aelig;ttelsestype:</b> Fastans&aelig;ttelse</p>
    <p><b>Hjemmearbejde:</b> Ikke oplyst</p>
    <p><b>Ugentlig arbejdstid:</b> Fuldtid</p>
  </div>
  <div class="jix_onlineapplication_button">Ans&oslash;g</div>
</div>
</body></html>"""

AREA_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.jobindex.dk/jobsoegning/dragoer</loc></url>
<url><loc>https://www.jobindex.dk/jobsoegning/it</loc></url>
<url><loc>https://www.jobindex.dk/company/123</loc></url>
</urlset>"""


class _Resp:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.status_code = 200


def _raw(
    listing: dict, html: str = FULL_BODY_HTML, page_kind: str = "jobannonce"
) -> RawJobIndexJob:
    return RawJobIndexJob(
        job_id=str(listing["tid"]),
        listing=listing,
        ad_url=f"https://www.jobindex.dk/jobannonce/{listing['tid']}/slug",
        html_content=html,
        page_kind=page_kind,
    )


# --------------------------------------------------------------------------- #
# Ad-link detection
# --------------------------------------------------------------------------- #


class TestJobannoncePath:
    def test_a_matching_escaped_link_is_returned_unescaped(self):
        row = _row("h1716213", link_slug="deltidsjob-i-koebenhavn")
        assert jobannonce_path(row["html"], "h1716213") == (
            "/jobannonce/h1716213/deltidsjob-i-koebenhavn"
        )

    def test_a_robot_feed_id_is_accepted(self):
        row = _row("r14107185", link_slug="lagerarbejde")
        assert jobannonce_path(row["html"], "r14107185") == "/jobannonce/r14107185/lagerarbejde"

    def test_a_different_id_in_the_snippet_is_ignored(self):
        row = _row("h1716213", link_slug="x")
        assert jobannonce_path(row["html"], "h9999999") is None

    @pytest.mark.parametrize("snippet", ["", "<a href=\\/jobannonce\\/reportage>x</a>", "no link"])
    def test_non_ad_or_absent_links_are_rejected(self, snippet):
        assert jobannonce_path(snippet, "h1716213") is None


# --------------------------------------------------------------------------- #
# Stash / listing parsing
# --------------------------------------------------------------------------- #


class TestStashParsing:
    def test_the_stash_object_is_brace_matched_not_regexed(self):
        html = _listing_page([_row("h1", headline="A")])
        stash = extract_stash(html)
        assert "jobsearch/result_app/list" in stash

    def test_listing_results_are_read_structurally(self):
        html = _listing_page([_row("h1", headline="A"), _row("h2", headline="B")])
        rows = listing_results(html)
        assert [r["tid"] for r in rows] == ["h1", "h2"]

    def test_rows_without_a_tid_are_dropped(self):
        html = _listing_page([_row("h1"), {"headline": "no id"}])
        assert [r["tid"] for r in listing_results(html)] == ["h1"]

    def test_a_page_without_a_stash_object_raises(self):
        with pytest.raises(JobIndexParseError, match="var Stash"):
            extract_stash("<html><body>nothing</body></html>")

    def test_an_empty_results_array_is_not_an_error(self):
        assert listing_results(_listing_page([])) == []

    @pytest.mark.parametrize(
        "html",
        [
            '<link rel="canonical" href="https://www.jobindex.dk/jobannonce/h1/slug">',
            '<link href="https://www.jobindex.dk/jobannonce/h1/slug" rel="canonical">',
        ],
    )
    def test_canonical_is_found_in_either_attribute_order(self, html):
        assert canonical_url(html) == "https://www.jobindex.dk/jobannonce/h1/slug"

    def test_no_canonical_link_is_none(self):
        assert canonical_url("<html></html>") is None


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def _stub_client(pages: dict[str, str], sitemap: str = AREA_SITEMAP, **overrides) -> JobIndexClient:
    settings = JobIndexSettings(rate_limit_delay=0, start_offset=0, **overrides)
    client = JobIndexClient(settings)

    def route(url: str) -> _Resp:
        if url.endswith("area.gz"):
            return _Resp(gzip.compress(sitemap.encode("utf-8")))
        return _Resp(pages[url].encode("utf-8"))

    client._request = route  # type: ignore[method-assign]
    return client


class TestDiscovery:
    def test_area_urls_come_from_the_sitemap_and_are_sorted(self):
        client = _stub_client({})
        assert client.area_urls() == [
            "https://www.jobindex.dk/jobsoegning/dragoer",
            "https://www.jobindex.dk/jobsoegning/it",
        ]

    def test_a_plain_xml_sitemap_is_also_read(self):
        client = _stub_client({})
        client._request = lambda url: _Resp(AREA_SITEMAP.encode("utf-8"))
        assert len(client.area_urls()) == 2

    def test_a_sitemapindex_is_rejected(self):
        client = _stub_client({})
        index = "<sitemapindex><sitemap><loc>x</loc></sitemap></sitemapindex>"
        client._request = lambda url: _Resp(index.encode("utf-8"))
        with pytest.raises(JobIndexParseError, match="sitemapindex"):
            client.area_urls()

    def test_a_sitemap_without_area_pages_raises(self):
        client = _stub_client({})
        empty = "<urlset><url><loc>https://www.jobindex.dk/company/1</loc></url></urlset>"
        client._request = lambda url: _Resp(empty.encode("utf-8"))
        with pytest.raises(JobIndexResponseError, match="sitemap shape changed"):
            client.area_urls()

    def test_discover_dedupes_by_tid_and_orders_newest_first(self):
        newest = _listing_page(
            [
                _row("h1716213", headline="A", firstdate="2026-11-20"),
                _row("h1000000", headline="C", firstdate="2026-11-01"),
            ]
        )
        area = _listing_page(
            [
                _row("h1716213", headline="A", firstdate="2026-11-20"),
                _row("h1718527", headline="B", firstdate="2026-11-18"),
            ]
        )
        client = _stub_client(
            {
                "https://www.jobindex.dk/jobsoegning": newest,
                "https://www.jobindex.dk/jobsoegning/dragoer": area,
                "https://www.jobindex.dk/jobsoegning/it": _listing_page([]),
            }
        )
        rows, pages = client.discover()
        assert pages == 3  # newest + 2 area pages
        assert [r["tid"] for r in rows] == ["h1716213", "h1718527", "h1000000"]

    def test_an_empty_board_raises_rather_than_returning_nothing(self):
        client = _stub_client(
            {
                "https://www.jobindex.dk/jobsoegning": _listing_page([]),
                "https://www.jobindex.dk/jobsoegning/dragoer": _listing_page([]),
                "https://www.jobindex.dk/jobsoegning/it": _listing_page([]),
            }
        )
        with pytest.raises(JobIndexResponseError, match="no ads found"):
            client.discover()


# --------------------------------------------------------------------------- #
# Rotating window
# --------------------------------------------------------------------------- #


class TestWindow:
    def _items(self, n: int) -> list[tuple[str, str]]:
        return [(f"u{i}", f"{i:04d}") for i in range(n)]

    def test_a_budget_above_the_board_takes_everything(self):
        client = JobIndexClient(JobIndexSettings(rate_limit_delay=0))
        assert client.select_window(self._items(5), 10) == self._items(5)

    def test_the_newest_rows_are_always_taken(self):
        client = JobIndexClient(JobIndexSettings(rate_limit_delay=0, fresh_rows=3, start_offset=0))
        chosen = client.select_window(self._items(10), 5)
        assert [jid for _, jid in chosen] == ["0000", "0001", "0002", "0003", "0004"]

    def test_the_tail_window_rotates(self):
        client = JobIndexClient(JobIndexSettings(rate_limit_delay=0, fresh_rows=2, start_offset=4))
        chosen = client.select_window(self._items(10), 5)
        assert [jid for _, jid in chosen] == ["0000", "0001", "0006", "0007", "0008"]

    def test_the_window_wraps_around_the_tail(self):
        client = JobIndexClient(JobIndexSettings(rate_limit_delay=0, fresh_rows=0, start_offset=8))
        chosen = client.select_window(self._items(10), 4)
        assert [jid for _, jid in chosen] == ["0008", "0009", "0000", "0001"]

    def test_the_offset_advances_one_window_per_day(self):
        client = JobIndexClient(JobIndexSettings(rate_limit_delay=0))
        today = date.today().toordinal()
        assert client.rotation_offset(1000, 90) == (today * 90) % 1000

    def test_the_offset_can_be_pinned_for_reproducibility(self):
        client = JobIndexClient(JobIndexSettings(rate_limit_delay=0, start_offset=4))
        assert client.rotation_offset(1000, 90) == 4


# --------------------------------------------------------------------------- #
# Ad fetching
# --------------------------------------------------------------------------- #


class TestFetchJob:
    def test_the_snippet_link_is_used_when_present(self):
        client = JobIndexClient(JobIndexSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: FULL_BODY_HTML  # type: ignore[method-assign]
        raw = client.fetch_job(_row("h1716213", link_slug="some-slug", headline="A"))
        assert raw.page_kind == "jobannonce"
        assert raw.ad_url == "https://www.jobindex.dk/jobannonce/h1716213/some-slug"

    def test_the_canonical_link_is_followed_when_the_snippet_has_none(self):
        client = JobIndexClient(JobIndexSettings(rate_limit_delay=0))
        pages = {
            "https://www.jobindex.dk/vis-job/h1718526": TEASER_WITH_CANONICAL_HTML,
            "https://www.jobindex.dk/jobannonce/h1718526/student-assistant": FULL_BODY_HTML,
        }
        client._fetch_html = lambda url: pages[url]  # type: ignore[method-assign]
        raw = client.fetch_job(_row("h1718526", headline="Student Assistant"))
        assert raw.page_kind == "jobannonce"
        assert raw.ad_url == "https://www.jobindex.dk/jobannonce/h1718526/student-assistant"

    def test_a_self_canonical_teaser_stays_a_teaser(self):
        client = JobIndexClient(JobIndexSettings(rate_limit_delay=0))
        client._fetch_html = lambda url: TEASER_HTML  # type: ignore[method-assign]
        raw = client.fetch_job(_row("h1718527", headline="Lead Technician"))
        assert raw.page_kind == "vis_job"
        assert raw.ad_url == "https://www.jobindex.dk/vis-job/h1718527"

    def test_fetch_raw_jobs_applies_the_budget(self):
        rows = [_row("h1", headline="A", link_slug="a"), _row("h2", headline="B", link_slug="b")]
        client = JobIndexClient(JobIndexSettings(rate_limit_delay=0, max_jobs_per_run=1))
        client.discover = lambda: (rows, 1)  # type: ignore[method-assign]
        client._fetch_html = lambda url: FULL_BODY_HTML  # type: ignore[method-assign]
        raws, failures, pages, discovered = client.fetch_raw_jobs()
        assert len(raws) == 1
        assert failures == []
        assert pages == 1
        assert discovered == 2


# --------------------------------------------------------------------------- #
# Employment / remote / dates
# --------------------------------------------------------------------------- #


class TestEmploymentMapping:
    @pytest.mark.parametrize(
        ("employment", "expected"),
        [
            ("Fastansættelse", "full_time"),
            ("Permanent", "full_time"),
            ("Fuldtid", "full_time"),
            ("Full-time", "full_time"),
            ("Deltid", "part_time"),
            ("Studiejob", "part_time"),
            ("Freelance", "freelance"),
            ("Vikariat", "temporary"),
            ("Praktik", "internship"),
            ("Elevplads", "apprenticeship"),
            ("Fastansættelse, Fleksjob", "full_time"),
            ("Fuldtid, Deltid", None),
            ("Freelance, Studiejob", None),
            ("Ikke oplyst", None),
            ("", None),
            (None, None),
        ],
    )
    def test_employment_mapping(self, employment, expected):
        assert map_employment_type(employment) == expected

    def test_weekly_hours_is_the_more_specific_signal(self):
        assert map_employment_type("Permanent", "Deltid (12\u201337 timer)") == "part_time"

    def test_two_different_hours_codes_fall_back_to_the_type(self):
        assert map_employment_type("Fastansættelse", "Fuldtid, Deltid") == "full_time"

    def test_two_different_types_are_ambiguous(self):
        assert map_employment_type("Freelance, Studiejob", None) is None


class TestRemoteMapping:
    @pytest.mark.parametrize(
        ("raw", "home_workplace", "expected"),
        [
            ("100 % hjemmearbejde", False, "remote_country"),
            ("100% remote", False, "remote_country"),
            ("Tilbydes ikke", False, "on_site"),
            ("Ikke oplyst", False, "on_site"),
            ("Not offered", False, "on_site"),
            ("Not disclosed", False, "on_site"),
            ("", False, "on_site"),
            ("", True, "remote_country"),
        ],
    )
    def test_remote_mapping(self, raw, home_workplace, expected):
        assert detect_remote(raw, home_workplace) == expected

    def test_the_card_beats_the_body_text(self):
        assert detect_remote("Ikke oplyst", False, "100% remote anywhere") == "on_site"

    def test_a_global_phrase_in_the_body_is_global(self):
        assert detect_remote("100% remote", False, "open worldwide") == "remote_global"

    def test_a_hybrid_phrase_is_hybrid(self):
        assert detect_remote("", False, "hybrid work possible") == "hybrid"

    def test_the_home_work_area_suffix_is_hybrid(self):
        assert detect_remote("", False, "Nordhavn og mulighed for hjemmearbejde") == "hybrid"


class TestDates:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2026-11-20", datetime(2026, 11, 20)),
            ("2026-11-20T15:55:02+02:00", datetime(2026, 11, 20)),
            ("20. november 2026", datetime(2026, 11, 20)),
            ("30. november 2026", datetime(2026, 11, 30)),
            ("18 November 2026", datetime(2026, 11, 18)),
            ("20/11/2026", datetime(2026, 11, 20)),
            ("Snarest muligt", None),
            ("2026-13-40", None),
            ("", None),
            (None, None),
        ],
    )
    def test_date_shapes(self, value, expected):
        assert parse_date(value) == expected


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


class TestParserFullBody:
    def _job(self, html: str = FULL_BODY_HTML, **row_kwargs):
        fields: dict = {
            "headline": "Uddannet jordemoder eller sygeplejerske",
            "company": "Klinik Hedegaard",
            "firstdate": "2026-11-20",
            "lastdate": "2026-11-30",
            "area": "København K",
            "addresses": [{"city": "København K", "simple_string": "København K"}],
            "listlogo_url": "https://www.jobindex.dk/logo/klinik.png",
        }
        fields.update(row_kwargs)
        return JobIndexParser().parse_job(_raw(_row("h1716213", **fields), html))

    def test_the_contract_is_fully_populated(self):
        job = self._job()
        assert job.source_job_id == "h1716213"
        assert job.job_title == "Uddannet jordemoder eller sygeplejerske"
        assert job.company_name == "Klinik Hedegaard"
        assert job.company_logo_url == "https://www.jobindex.dk/logo/klinik.png"
        assert job.location_cleaned == f"København K, {HOME_COUNTRY}"
        assert job.posting_date == datetime(2026, 11, 20)
        assert job.closing_date == datetime(2026, 11, 30)
        assert job.employment_type_code == "full_time"
        assert job.remote_work_type_code == "on_site"
        assert job.currency_iso_code == "DKK"
        assert job.pay_period == "monthly"
        assert job.description_clean and "gynækologisk" in job.description_clean
        assert job.word_count > 10

    def test_the_full_body_is_flagged(self):
        job = self._job()
        assert job.raw_payload["description_source"] == "jobtext-jobad__body"
        assert job.raw_payload["page_kind"] == "jobannonce"
        assert job.raw_payload["employment_type_raw"] == "Fastansættelse"
        assert job.raw_payload["remote_raw"] == "Tilbydes ikke"

    def test_no_salary_is_invented(self):
        job = self._job()
        assert job.salary_min is None and job.salary_max is None
        assert job.salary_disclosed is False

    def test_a_published_salary_is_read_when_present(self):
        job = self._job(salary={"min": 45000, "max": 55000, "currency": "DKK", "period": "monthly"})
        assert job.salary_min == 45000 and job.salary_max == 55000
        assert job.salary_disclosed is True

    def test_html_entities_in_the_title_are_decoded(self):
        listing = _row("h1716213", headline="Sales Engineer &#8211; Building Materials")
        job = JobIndexParser().parse_job(_raw(listing))
        assert "\u2013" in job.job_title

    def test_a_missing_listing_date_falls_back_to_the_card(self):
        job = self._job(firstdate=None, lastdate=None)
        assert job.posting_date == datetime(2026, 11, 20)
        assert job.closing_date == datetime(2026, 11, 30)

    def test_the_published_application_deadline_beats_the_ad_expiry(self):
        job = self._job(apply_deadline="2026-12-19T22:59:59Z", lastdate="2026-12-17")
        assert job.closing_date == datetime(2026, 12, 19)

    def test_a_closing_date_before_the_posting_is_dropped(self):
        job = self._job(firstdate="2026-12-01")
        assert job.closing_date is None

    def test_no_description_is_none_not_the_title(self):
        html = FULL_BODY_HTML.replace(
            FULL_BODY_HTML[
                FULL_BODY_HTML.index("<section") : FULL_BODY_HTML.index("</section>") + 10
            ],
            "",
        )
        job = self._job(html)
        assert job.description_clean is None
        assert job.word_count == 0

    def test_a_page_without_a_title_is_skipped_not_invented(self):
        listing = _row("h1716213", headline="")
        raw = _raw(listing, "<html><body><p>nothing</p></body></html>")
        assert JobIndexParser().parse_jobs([raw]) == []

    def test_one_bad_page_does_not_drop_the_good_ones(self):
        good_raw = _raw(
            _row("h1716213", headline="Uddannet jordemoder eller sygeplejerske"),
            FULL_BODY_HTML,
        )
        bad = _raw(_row("h9999999", headline=""), "<html><body><p>nothing</p></body></html>")
        jobs = JobIndexParser().parse_jobs([good_raw, bad])
        assert [j.source_job_id for j in jobs] == ["h1716213"]


class TestParserCustomLayout:
    def _job(self, **row_kwargs):
        fields: dict = {
            "headline": "Sales Executive, Pension & Sundhed",
            "company": "Aon Denmark A/S",
            "area": "Nordhavn og mulighed for hjemmearbejde",
            "firstdate": "2026-11-20",
            "lastdate": "2026-11-30",
        }
        fields.update(row_kwargs)
        return JobIndexParser().parse_job(_raw(_row("h1718383", **fields), CUSTOM_LAYOUT_HTML))

    def test_the_custom_layout_body_is_read_from_jobcontent(self):
        job = self._job()
        assert job.raw_payload["description_source"] == "jobcontent"
        assert job.description_clean and "pension" in job.description_clean
        assert job.word_count > 10
        assert job.data_quality_score == 0.85

    def test_the_trailing_call_to_action_is_not_part_of_the_body(self):
        job = self._job()
        assert "Ansøg" not in job.description_clean
        assert "Læs mere" not in job.description_clean

    def test_the_home_work_suffix_is_a_hybrid_signal_not_a_place(self):
        job = self._job()
        assert job.location_cleaned == f"Nordhavn, {HOME_COUNTRY}"
        assert job.remote_work_type_code == "hybrid"

    def test_a_parenthesised_home_work_suffix_is_stripped_too(self):
        listing = _row(
            "h1718508",
            area="Vejle eller Odense SØ (og mulighed for hjemmearbejde)",
        )
        assert build_location(listing, "", "hybrid") == f"Vejle eller Odense SØ, {HOME_COUNTRY}"


class TestParserEmployerLayout:
    def test_the_job_box_body_is_clean_and_the_jix_info_is_not_in_it(self):
        listing = _row("h1718526", headline="Student Assistant", company="Force Technology")
        job = JobIndexParser().parse_job(_raw(listing, EMPLOYER_LAYOUT_HTML))
        assert job.raw_payload["description_source"] == "jobcontent"
        assert job.description_clean and "clarity" in job.description_clean
        assert "Ansættelsestype" not in job.description_clean
        assert "Apply" not in job.description_clean
        assert "Brøndby" not in job.description_clean

    def test_the_jix_info_block_supplies_employment_and_remote(self):
        listing = _row("h1718526", headline="Student Assistant", company="Force Technology")
        job = JobIndexParser().parse_job(_raw(listing, EMPLOYER_LAYOUT_HTML))
        assert job.employment_type_code == "part_time"
        assert job.remote_work_type_code == "on_site"
        assert job.raw_payload["offers"]["ansættelsestype"] == "Student job"

    def test_the_jobtext_container_is_also_read(self):
        listing = _row(
            "h1718289", headline="AP Pension søger pensionsrådgiver", company="AP Pension"
        )
        job = JobIndexParser().parse_job(_raw(listing, JOBTEXT_LAYOUT_HTML))
        assert job.raw_payload["description_source"] == "jobcontent"
        assert job.description_clean and "pensionsrådgiver" in job.description_clean
        assert "Ansøg" not in job.description_clean
        assert job.employment_type_code == "full_time"


class TestParserTeaser:
    def test_a_teaser_is_stored_and_flagged(self):
        listing = _row("h1718527", headline="Lead Technician")
        job = JobIndexParser().parse_job(_raw(listing, TEASER_HTML, page_kind="vis_job"))
        assert job.source_job_id == "h1718527"
        assert job.raw_payload["description_source"] == "vis_job_teaser"
        assert job.raw_payload["page_kind"] == "vis_job"
        assert job.description_clean and "skruetrækkeren" in job.description_clean
        assert job.employment_type_code is None

    def test_the_teaser_page_fills_company_and_area(self):
        listing = _row("h1718527", headline="Lead Technician")
        job = JobIndexParser().parse_job(_raw(listing, TEASER_HTML, page_kind="vis_job"))
        assert job.company_name == "Dynatest A/S"
        assert job.location_cleaned == f"Ballerup, {HOME_COUNTRY}"

    def test_a_home_workplace_teaser_with_no_area_is_remote(self):
        listing = _row("h1717721", headline="Area Sales Manager", home_workplace=True)
        job = JobIndexParser().parse_job(_raw(listing, TEASER_NO_AREA_HTML, page_kind="vis_job"))
        assert job.remote_work_type_code == "remote_country"
        assert job.location_cleaned == f"Remote, {HOME_COUNTRY}"
        assert job.company_name == "M&J Recycling"


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


class TestPipelineDryRun:
    class _Client:
        def __init__(self, raws, discovered=1, pages=1):
            self.raws = raws
            self.discovered = discovered
            self.pages = pages

        def fetch_raw_jobs(self, max_jobs=None):
            return self.raws, [], self.pages, self.discovered

    def test_a_dry_run_parses_without_persisting(self):
        listing = _row("h1716213", headline="Uddannet jordemoder")
        client = self._Client([_raw(listing)], discovered=25, pages=3)
        result = JobIndexPipeline(settings=JobIndexSettings(rate_limit_delay=0), client=client).run(
            store_db=False
        )
        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.cleaned_count == 1
        assert result.validation_passed is True
        assert result.discovered_count == 25
        assert result.pages_scraped == 3
        assert result.session_id is None

    def test_no_rows_fetched_is_reported_not_a_silent_success(self):
        client = self._Client([], discovered=0, pages=1)
        result = JobIndexPipeline(settings=JobIndexSettings(rate_limit_delay=0), client=client).run(
            store_db=False
        )
        assert result.validation_passed is False
        assert result.parsed_count == 0
        assert result.issues
