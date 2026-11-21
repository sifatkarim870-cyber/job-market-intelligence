"""Cleans validated ANPE Burkina Faso records into storage-ready records.

Same boundary as the other cleaners: ``RawAnpeBfJob`` -> ``CleanedJob``,
only removing noise with no analytical value, never making judgment calls
about meaning.

ANPE-BF-specific quirks handled here (measured on all 97 posts,
2026-11-21):

* **No salary is ever stated.** "francs CFA"/"F CFA" appears only in
  stamp-fee instructions ("une demande manuscrite timbree a 200 F CFA"),
  never as pay, so ``salary_disclosed`` is always False and no bounds are
  invented. Currency is XOF (Burkina Faso's CFA franc). ``pay_period`` is
  a required str on ``CleanedJob`` with no "unknown" member, so it takes
  ``DEFAULT_PAY_PERIOD`` -- the same inert placeholder Jobicy, Reed and
  TheMuse use -- and is never used to annualise anything (see the field
  comment in ``clean_job``).
* **Location is free prose.** "commune de <name>" appears in 50 of 97
  bodies, with "Mairie <name>", "province du <name>" and "region de
  <name>" variants. The cleaner lifts the first such phrase into
  ``location_cleaned``; the shared resolver then places the row in
  Burkina Faso (the commune names are not in the curated city seed).
* **Contract type is prose.** "CDI"/"duree indeterminee" -> ``full_time``,
  "CDD"/"duree determinee" -> ``contract``, ``stagiaire``/"stage
  d'initiation" -> ``internship``, "temps partiel" -> ``part_time``. A bare
  "stage" is usually "attestation de stage" (proof of a *past* internship)
  and is deliberately NOT mapped. Absent wording stays unset rather than
  guessed.
* **Titles can be Unicode mathematical-bold text** ("COMMUNIQUE" built
  from U+1D5D4 etc.); NFKC normalization in the model plus
  ``clean_plain_text`` here turns them into searchable Latin text.
* **No skills are published**; ``skills`` stays empty. The shared
  skill-extraction step can mine the description later.
* **The employer is not a field.** The agency is the publisher and is used
  as ``company_name``; client mairies/agencies are named only inside the
  prose and are deliberately not guessed from the title.
"""

from __future__ import annotations

import re

from loguru import logger

from job_market_intel.scrapers.anpe_bf.models import RawAnpeBfJob

from .common import CleanedJob
from .text_utils import clean_html_text, clean_plain_text

_SUBSTANTIAL_DESCRIPTION_WORD_COUNT = 20

#: ``CleanedJob.pay_period`` is a required ``str`` with no "unknown" member.
#: No ANPE Burkina Faso notice states a salary, let alone a period, so this
#: documented placeholder is carried only to satisfy the model -- with
#: ``salary_min``/``salary_max`` both None, nothing is ever annualised from
#: it. Matches the Jobicy/Reed/TheMuse convention.
DEFAULT_PAY_PERIOD = "yearly"

#: One capitalized word of a free-text place name, e.g. "Tougan",
#: "Gbomblora", "Béguédo", "Kouka", "Bobo-Dioulasso". French function words
#: ("La Direction", "Le Maire", "Des Services") are excluded so a following
#: sentence fragment is not swallowed into the place name.
_STOPWORD = r"(?:[Ll]a|[Ll]e|[Ll]es|[Dd]es|[Dd]u|[Dd]e|[Ee]t|[Uu]n|[Uu]ne|[Aa]u|[Aa]ux)"
_PLACE_WORD = (
    rf"(?!{_STOPWORD}\b)(?![Ll]['’])(?![Dd]['’])(?![Qq]u['’])"
    r"[A-ZÀ-ÖØ-Þ](?:[\w'’\-]*[\w])?"
)

#: Ordered most-specific first; each captures up to two capitalized words
#: so "Mairie de Pibaore La Direction Regionale" yields just "Pibaore".
_LOCATION_PATTERNS = (
    re.compile(rf"\b[Cc]ommune\s+d[eu]\s+({_PLACE_WORD}(?:\s+{_PLACE_WORD}){{0,1}})"),
    re.compile(rf"\b[Mm]airie\s+(?:de\s+|d[eu]\s+)?({_PLACE_WORD}(?:\s+{_PLACE_WORD}){{0,1}})"),
    re.compile(rf"\b[Pp]rovince\s+d[eu]\s+({_PLACE_WORD}(?:\s+{_PLACE_WORD}){{0,1}})"),
    re.compile(
        rf"\b[Rr][ée]gion\s+(?:de\s+|du\s+|des\s+)?({_PLACE_WORD}(?:\s+{_PLACE_WORD}){{0,1}})"
    ),
)

_CDI = re.compile(r"\bcdi\b|dur[ée]e\s+ind[ée]termin[ée]e", re.IGNORECASE)
_CDD = re.compile(r"\bcdd\b|dur[ée]e\s+d[ée]termin[ée]e", re.IGNORECASE)
# "stage" alone is almost always "attestation de stage" (proof of a past
# internship), so only an explicit internship posting is mapped.
_INTERNSHIP = re.compile(r"stage\s+d['’]initiation|stagiaire", re.IGNORECASE)
_PART_TIME = re.compile(r"temps\s+partiel", re.IGNORECASE)
_FULL_TIME = re.compile(r"temps\s+plein|plein\s+temps", re.IGNORECASE)


def _compute_data_quality_score(
    *,
    salary_disclosed: bool,
    location_cleaned: str | None,
    skills: list[str],
    word_count: int,
) -> float:
    """Same four-signal, equally-weighted formula every other cleaner uses."""
    signals = [
        salary_disclosed,
        location_cleaned is not None,
        len(skills) > 0,
        word_count >= _SUBSTANTIAL_DESCRIPTION_WORD_COUNT,
    ]
    return round(sum(signals) / len(signals), 2)


def extract_location(text: str | None) -> str | None:
    """The first commune/mairie/province/region phrase in the prose."""
    if not text:
        return None
    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def map_employment_type(text: str | None) -> str | None:
    """Map the prose contract wording onto ref.employment_types.code."""
    if not text:
        return None
    # CDI before CDD: "CDI" is not a substring of "CDD", but the phrases
    # can co-occur in a notice listing several posts; the first stated is
    # the one the cleanser keeps if only one flag can apply.
    if _CDI.search(text):
        return "full_time"
    if _CDD.search(text):
        return "contract"
    if _PART_TIME.search(text):
        return "part_time"
    if _INTERNSHIP.search(text):
        return "internship"
    if _FULL_TIME.search(text):
        return "full_time"
    return None


class AnpeBfCleaner:
    """Cleans a batch of validated ANPE Burkina Faso records into CleanedJob."""

    def clean_job(self, raw_job: RawAnpeBfJob) -> CleanedJob:
        """Clean a single validated ANPE Burkina Faso record."""
        description_clean = clean_html_text(raw_job.description_html) or clean_html_text(
            raw_job.excerpt_html
        )
        description_clean = description_clean or ""
        title = clean_plain_text(raw_job.job_title) or raw_job.job_title
        location_cleaned = extract_location(description_clean or title)
        word_count = len(description_clean.split()) if description_clean else 0
        skills: list[str] = []

        return CleanedJob(
            source_job_id=raw_job.source_job_id,
            job_title=title,
            company_name=clean_plain_text(raw_job.company_name) or raw_job.company_name,
            # No employer logo is published anywhere on the site.
            company_logo_url=None,
            skills=skills,
            location_cleaned=location_cleaned,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=description_clean,
            word_count=word_count,
            apply_url=raw_job.original_url,
            original_url=raw_job.original_url,
            posting_date=raw_job.posting_date,
            closing_date=None,
            data_quality_score=_compute_data_quality_score(
                salary_disclosed=False,
                location_cleaned=location_cleaned,
                skills=skills,
                word_count=word_count,
            ),
            raw_payload=raw_job.raw_payload,
            # Burkina Faso's CFA franc; the notices never quote pay, so
            # salary_disclosed is False and no bounds are invented. The
            # required pay_period str takes the documented inert default.
            currency_iso_code="XOF",
            pay_period=DEFAULT_PAY_PERIOD,
            employment_type_code=map_employment_type(description_clean),
            remote_work_type_code=None,
        )

    def clean_jobs(self, raw_jobs: list[RawAnpeBfJob]) -> list[CleanedJob]:
        """Clean a batch, skipping (not crashing on) any record that fails."""
        cleaned_jobs: list[CleanedJob] = []
        for raw_job in raw_jobs:
            try:
                cleaned_jobs.append(self.clean_job(raw_job))
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                logger.error(
                    "Unexpected error cleaning ANPE Burkina Faso post {}: {}",
                    raw_job.source_job_id,
                    exc,
                )
                continue

        logger.info(
            "ANPE Burkina Faso cleaning complete: {} cleaned, {} failed, {} total records.",
            len(cleaned_jobs),
            len(raw_jobs) - len(cleaned_jobs),
            len(raw_jobs),
        )
        return cleaned_jobs
