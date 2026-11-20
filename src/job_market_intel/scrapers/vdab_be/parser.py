"""Parser for VDAB (vdab.be) vacancy detail payloads.

The REST detail endpoint returns a JSON object whose fields are the board's own
Dutch vocabulary. The mapping onto the shared ``CleanedJob`` contract is:

  * **Title** is the Schema.org ``jobPosting.title`` (== ``functie.naam``).
  * **Company** is ``jobPosting.hiringOrganization.name`` (== the listing's
    ``vacatureBedrijfsnaam`` / ``leverancier.naam``).
  * **Description** is ``functie.omschrijving.plainText`` -- the same text as
    the Schema.org markdown ``jobPosting.description`` but with markdown
    artifacts already removed. Measured on 12 sampled ads the two are equal in
    length ordering (plainText 443-2,597 chars), and on 8 other sampled ads
    ``plainText`` was always present. If it is ever missing, the markdown
    ``jobPosting.description`` is stripped and used instead.
  * **Location** is the first ``jobPosting.jobLocation[].address.addressLocality``
    (an ALL-CAPS Belgian place name, title-cased for display), falling back to
    ``profiel.tewerkstellingsLocatie.regioOfAdres`` then the company
    municipality, always composed with the home country.
  * **Posting date** is ``jobPosting.datePosted`` (== ``eerstePublicatieDatum``).
    **Closing date** is ``jobPosting.validThrough`` when the employer publishes
    one -- 12 of 200 sampled ads did (dates 1-3 months out) -- and ``None``
    otherwise, since no other end-date field exists in the payload. It is
    dropped if it would precede the posting date.
  * **Salary.** The payload publishes no salary field at all (``baseSalary`` is
    absent and no ``loon``/``wedde`` amount field exists), so no amount is
    invented; rows state EUR / monthly with ``salary_disclosed=False``.
  * **Apply URL** is the board's own ad page, which carries the live apply
    button. The employer's ``profiel.sollicitatieInfo.logischeLocatie.webadres``
    is frequently a third-party redirect/campaign link, so it is stored in
    ``raw_payload["external_apply_url"]`` rather than as ``apply_url``.
  * **Employment type** is read from the board's richest signal,
    ``functie.arbeidscircuit.code`` (its own contract vocabulary), resolved by
    ``profiel.dienstregeling.arbeidsDuur`` (full/part time) or the Schema.org
    ``jobPosting.employmentType`` for the ordinary-contract codes. A code with
    no honest ``ref.employment_types`` equivalent (Flexijob, Werfreserve,
    recruitment exam) is stored as None rather than guessed.
  * **Remote work.** The payload has no structured remote field: there is no
    ``jobLocationType``, and the search filter catalogue has no telewerk/remote
    facet. Remote is therefore read from an unambiguous Dutch/French phrase in
    the title and description (see ``detect_remote``), defaulting to ``on_site``.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.cleaning.text_utils import clean_html_text, clean_plain_text

from .exceptions import VdabParseError
from .models import RawVdabJob

HOME_COUNTRY = "Belgium"
HOME_CURRENCY = "EUR"

#: ``functie.arbeidscircuit.code`` -> a ``ref.employment_types.code``. Only the
#: codes that directly imply a type are listed; ``G``/``GC`` (ordinary
#: employment) resolve full/part from the working-time code, and ``FL``/``WS``/
#: ``E`` have no honest code and are deliberately absent (-> None).
_ARBEIDSCIRCUIT_DIRECT: dict[str, str] = {
    "GB": "part_time",  # Beperkte tewerkstelling <13 uren/week
    "Z": "freelance",  # Zelfstandige activiteit
    "I": "temporary",  # Interimcontract
    "IV": "temporary",  # Interim met optie 'vast werk'
    "T": "temporary",  # Tijdelijke job
    "Q": "temporary",  # Vervangingscontract brugpensioen
    "V": "part_time",  # Studentenjob
    "MO": "apprenticeship",  # Middenstandsopleiding
}
_ARBEIDSCIRCUIT_REGULAR = frozenset({"G", "GC"})

#: Schema.org ``employmentType`` -> a ``ref.employment_types.code``.
_SCHEMA_EMPLOYMENT_MAP: dict[str, str] = {
    "FULL_TIME": "full_time",
    "PART_TIME": "part_time",
    "CONTRACTOR": "freelance",
    "CONTRACT": "contract",
    "TEMPORARY": "temporary",
    "INTERN": "internship",
    "INTERNSHIP": "internship",
    "APPRENTICESHIP": "apprenticeship",
    "PERMANENT": "full_time",
}

#: Unambiguous full-remote phrases (Dutch/French).
_FULL_REMOTE_MARKERS = (
    "100% telewerk",
    "100 % telewerk",
    "100% thuiswerk",
    "100 % thuiswerk",
    "volledig telewerk",
    "volledig thuiswerk",
    "volledig van thuis",
    "voltijds telewerk",
    "fulltime telewerk",
    "100% télétravail",
    "télétravail complet",
    "100% remote",
    "volledig remote",
)
#: Unambiguous hybrid phrases (Dutch/French).
_HYBRID_MARKERS = (
    "hybride",
    "gedeeltelijk telewerk",
    "deels telewerk",
    "deeltijds telewerk",
    "enkele dagen telewerk",
    "dag telewerk",
    "dagen telewerk",
    "telewerk mogelijk",
    "thuiswerk mogelijk",
    "mogelijkheid tot telewerk",
    "mogelijkheid tot thuiswerk",
    "deels van thuis",
    "télétravail partiel",
    "télétravail possible",
)
_GLOBAL_MARKERS = ("wereldwijd", "worldwide", "global", "anywhere", "any country")

#: Markdown artifacts still present in ``jobPosting.description``.
_MD_BOLD_RE = re.compile(r"\*\*([^*]{1,300})\*\*")
_MD_BULLET_RE = re.compile(r"(?m)^\s*[-*]\s+")
_MD_HEADING_RE = re.compile(r"(?m)^\s*#{1,6}\s*")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def clean_text(value: Any) -> str:
    """Decode entities and collapse whitespace to a single line."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split()).strip()


def _titlecase_place(value: str) -> str:
    """Title-case an ALL-CAPS Belgian place name, keeping hyphens intact."""
    return " ".join(
        "-".join(part.capitalize() for part in token.split("-")) for token in value.split()
    )


def _map_schema_employment(raw_types: Any) -> str | None:
    """First *single* distinct Schema.org employmentType, or None.

    Two different recognized codes (e.g. ``FULL_TIME`` + ``CONTRACTOR``) mean
    the ad offers either, so no single code is a correct answer.
    """
    items = raw_types if isinstance(raw_types, list) else ([raw_types] if raw_types else [])
    codes: set[str] = set()
    for raw in items:
        key = re.sub(r"[^A-Z]+", "_", str(raw).strip().upper()).strip("_")
        code = _SCHEMA_EMPLOYMENT_MAP.get(key)
        if code:
            codes.add(code)
    if len(codes) == 1:
        return next(iter(codes))
    return None


def map_employment_type(
    circuit_code: str | None,
    working_time_code: str | None,
    raw_types: Any,
) -> str | None:
    """Return one ``ref.employment_types.code`` for the ad, or None.

    ``functie.arbeidscircuit.code`` is the board's own contract vocabulary and
    is the primary signal. Ordinary employment (``G``/``GC``) is split
    full/part from ``profiel.dienstregeling.arbeidsDuur`` (``V``/``D``), then
    Schema.org. Codes with no honest equivalent (``FL`` Flexijob, ``WS``
    Werfreserve, ``E`` recruitment exam) return None rather than a guess.
    """
    code = (circuit_code or "").strip().upper()
    if code == "FL" or code == "WS" or code == "E":
        return None
    if code in _ARBEIDSCIRCUIT_DIRECT:
        return _ARBEIDSCIRCUIT_DIRECT[code]
    if code in _ARBEIDSCIRCUIT_REGULAR or not code:
        duur = (working_time_code or "").strip().upper()
        if duur == "D":
            return "part_time"
        if duur == "V":
            # Fall through only if Schema.org disagrees is not needed: an
            # ordinary contract is full-time unless arbeidsDuur says part-time.
            return "full_time"
    return _map_schema_employment(raw_types)


def detect_remote(*texts: str | None) -> str:
    """Return a ``ref.remote_work_types`` code from title/description text.

    The board publishes no structured remote field, so this is a conservative
    phrase scan: only unambiguous wording assigns hybrid/remote, and the
    default for a Belgium-based board with no such wording is ``on_site``.
    """
    haystack = " ".join(text.lower() for text in texts if text)
    if any(marker in haystack for marker in _FULL_REMOTE_MARKERS):
        if any(marker in haystack for marker in _GLOBAL_MARKERS):
            return "remote_global"
        return "remote_country"
    if any(marker in haystack for marker in _HYBRID_MARKERS):
        return "hybrid"
    return "on_site"


def _titlecase_or_blank(value: str) -> str:
    return _titlecase_place(value) if value else ""


def build_location(payload: dict[str, Any], job_posting: dict[str, Any]) -> str:
    """Compose a readable ``"<place>, Belgium"`` location string."""
    profiel = payload.get("profiel") or {}
    listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
    locality = ""

    locations = job_posting.get("jobLocation") or []
    if isinstance(locations, list):
        for loc in locations:
            if isinstance(loc, dict):
                address = loc.get("address") or {}
                candidate = clean_text(address.get("addressLocality"))
                if candidate:
                    locality = candidate
                    break

    if not locality:
        tewerkstelling = profiel.get("tewerkstellingsLocatie") or {}
        locality = clean_text(tewerkstelling.get("regioOfAdres"))
        if not locality:
            bedrijf = tewerkstelling.get("bedrijfsLocatie") or {}
            structured = bedrijf.get("gestructureerdAdres") or {}
            locality = clean_text(structured.get("gemeente"))
    if not locality:
        locality = clean_text(listing.get("tewerkstellingsLocatieRegioOfAdres"))

    locality = _titlecase_or_blank(locality)
    if locality and locality.lower() in {HOME_COUNTRY.lower(), "be", "belgie", "belgië"}:
        locality = ""
    parts = [part for part in (locality, HOME_COUNTRY) if part]
    return ", ".join(dict.fromkeys(parts)) or HOME_COUNTRY


def strip_markdown(text: str) -> str:
    """Remove the few markdown artifacts the Schema.org description carries."""
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_BULLET_RE.sub("", text)
    text = _MD_HEADING_RE.sub("", text)
    return text


def extract_description(job_posting: dict[str, Any], functie: dict[str, Any]) -> tuple[str, str]:
    """Return ``(description, source)`` preferring the plain-text field."""
    omschrijving = functie.get("omschrijving") or {}
    plain = clean_plain_text(omschrijving.get("plainText") or "")
    if plain:
        return plain, "functie_plain_text"

    markdown = job_posting.get("description") or ""
    if markdown:
        stripped = clean_plain_text(strip_markdown(str(markdown)))
        if stripped:
            return stripped, "job_posting_markdown"

    html_body = clean_html_text(omschrijving.get("html") or "")
    if html_body:
        return html_body, "functie_html"
    return "", "none"


def parse_date(value: Any) -> datetime | None:
    """Parse an ISO-8601 (or date-first) timestamp into a naive midnight date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        try:
            return datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    day_first = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if day_first:
        try:
            return datetime(
                int(day_first.group(3)),
                int(day_first.group(2)),
                int(day_first.group(1)),
            )
        except ValueError:
            return None
    return None


def _as_job_posting(payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    """The Schema.org ``jobPosting`` block, decoded from its JSON string."""
    raw = payload.get("jobPosting")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            raise VdabParseError(f"jobPosting JSON decode failed for {job_id}: {exc}") from exc
        if isinstance(decoded, dict):
            return decoded
    return {}


class VdabParser:
    """Extracts structured ``CleanedJob`` records from VDAB detail payloads."""

    def parse_job(self, raw: RawVdabJob) -> CleanedJob:  # noqa: C901 - field-by-field contract
        """Parse one VDAB detail payload into a ``CleanedJob``."""
        payload = dict(raw.payload)
        payload.setdefault("listing", raw.listing)
        job_posting = _as_job_posting(payload, raw.job_id)
        functie = payload.get("functie") or {}
        profiel = payload.get("profiel") or {}

        title = clean_text(job_posting.get("title")) or clean_text(functie.get("naam"))
        if not title:
            raise VdabParseError(f"no title in vdab.be ad {raw.job_id} ({raw.url})")

        organization = job_posting.get("hiringOrganization") or {}
        if isinstance(organization, str):
            organization = {"name": organization}
        company = clean_text(organization.get("name"))
        if not company:
            company = clean_text(raw.listing.get("vacatureBedrijfsnaam"))
        if not company:
            company = clean_text((payload.get("leverancier") or {}).get("naam"))
        if not company:
            company = "Confidential Employer"

        logo = clean_text(organization.get("logo")) or None
        if not logo:
            opmaak = payload.get("opmaak") or {}
            logo = clean_text(opmaak.get("logo")) or None
        if not logo:
            opmaak = raw.listing.get("opmaak") or {}
            if isinstance(opmaak, dict):
                logo = clean_text(opmaak.get("logo")) or None

        description, description_source = extract_description(job_posting, functie)
        word_count = len(description.split()) if description else 0

        circuit = functie.get("arbeidscircuit") or {}
        circuit_code = clean_text(circuit.get("code"))
        dienstregeling = profiel.get("dienstregeling") or {}
        duur = dienstregeling.get("arbeidsDuur") or {}
        duur_code = clean_text(duur.get("code"))
        raw_types = job_posting.get("employmentType")
        employment_code = map_employment_type(circuit_code, duur_code, raw_types)

        remote_code = detect_remote(title, description)

        posting_date = parse_date(job_posting.get("datePosted")) or parse_date(
            payload.get("eerstePublicatieDatum")
        )
        closing_date = parse_date(job_posting.get("validThrough"))
        if posting_date and closing_date and closing_date < posting_date:
            closing_date = None

        location = build_location(payload, job_posting)

        offer = profiel.get("voorgesteldeArbeidsovereenkomst") or {}
        arbeidscontract = offer.get("arbeidscontract") or {}
        sollicitatie = profiel.get("sollicitatieInfo") or {}
        logische_locatie = sollicitatie.get("logischeLocatie") or {}
        # Where the employer asks applicants to go. It is frequently a
        # third-party redirect/short link, so it is kept as metadata and the
        # board's own ad page stays the canonical apply URL -- the page carries
        # the live apply button and does not rot with a campaign link.
        external_apply_url = clean_text(logische_locatie.get("webadres")) or None

        # Same convention as the other bespoke parsers: a full body scores 0.95,
        # a short one 0.7, so the score still separates thin ads from rich ones.
        quality = 0.95 if word_count > 50 else 0.7

        raw_payload: dict[str, Any] = {
            "url": raw.url,
            "description_source": description_source,
            "listing": raw.listing,
            "arbeidscircuit": circuit,
            "arbeidsduur": duur,
            "arbeidscontract": arbeidscontract,
            "employment_type_raw": raw_types,
            "first_published": payload.get("eerstePublicatieDatum"),
            "last_modified": payload.get("laatsteWijzigingDatum"),
            "status": payload.get("status"),
            "gesloten": payload.get("gesloten"),
            "referentie": payload.get("referentie"),
            "jobdomeinen": profiel.get("jobdomeinen"),
            "studies": profiel.get("studies"),
            "talenkennis": profiel.get("talenKennis"),
            "job_location": job_posting.get("jobLocation"),
            "external_apply_url": external_apply_url,
        }

        return CleanedJob(
            source_job_id=raw.job_id,
            job_title=title,
            company_name=company,
            company_logo_url=logo,
            skills=[],
            location_cleaned=location,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=description,
            word_count=word_count,
            apply_url=raw.url,
            original_url=raw.url,
            posting_date=posting_date,
            closing_date=closing_date,
            data_quality_score=quality,
            raw_payload=raw_payload,
            currency_iso_code=HOME_CURRENCY,
            pay_period="monthly",
            employment_type_code=employment_code,
            remote_work_type_code=remote_code,
        )

    def parse_jobs(self, raw_jobs: list[RawVdabJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except VdabParseError as exc:
                logger.warning("Skipping vdab.be ad {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unexpected parse error for vdab.be ad {}: {}", raw.job_id, exc)
        return cleaned
