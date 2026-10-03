"""Unit tests for job_market_intel.scrapers.indeed.parser.

Fixtures below are shaped to match real Indeed markup, confirmed from an
actual captured search-results page (title node structure, id="job_<jk>"
on the title anchor, company-name/text-location data-testids, and the
detail-page description container) — not the earlier, wrong guesses these
tests originally shipped with. See parser.py's own inline notes for which
parts of the fixture are confirmed vs. still-best-effort (sponsored
marker, salary/job-type metadata).
"""

from __future__ import annotations

from job_market_intel.scrapers.indeed.parser import parse_detail_page, parse_search_page

_ORGANIC_CARD = """
<div class="job_seen_beacon">
  <table><tbody><tr><td class="resultContent">
    <div>
      <h3 class="jobTitle css-1o1rnx9 eu4oa1w0">
        <a id="job_aabbccdd11223344" class="jcs-JobTitle"
           href="/rc/clk?jk=aabbccdd11223344&amp;bb=abc123">Backend Engineer</a>
      </h3>
    </div>
    <div>
      <span data-testid="company-name">Acme Corp</span>
      <div data-testid="text-location">Austin, TX</div>
    </div>
    <div class="jobMetaDataGroup">
      <ul class="metadataContainer">
        <li>$90,000 - $120,000 a year</li>
        <li>Full-time</li>
      </ul>
    </div>
  </td></tr></tbody></table>
</div>
"""

_SPONSORED_CARD = """
<div class="job_seen_beacon">
  <table><tbody><tr><td class="resultContent">
    <div>
      <h3 class="jobTitle css-1o1rnx9 eu4oa1w0">Data Analyst</h3>
    </div>
    <span>Sponsored</span>
    <span data-testid="company-name">Globex</span>
    <div data-testid="text-location">Remote</div>
    <a href="/pagead/clk?mo=r&amp;ad=xyz">Apply</a>
  </td></tr></tbody></table>
</div>
"""

_MALFORMED_CARD = """
<div class="job_seen_beacon">
  <span data-testid="company-name">No Title Inc</span>
</div>
"""


class TestParseSearchPage:
    def test_organic_card_parses_with_detail_url(self) -> None:
        jobs = parse_search_page(
            f"<html><body>{_ORGANIC_CARD}</body></html>",
            query_text="backend engineer",
            location_text="Austin, TX",
            search_page_number=1,
        )
        assert len(jobs) == 1
        job = jobs[0]
        assert job.job_title == "Backend Engineer"
        assert job.company_name == "Acme Corp"
        assert job.source_job_id == "aabbccdd11223344"
        assert job.detail_url == "https://www.indeed.com/viewjob?jk=aabbccdd11223344"
        assert job.is_sponsored is False
        assert job.query_text == "backend engineer"
        assert job.search_page_number == 1
        assert job.raw_payload["metadata_items"] == ["$90,000 - $120,000 a year", "Full-time"]

    def test_job_key_comes_from_anchor_id_not_href(self) -> None:
        # The id="job_<jk>" attribute is preferred over parsing the
        # tracking-heavy href — confirm it's actually being used, not
        # just coincidentally matching via the href fallback.
        card = _ORGANIC_CARD.replace('id="job_aabbccdd11223344"', 'id="job_ffffffffffffffff"')
        jobs = parse_search_page(
            f"<html><body>{card}</body></html>",
            query_text="q",
            location_text="l",
            search_page_number=1,
        )
        assert jobs[0].source_job_id == "ffffffffffffffff"

    def test_sponsored_card_parses_without_detail_url(self) -> None:
        jobs = parse_search_page(
            f"<html><body>{_SPONSORED_CARD}</body></html>",
            query_text="data analyst",
            location_text="Remote",
            search_page_number=1,
        )
        assert len(jobs) == 1
        job = jobs[0]
        assert job.is_sponsored is True
        assert job.detail_url is None
        # Synthetic id derived from title+company+location — see parser.py.
        assert job.source_job_id.startswith("sponsored:")

    def test_malformed_card_is_skipped_not_raised(self) -> None:
        jobs = parse_search_page(
            f"<html><body>{_MALFORMED_CARD}</body></html>",
            query_text="anything",
            location_text="anywhere",
            search_page_number=1,
        )
        assert jobs == []

    def test_multiple_cards_one_bad_one_good(self) -> None:
        html = f"<html><body>{_ORGANIC_CARD}{_MALFORMED_CARD}</body></html>"
        jobs = parse_search_page(html, query_text="q", location_text="l", search_page_number=2)
        assert len(jobs) == 1
        assert jobs[0].job_title == "Backend Engineer"

    def test_no_cards_returns_empty_list(self) -> None:
        jobs = parse_search_page(
            "<html><body>no results</body></html>",
            query_text="q",
            location_text="l",
            search_page_number=1,
        )
        assert jobs == []

    def test_raw_payload_carries_extracted_fields(self) -> None:
        jobs = parse_search_page(
            f"<html><body>{_ORGANIC_CARD}</body></html>",
            query_text="q",
            location_text="l",
            search_page_number=1,
        )
        assert jobs[0].raw_payload["is_sponsored"] is False
        assert jobs[0].raw_payload["job_title"] == "Backend Engineer"


class TestParseDetailPage:
    def test_extracts_description_text(self) -> None:
        html = (
            '<html><body><div class="react-native-html-content simple-job-description-html">'
            "<p>We are looking for a great engineer.</p>"
            "<p>5+ years experience required.</p>"
            "</div></body></html>"
        )
        description = parse_detail_page(html)
        assert description is not None
        assert "great engineer" in description
        assert "5+ years experience" in description

    def test_missing_description_container_returns_none(self) -> None:
        assert parse_detail_page("<html><body>nothing here</body></html>") is None

    def test_empty_description_container_returns_none(self) -> None:
        html = (
            '<html><body><div class="react-native-html-content '
            'simple-job-description-html">   </div></body></html>'
        )
        assert parse_detail_page(html) is None
