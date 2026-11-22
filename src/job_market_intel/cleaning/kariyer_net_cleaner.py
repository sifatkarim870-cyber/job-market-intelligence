"""Cleans validated Kariyer.net records into standardized, storage-ready records.

Kariyer.net publishes structured facts, not a JSON-LD block, so this cleaner
maps those fields directly rather than inferring from prose:

* ``workType`` (English, ``FullTime``) / ``workTypeText`` (Turkish,
  ``Tam Zamanlı``) -> ``employment_type_code``;
* ``workModel`` (``OnSite``/``Remote``/``Hybrid``) -> ``remote_work_type_code``;
* ``educationLevelText`` (Turkish) -> ``education_level_code``. The field is a
  list of EVERY level the ad accepts, ordered lowest first, so the requirement
  is the MINIMUM: a ``["Lise(Mezun)", ..., "Yüksek Lisans(Mezun)"]`` ad is a
  high-school role, not a master's one. Levels below high school
  (``İlk Öğretim``) have no equivalent in ``ref.education_levels`` and map to
  ``None`` rather than being forced onto ``high_school``;
* ``experienceText`` (``En az 1 yıl tecrübeli``) -> years -> ``experience_level_code``.

``location_cleaned`` folds Turkish letters to ASCII and drops the
``(Asya)``/``(Avr.)`` side markers Kariyer.net appends to Istanbul, because the
shared geo resolver's ``ref.cities`` seed holds ASCII names ("Istanbul") and
does not fold diacritics -- without this every posting falls through to the
country-only location even though "İstanbul" is seeded.

Salary is stored undisclosed in TRY. ``jobSalaryBudget`` was ``null`` on every
Turkish posting sampled on 2026-11-22, so no figure is invented; ``pay_period``
is a required column and Turkish salaries are quoted monthly, so it is set to
``monthly`` even though no amount is attached.

Descriptions arrive as HTML (``qualificationsWithHtml``) with a plain-text
twin (``qualifications``); the HTML is preferred and the plain text is the
fallback.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.qualification_mappers import (
    extract_normalized_benefits,
    extract_normalized_skills,
    extract_seniority_and_management,
    extract_work_schedule,
    map_experience_level,
    map_job_category,
)
from job_market_intel.cleaning.text_utils import clean_html_text, clean_plain_text
from job_market_intel.scrapers.kariyer_net.models import RawKariyerNetJob

#: Raw employment-type spellings -> ``ref.employment_types.code``. Keys are the
#: lowercased values as the API writes them (English ``workType`` and Turkish
#: ``workTypeText``). An unmapped value falls through to ``None``.
_EMPLOYMENT_TYPES: dict[str, str] = {
    "fulltime": "full_time",
    "full-time": "full_time",
    "full time": "full_time",
    "tam zamanlı": "full_time",
    "tam zamanli": "full_time",
    "parttime": "part_time",
    "part-time": "part_time",
    "part time": "part_time",
    "yarı zamanlı": "part_time",
    "yari zamanli": "part_time",
    "contract": "contract",
    "contractor": "contract",
    "sözleşmeli": "contract",
    "sozlesmeli": "contract",
    "temporary": "temporary",
    "dönemsel": "temporary",
    "donemsel": "temporary",
    "geçici": "temporary",
    "gecici": "temporary",
    "internship": "internship",
    "intern": "internship",
    "stajyer": "internship",
    "staj": "internship",
    "freelance": "freelance",
    "serbest": "freelance",
    "apprenticeship": "apprenticeship",
    "çırak": "apprenticeship",
    "cirak": "apprenticeship",
}

#: Classify one Turkish ``educationLevelText`` element. Ordered most-specific
#: first because ``Ön Lisans`` and ``Yüksek Lisans`` both contain ``lisans``.
#: ``None`` means "a level below high school, with no column to hold it".
_EDUCATION_BY_VALUE: list[tuple[str | None, tuple[str, ...]]] = [
    ("phd", ("doktora",)),
    ("master", ("yüksek lisans", "yuksek lisans")),
    ("associate", ("ön lisans", "on lisans", "meslek yüksek", "yüksek okul", "yuksek okul")),
    ("professional_certification", ("sertifika",)),
    ("bachelor", ("üniversite", "universite", "lisans")),
    ("high_school", ("lise",)),
    (None, ("ilk öğretim", "ilkogretim", "ilköğretim")),
]

#: Lowest-to-highest rank. ``educationLevelText`` lists EVERY level the ad
#: accepts from lowest to highest, so the requirement is the MINIMUM the list
#: allows -- the lowest-ranked code -- not the most specific match. Scanning for
#: the highest match turned a ``["Lise(Mezun)", ..., "Yüksek Lisans(Mezun)"]``
#: ad (a service role open to high-school graduates) into ``master``.
_EDUCATION_RANK: dict[str | None, int] = {
    None: 0,
    "high_school": 1,
    "professional_certification": 2,
    "associate": 3,
    "bachelor": 4,
    "master": 5,
    "phd": 6,
}

#: Turkish ``positionLevelText`` -> seniority vocabulary shared with the other
#: cleaners (``qualification_mappers.extract_seniority_and_management``). Ordered
#: most-senior first because ``Üst Düzey Yönetici`` contains ``yönetici``.
_POSITION_LEVELS: list[tuple[str, tuple[str, ...]]] = [
    ("executive", ("genel müdür", "genel mudur", "üst düzey yönetici", "ust duzey yonetici")),
    ("director", ("direktör", "direktor", "müdür", "mudur", "başkan", "baskan")),
    ("manager", ("orta düzey yönetici", "yönetici", "yonetici", "süpervizör", "supervizor")),
    ("team_lead", ("takım lideri", "takim lideri", "ekip lideri", "lider")),
    ("individual_contributor", ("uzman", "eleman", "memur", "personel", "stajyer", "asistan")),
]

_MANAGERIAL_ROLES = {"executive", "director", "manager"}

#: Turkish letters -> ASCII. ``ref.cities`` is seeded with ASCII spellings
#: ("Istanbul"), and the shared geo resolver lowercases without folding
#: diacritics, so ``"İstanbul"`` lowercases to ``"i̇stanbul"`` (i + combining dot)
#: and matches nothing. Folding here lets the resolver do its job instead of
#: every posting collapsing onto the country-only location.
_TURKISH_FOLD = str.maketrans(
    {
        "İ": "I",
        "ı": "i",
        "Ş": "S",
        "ş": "s",
        "Ğ": "G",
        "ğ": "g",
        "Ç": "C",
        "ç": "c",
        "Ö": "O",
        "ö": "o",
        "Ü": "U",
        "ü": "u",
        "Â": "A",
        "â": "a",
        "Î": "I",
        "î": "i",
        "Û": "U",
        "û": "u",
    }
)

#: ``"İstanbul(Asya)"`` / ``"İstanbul(Avr.)"`` -- the Asian- and European-side
#: markers Kariyer.net appends to Istanbul. The resolver recognises neither, and
#: the side is not a distinction ``ref.cities`` records, so the parenthetical is
#: dropped rather than stored.
_LOCATION_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")


def _clean_location(text: str | None) -> str | None:
    """Fold Turkish letters and drop parentheticals so a city can resolve."""
    if not text:
        return None
    folded = text.strip().translate(_TURKISH_FOLD)
    folded = _LOCATION_PARENTHETICAL.sub("", folded)
    folded = " ".join(folded.split())
    return folded or None


#: ``En az 3 yıl`` / ``3-5 yıl`` / ``5 yıl ve üzeri``.
_YEARS_RANGE = re.compile(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s*yıl", re.IGNORECASE)
_YEARS_MIN = re.compile(r"(?:en az\s*)?(\d{1,2})\s*\+?\s*yıl", re.IGNORECASE)
_NO_EXPERIENCE = re.compile(
    r"tecrübesiz|tecrubesiz|yeni mezun|deneyimsiz|no experience", re.IGNORECASE
)


def _map_employment_type(raw: str | None, text: str | None) -> str | None:
    for value in (raw, text):
        if not value:
            continue
        key = re.sub(r"\s+", " ", str(value).strip().lower())
        if key in _EMPLOYMENT_TYPES:
            return _EMPLOYMENT_TYPES[key]
    return None


def _map_remote_work(work_model_raw: str | None, is_remote_work: bool | None) -> str | None:
    model = (work_model_raw or "").strip().lower().replace(" ", "").replace("-", "")
    if model in {"remote", "fullyremote", "remoteonly"}:
        return "remote_country"
    if model == "hybrid":
        return "hybrid"
    if model in {"onsite", "office", "inoffice"}:
        return "on_site"
    if is_remote_work is True:
        return "remote_country"
    if is_remote_work is False:
        return "on_site"
    return None


def _map_education_level(values: list[str]) -> str | None:
    """The MINIMUM education level the ad accepts, across the whole list."""
    codes: list[str | None] = []
    for value in values:
        text = str(value).strip().lower()
        if not text:
            continue
        for code, needles in _EDUCATION_BY_VALUE:
            if any(needle in text for needle in needles):
                codes.append(code)
                break
    if not codes:
        return None
    return min(codes, key=lambda code: _EDUCATION_RANK.get(code, 99))


def _map_position_level(
    position_level_text: str | None, title: str | None, description: str | None
) -> tuple[str | None, bool | None]:
    level = (position_level_text or "").lower()
    if level:
        for code, needles in _POSITION_LEVELS:
            if any(needle in level for needle in needles):
                managerial = (
                    True
                    if code in _MANAGERIAL_ROLES
                    else (False if code == "individual_contributor" else None)
                )
                return code, managerial
    # Fall back to the shared title/text extractor.
    return extract_seniority_and_management(title, description)


def _parse_experience_years(text: str | None) -> tuple[int | None, int | None, int | None]:
    """Return ``(min_years, max_years, level_basis)`` from Turkish prose."""
    if not text:
        return None, None, None
    if _NO_EXPERIENCE.search(text):
        return 0, 0, 0
    match = _YEARS_RANGE.search(text)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        if 0 <= low <= high <= 40:
            return low, high, low
    match = _YEARS_MIN.search(text)
    if match:
        value = int(match.group(1))
        if 0 <= value <= 40:
            return value, None, value
    return None, None, None


def _to_datetime(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime(value.year, value.month, value.day)


def _quality_score(*, description: str, has_location: bool, skills_normalized: str | None) -> float:
    """Four-signal completeness score, identical in shape to the other cleaners."""
    signals = [
        False,  # salary_disclosed -- Kariyer.net never publishes a figure
        has_location,
        skills_normalized is not None,
        len(description.split()) >= 50,
    ]
    return round(sum(signals) / len(signals), 2)


class KariyerNetCleaner:
    """Turns ``RawKariyerNetJob`` records into ``CleanedJob``."""

    def clean_job(self, raw: RawKariyerNetJob) -> CleanedJob:
        title = clean_plain_text(raw.title) or raw.title

        body = clean_html_text(raw.description_html) or clean_plain_text(raw.description_text)
        word_count = len(body.split()) if body else 0
        full_text = "\n\n".join(part for part in (title, body) if part)

        employment_code = _map_employment_type(raw.employment_type_raw, raw.employment_type_text)
        remote_code = _map_remote_work(raw.work_model_raw, raw.is_remote_work)
        education_code = _map_education_level(raw.education_level_text)
        seniority, is_managerial = _map_position_level(raw.position_level_text, title, body)

        exp_min, exp_max, level_basis = _parse_experience_years(raw.experience_text)
        experience_code = (
            map_experience_level(None, None, years=level_basis) if level_basis is not None else None
        )

        skills_normalized = extract_normalized_skills(full_text)
        benefits_normalized = extract_normalized_benefits(full_text)
        work_schedule = extract_work_schedule(full_text)
        category_code = map_job_category(title, raw.job_category_raw)

        location_cleaned = _clean_location(raw.location_text) or "Turkey"

        posting_dt = _to_datetime(raw.posting_date)
        closing_dt = _to_datetime(raw.closing_date)
        if posting_dt and closing_dt and closing_dt < posting_dt:
            closing_dt = None

        payload = dict(raw.raw or {})
        payload.update(
            {
                "salary_published": False,
                "employment_type_raw": raw.employment_type_raw,
                "employment_type_text": raw.employment_type_text,
                "work_model_raw": raw.work_model_raw,
                "is_remote_work": raw.is_remote_work,
                "position_level_text": raw.position_level_text,
                "education_level_text": raw.education_level_text,
                "experience_text": raw.experience_text,
                "company_sector": raw.company_sector,
                "language": "tr",
            }
        )

        return CleanedJob(
            source_job_id=raw.source_job_id,
            job_title=title,
            company_name=clean_plain_text(raw.company_name) or "Unknown employer",
            company_logo_url=raw.company_logo_url or None,
            skills=[],
            location_cleaned=location_cleaned,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=body or None,
            word_count=word_count,
            apply_url=raw.job_url,
            original_url=raw.job_url or "",
            posting_date=posting_dt,
            closing_date=closing_dt,
            data_quality_score=_quality_score(
                description=body,
                has_location=bool(raw.location_text and raw.location_text.strip()),
                skills_normalized=skills_normalized,
            ),
            raw_payload=payload,
            currency_iso_code="TRY",
            pay_period="monthly",
            employment_type_code=employment_code,
            education_level_code=education_code,
            experience_level_code=experience_code,
            remote_work_type_code=remote_code,
            job_category_code=category_code,
            experience_years_min=exp_min,
            experience_years_max=exp_max,
            seniority_role_type=seniority,
            is_managerial=is_managerial,
            work_schedule=work_schedule,
            skills_normalized=skills_normalized,
            benefits_normalized=benefits_normalized,
        )

    def clean_jobs(self, jobs: list[RawKariyerNetJob]) -> list[CleanedJob]:
        cleaned: list[CleanedJob] = []
        failures: list[str] = []
        for raw in jobs:
            try:
                cleaned.append(self.clean_job(raw))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{raw.source_job_id}: {type(exc).__name__}: {exc}")
        if failures:
            logger.warning(
                "dropped {} of {} Kariyer.net postings that could not be cleaned: {}",
                len(failures),
                len(jobs),
                failures[:3],
            )
        if jobs and not cleaned:
            logger.error(
                "every Kariyer.net posting failed cleaning -- the scraper would "
                "report success while persisting nothing"
            )
        return cleaned
