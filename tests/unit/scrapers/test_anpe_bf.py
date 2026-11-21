"""Unit tests for the ANPE Burkina Faso (anpe.gov.bf) scraper.

Pinned measured facts (2026-11-21, live site):

  * Discovery is ``GET https://www.anpe.gov.bf/wp-json/wp/v2/posts`` with
    ``categories=77&per_page=100&page=N``, answering a JSON array and
    ``X-WP-Total: 97`` / ``X-WP-TotalPages: 1``; the whole category is
    97 recruitment notices.
  * ``robots.txt`` is ``User-agent: *`` / ``Allow: /`` (no Disallow).
  * One post is the whole record: ``{id, date, modified, link,
    title.rendered, content.rendered, excerpt.rendered}``; there is no
    salary, employer, location or contract field.
  * Salary is never stated ("francs CFA" appears only in stamp-fee
    instructions); contract wording and commune names are free prose.
  * Some titles use Unicode mathematical-bold letters; NFKC makes them
    plain Latin.

No test touches the network.
"""

from __future__ import annotations

import pytest

from job_market_intel.cleaning.anpe_bf_cleaner import (
    AnpeBfCleaner,
    extract_location,
    map_employment_type,
)
from job_market_intel.scrapers.anpe_bf.config import AnpeBfSettings
from job_market_intel.scrapers.anpe_bf.models import DEFAULT_COMPANY_NAME, RawAnpeBfJob
from job_market_intel.scrapers.anpe_bf.parser import AnpeBfParser
from job_market_intel.validation.anpe_bf_validator import (
    AnpeBfBatchValidator,
    AnpeBfValidationSettings,
)

POST = {
    "id": 11638,
    "date": "2026-07-03T13:23:38",
    "modified": "2026-07-03T13:33:00",
    "link": "https://anpe.gov.bf/actualite/avis-de-recrutement-mairie-pibaore/",
    "title": {"rendered": "Avis de recrutement/ Mairie Pibaoré"},
    "content": {
        "rendered": (
            "<p>Avis de recrutement/ Mairie Pibaoré</p>"
            "<p>La Direction Régionale de l’Agence Burkinabè Pour l’Emploi (ABPE) "
            "recherche pour le compte de la Mairie de Pibaoré des candidatures pour "
            "le recrutement d’un (01) Agent d’état civil.</p>"
            "<p>Type de contrat de travail : Contrat à durée indéterminée (CDI).</p>"
            "<p>Profil : être de nationalité burkinabè ; être âgé de 18 ans au moins "
            "et de 37 ans au plus au 31 décembre 2026 ; être titulaire du BEPC.</p>"
            "<p>Une demande manuscrite timbrée à 300 francs CFA (timbre communal de "
            "Pibaoré) adressée à Monsieur le Directeur Régional.</p>"
        )
    },
    "excerpt": {
        "rendered": (
            "<p>Avis de recrutement/ Mairie Pibaoré La Direction Régionale de "
            "l’Agence Burkinabè Pour l’Emploi recherche pour le compte de la Mairie "
            "de Pibaoré des candidatures [&hellip;]</p>"
        )
    },
}


class TestModels:
    def test_from_payload_reads_the_post(self) -> None:
        job = RawAnpeBfJob.from_payload(POST)
        assert job.source_job_id == "11638"
        assert job.job_title == "Avis de recrutement/ Mairie Pibaoré"
        assert job.company_name == DEFAULT_COMPANY_NAME
        assert job.original_url.endswith("avis-de-recrutement-mairie-pibaore/")
        assert job.description_html and "durée indéterminée" in job.description_html
        assert job.posting_date is not None
        assert job.posting_date.year == 2026

    def test_math_bold_title_is_normalized(self) -> None:
        post = {
            **POST,
            "title": {"rendered": "𝗖𝗢𝗠𝗠𝗨𝗡𝗜𝗤𝗨𝗘 / 𝗥𝗲𝗰𝗿𝘂𝘁𝗲𝗺𝗲𝗻𝘁 𝗟𝗢𝗡𝗔𝗕"},
        }
        job = RawAnpeBfJob.from_payload(post)
        assert job.job_title == "COMMUNIQUE / Recrutement LONAB"

    def test_missing_id_is_rejected(self) -> None:
        post = {**POST, "id": None}
        with pytest.raises(ValueError):
            RawAnpeBfJob.from_payload(post)

    def test_non_object_post_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            RawAnpeBfJob.from_payload(["not", "an", "object"])


class TestParser:
    def test_parses_valid_and_skips_malformed(self) -> None:
        parsed = AnpeBfParser().parse_jobs([POST, {"id": None}, "junk"])
        assert len(parsed) == 1
        assert parsed[0].source_job_id == "11638"


class TestCleaner:
    def test_clean_job_maps_the_known_fields(self) -> None:
        cleaned = AnpeBfCleaner().clean_job(RawAnpeBfJob.from_payload(POST))
        assert cleaned.job_title == "Avis de recrutement/ Mairie Pibaoré"
        assert cleaned.company_name == DEFAULT_COMPANY_NAME
        assert cleaned.location_cleaned == "Pibaoré"
        assert cleaned.employment_type_code == "full_time"
        assert cleaned.salary_disclosed is False
        assert cleaned.salary_min is None and cleaned.salary_max is None
        assert cleaned.currency_iso_code == "XOF"
        assert cleaned.pay_period == "yearly"
        assert cleaned.description_clean
        assert cleaned.word_count > 20
        # salary False, location True, skills False, words True -> 0.5
        assert cleaned.data_quality_score == 0.5

    def test_cdd_maps_to_contract(self) -> None:
        post = {
            **POST,
            "content": {"rendered": "<p>Contrat à durée déterminée (CDD) de 12 mois.</p>"},
        }
        cleaned = AnpeBfCleaner().clean_job(RawAnpeBfJob.from_payload(post))
        assert cleaned.employment_type_code == "contract"

    def test_stage_maps_to_internship(self) -> None:
        assert map_employment_type("Nous recherchons un stagiaire pour un stage.") == "internship"

    def test_no_contract_wording_leaves_none(self) -> None:
        assert map_employment_type("Avis de recrutement sans autre precision") is None

    def test_clean_jobs_batch(self) -> None:
        job = RawAnpeBfJob.from_payload(POST)
        assert len(AnpeBfCleaner().clean_jobs([job, job])) == 2


class TestLocationExtraction:
    def test_commune_de(self) -> None:
        assert extract_location("recherche pour la commune de Tougan des candidatures") == "Tougan"

    def test_mairie_variant(self) -> None:
        assert extract_location("Mairie de Pibaoré recherche un agent") == "Pibaoré"

    def test_province_variant(self) -> None:
        assert extract_location("Mairie de Tougo (Province du Zondoma)") == "Tougo"

    def test_none_when_absent(self) -> None:
        assert extract_location("Avis de recrutement sans lieu") is None


class TestValidator:
    def _jobs(self, n: int) -> list[RawAnpeBfJob]:
        return [
            RawAnpeBfJob.from_payload(
                {
                    **POST,
                    "id": 91000 + i,
                    "link": f"https://anpe.gov.bf/actualite/notice-{i}/",
                }
            )
            for i in range(n)
        ]

    def test_healthy_batch_passes(self) -> None:
        jobs = self._jobs(40)
        report = AnpeBfBatchValidator().validate(list(jobs), jobs)
        assert report.passed is True
        assert report.total_parsed == 40

    def test_too_few_jobs_fails(self) -> None:
        jobs = self._jobs(3)
        report = AnpeBfBatchValidator().validate(list(jobs), jobs)
        assert report.passed is False
        assert any("below the configured minimum" in issue for issue in report.issues)

    def test_zero_raw_records_fails(self) -> None:
        report = AnpeBfBatchValidator().validate([], [])
        assert report.passed is False

    def test_duplicate_ids_are_flagged(self) -> None:
        jobs = self._jobs(40)
        report = AnpeBfBatchValidator().validate(list(jobs), jobs + [jobs[0]])
        assert report.passed is False
        assert report.duplicate_source_job_ids == ["91000"]

    def test_default_thresholds(self) -> None:
        settings = AnpeBfValidationSettings()
        assert settings.min_expected_jobs == 30
        assert settings.max_skip_rate == 0.10


class TestSettings:
    def test_defaults(self) -> None:
        settings = AnpeBfSettings()
        assert settings.category_id == 77
        assert settings.per_page == 100
        assert settings.max_jobs_per_run == 200
        assert settings.posts_url.endswith("/wp-json/wp/v2/posts")
        assert settings.user_agent.startswith("Mozilla/5.0")
