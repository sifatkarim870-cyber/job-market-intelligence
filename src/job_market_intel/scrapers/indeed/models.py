"""Raw Indeed job record.

Unlike RemoteOK/Remotive/WWR, there's no raw JSON/XML payload with its own
field names to alias against — parser.py builds this directly from strings
pulled out of rendered HTML via BeautifulSoup. So no ``Field(alias=...)``
here; field names are just the sensible Python names, and validation is
about normalizing messy scraped text (stray whitespace, "N/A"-style
placeholders) rather than reconciling a third party's schema.

description_raw is Optional and only populated when the pipeline actually
visited the job's detail page (organic results, within
``max_detail_pages_per_session``) — sponsored cards, and organic cards
skipped once the session's detail-page cap is hit, are stored with
description_raw=None and whatever the search card itself carried. That
partial record is still stored (per "scrape everything possible" — a
card-level record is strictly more than nothing), and cleaning/validation
downstream must tolerate a missing description rather than reject the
record.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def _clean_text(value: str | None) -> str | None:
    """Collapse whitespace and treat empty/placeholder text as absent.

    Indeed's rendered cards routinely contain stray "\\xa0", doubled
    spaces from collapsed inline elements, and the literal text "N/A" or
    "—" where a field (usually salary) wasn't disclosed.
    """
    if value is None:
        return None
    collapsed = " ".join(value.split())
    if collapsed in {"", "N/A", "—", "-"}:
        return None
    return collapsed


class RawIndeedJob(BaseModel):
    """A single job record as extracted from an Indeed search card, with an
    optional full description merged in from the detail page.

    Attributes:
        source_job_id: Indeed's own job key (the ``jk`` query-param value
            from a ``/viewjob?jk=...`` link) for organic results. Sponsored
            cards have no stable ``jk`` — see ``is_sponsored`` — so
            parser.py derives a synthetic id for those instead (documented
            on the parser).
        job_title: As shown on the card.
        company_name: As shown on the card.
        location_raw: The card's location text verbatim, including Indeed's
            own phrasing (e.g. "Hybrid work in Austin, TX", "Remote").
            Geographic parsing happens downstream in
            ``normalization/geographic_resolution.py``, same as the other
            three sources — this field is intentionally unparsed.
        salary_text: Raw salary text verbatim (e.g. "$77,322.59 -
            $93,119.67 a year", "$45 - $47 an hour"), or None if Indeed
            didn't disclose one on the card. Deliberately left as raw text
            rather than parsed into min/max/period here — Indeed shows
            multiple pay periods (yearly, hourly, per-project), which
            cleaning/indeed_cleaner.py's docstring flags as a real, not yet
            fully resolved, gap against job_repository.py's
            _ASSUMED_PAY_PERIOD/_ASSUMED_CURRENCY_ISO_CODE constants.
        employment_type_text: Raw badge text (e.g. "Full-time", "Contract"),
            or None.
        is_sponsored: Whether the card was a sponsored/ad listing (links
            through ``/pagead/clk?...``) rather than an organic result.
            Confirmed decision: sponsored cards are stored at card-level
            only — the ad-redirect is never followed.
        is_easy_apply: Whether the card carried Indeed's "Easily apply"
            badge.
        posted_text: Raw "posted" badge text (e.g. "New", "Posted 3 days
            ago"), or None.
        benefits: Benefit strings as listed on the card, verbatim (mapped
            to ref.benefits downstream the same way the other sources'
            cleaners already do).
        detail_url: The job's ``/viewjob?jk=...`` URL, or None for
            sponsored cards (which have no such URL to visit).
        description_raw: Full description text, only present when the
            detail page was actually visited this run.
        query_text / location_text / search_page_number: The
            ``ops.scrape_query_queue`` row and page this record came from —
            carried through for traceability and left off of
            ``CleanedJob``/``core.jobs`` (which has no such column); useful
            for debugging a bad parse without re-running the scraper.
        raw_payload: The extracted-but-uncleaned field values as a plain
            dict, per this project's "never discard original source data"
            principle (mirrors every other source's raw_payload field).
            This is also where ``employment_type_text``, ``benefits``,
            ``is_sponsored``, ``is_easy_apply``, and ``posted_text`` end up
            preserved even though ``CleanedJob`` (cleaning/common.py) has
            no field for any of them today — flagged, not silently
            dropped: promoting them onto ``core.jobs.employment_type_id``
            / ``bridge.job_benefits`` is future work this delivery
            deliberately doesn't take on. See indeed_cleaner.py's module
            docstring.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    source_job_id: str
    job_title: str
    company_name: str
    location_raw: str | None = None
    salary_text: str | None = None
    employment_type_text: str | None = None
    is_sponsored: bool = False
    is_easy_apply: bool = False
    posted_text: str | None = None
    benefits: list[str] = []
    detail_url: str | None = None
    description_raw: str | None = None

    query_text: str
    location_text: str
    search_page_number: int
    raw_payload: dict[str, Any] = {}

    @field_validator(
        "location_raw",
        "salary_text",
        "employment_type_text",
        "posted_text",
        "description_raw",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            return _clean_text(value)
        return value

    @field_validator("job_title", "company_name", mode="before")
    @classmethod
    def _require_normalized_text(cls, value: object) -> object:
        # job_title/company_name are required — collapse whitespace but
        # never silently convert to None the way optional fields do.
        # A genuinely empty title/company should fail validation loudly
        # (parser.py catches this per-record, same skip-and-log posture
        # as the other three scrapers) rather than produce a hollow record.
        if isinstance(value, str):
            return " ".join(value.split())
        return value

    @field_validator("benefits", mode="before")
    @classmethod
    def _normalize_benefits(cls, value: object) -> object:
        if isinstance(value, list):
            cleaned = [_clean_text(item) for item in value if isinstance(item, str)]
            return [item for item in cleaned if item]
        return value
