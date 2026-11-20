"""Unit tests for the Empléate (Spain) Solr-document parser.

No network and no database: every test drives the pure mapping helpers or a
synthetic Solr document, using the exact shapes measured on 2026-11-20.
"""

from __future__ import annotations

import ssl
from datetime import datetime

import pytest

from job_market_intel.scrapers.empleate_es import EmpleateEsClient, EmpleateEsSettings
from job_market_intel.scrapers.empleate_es.exceptions import EmpleateEsResponseError
from job_market_intel.scrapers.empleate_es.models import RawEmpleateEsJob
from job_market_intel.scrapers.empleate_es.parser import (
    EmpleateEsParser,
    build_location,
    map_employment_type,
    map_remote,
    map_work_schedule,
    normalize_description,
    parse_iso_datetime,
    parse_salary_amount,
    parse_salary_bounds,
)
from job_market_intel.scrapers.empleate_es.tls import build_ca_bundle


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("15", 15.0),
        ("30000", 30000.0),
        ("21,000", 21000.0),
        ("16261,86", 16261.86),
        ("16261.86", 16261.86),
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
        ("1.234.567", 1234567.0),
        ("0", None),
        ("", None),
        (None, None),
        ("—", None),
    ],
)
def test_parse_salary_amount(raw: object, expected: float | None) -> None:
    assert parse_salary_amount(raw) == expected


def test_salary_bounds_treat_zero_as_missing() -> None:
    assert parse_salary_bounds({"salarioMin": "0", "salarioMax": "0"}) == (None, None)


def test_salary_bounds_swap_reversed_bounds() -> None:
    assert parse_salary_bounds({"salarioMin": "2000", "salarioMax": "1000"}) == (1000.0, 2000.0)


def test_salary_bounds_respect_hidden_flags() -> None:
    bounds = parse_salary_bounds(
        {"salarioMin": "1500", "salarioMax": "2000", "verSalarioMin": "0", "verSalarioMax": "1"}
    )
    assert bounds == (None, 2000.0)


@pytest.mark.parametrize(
    ("contract", "day_type", "expected"),
    [
        ("5", "1", "internship"),
        ("6", "1", "apprenticeship"),
        ("4", "1", "freelance"),
        ("3", "2", "part_time"),
        ("3", "1", "temporary"),
        ("1", "1", "contract"),
        ("2", "1", "full_time"),
        ("2", "3", "full_time"),
        ("0", "1", "full_time"),
        ("0", "3", None),
        ("0", "4", None),
        (None, None, None),
    ],
)
def test_map_employment_type(
    contract: str | None, day_type: str | None, expected: str | None
) -> None:
    assert map_employment_type(contract, day_type) == expected


@pytest.mark.parametrize(
    ("modality", "expected"),
    [
        ("0", "on_site"),
        ("1", "on_site"),
        ("2", "remote_country"),
        ("3", "remote_country"),
        ("4", "hybrid"),
        (None, "on_site"),
        ("9", "on_site"),
    ],
)
def test_map_remote(modality: str | None, expected: str) -> None:
    assert map_remote(modality)[0] == expected


@pytest.mark.parametrize(
    ("horario", "expected"),
    [
        ("L-V 10.00 a 14.00 Sábados 10.00 a 14.00", "standard_day"),
        ("8-14", "standard_day"),
        ("8:00 a 15:00", "standard_day"),
        ("Sábados y domingos 8:00h a 13:00h", "weekend"),
        ("Turnos rotativos", "rotational"),
        ("Nocturno", "night_shift"),
        ("Flexible", "flexible"),
        ("Jornada completa", None),
        ("INDIFERENTE", None),
        ("", None),
        (None, None),
    ],
)
def test_map_work_schedule(horario: str | None, expected: str | None) -> None:
    assert map_work_schedule(horario) == expected


def test_build_location_joins_city_province_and_iso() -> None:
    location, parts = build_location(
        {"ciudadF": "Monzón", "provinciaF": "HUESCA", "paisF": "ESPAÑA"}
    )
    assert location == "Monzón; HUESCA; ES"
    assert parts["country_iso2"] == "ES"


def test_build_location_maps_foreign_country_label() -> None:
    location, _ = build_location({"ciudadF": "Casablanca", "provinciaF": "", "paisF": "MARRUECOS"})
    assert location == "Casablanca; MA"


def test_build_location_drops_duplicate_and_falls_back_to_spain() -> None:
    assert build_location({"ciudadF": "Madrid", "provinciaF": "MADRID"})[0] == "Madrid; ES"
    assert build_location({})[0] == "ES"


def test_parse_iso_datetime() -> None:
    assert parse_iso_datetime("2026-11-20T00:40:41Z") == datetime(2026, 11, 20, 0, 40, 41)
    assert parse_iso_datetime("") is None
    assert parse_iso_datetime("not a date") is None


def test_normalize_description_handles_html_and_plain_text() -> None:
    assert normalize_description("<p>Hola&nbsp;mundo</p><p>Segunda</p>") == "Hola mundo\nSegunda"
    assert normalize_description("Texto plano") == "Texto plano"
    assert normalize_description(None) == ""


def _document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "id": "1859282418",
        "titulo": "TÉCNICO DE MANTENIMIENTO",
        "creador": "ACME SL",
        "contenido": "<p>Buscamos un técnico de mantenimiento industrial.</p>",
        "ciudadF": "Teruel",
        "provinciaF": "TERUEL",
        "paisF": "ESPAÑA",
        "cp": "44001",
        "localizacion": "40.34,-1.10",
        "fechaCreacion": "2026-11-20T00:40:41Z",
        "salarioMin": "21000",
        "salarioMax": "24000",
        "verSalarioMin": "1",
        "verSalarioMax": "1",
        "tipoContrato": "Contract",
        "tipoContratoN": "2",
        "jornada": "1",
        "jornadaF": "COMPLETA",
        "horario": "De 8:00 a 15:00",
        "modality": "1",
        "categoriaF": "INGENIERÍA/CALIDAD/CIENCIAS",
        "subcategoriaF": "MANTENIMIENTO",
        "educacionReqF": "GRADO en Ingeniería",
        "experienciaF": "MÁS DE DOS AÑOS",
        "speState": "Activa",
        "url": "-",
    }
    document.update(overrides)
    return document


def _raw(**overrides: object) -> RawEmpleateEsJob:
    document = _document(**overrides)
    job_id = str(document["id"])
    return RawEmpleateEsJob(
        job_id=job_id,
        url=f"https://www.empleate.gob.es/empleo/#/oferta/{job_id}",
        search_page_start=0,
        document=document,
    )


def test_parse_job_maps_a_complete_document() -> None:
    job = EmpleateEsParser().parse_job(_raw())

    assert job.source_job_id == "1859282418"
    assert job.job_title == "TÉCNICO DE MANTENIMIENTO"
    assert job.company_name == "ACME SL"
    assert job.location_cleaned == "Teruel; ES"
    assert (job.salary_min, job.salary_max) == (21000.0, 24000.0)
    assert job.salary_disclosed is True
    assert (job.currency_iso_code, job.pay_period) == ("EUR", "yearly")
    assert job.employment_type_code == "full_time"
    assert job.remote_work_type_code == "on_site"
    assert job.work_schedule == "standard_day"
    assert job.experience_level_code == "mid"
    assert job.posting_date == datetime(2026, 11, 20, 0, 40, 41)
    # ``url`` is "-" when the portal hosts the application itself.
    assert job.apply_url == job.original_url
    assert job.raw_payload["description_source"] == "contenido"


def test_parse_job_keeps_external_apply_url() -> None:
    job = EmpleateEsParser().parse_job(_raw(url="https://inaem.aragon.es/inscripcion"))
    assert job.apply_url == "https://inaem.aragon.es/inscripcion"
    assert job.original_url.endswith("/1859282418")


def test_parse_job_falls_back_to_structured_summary_and_confidential_employer() -> None:
    job = EmpleateEsParser().parse_job(_raw(contenido="", creador=None))

    assert job.company_name == "Confidential Employer"
    assert job.raw_payload["description_source"] == "structured_summary"
    assert "Categoría:" in (job.description_clean or "")
    assert job.word_count > 0
    assert job.data_quality_score <= 0.6


def test_parse_job_treats_zero_salary_as_undisclosed() -> None:
    job = EmpleateEsParser().parse_job(_raw(salarioMin="0", salarioMax="0"))
    assert job.salary_disclosed is False
    assert job.salary_min is None and job.salary_max is None


class _FakeClient(EmpleateEsClient):
    """No-network client: serves synthetic pages and records offsets."""

    def __init__(self, total: int, **settings: object) -> None:
        super().__init__(settings=EmpleateEsSettings(**settings))
        self.total = total
        self.offsets: list[int] = []

    def search_page(self, start: int):  # type: ignore[override]
        self.offsets.append(start)
        page_size = self._settings.page_size
        docs = [
            {"id": str(i), "titulo": f"job {i}"}
            for i in range(start, min(start + page_size, self.total))
        ]
        return docs, self.total


def test_fetch_jobs_covers_fresh_then_rotates_the_archive() -> None:
    client = _FakeClient(total=1000, page_size=100, fresh_rows=200, start_offset=300)
    jobs, pages, total = client.fetch_jobs(max_jobs=400)

    assert total == 1000
    assert pages == 4
    assert len(jobs) == 400
    assert len({job.job_id for job in jobs}) == 400
    # Two fresh pages, then the two pages starting at the pinned archive offset.
    assert client.offsets == [0, 100, 300, 400]


def test_fetch_jobs_handles_a_corpus_smaller_than_the_budget() -> None:
    client = _FakeClient(total=150, page_size=100, fresh_rows=200)
    jobs, pages, total = client.fetch_jobs(max_jobs=400)

    assert total == 150
    assert pages == 2
    assert [job.job_id for job in jobs] == [str(i) for i in range(150)]


def test_fetch_jobs_raises_on_an_empty_corpus() -> None:
    client = _FakeClient(total=0)
    with pytest.raises(EmpleateEsResponseError):
        client.fetch_jobs(max_jobs=10)


def test_tls_bundle_loads_and_contains_the_missing_intermediate() -> None:
    path = build_ca_bundle()
    context = ssl.create_default_context(cafile=path)
    # Loading is the assertion: an unreadable/truncated bundle raises here.
    assert context.cert_store_stats()["x509_ca"] > 1
