"""Unit tests for the ANPE Mali (anpe-mali.org) scraper.

Pinned measured facts (2026-11-21, live site):

  * Discovery is ``GET https://anpe-mali.org/wp-json/wp/v2/job-listings``
    with ``per_page=100&page=N``, answering a JSON array and
    ``X-WP-Total: 15`` / ``X-WP-TotalPages: 1``; the board's own sitemap
    lists the same 15 pages.
  * ``robots.txt`` is ``User-agent: *`` / ``Disallow: /wp-admin/`` /
    ``Allow: /wp-admin/admin-ajax.php``; ``/wp-json/`` is allowed.
  * One listing is the whole record: title, HTML body, date, link,
    employer (``meta._company_name``), free-text location
    (``meta._job_location``), a 0/1 ``meta._remote_position`` flag and a
    ``class_list``/``job-types`` contract taxonomy.
  * Salary is never stated (``meta._job_salary`` is empty on all 15).
  * Locations seen: "Bamako" (8), "Mali"/"MALI" (3), "Sur site" (4), "" (1).

No test touches the network.
"""

from __future__ import annotations

import pytest

from job_market_intel.cleaning.anpe_mali_cleaner import (
    AnpeMaliCleaner,
    extract_location,
    map_employment_type,
)
from job_market_intel.scrapers.anpe_mali.config import AnpeMaliSettings
from job_market_intel.scrapers.anpe_mali.models import (
    DEFAULT_COMPANY_NAME,
    RawAnpeMaliJob,
)
from job_market_intel.scrapers.anpe_mali.parser import AnpeMaliParser
from job_market_intel.validation.anpe_mali_validator import (
    AnpeMaliBatchValidator,
    AnpeMaliValidationSettings,
)

RECORD = {
    "id": 2188,
    "date": "2026-11-19T16:54:43",
    "modified": "2026-11-19T16:54:59",
    "slug": "imas-conseils-bamako-charge-de-projet-en-genie-civil-hydraulique",
    "status": "publish",
    "type": "job_listing",
    "link": (
        "https://anpe-mali.org/poste/imas-conseils-bamako-charge-de-projet-en-"
        "genie-civil-hydraulique/"
    ),
    "title": {"rendered": "CHARG&Eacute;(E) DE PROJET EN G&Eacute;NIE CIVIL / HYDRAULIQUE"},
    "content": {
        "rendered": (
            "<p>AVIS DE RECRUTEMENT<br />Un (01) poste a pourvoir chez un bureau "
            "d'etudes et d'ingenierie-conseil.<br />Lieu d'affectation : Bamako, "
            "Mali<br />Type de contrat : CDD de douze (12) mois renouvelable.<br />"
            "Sous la responsabilite de la Direction technique, le ou la charge(e) "
            "de projet assurera les etudes techniques et de faisabilite des "
            "projets, le dimensionnement des ouvrages et le suivi technique des "
            "chantiers.</p>"
        )
    },
    "meta": {
        "_company_name": "IMAS Conseils",
        "_job_location": "Bamako",
        "_application": "recrutimas@gmail.com",
        "_remote_position": 0,
        "_filled": 0,
        "_job_salary": "",
        "_job_salary_currency": "",
        "_job_salary_unit": "",
    },
    "job-types": [9],
    "job-categories": [11],
    "class_list": [
        "post-2188",
        "job_listing",
        "type-job_listing",
        "status-publish",
        "hentry",
        "job-type-cdd",
    ],
    "featured_media": 0,
    "_embedded": {},
}


def _record(**overrides: object) -> dict:
    """A copy of ``RECORD`` with ``meta``/top-level keys overridden."""
    record = {**RECORD, **{k: v for k, v in overrides.items() if k != "meta"}}
    if "meta" in overrides:
        record["meta"] = {**RECORD["meta"], **overrides["meta"]}  # type: ignore[dict-item]
    return record


class TestModels:
    def test_from_payload_reads_the_listing(self) -> None:
        job = RawAnpeMaliJob.from_payload(RECORD)
        assert job.source_job_id == "2188"
        assert job.job_title == "CHARGÉ(E) DE PROJET EN GÉNIE CIVIL / HYDRAULIQUE"
        assert job.company_name == "IMAS Conseils"
        assert job.company_logo_url is None
        assert job.location_raw == "Bamako"
        assert job.application == "recrutimas@gmail.com"
        assert job.remote_position is False
        assert job.employment_type_slugs == ["cdd"]
        assert job.job_type_ids == [9]
        assert job.original_url.endswith("genie-civil-hydraulique/")
        assert job.description_html and "CDD" in job.description_html
        assert job.posting_date is not None
        assert job.posting_date.year == 2026

    def test_logo_from_embedded_media(self) -> None:
        record = _record(
            _embedded={
                "wp:featuredmedia": [
                    {
                        "source_url": (
                            "https://anpe-mali.org/wp-content/uploads/job-manager-uploads/"
                            "company_logo/2026/11/logo_ADAFO.jpeg"
                        )
                    }
                ]
            }
        )
        job = RawAnpeMaliJob.from_payload(record)
        assert job.company_logo_url is not None
        assert job.company_logo_url.endswith("logo_ADAFO.jpeg")

    def test_missing_company_uses_default(self) -> None:
        job = RawAnpeMaliJob.from_payload(_record(meta={"_company_name": ""}))
        assert job.company_name == DEFAULT_COMPANY_NAME

    def test_missing_id_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            RawAnpeMaliJob.from_payload(_record(id=None))

    def test_non_object_listing_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            RawAnpeMaliJob.from_payload(["not", "an", "object"])


class TestParser:
    def test_parses_valid_and_skips_malformed(self) -> None:
        parsed = AnpeMaliParser().parse_jobs([RECORD, {"id": None}, "junk"])
        assert len(parsed) == 1
        assert parsed[0].source_job_id == "2188"


class TestCleaner:
    def test_clean_job_maps_the_known_fields(self) -> None:
        cleaned = AnpeMaliCleaner().clean_job(RawAnpeMaliJob.from_payload(RECORD))
        assert cleaned.job_title == "CHARGÉ(E) DE PROJET EN GÉNIE CIVIL / HYDRAULIQUE"
        assert cleaned.company_name == "IMAS Conseils"
        assert cleaned.location_cleaned == "Bamako"
        assert cleaned.employment_type_code == "contract"
        assert cleaned.remote_work_type_code is None
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None and cleaned.salary_max is None
        assert cleaned.currency_iso_code == "XOF"
        assert cleaned.pay_period == "yearly"
        assert cleaned.description_clean
        assert cleaned.word_count > 20
        # salary False, location True, skills False, words True -> 0.5
        assert cleaned.data_quality_score == 0.5

    def test_on_site_location_becomes_remote(self) -> None:
        cleaned = AnpeMaliCleaner().clean_job(
            RawAnpeMaliJob.from_payload(_record(meta={"_job_location": "Sur site"}))
        )
        assert cleaned.location_cleaned is None
        assert cleaned.remote_work_type_code == "on_site"

    def test_empty_location_is_none(self) -> None:
        cleaned = AnpeMaliCleaner().clean_job(
            RawAnpeMaliJob.from_payload(_record(meta={"_job_location": ""}))
        )
        assert cleaned.location_cleaned is None
        assert cleaned.remote_work_type_code is None

    def test_country_only_location_is_kept(self) -> None:
        cleaned = AnpeMaliCleaner().clean_job(
            RawAnpeMaliJob.from_payload(_record(meta={"_job_location": "Mali"}))
        )
        assert cleaned.location_cleaned == "Mali"

    def test_cdi_maps_to_full_time(self) -> None:
        assert map_employment_type(["cdi"], []) == "full_time"

    def test_independant_maps_to_freelance(self) -> None:
        assert map_employment_type([], [8]) == "freelance"

    def test_interim_maps_to_temporary(self) -> None:
        assert map_employment_type(["interim"], []) == "temporary"

    def test_stage_maps_to_internship(self) -> None:
        assert map_employment_type(["stage"], []) == "internship"

    def test_id_fallback_when_no_class_list(self) -> None:
        cleaned = AnpeMaliCleaner().clean_job(
            RawAnpeMaliJob.from_payload(_record(**{"class_list": []}))
        )
        assert cleaned.employment_type_code == "contract"

    def test_multi_type_is_unset(self) -> None:
        record = _record(
            **{
                "class_list": [
                    "job_listing",
                    "job-type-cdi",
                    "job-type-cdd",
                ]
            }
        )
        cleaned = AnpeMaliCleaner().clean_job(RawAnpeMaliJob.from_payload(record))
        assert cleaned.employment_type_code is None

    def test_no_type_leaves_none(self) -> None:
        cleaned = AnpeMaliCleaner().clean_job(
            RawAnpeMaliJob.from_payload(_record(**{"class_list": [], "job-types": []}))
        )
        assert cleaned.employment_type_code is None

    def test_clean_jobs_batch(self) -> None:
        job = RawAnpeMaliJob.from_payload(RECORD)
        assert len(AnpeMaliCleaner().clean_jobs([job, job])) == 2


class TestLocationExtraction:
    def test_place_is_kept(self) -> None:
        assert extract_location("Bamako") == ("Bamako", None)

    def test_on_site_variants(self) -> None:
        assert extract_location("Sur site") == (None, "on_site")
        assert extract_location("on-site") == (None, "on_site")
        assert extract_location("presentiel") == (None, "on_site")

    def test_empty_is_none(self) -> None:
        assert extract_location("") == (None, None)
        assert extract_location(None) == (None, None)


class TestValidator:
    def _jobs(self, n: int) -> list[RawAnpeMaliJob]:
        return [
            RawAnpeMaliJob.from_payload(
                _record(id=91000 + i, link=f"https://anpe-mali.org/poste/notice-{i}/")
            )
            for i in range(n)
        ]

    def test_healthy_batch_passes(self) -> None:
        jobs = self._jobs(15)
        report = AnpeMaliBatchValidator().validate(list(jobs), jobs)
        assert report.passed is True
        assert report.total_parsed == 15

    def test_too_few_jobs_fails(self) -> None:
        jobs = self._jobs(3)
        report = AnpeMaliBatchValidator().validate(list(jobs), jobs)
        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_fails(self) -> None:
        report = AnpeMaliBatchValidator().validate([], [])
        assert report.passed is False

    def test_duplicate_ids_are_flagged(self) -> None:
        jobs = self._jobs(15)
        report = AnpeMaliBatchValidator().validate(list(jobs), jobs + [jobs[0]])
        assert report.passed is False
        assert report.duplicate_source_job_ids == ["91000"]

    def test_default_thresholds(self) -> None:
        settings = AnpeMaliValidationSettings()
        assert settings.min_expected_jobs == 5
        assert settings.max_skip_rate == 0.10


class TestSettings:
    def test_defaults(self) -> None:
        settings = AnpeMaliSettings()
        assert settings.per_page == 100
        assert settings.max_jobs_per_run == 200
        assert settings.listings_url.endswith("/wp-json/wp/v2/job-listings")
        assert settings.user_agent.startswith("Mozilla/5.0")
