"""Parser for Empléate (Spain) search documents.

One Solr document carries the whole posting, so there is no detail-page
parsing here. The mapping decisions below were measured against live
documents and the portal's own master endpoints on 2026-11-20:

**Contract type.** ``open/master/contracttypes`` returns the authoritative
list, and ``tipoContratoN`` on each document is its ``id``::

    0 SIN ESPECIFICAR / " "        4 Mercantil / SelfEmployed
    1 Laboral indiferente / ContractToHire
    2 Laboral indefinido / Contract
    3 Laboral temporal / Temporary
    5 En prácticas / Internship    6 Formación y aprendizaje / Apprenticeship

``jornada`` is the day type from ``open/master/daytypes``:
``1 COMPLETA``, ``2 PARCIAL``, ``3 INDIFERENTE``, ``4 FLEXIBLE``.

The two combine into one ``ref.employment_types`` code. Internship,
apprenticeship, freelance and part-time are strong independent signals, so
they win outright; otherwise the contract type decides.

**Salary.** ``salarioMin``/``salarioMax`` are *strings* in mixed Spanish
formatting -- measured values include ``"15"``, ``"200"``, ``"30000"``,
``"21,000"``, ``"16261,86"`` and ``"0"``. ``0`` means "not stated", not
"zero euros". The rendered offer page appends the literal ``Brutos/año``
(gross per year), while the SPA's generated JSON-LD says
``unitText: MONTH``; the visible label is the one a human is shown, so
amounts are stored as ``yearly`` and the inconsistency is recorded in
``raw_payload``. The raw strings are kept there too.

**Location.** The board publishes ``ciudadF`` (municipality),
``provinciaF`` (province, one of exactly 52 values measured from the live
facet) and ``paisF`` (23,801 ES + ~20 foreign ads). The resolver splits on
``;`` and takes the most specific segment, so the three are joined with
``"; "`` and the province is seeded as a ``ref.regions`` row. The country
segment is emitted as an ISO 3166-1 alpha-2 code, which
``_match_country`` matches explicitly and which cannot be confused with a
city name.

**Remote modality.** ``modality`` codes measured from the facet:
``0`` No informado (24,091 ads), ``1`` Presencial (1,885), ``2`` A
distancia, ``3`` Teletrabajo, ``4`` Mixto (83). ``0`` is treated as
on-site with the raw value noted -- it is the portal's default, not a
claim of remote work.

**Work schedule.** ``horario`` is free text ("Jornada completa de 8:00 a
15:00", "Turnos rotativos", "Flexible", "Nocturno"); it is mapped by
keyword and left ``None`` when it only restates full/part-time hours.

**Experience.** ``experienciaF`` has exactly four measured values, so it
maps cleanly onto ``ref.experience_levels``.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.cleaning.common import CleanedJob

from .exceptions import EmpleateEsParseError
from .models import RawEmpleateEsJob

#: ``paisF`` label -> ISO 3166-1 alpha-2. Measured from the ``paisF`` facet
#: (23,801 ES plus ~20 foreign ads across these eleven labels).
_PAIS_TO_ISO2: dict[str, str] = {
    "ESPAÑA": "ES",
    "HOLANDA (PAISES BAJOS)": "NL",
    "FRANCIA": "FR",
    "ANDORRA": "AD",
    "ARGELIA": "DZ",
    "ALEMANIA": "DE",
    "AUSTRIA": "AT",
    "BÉLGICA": "BE",
    "CANADÁ": "CA",
    "IRLANDA": "IE",
    "MARRUECOS": "MA",
    "UGANDA": "UG",
}

#: ``open/master/contracttypes`` ids that map to one code regardless of hours.
_CONTRACT_OVERRIDES: dict[str, str] = {
    "4": "freelance",  # Mercantil / SelfEmployed
    "5": "internship",  # En prácticas / Internship
    "6": "apprenticeship",  # Formación y aprendizaje / Apprenticeship
}

#: ``modality`` code -> (remote_work_types code, raw label).
_MODALITY: dict[str, tuple[str, str]] = {
    "0": ("on_site", "No informado"),
    "1": ("on_site", "Presencial"),
    "2": ("remote_country", "A distancia"),
    "3": ("remote_country", "Teletrabajo"),
    "4": ("hybrid", "Mixto"),
}

_EXPERIENCE: dict[str, str] = {
    "NO SE REQUIERE": "entry",
    "MÁS DE SEIS MESES": "junior",
    "MÁS DE DOS AÑOS": "mid",
    "MÁS DE CINCO AÑOS": "senior",
}

_TIME_RANGE_RE = re.compile(r"\d{1,2}\s*[:h.]\s*\d{2}")
_BARE_RANGE_RE = re.compile(r"\d{1,2}\s*[-–]\s*\d{1,2}")
_WEEKEND_TERMS = ("fin de semana", "sábado", "sabado", "domingo")
_WEEKDAY_TERMS = ("l-v", "lunes", "martes", "miércoles", "miercoles", "jueves", "viernes")


def clean_text(value: Any) -> str:
    """Unescape entities and collapse whitespace."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split()).strip()


def parse_salary_amount(value: Any) -> float | None:
    """Parse a Spanish-formatted salary string into a positive float.

    Handles the formats actually measured: ``"15"``, ``"30000"``,
    ``"21,000"`` (comma as thousands separator), ``"16261,86"`` (comma as
    decimal) and ``"0"`` / empty (missing). A trailing group of exactly
    three digits after the only separator is read as thousands, which is
    the Spanish convention; otherwise it is a decimal.
    """
    if value is None:
        return None
    text = str(value).replace("\u00a0", " ").replace("€", "").strip()
    if not text:
        return None
    digits = re.sub(r"[^0-9,.\-]", "", text)
    if not digits:
        return None
    if "," in digits and "." in digits:
        if digits.rfind(",") > digits.rfind("."):
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif "," in digits:
        head, _, tail = digits.rpartition(",")
        digits = head.replace(",", "") + ("." if len(tail) != 3 else "") + tail
    elif "." in digits:
        head, _, tail = digits.rpartition(".")
        digits = head.replace(".", "") + ("." if len(tail) != 3 else "") + tail
    try:
        amount = float(digits)
    except ValueError:
        return None
    return amount if amount > 0 else None


def parse_salary_bounds(document: dict[str, Any]) -> tuple[float | None, float | None]:
    """Return ``(min, max)`` with hidden/zero bounds treated as missing."""
    minimum = parse_salary_amount(document.get("salarioMin"))
    maximum = parse_salary_amount(document.get("salarioMax"))
    if str(document.get("verSalarioMin", "1")).strip() == "0":
        minimum = None
    if str(document.get("verSalarioMax", "1")).strip() == "0":
        maximum = None
    if minimum is not None and maximum is not None and maximum < minimum:
        minimum, maximum = maximum, minimum
    return minimum, maximum


def map_employment_type(contract_id: Any, day_type_code: Any) -> str | None:
    """Combine ``tipoContratoN`` and ``jornada`` into one employment code."""
    contract = str(contract_id or "").strip()
    day_type = str(day_type_code or "").strip()

    override = _CONTRACT_OVERRIDES.get(contract)
    if override is not None:
        return override
    if day_type == "2":  # PARCIAL
        return "part_time"
    if contract == "3":  # Laboral temporal
        return "temporary"
    if contract == "1":  # Laboral indiferente
        return "contract"
    if contract == "2":  # Laboral indefinido
        return "full_time"
    if day_type == "1":  # COMPLETA
        return "full_time"
    return None


def map_work_schedule(horario: Any) -> str | None:
    """Map the free-text ``horario`` onto a ``core.jobs.work_schedule`` value.

    Measured values include "L-V 10.00 a 14.00 Sábados 10.00 a 14.00",
    "8-14", "Sábados y domingos 8:00h a 13:00h", "Turnos rotativos",
    "Nocturno" and plain restatements of full/part-time hours. A weekday
    term keeps an otherwise weekend-looking text on ``standard_day``:
    a Monday-to-Saturday schedule is not a weekend shift.
    """
    text = clean_text(horario).lower()
    if not text or text == "indiferente":
        return None
    if "flexib" in text:
        return "flexible"
    if "nocturn" in text or "noche" in text:
        return "night_shift"
    if "rotat" in text or "turno" in text:
        return "rotational"

    weekend = any(term in text for term in _WEEKEND_TERMS)
    weekday = any(term in text for term in _WEEKDAY_TERMS)
    if weekend and not weekday:
        return "weekend"
    if _TIME_RANGE_RE.search(text) or _BARE_RANGE_RE.fullmatch(text):
        return "standard_day"
    if weekend:
        return "weekend"
    return None


def map_remote(modality: Any) -> tuple[str, str]:
    """Return ``(remote_work_types code, raw label)`` for ``modality``."""
    key = str(modality if modality is not None else "0").strip()
    if key in _MODALITY:
        return _MODALITY[key]
    return "on_site", f"unknown modality {key!r}"


def build_location(document: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """Compose ``"<city>; <province>; <ISO2>"`` and return the raw parts.

    ``ciudadF`` was measured across 2,478 distinct municipalities; only
    Madrid and Barcelona collide with a seeded city, and both are Spanish,
    so keeping the municipality adds precision without a country risk.
    """
    city = clean_text(document.get("ciudadF"))
    province = clean_text(document.get("provinciaF"))
    pais_raw = clean_text(document.get("paisF"))
    country = _PAIS_TO_ISO2.get(pais_raw.upper(), pais_raw.upper() or "ES")

    parts: list[str] = []
    seen: set[str] = set()
    for part in (city, province, country):
        key = part.lower()
        if part and key not in seen:
            seen.add(key)
            parts.append(part)
    return ("; ".join(parts) if parts else "ES"), {
        "city": city,
        "province": province,
        "country_raw": pais_raw,
        "country_iso2": country,
    }


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse Solr's ``2026-08-24T17:44:23Z`` into a naive UTC datetime."""
    text = clean_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def normalize_description(raw: Any) -> str:
    """Strip markup, decode entities once and collapse blank lines."""
    if raw is None:
        return ""
    text = html.unescape(str(raw))
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text("\n", strip=True)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def structured_summary(document: dict[str, Any]) -> str:
    """A clearly-labelled summary for ads whose ``contenido`` is empty.

    About 15% of sampled ads carry fewer than ten words of body text. The
    fields below are the portal's own structured values, not invented
    prose; the raw ``contenido`` stays in ``raw_payload``.
    """
    lines = ["Oferta de empleo publicada en Empléate (SEPE)."]
    for label, key in (
        ("Categoría", "categoriaF"),
        ("Subcategoría", "subcategoriaF"),
        ("Formación requerida", "educacionReqF"),
        ("Experiencia", "experienciaF"),
        ("Jornada", "jornadaF"),
        ("Provincia", "provinciaF"),
        ("País", "paisF"),
    ):
        value = clean_text(document.get(key))
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


class EmpleateEsParser:
    """Turns Empléate Solr documents into validated ``CleanedJob`` records."""

    def parse_job(self, raw: RawEmpleateEsJob) -> CleanedJob:
        """Parse one search document into a ``CleanedJob``."""
        document = raw.document
        title = clean_text(document.get("titulo"))
        if not title:
            raise EmpleateEsParseError(f"no title in Empléate posting {raw.job_id} ({raw.url})")

        job_id = clean_text(document.get("id")) or raw.job_id
        company = clean_text(document.get("creador")) or "Confidential Employer"

        body = normalize_description(document.get("contenido"))
        if len(body.split()) < 5:
            body = structured_summary(document)
            description_source = "structured_summary"
        else:
            description_source = "contenido"

        location, location_parts = build_location(document)
        remote_code, modality_label = map_remote(document.get("modality"))
        employment_code = map_employment_type(
            document.get("tipoContratoN"), document.get("jornada")
        )
        work_schedule = map_work_schedule(document.get("horario"))
        experience_raw = clean_text(document.get("experienciaF"))
        experience_code = _EXPERIENCE.get(experience_raw.upper())

        salary_min, salary_max = parse_salary_bounds(document)
        salary_disclosed = salary_min is not None or salary_max is not None
        posting_date = parse_iso_datetime(document.get("fechaCreacion"))

        external_url = clean_text(document.get("url"))
        if not external_url.lower().startswith(("http://", "https://")):
            external_url = ""

        words = len(body.split())
        score = 0.4
        score += 0.2 if words >= 60 else (0.1 if words >= 20 else 0.0)
        score += 0.1 if company != "Confidential Employer" else 0.0
        score += 0.1 if location != "ES" else 0.0
        score += 0.1 if salary_disclosed else 0.0
        score += 0.05 if posting_date else 0.0
        if description_source == "structured_summary":
            score = min(score, 0.6)

        raw_payload = {
            "url": raw.url,
            "search_page_start": raw.search_page_start,
            "description_source": description_source,
            "salary_display": " - ".join(
                clean_text(document.get(key)) for key in ("salarioMin", "salarioMax")
            )
            or None,
            "salary_period_note": (
                "Offer page renders 'Brutos/año' (gross per year); the SPA-generated "
                "JSON-LD says unitText MONTH. Stored as yearly, following the visible "
                "label; the raw strings are in solr.salarioMin/salarioMax."
            ),
            "modality_raw": document.get("modality"),
            "modality_label": modality_label,
            "contract_type_raw": document.get("tipoContrato"),
            "contract_type_id": document.get("tipoContratoN"),
            "day_type_raw": document.get("jornadaF"),
            "work_schedule_raw": document.get("horario"),
            "education_required_raw": document.get("educacionReqF"),
            "experience_required_raw": document.get("experienciaF"),
            "category_raw": document.get("categoriaF"),
            "subcategory_raw": document.get("subcategoriaF"),
            "location_parts": location_parts,
            "postal_code": document.get("cp"),
            "coordinates": document.get("localizacion"),
            "external_url": external_url or None,
            "spe_state": document.get("speState"),
            "solr": document,
        }

        return CleanedJob(
            source_job_id=job_id,
            job_title=title,
            company_name=company,
            company_logo_url=None,
            skills=[],
            location_cleaned=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=body or None,
            word_count=words,
            apply_url=external_url or raw.url,
            original_url=raw.url,
            posting_date=posting_date,
            # The listing has no expiration field; ``open/offer/load/<id>``
            # carries one but would cost a request per ad for a single date.
            closing_date=None,
            data_quality_score=round(min(score, 0.95), 2),
            raw_payload=raw_payload,
            currency_iso_code="EUR",
            pay_period="yearly",
            employment_type_code=employment_code,
            experience_level_code=experience_code,
            remote_work_type_code=remote_code,
            work_schedule=work_schedule,
        )

    def parse_jobs(self, raw_jobs: list[RawEmpleateEsJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except EmpleateEsParseError as exc:
                logger.warning("Skipping Empléate posting {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Unexpected parse error for Empléate posting {}: {}",
                    raw.job_id,
                    exc,
                )
        return cleaned
