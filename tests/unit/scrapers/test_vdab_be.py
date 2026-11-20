"""Unit tests for the VDAB (Flanders, Belgium, vdab.be) scraper.

Pinned measured facts (2026-11-21, live service):

  * Discovery is the robots-allowed ``POST /rest/vindeenjob/v4/vacatureLight/zoek``
    endpoint; ``paginaGrootte`` up to 200 is accepted and the board reported
    ~212,800 active vacancies.
  * Every request needs the ``vej-key-monitor`` header (a static public
    constant from the site's own JavaScript); without it the API answers 403.
  * Detail is ``GET /rest/vindeenjob/v4/vacatures/<id>?preview=false``; the
    Schema.org ``jobPosting`` arrives as a JSON *string*.
  * ``functie.omschrijving.plainText`` is the full body; the markdown
    ``jobPosting.description`` is the same text with markdown artifacts.
  * ``validThrough`` is published on roughly 6% of ads (12 of 200 sampled).
  * No salary field exists anywhere in the payload.
  * ``profiel.dienstregeling.arbeidsDuur.code`` is ``V``/``D`` and
    ``functie.arbeidscircuit.code`` is the board's contract vocabulary.

No test touches the network.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from job_market_intel.scrapers.vdab_be import (
    DEFAULT_MONITOR_KEY,
    RawVdabJob,
    VdabClient,
    VdabParser,
    VdabPipeline,
    VdabResponseError,
    VdabSettings,
)
from job_market_intel.scrapers.vdab_be.client import _result_id
from job_market_intel.scrapers.vdab_be.parser import (
    HOME_COUNTRY,
    build_location,
    detect_remote,
    extract_description,
    map_employment_type,
    parse_date,
    strip_markdown,
)

#: A realistic detail payload: ``jobPosting`` is the JSON string the API sends.
JOB_POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Kwaliteitsverantwoordelijke",
    "datePosted": "2026-11-20T10:00:00Z",
    "validThrough": "2026-12-31T00:00:00Z",
    "employmentType": ["FULL_TIME"],
    "hiringOrganization": {
        "@type": "Organization",
        "name": "Tecjobz Oost-Vlaanderen",
        "logo": "https://cdn.example.test/logo.png",
    },
    "jobLocation": [
        {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": "BE",
                "addressLocality": "OUDENAARDE",
                "postalCode": "9700",
            },
        }
    ],
    "description": "**Kwaliteitsverantwoordelijke**\n\n- Je bewaakt de kwaliteit.\n",
}


def _payload(
    *,
    job_posting: dict | str | None = None,
    description_plain: str | None = (
        "Wij zoeken een kwaliteitsverantwoordelijke voor een productiebedrijf in "
        "Oudenaarde. Je bewaakt de kwaliteitsnormen, volgt afwijkingen op en "
        "rapporteert aan de productieleider. Je bereidt interne en externe audits "
        "voor, onderhoudt het kwaliteitshandboek en begeleidt verbeterprojecten op "
        "de werkvloer. Ervaring met ISO 9001 en met metrologie is een plus. Je "
        "werkt in dagdienst, in een stabiel team met ruime opleidingsmogelijkheden "
        "en een correcte verloning volgens de sector."
    ),
    circuit: str = "G",
    duur: str = "V",
    valid_through_present: bool = True,
) -> dict:
    posting = dict(JOB_POSTING)
    posting["description"] = str(JOB_POSTING["description"])
    if not valid_through_present:
        posting.pop("validThrough", None)
    if job_posting is not None:
        payload_posting = job_posting
    else:
        payload_posting = json.dumps(posting)

    omschrijving = {"markdown": posting["description"], "html": "<p>x</p>"}
    if description_plain is not None:
        omschrijving["plainText"] = description_plain

    return {
        "jobPosting": payload_posting,
        "eerstePublicatieDatum": "2026-11-20T10:00:00Z",
        "laatsteWijzigingDatum": "2026-11-20T10:00:00Z",
        "status": "ONLINE",
        "gesloten": False,
        "functie": {
            "naam": "Kwaliteitsverantwoordelijke",
            "arbeidscircuit": {"code": circuit, "label": "Gewoon contract."},
            "omschrijving": omschrijving,
        },
        "profiel": {
            "dienstregeling": {"arbeidsDuur": {"code": duur, "label": "Voltijds"}},
            "tewerkstellingsLocatie": {"regioOfAdres": "OUDENAARDE"},
            "voorgesteldeArbeidsovereenkomst": {
                "arbeidscontract": {"code": "ONBEPAALD", "label": "onbepaalde duur"}
            },
            "sollicitatieInfo": {"logischeLocatie": {"webadres": "https://apply.example.test/x"}},
            "studies": [{"code": "BACH"}],
            "jobdomeinen": [{"code": "PRODUCTIE"}],
        },
        "leverancier": {"naam": "Tecjobz Oost-Vlaanderen"},
        "opmaak": {"logo": "https://cdn.example.test/logo.png"},
    }


def _raw(payload: dict | None = None, job_id: str = "75097726") -> RawVdabJob:
    return RawVdabJob(
        job_id=job_id,
        url=f"https://www.vdab.be/vindeenjob/vacatures/{job_id}",
        listing={"vacatureBedrijfsnaam": "Tecjobz Oost-Vlaanderen"},
        payload=payload if payload is not None else _payload(),
    )


class TestResultId:
    @pytest.mark.parametrize(
        ("item", "expected"),
        [
            ({"id": {"id": 75026773}}, "75026773"),
            ({"id": 75026773}, "75026773"),
            ({"id": {"id": " 42 "}}, "42"),
            ({"id": {"id": None}}, None),
            ({"id": {}}, None),
            ({}, None),
            ({"id": {"id": "   "}}, None),
        ],
    )
    def test_extraction(self, item, expected):
        assert _result_id(item) == expected


class TestClientShape:
    def test_ad_and_detail_urls(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0))
        assert client.ad_url("42") == "https://www.vdab.be/vindeenjob/vacatures/42"
        assert client.detail_url("42") == ("https://www.vdab.be/rest/vindeenjob/v4/vacatures/42")

    def test_the_static_monitor_header_is_sent(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0))
        assert client._session.headers["vej-key-monitor"] == DEFAULT_MONITOR_KEY

    def test_tls_verification_is_left_on(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0))
        assert client._session.verify is True

    def test_defaults_are_the_measured_ones(self):
        settings = VdabSettings()
        assert settings.page_size == 200
        assert settings.max_pages >= 1
        assert settings.max_jobs_per_run >= 1
        assert settings.search_url.endswith("/rest/vindeenjob/v4/vacatureLight/zoek")
        assert settings.sort_field == "DATUM"
        assert settings.online_sinds_code == "9000"


class TestDiscovery:
    def _rows(self, ids):
        return {
            "resultaten": [
                {
                    "id": {"id": job_id},
                    "eerstePublicatieDatum": published,
                    "vacatureBedrijfsnaam": f"Co {job_id}",
                }
                for job_id, published in ids
            ],
            "totaalAantal": len(ids),
        }

    def test_pages_are_read_and_deduped(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0, max_pages=3))
        pages = {
            0: self._rows([(1, "2026-11-20T10:00:00Z"), (2, "2026-11-20T09:00:00Z")]),
            1: self._rows([(2, "2026-11-20T09:00:00Z"), (3, "2026-11-19T09:00:00Z")]),
            2: self._rows([]),
        }
        client.search_page = lambda page: pages.get(page, self._rows([]))
        rows, pages_scraped = client.discover()
        assert [row["job_id"] for row in rows] == ["1", "2", "3"]
        assert pages_scraped == 3

    def test_rows_are_sorted_newest_first_then_by_id(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0, max_pages=1))
        client.search_page = lambda page: self._rows(
            [
                (10, "2026-11-20T10:00:00Z"),
                (11, "2026-11-20T12:00:00Z"),
                (12, "2026-11-20T12:00:00Z"),
            ]
        )
        rows, _ = client.discover()
        assert [row["job_id"] for row in rows] == ["12", "11", "10"]

    def test_a_page_with_no_new_rows_stops_the_walk(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0, max_pages=5))
        client.search_page = lambda page: (
            self._rows([(1, "2026-11-20T10:00:00Z")])
            if page == 0
            else self._rows([(1, "2026-11-20T10:00:00Z")])
        )
        rows, pages_scraped = client.discover()
        assert len(rows) == 1
        assert pages_scraped == 2

    def test_an_empty_board_raises_rather_than_returning_nothing(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0, max_pages=2))
        client.search_page = lambda page: self._rows([])
        with pytest.raises(VdabResponseError, match="request shape changed"):
            client.discover()


class TestWindow:
    def _rows(self, n: int) -> list[dict]:
        return [
            {"job_id": str(i), "published": f"2026-11-20T{i:02d}:00:00Z", "listing": {}}
            for i in range(n)
        ]

    def test_a_budget_above_the_board_takes_everything(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0))
        assert client.select_window(self._rows(5), 10) == self._rows(5)

    def test_the_newest_rows_are_always_taken(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0, fresh_rows=3, start_offset=0))
        chosen = client.select_window(self._rows(10), 5)
        assert [row["job_id"] for row in chosen] == ["0", "1", "2", "3", "4"]

    def test_the_tail_window_rotates(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0, fresh_rows=2, start_offset=4))
        chosen = client.select_window(self._rows(10), 5)
        assert [row["job_id"] for row in chosen] == ["0", "1", "6", "7", "8"]

    def test_the_window_wraps_around_the_tail(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0, fresh_rows=0, start_offset=8))
        chosen = client.select_window(self._rows(10), 4)
        assert [row["job_id"] for row in chosen] == ["8", "9", "0", "1"]

    def test_a_pinned_offset_is_reproducible(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0, start_offset=7))
        assert client.rotation_offset(1000, 90) == 7
        assert client.rotation_offset(1000, 90) == 7

    def test_the_offset_advances_one_window_per_day(self):
        client = VdabClient(VdabSettings(rate_limit_delay=0, fresh_rows=0))
        assert client.rotation_offset(1000, 90) == (date.today().toordinal() * 90) % 1000


class TestEmploymentType:
    @pytest.mark.parametrize(
        ("circuit", "duur", "raw_types", "expected"),
        [
            ("G", "V", ["FULL_TIME"], "full_time"),
            ("G", "D", ["FULL_TIME"], "part_time"),
            ("GC", "V", None, "full_time"),
            ("GC", "", None, None),
            ("", "D", None, "part_time"),
            ("GB", "V", None, "part_time"),
            ("Z", "V", None, "freelance"),
            ("I", "V", None, "temporary"),
            ("IV", "V", None, "temporary"),
            ("T", "V", None, "temporary"),
            ("Q", "V", None, "temporary"),
            ("V", "V", None, "part_time"),
            ("MO", "V", None, "apprenticeship"),
            ("FL", "V", ["FULL_TIME"], None),
            ("WS", "V", None, None),
            ("E", "V", None, None),
            ("G", None, ["TEMPORARY"], "temporary"),
            ("", None, ["INTERN"], "internship"),
            ("", None, ["CONTRACTOR"], "freelance"),
            ("", None, ["PERMANENT"], "full_time"),
            ("", None, ["FULL_TIME", "TEMPORARY"], None),
            ("", None, ["PER_DIEM"], None),
            ("", None, None, None),
        ],
    )
    def test_mapping(self, circuit, duur, raw_types, expected):
        assert map_employment_type(circuit, duur, raw_types) == expected


class TestRemote:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Kwaliteitsverantwoordelijke", "on_site"),
            ("100% telewerk, je werkt volledig van thuis", "remote_country"),
            ("Volledig thuiswerk mogelijk", "remote_country"),
            ("Hybride werken: 2 dagen kantoor", "hybrid"),
            ("Telewerk mogelijk na inwerkperiode", "hybrid"),
            ("Mogelijkheid tot thuiswerk", "hybrid"),
            ("100% telewerk, wereldwijd", "remote_global"),
            (None, "on_site"),
            ("", "on_site"),
        ],
    )
    def test_detection(self, text, expected):
        assert detect_remote("Vacature", text) == expected

    def test_title_alone_is_enough(self):
        assert detect_remote("Remote Data Engineer", "") == "on_site"
        assert detect_remote("100% telewerk engineer", "") == "remote_country"


class TestLocation:
    def test_a_locality_is_title_cased_and_country_appended(self):
        assert build_location(_payload(), json.loads(_payload()["jobPosting"])) == (
            "Oudenaarde, Belgium"
        )

    def test_a_compound_place_keeps_its_hyphen(self):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting["jobLocation"][0]["address"]["addressLocality"] = "SINT-NIKLAAS"
        assert build_location(payload, posting) == "Sint-Niklaas, Belgium"

    @pytest.mark.parametrize("locality", ["Belgium", "BELGIUM", "België", "BE"])
    def test_a_country_only_locality_is_not_repeated(self, locality):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting["jobLocation"][0]["address"]["addressLocality"] = locality
        assert build_location(payload, posting) == HOME_COUNTRY

    def test_the_employer_municipality_is_the_fallback(self):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting.pop("jobLocation")
        assert build_location(payload, posting) == "Oudenaarde, Belgium"

    def test_the_listing_region_is_the_last_resort(self):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting.pop("jobLocation")
        payload["profiel"]["tewerkstellingsLocatie"] = {}
        payload["listing"] = {"tewerkstellingsLocatieRegioOfAdres": "PITTEM"}
        assert build_location(payload, posting) == "Pittem, Belgium"

    def test_with_no_signal_the_country_is_used(self):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting.pop("jobLocation")
        payload["profiel"] = {}
        assert build_location(payload, posting) == HOME_COUNTRY


class TestDates:
    def test_iso_timestamp(self):
        assert parse_date("2026-11-20T10:00:00Z") == datetime(2026, 11, 20)

    @pytest.mark.parametrize("value", ["20.11.2026", "20/11/2026"])
    def test_day_first(self, value):
        assert parse_date(value) == datetime(2026, 11, 20)

    @pytest.mark.parametrize("value", [None, "", "TBD", "31/02/2026"])
    def test_unreadable(self, value):
        assert parse_date(value) is None


class TestDescription:
    def test_plain_text_is_preferred(self):
        payload = _payload(description_plain="De volledige tekst.")
        text, source = extract_description(json.loads(payload["jobPosting"]), payload["functie"])
        assert text == "De volledige tekst."
        assert source == "functie_plain_text"

    def test_markdown_is_stripped_when_plain_text_is_absent(self):
        payload = _payload(description_plain=None)
        text, source = extract_description(json.loads(payload["jobPosting"]), payload["functie"])
        assert source == "job_posting_markdown"
        assert "**" not in text
        assert "\n" not in text
        assert text.startswith("Kwaliteitsverantwoordelijke")

    def test_html_is_the_last_resort(self):
        text, source = extract_description(
            {"description": ""}, {"omschrijving": {"html": "<p>Alleen HTML.</p>"}}
        )
        assert text == "Alleen HTML."
        assert source == "functie_html"

    def test_nothing_at_all_is_empty(self):
        text, source = extract_description({}, {})
        assert text == ""
        assert source == "none"

    def test_strip_markdown_handles_links_and_headings(self):
        assert strip_markdown("## Kop\n[tekst](https://x.test)") == "Kop\ntekst"


class TestParser:
    def test_the_contract_is_fully_populated(self):
        job = VdabParser().parse_job(_raw())
        assert job.source_job_id == "75097726"
        assert job.job_title == "Kwaliteitsverantwoordelijke"
        assert job.company_name == "Tecjobz Oost-Vlaanderen"
        assert job.company_logo_url == "https://cdn.example.test/logo.png"
        assert job.location_cleaned == "Oudenaarde, Belgium"
        assert job.posting_date == datetime(2026, 11, 20)
        assert job.closing_date == datetime(2026, 12, 31)
        assert job.employment_type_code == "full_time"
        assert job.remote_work_type_code == "on_site"
        assert job.currency_iso_code == "EUR"
        assert job.pay_period == "monthly"
        assert job.description_clean and "kwaliteitsverantwoordelijke" in job.description_clean
        assert job.word_count > 10
        assert job.data_quality_score == 0.95

    def test_no_salary_is_invented(self):
        job = VdabParser().parse_job(_raw())
        assert job.salary_min is None and job.salary_max is None
        assert job.salary_disclosed is False

    def test_the_board_ad_page_is_the_apply_url(self):
        job = VdabParser().parse_job(_raw())
        assert job.apply_url == "https://www.vdab.be/vindeenjob/vacatures/75097726"
        assert job.original_url == job.apply_url
        assert job.raw_payload["external_apply_url"] == "https://apply.example.test/x"

    def test_a_missing_closing_date_stays_none(self):
        job = VdabParser().parse_job(_raw(_payload(valid_through_present=False)))
        assert job.closing_date is None

    def test_a_closing_date_before_the_posting_is_dropped(self):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting["validThrough"] = "2026-11-01T00:00:00Z"
        payload["jobPosting"] = json.dumps(posting)
        assert VdabParser().parse_job(_raw(payload)).closing_date is None

    def test_a_short_description_scores_lower(self):
        job = VdabParser().parse_job(_raw(_payload(description_plain="Korte tekst.")))
        assert job.data_quality_score == 0.7

    def test_a_missing_plain_text_falls_back_to_markdown(self):
        job = VdabParser().parse_job(_raw(_payload(description_plain=None)))
        assert job.raw_payload["description_source"] == "job_posting_markdown"
        assert job.description_clean and "**" not in job.description_clean

    def test_the_company_falls_back_to_the_listing(self):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting.pop("hiringOrganization")
        payload["jobPosting"] = json.dumps(posting)
        payload["leverancier"] = {}
        job = VdabParser().parse_job(_raw(payload))
        assert job.company_name == "Tecjobz Oost-Vlaanderen"

    def test_an_unknown_company_is_labelled_not_invented(self):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting["hiringOrganization"] = {}
        payload["jobPosting"] = json.dumps(posting)
        payload["leverancier"] = {}
        raw = RawVdabJob(
            job_id="75097726",
            url="https://www.vdab.be/vindeenjob/vacatures/75097726",
            listing={},
            payload=payload,
        )
        job = VdabParser().parse_job(raw)
        assert job.company_name == "Confidential Employer"

    def test_the_logo_falls_back_to_the_payload_markup_block(self):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting["hiringOrganization"] = {"name": "Tecjobz Oost-Vlaanderen"}
        payload["jobPosting"] = json.dumps(posting)
        job = VdabParser().parse_job(_raw(payload))
        assert job.company_logo_url == "https://cdn.example.test/logo.png"

    def test_a_direct_dict_job_posting_is_accepted(self):
        payload = _payload(job_posting=dict(JOB_POSTING))
        job = VdabParser().parse_job(_raw(payload))
        assert job.job_title == "Kwaliteitsverantwoordelijke"

    def test_a_flexijob_has_no_honest_employment_code(self):
        job = VdabParser().parse_job(_raw(_payload(circuit="FL")))
        assert job.employment_type_code is None

    def test_a_part_time_ordinary_contract(self):
        job = VdabParser().parse_job(_raw(_payload(duur="D")))
        assert job.employment_type_code == "part_time"

    def test_hybrid_wording_is_detected_from_the_body(self):
        payload = _payload(description_plain="Hybride werken: twee dagen kantoor.")
        job = VdabParser().parse_job(_raw(payload))
        assert job.remote_work_type_code == "hybrid"

    def test_the_title_is_the_fallback_when_job_posting_has_none(self):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting.pop("title")
        payload["jobPosting"] = json.dumps(posting)
        job = VdabParser().parse_job(_raw(payload))
        assert job.job_title == "Kwaliteitsverantwoordelijke"

    def test_a_payload_without_a_title_is_skipped_not_invented(self):
        payload = _payload()
        posting = json.loads(payload["jobPosting"])
        posting.pop("title")
        payload["jobPosting"] = json.dumps(posting)
        payload["functie"] = {"naam": "  "}
        assert VdabParser().parse_jobs([_raw(payload)]) == []

    def test_broken_job_posting_json_is_skipped(self):
        payload = _payload(job_posting="{not json")
        assert VdabParser().parse_jobs([_raw(payload)]) == []

    def test_one_bad_payload_does_not_drop_the_good_ones(self):
        good = _raw()
        bad = _raw(_payload(job_posting="{not json"), job_id="bad")
        jobs = VdabParser().parse_jobs([good, bad])
        assert [job.source_job_id for job in jobs] == ["75097726"]


class TestPipelineDryRun:
    class _Client:
        def __init__(self, raws, pages=2, discovered=None):
            self.raws = raws
            self.pages = pages
            self.discovered = len(raws) if discovered is None else discovered

        def fetch_raw_jobs(self, max_jobs=None):
            return self.raws, [], self.pages, self.discovered

    def test_a_dry_run_parses_without_persisting(self):
        result = VdabPipeline(
            settings=VdabSettings(rate_limit_delay=0), client=self._Client([_raw()])
        ).run(store_db=False)
        assert result.pages_scraped == 2
        assert result.discovered_count == 1
        assert result.raw_count == 1
        assert result.parsed_count == 1
        assert result.validation_passed is True
        assert result.inserted_count == 0
        assert result.failed_count == 0

    def test_zero_fetched_details_is_reported(self):
        result = VdabPipeline(
            settings=VdabSettings(rate_limit_delay=0), client=self._Client([], pages=1)
        ).run(store_db=False)
        assert result.validation_passed is False
        assert result.parsed_count == 0
        assert any("Zero vacancy details" in issue for issue in result.issues)

    def test_zero_parsed_details_fails_validation(self):
        bad = _raw(_payload(job_posting="{not json"), job_id="bad")
        result = VdabPipeline(
            settings=VdabSettings(rate_limit_delay=0), client=self._Client([bad])
        ).run(store_db=False)
        assert result.validation_passed is False
        assert any("Zero jobs successfully parsed" in issue for issue in result.issues)
