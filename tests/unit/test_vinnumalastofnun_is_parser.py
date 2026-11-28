"""Unit tests for the Vinnumalastofnun (Iceland) scraper.

No network and no database: every test drives the pure mapping helpers or a
synthetic list-item + detail pair built from the shapes measured on
2026-11-28. The fixtures are constructed here, not copied from a live
response, so the tests describe the contract rather than one capture.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from job_market_intel.scrapers.vinnumalastofnun_is import (
    VinnumalastofnunIsClient,
    VinnumalastofnunIsSettings,
)
from job_market_intel.scrapers.vinnumalastofnun_is.exceptions import (
    VinnumalastofnunIsParseError,
)
from job_market_intel.scrapers.vinnumalastofnun_is.models import (
    RawVinnumalastofnunIsJob,
)
from job_market_intel.scrapers.vinnumalastofnun_is.parser import (
    VinnumalastofnunIsParser,
    build_location,
    card_intro_text,
    clean_text,
    map_employment_type,
    normalize_description,
    parse_date,
    rich_text_to_text,
    split_title_company,
    work_percentage,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _document(*paragraphs: str) -> dict:
    return {
        "nodeType": "document",
        "content": [
            {
                "nodeType": "paragraph",
                "content": [{"nodeType": "text", "value": text}],
            }
            for text in paragraphs
        ],
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-12-31", datetime(2026, 12, 31)),
        ("2027-02-16", datetime(2027, 2, 16)),
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_date(raw: object, expected: datetime | None) -> None:
    assert parse_date(raw) == expected


def test_rich_text_to_text_walks_blocks_and_hyperlinks() -> None:
    document = {
        "nodeType": "document",
        "content": [
            {
                "nodeType": "paragraph",
                "content": [
                    {"nodeType": "text", "value": "Apply at "},
                    {
                        "nodeType": "hyperlink",
                        "data": {"uri": "https://example.is"},
                        "content": [{"nodeType": "text", "value": "our site"}],
                    },
                    {"nodeType": "text", "value": "."},
                ],
            },
            {
                "nodeType": "list-item",
                "content": [{"nodeType": "text", "value": "Full time"}],
            },
        ],
    }
    text = rich_text_to_text(document)
    assert "Apply at our site." in text
    assert "Full time" in text
    assert text.count("\n") >= 1


def test_rich_text_to_text_tolerates_non_documents() -> None:
    assert rich_text_to_text(None) == ""
    assert rich_text_to_text("not a dict") == ""


def test_normalize_description_collapses_whitespace_and_blank_lines() -> None:
    raw = "Line one\r\n\r\n\r\nLine two   with   spaces"
    text = normalize_description(raw)
    assert "\r" not in text
    assert text == "Line one\n\nLine two with spaces"


def test_clean_text_collapses_to_one_line() -> None:
    assert clean_text("  DH   veitingar\nehf. \n") == "DH veitingar ehf."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100", 100),
        ("90", 90),
        ("10", 10),
        ("eures", None),
        (None, None),
    ],
)
def test_work_percentage(raw: object, expected: int | None) -> None:
    item = {"filterTags": [{"slug": raw, "title": str(raw)}] if raw else []}
    assert work_percentage(item) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (100, "full_time"),
        (90, "part_time"),
        (50, "part_time"),
        (None, None),
    ],
)
def test_map_employment_type(raw: int | None, expected: str | None) -> None:
    assert map_employment_type(raw) == expected


def test_build_location_uses_the_region_tag_then_the_country() -> None:
    with_region = {
        "filterTags": [
            {"title": "Höfuðborgarsvæðið", "slug": "hoefudborgarsvaedid"},
            {"title": "100%", "slug": "100"},
        ]
    }
    assert build_location(with_region) == "Höfuðborgarsvæðið; IS"
    assert build_location({"filterTags": [{"title": "Eures", "slug": "eures"}]}) == "IS"
    assert build_location({}) == "IS"


@pytest.mark.parametrize(
    ("title", "abroad", "expected"),
    [
        ("Kokkur / Chef - DH veitingar ehf.", False, ("Kokkur / Chef", "DH veitingar ehf.")),
        (
            "Chef - Vietnamese Cuisine - Down Town ehf.",
            False,
            ("Chef - Vietnamese Cuisine", "Down Town ehf."),
        ),
        (
            "Experienced Bicycle Mechanics - Ride On Bike AS - Norway",
            True,
            ("Experienced Bicycle Mechanics", "Ride On Bike AS"),
        ),
        (
            "Concrete Formwork Carpenter - Aldelia Sweden AB",
            True,
            ("Concrete Formwork Carpenter", "Aldelia Sweden AB"),
        ),
        ("Solo role", False, ("Solo role", "")),
        ("", False, ("", "")),
    ],
)
def test_split_title_company(title: str, abroad: bool, expected: tuple[str, str]) -> None:
    assert split_title_company(title, abroad=abroad) == expected


def test_card_intro_text_flattens_every_block() -> None:
    item = {
        "cardIntro": [
            {"document": _document("We are looking for an experienced Nail Technician.")},
            {"document": _document("Join our team.")},
        ]
    }
    text = card_intro_text(item)
    assert "experienced Nail Technician" in text
    assert "Join our team." in text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "Fine Restaurant í Reykjavík leitar að reyndum matreiðslumanni með góða þekkingu "
    "á kínverskri matargerð.\n\n"
    "Helstu verkefni:\nUndirbúningur og matreiðsla kínverskra rétta samkvæmt matseðli.\n"
    "Matreiðsla með wok-pönnu og notkun viðeigandi eldunaraðferða.\n\n"
    "Laun og starfskjör samkvæmt gildandi kjarasamningi."
)


def _tags(*pairs: tuple[str, str]) -> list[dict]:
    return [
        {"id": f"tag-{index}", "title": title, "slug": slug, "__typename": "GenericTag"}
        for index, (title, slug) in enumerate(pairs)
    ]


def _list_item(**overrides: object) -> dict:
    item: dict = {
        "id": "37AfGWDNqeeFH60F5Pfanh",
        "date": "2026-12-31",
        "title": "Kokkur / Chef - DH veitingar ehf.",
        "cardIntro": [
            {
                "__typename": "Html",
                "id": "37AfGWDNqeeFH60F5Pfanh:cardIntro:0",
                "document": _document("Fine Restaurant leitar að reyndum matreiðslumanni."),
            }
        ],
        "filterTags": _tags(
            ("100%", "100"),
            ("Höfuðborgarsvæðið", "hoefudborgarsvaedid"),
            ("Eures", "eures"),
        ),
        "slug": "kokkur-chef-dh-veitingar-ehf-31-12-2026",
        "assetUrl": "",
        "externalUrl": "",
        "image": None,
        "__typename": "GenericListItem",
    }
    item.update(overrides)
    return item


_UNSET = object()

#: Pinned so the closing-date guard is deterministic: the board's date is the
#: application deadline, and a deadline before the scrape day is not stored as
#: a closing date (core.jobs requires closing_date >= posting_date, and a missing
#: posting_date is filled with the scrape day).
_TODAY = date(2026, 11, 28)


def _raw(detail: object = _UNSET, **overrides: object) -> RawVinnumalastofnunIsJob:
    payload: dict = {
        "job_id": "37AfGWDNqeeFH60F5Pfanh",
        "slug": "kokkur-chef-dh-veitingar-ehf-31-12-2026",
        "url": (
            "https://island.is/s/vinnumalastofnun/laus-storf/"
            "kokkur-chef-dh-veitingar-ehf-31-12-2026"
        ),
        "list_position": 0,
        "list_total": 26,
        "list_item": _list_item(),
        "detail": {"body": _DESCRIPTION} if detail is _UNSET else detail,
    }
    payload.update(overrides)
    return RawVinnumalastofnunIsJob(**payload)


# ---------------------------------------------------------------------------
# Vacancy parsing
# ---------------------------------------------------------------------------


def _parse(raw: RawVinnumalastofnunIsJob):  # noqa: ANN202 - test helper
    return VinnumalastofnunIsParser().parse_job(raw, today=_TODAY)


def test_parse_job_maps_a_complete_vacancy() -> None:
    job = _parse(_raw())

    assert job.source_job_id == "37AfGWDNqeeFH60F5Pfanh"
    assert job.job_title == "Kokkur / Chef"
    assert job.company_name == "DH veitingar ehf."
    assert job.company_logo_url is None
    assert job.location_cleaned == "Höfuðborgarsvæðið; IS"
    assert job.salary_disclosed is False
    assert (job.currency_iso_code, job.pay_period) == ("ISK", "monthly")
    assert job.employment_type_code == "full_time"
    assert job.posting_date is None
    assert job.closing_date == datetime(2026, 12, 31)
    assert job.apply_url == job.original_url
    assert job.raw_payload["description_source"] == "content"
    assert job.raw_payload["work_percentage"] == 100
    assert job.word_count > 10


def test_parse_job_falls_back_to_the_card_intro_without_a_detail() -> None:
    job = _parse(_raw(detail=None))

    assert job.raw_payload["description_source"] == "card_intro"
    assert "reyndum matreiðslumanni" in (job.description_clean or "")
    assert job.job_title == "Kokkur / Chef"
    assert job.company_name == "DH veitingar ehf."


def test_parse_job_builds_a_structured_summary_when_both_bodies_are_thin() -> None:
    item = _list_item(cardIntro=[])
    job = _parse(_raw(detail={"body": ""}, list_item=item))

    assert job.raw_payload["description_source"] == "structured_summary"
    assert "Vinnumalastofnun" in (job.description_clean or "")
    assert "Kokkur / Chef - DH veitingar ehf." in (job.description_clean or "")
    assert job.data_quality_score <= 0.6


def test_parse_job_maps_a_less_than_full_ratio_to_part_time() -> None:
    item = _list_item(filterTags=_tags(("80%", "80"), ("Vesturland", "vesturlandi")))
    job = _parse(_raw(list_item=item))

    assert job.employment_type_code == "part_time"
    assert job.location_cleaned == "Vesturland; IS"


def test_parse_job_splits_the_country_off_an_abroad_title() -> None:
    item = _list_item(
        title="Experienced Bicycle Mechanics - Ride On Bike AS - Norway",
        filterTags=_tags(("100%", "100"), ("Störf erlendis", "stoerf-erlendis")),
    )
    job = _parse(_raw(list_item=item))

    assert job.job_title == "Experienced Bicycle Mechanics"
    assert job.company_name == "Ride On Bike AS"
    assert job.location_cleaned == "IS"


def test_parse_job_falls_back_to_confidential_employer() -> None:
    job = _parse(_raw(list_item=_list_item(title="Solo role")))

    assert job.job_title == "Solo role"
    assert job.company_name == "Confidential Employer"


def test_parse_job_drops_a_closing_date_the_poster_left_in_the_past() -> None:
    job = _parse(_raw(list_item=_list_item(date="2026-11-01")))

    assert job.closing_date is None
    assert job.raw_payload["date_raw"] == "2026-11-01"
    assert job.raw_payload["closing_date_dropped"] is True


def test_parse_job_keeps_a_closing_date_on_the_scrape_day() -> None:
    job = _parse(_raw(list_item=_list_item(date="2026-11-28")))

    assert job.closing_date == datetime(2026, 11, 28)


def test_parse_job_rejects_a_vacancy_with_no_title() -> None:
    with pytest.raises(VinnumalastofnunIsParseError):
        _parse(_raw(list_item=_list_item(title="")))


def test_parse_jobs_skips_bad_vacancies_and_keeps_good_ones() -> None:
    good = _raw()
    bad = _raw(job_id="0", list_item=_list_item(title=""))
    jobs = VinnumalastofnunIsParser().parse_jobs([good, bad])
    assert [job.source_job_id for job in jobs] == ["37AfGWDNqeeFH60F5Pfanh"]


# ---------------------------------------------------------------------------
# Client helpers (no network)
# ---------------------------------------------------------------------------


def _client(**settings: object) -> VinnumalastofnunIsClient:
    return VinnumalastofnunIsClient(
        VinnumalastofnunIsSettings(inter_request_delay_seconds=0, **settings)
    )


def test_build_list_url_carries_the_persisted_query() -> None:
    url = _client().build_list_url(2)
    assert "operationName=GetGenericListItems" in url
    assert "sha256Hash" in url
    assert "%22page%22%3A2" in url
    assert "%22genericListId%22" in url


def test_apollo_state_reads_the_direct_shape() -> None:
    payload = '{"props":{"pageProps":{"apolloState":{"GenericListItem:x":{"id":"x"}}}}}'
    page = f'<html><script id="__NEXT_DATA__" type="application/json">{payload}</script></html>'
    apollo = VinnumalastofnunIsClient._apollo_state(page)
    assert apollo is not None
    assert apollo["GenericListItem:x"]["id"] == "x"


def test_apollo_state_reads_the_nested_shape() -> None:
    payload = (
        '{"props":{"pageProps":{"pageProps":{},"apolloState":{"GenericListItem:x":{"id":"x"}}}}}'
    )
    page = f'<html><script id="__NEXT_DATA__" type="application/json">{payload}</script></html>'
    apollo = VinnumalastofnunIsClient._apollo_state(page)
    assert apollo is not None
    assert "GenericListItem:x" in apollo


def test_apollo_state_returns_none_without_next_data() -> None:
    assert VinnumalastofnunIsClient._apollo_state("<html></html>") is None
