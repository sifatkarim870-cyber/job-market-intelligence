"""Parses a Revolico (Cuba) item page into a ``RawRevolicoCuJob``.

No JSON-LD, but no HTML scraping either: the page embeds the Apollo cache in
``<script id="__NEXT_DATA__">`` and the ad is the ``AdType:*`` entry of
``props.pageProps.__APOLLO_STATE__``. Measured 2026-11-21 on
``/item/se-busca-custodio-de-la-finca-55794055``::

    "AdType:55794055": {"__typename": "AdType", "id": "55794055",
        "title": "Se busca: Custodio de La Finca",
        "description": "Se busca: Custodio de La Finca\\n_\\n...",
        "price": 1000, "currency": "CUP",
        "province": {"__ref": "ProvinceType:1"},
        "municipality": {"__ref": "MunicipalityType:43"},
        "subcategory": {"__ref": "CategoryType:1301"},
        "updatedOnByUser": "2026-11-20T20:51:46.137Z", ...}

Each piece has a trap:

* **No original posting date.** Only ``updatedOnByUser`` (the last bump) exists;
  its date is used and flagged as such in ``raw_payload``.
* **No employer.** The ad's ``name`` is the poster, kept on the model but never
  promoted to ``company_name``.
* **``price`` is not a salary.** 55 of 102 sampled ads carry none and many of
  the rest carry a placeholder ``1``; both price and currency are kept in
  ``raw_payload`` only.
* Provinces, municipalities and subcategories are Apollo *references*
  (``{"__ref": "ProvinceType:1"}``) that must be resolved against the same
  state object.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from job_market_intel.scrapers.revolico_cu.client import apollo_state
from job_market_intel.scrapers.revolico_cu.models import RawRevolicoCuJob

from .exceptions import RevolicoCuParseError

_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

_REMOTE_PHRASES = (
    "teletrabajo",
    "trabajo remoto",
    "remoto",
    "a distancia",
    "desde casa",
    "home office",
)


def _resolve(state: dict[str, Any], ref: Any) -> dict[str, Any] | None:
    """Follow one Apollo ``{"__ref": "Type:id"}`` into the state."""
    if not isinstance(ref, dict):
        return None
    key = ref.get("__ref")
    if not isinstance(key, str):
        return None
    value = state.get(key)
    return value if isinstance(value, dict) else None


def _name_of(state: dict[str, Any], ref: Any) -> str | None:
    obj = _resolve(state, ref)
    if not obj:
        return None
    for field in ("name", "title"):
        value = obj.get(field)
        if value:
            return str(value)
    return None


def _extract_ad(state: dict[str, Any], job_id: str | None = None) -> dict[str, Any] | None:
    """Return the page's ``AdType`` object from its Apollo state.

    A detail page embeds exactly one ad, but the ad is selected by ``job_id``
    first so that a page which also carried related/similar ads would still
    yield the requested one rather than whichever happened to sort first.
    """
    ads = [
        (key, value)
        for key, value in state.items()
        if key.startswith("AdType:") and isinstance(value, dict)
    ]
    if job_id is not None:
        for key, value in ads:
            if str(value.get("id")) == str(job_id) or key.split(":", 1)[1] == str(job_id):
                return value
    return ads[0][1] if ads else None


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    match = _ISO_DATE.search(str(value))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _extract_phone(ad: dict[str, Any]) -> str | None:
    info = ad.get("phoneInfo")
    if not isinstance(info, dict):
        return None
    for slot in ("firstPhone", "secondPhone"):
        phone = info.get(slot)
        if isinstance(phone, dict) and phone.get("number"):
            prefix = phone.get("prefix") or ""
            return re.sub(r"\s+", "", f"{prefix}{phone['number']}")
    return None


def _detect_remote(description: str | None) -> str | None:
    lowered = (description or "").lower()
    for phrase in _REMOTE_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_detail(
    job_id: str,
    html: str,
    url: str | None = None,
    listing_page: int | None = None,
) -> RawRevolicoCuJob:
    """Parse one item page."""
    state = apollo_state(html)
    ad = _extract_ad(state, job_id)
    if ad is None:
        raise RevolicoCuParseError(
            f"Revolico ad {job_id} carries no AdType in __APOLLO_STATE__; the page "
            "was not an item detail page (the markup changed or the ad expired)."
        )

    title = (ad.get("title") or "").strip()
    if not title:
        raise RevolicoCuParseError(f"Revolico ad {job_id} has an empty title.")

    description = ad.get("description") or ad.get("shortDescription") or None
    if isinstance(description, str):
        description = description.strip() or None

    province = _name_of(state, ad.get("province"))
    municipality = _name_of(state, ad.get("municipality"))
    subcategory = _resolve(state, ad.get("subcategory"))
    category = str(subcategory.get("title")) if subcategory and subcategory.get("title") else None
    subcategory_slug = (
        str(subcategory.get("slug")) if subcategory and subcategory.get("slug") else None
    )

    if municipality and province:
        location = f"{municipality}, {province}"
    else:
        location = municipality or province or "Cuba"

    updated_on = ad.get("updatedOnByUser")
    posted_date = _parse_iso_date(updated_on)

    price = _to_float(ad.get("price"))
    price_currency = ad.get("currency")

    return RawRevolicoCuJob(
        source_job_id=str(job_id),
        title=title,
        company_name="Unknown employer",
        poster_name=ad.get("name"),
        location=location,
        province=province,
        municipality=municipality,
        country="Cuba",
        description=description,
        category=category,
        subcategory_slug=subcategory_slug,
        price=price,
        price_currency=price_currency,
        posted_date=posted_date,
        updated_on=str(updated_on) if updated_on else None,
        phone=_extract_phone(ad),
        remote_phrase=_detect_remote(description),
        url=url,
        listing_page=listing_page,
        raw={
            "ad_status": ad.get("status"),
            "price_raw": ad.get("price"),
            "price_currency": price_currency,
            "poster_name": ad.get("name"),
            "updated_on": str(updated_on) if updated_on else None,
            "date_source": "updatedOnByUser (last bump; the board has no original posting date)",
            "province": province,
            "municipality": municipality,
            "subcategory": category,
            "subcategory_slug": subcategory_slug,
            "view_count": ad.get("viewCount"),
            "contact_info": ad.get("contactInfo"),
            "phone": _extract_phone(ad),
            "url_path": urlparse(url).path if url else None,
        },
    )


class RevolicoCuParser:
    """Turns a Revolico (Cuba) item page into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_page: int | None = None,
    ) -> RawRevolicoCuJob:
        return parse_detail(job_id, html or "", url=url, listing_page=listing_page)

    def parse_many(self, records: list[dict]) -> tuple[list[RawRevolicoCuJob], list[str]]:
        parsed: list[RawRevolicoCuJob] = []
        issues: list[str] = []
        for rec in records:
            try:
                parsed.append(
                    self.parse(
                        str(rec.get("job_id") or ""),
                        rec.get("html"),
                        url=rec.get("url"),
                        listing_page=rec.get("listing_page"),
                    )
                )
            except RevolicoCuParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} Revolico records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
