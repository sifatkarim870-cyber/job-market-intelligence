"""Parses rendered Indeed HTML into RawIndeedJob records.

Mirrors the other three scrapers' parser.py role (raw page -> validated
Pydantic model, skip-and-log per record on a ValidationError/ParseError so
one broken card never aborts a whole page) but works off rendered HTML via
BeautifulSoup instead of a JSON/XML payload, since that's what a Selenium
session actually produces.

Selector honesty note, per this project's own fragility expectations:
Indeed changes its markup periodically (a known, expected failure mode --
see pipeline.py). The `data-testid` attributes used below are the more
stable signal Indeed itself has used for years, preferred here over CSS
class names (which are frequently auto-generated/obfuscated). Even so,
these selectors are only as good as the page structure observed during
this scraper's diligence and WILL need re-verification against a live
`uv run python scripts/run_indeed_scraper.py --no-db` before this is
considered working, not just written.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from job_market_intel.scrapers.indeed.exceptions import IndeedParseError
from job_market_intel.scrapers.indeed.models import RawIndeedJob

logger = logging.getLogger(__name__)

_JK_PATTERN = re.compile(r"[?&]jk=([a-f0-9]+)")
#: The <a> wrapping a job title carries its own id="job_<jobkey>" — a
#: cleaner, tracking-noise-free way to get the job key than parsing the
#: href (which now routes through /rc/clk?jk=...&bb=...&xkcb=... rather
#: than a bare /viewjob? link). Confirmed against a real captured page;
#: _extract_job_key(href) below is kept as a fallback for whichever of the
#: two is present.
_JOB_ID_ATTR_PATTERN = re.compile(r"^job_([a-f0-9]+)$")


def _find_by_testid(node: Tag, testid: str) -> Tag | None:
    """card.find(attrs={"data-testid": testid}), isolated to one place.

    bs4 4.15's own bundled type stubs overload find() such that a plain
    dict[str, str] literal doesn't structurally match any overload's attrs
    parameter (each expects a broader union type, and mypy's dict
    invariance means a concrete dict[str, str] isn't accepted even though
    every value in it is a valid member of that union) - a stub-precision
    issue, not a real type error: this is bs4's own documented, correct
    runtime usage. Suppressed once, here, rather than at each of the six
    call sites this used to be duplicated across.
    """
    node_or_string = node.find(attrs={"data-testid": testid})  # type: ignore[call-overload]
    return node_or_string if isinstance(node_or_string, Tag) else None


def _extract_job_key(href: str) -> str | None:
    match = _JK_PATTERN.search(href)
    return match.group(1) if match else None


def _extract_job_key_from_id(id_value: object) -> str | None:
    if not isinstance(id_value, str):
        return None
    match = _JOB_ID_ATTR_PATTERN.match(id_value)
    return match.group(1) if match else None


def _card_text(card: Tag, testid: str) -> str | None:
    node = _find_by_testid(card, testid)
    return node.get_text(" ", strip=True) if node is not None else None


def _card_benefits(card: Tag) -> list[str]:
    container = _find_by_testid(card, "benefits-test")
    if container is None:
        return []
    return [
        li.get_text(" ", strip=True) for li in container.find_all("li") if li.get_text(strip=True)
    ]


def _card_metadata_items(card: Tag) -> list[str]:
    """Text of each <li> in the card's real metadata list (confirmed
    location: <ul class="metadataContainer"> inside <div
    class="jobMetaDataGroup">) — this is likely where job type and
    sometimes salary actually render, based on the real captured page's
    structure, but every card in that specific capture had this list
    empty, so which li corresponds to which field is not yet confirmed.
    Returned as a flat raw list here rather than guessed apart into
    salary_text/employment_type_text.
    """
    container = card.find("ul", class_=re.compile(r"\bmetadataContainer\b"))
    if container is None:
        return []
    return [
        li.get_text(" ", strip=True) for li in container.find_all("li") if li.get_text(strip=True)
    ]


def parse_search_page(
    html: str,
    *,
    query_text: str,
    location_text: str,
    search_page_number: int,
) -> list[RawIndeedJob]:
    """Parse one rendered search-results page into card-level records
    (description_raw is always None here — filled in later, per job, by
    the pipeline visiting detail pages within its session cap).

    A single card that doesn't validate is logged and skipped; it never
    aborts parsing of the rest of the page.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("div", attrs={"class": re.compile(r"\bjob_seen_beacon\b")})

    records: list[RawIndeedJob] = []
    for card in cards:
        try:
            records.append(
                _parse_card(
                    card,
                    query_text=query_text,
                    location_text=location_text,
                    search_page_number=search_page_number,
                )
            )
        except (IndeedParseError, ValidationError):
            logger.warning(
                "indeed.parser.skip_card query=%r location=%r page=%d",
                query_text,
                location_text,
                search_page_number,
                exc_info=True,
            )
            continue

    logger.info(
        "indeed.parser.search_page cards_found=%d cards_parsed=%d page=%d",
        len(cards),
        len(records),
        search_page_number,
    )
    return records


def _parse_card(
    card: Tag,
    *,
    query_text: str,
    location_text: str,
    search_page_number: int,
) -> RawIndeedJob:
    # Confirmed against a real captured page: Indeed does not put a
    # data-testid on the title element at all. It's an <h3 class="jobTitle
    # ...">, not <h2> (the old fallback also missed it). This was the bug
    # causing every single card to fail on the first live run.
    title_node = card.find(class_=re.compile(r"\bjobTitle\b"))
    if title_node is None:
        raise IndeedParseError("card missing a title node")
    job_title = title_node.get_text(" ", strip=True)

    link_node = title_node.find("a", href=True) or card.find("a", href=True)
    href_value = link_node.get("href") if link_node is not None else None
    href = href_value if isinstance(href_value, str) else ""
    id_value = link_node.get("id") if link_node is not None else None

    # Not confirmed against real data: this capture had zero sponsored
    # cards to check the marker against, so this text-based check is a
    # reasonable guess, not a verified selector — revisit once a real run
    # actually hits a sponsored listing.
    is_sponsored = card.find(string=re.compile(r"^\s*Sponsored\s*$")) is not None

    job_key = _extract_job_key_from_id(id_value) or _extract_job_key(href)

    if job_key is not None:
        source_job_id = job_key
        detail_url = f"https://www.indeed.com/viewjob?jk={job_key}"
    elif is_sponsored:
        # Sponsored cards have no stable jk — Indeed's own /pagead/clk
        # redirect is the only link, and per the confirmed decision it's
        # never followed. Derive a synthetic id instead of dropping the
        # record: title+company+location is stable enough across a single
        # page render to dedupe against re-parses of the same page, and
        # job_repository's own (source_id, source_job_id) uniqueness check
        # handles a genuine re-scrape sensibly either way.
        company_node = _find_by_testid(card, "company-name")
        company_text = company_node.get_text(" ", strip=True) if company_node else ""
        location_node = _find_by_testid(card, "text-location")
        location_text_raw = location_node.get_text(" ", strip=True) if location_node else ""
        source_job_id = f"sponsored:{job_title}:{company_text}:{location_text_raw}"
        detail_url = None
    else:
        raise IndeedParseError("organic card has no extractable jk and isn't sponsored")

    company_name = _card_text(card, "company-name") or ""
    location_raw = _card_text(card, "text-location")
    # NOT CONFIRMED against real data — these testid strings don't exist
    # anywhere in the captured page used to fix the title bug above, but
    # that capture also had zero cards with a visible salary/job-type
    # badge to check the real selector against. Left as literal
    # placeholders (harmless: _card_text() returns None when not found,
    # same as before) rather than guessing a replacement with no evidence
    # either way. metadata_items below captures the real container's raw
    # text once populated, for whenever a sample with salary shown turns
    # up.
    salary_text = _card_text(card, "attribute_snippet_testid")
    employment_type_text = _card_text(card, "attribute_snippet_testid_2")
    is_easy_apply = bool(card.find(string=re.compile("Easily apply", re.IGNORECASE)))
    posted_text = _card_text(card, "myJobsStateDate")
    benefits = _card_benefits(card)  # NOT CONFIRMED either — see above.
    metadata_items = _card_metadata_items(card)

    return RawIndeedJob(
        source_job_id=source_job_id,
        job_title=job_title,
        company_name=company_name,
        location_raw=location_raw,
        salary_text=salary_text,
        employment_type_text=employment_type_text,
        is_sponsored=is_sponsored,
        is_easy_apply=is_easy_apply,
        posted_text=posted_text,
        benefits=benefits,
        detail_url=detail_url,
        description_raw=None,
        query_text=query_text,
        location_text=location_text,
        search_page_number=search_page_number,
        raw_payload={
            "job_title": job_title,
            "company_name": company_name,
            "location_raw": location_raw,
            "salary_text": salary_text,
            "employment_type_text": employment_type_text,
            "is_sponsored": is_sponsored,
            "is_easy_apply": is_easy_apply,
            "posted_text": posted_text,
            "benefits": benefits,
            "detail_url": detail_url,
            "metadata_items": metadata_items,
        },
    )


def parse_detail_page(html: str) -> str | None:
    """Extract full description text from a rendered job-detail page/panel.

    Returns None (rather than raising) when the description container
    isn't found — a missing description on a detail page that did load
    successfully is a partial-data situation, not a fatal one; the record
    keeps whatever card-level fields it already has.
    """
    soup = BeautifulSoup(html, "html.parser")
    # Confirmed against a real captured page: Indeed no longer uses
    # id="jobDescriptionText" (that selector matched nothing at all).
    # The real container is a div carrying both of these classes.
    container = soup.find(
        "div", class_=re.compile(r"\breact-native-html-content\b.*\bsimple-job-description-html\b")
    ) or soup.find("div", class_=re.compile(r"\bsimple-job-description-html\b"))
    if container is None:
        return None
    text = container.get_text("\n", strip=True)
    return text or None
