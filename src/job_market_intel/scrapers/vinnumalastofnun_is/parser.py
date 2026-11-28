"""Parser for Vinnumalastofnun (Iceland) vacancy documents.

The island.is generic list and the ad's server-rendered page together carry one
vacancy. Measured shapes (2026-11-28):

* List item (``GetGenericListItems``) -- ``{id, date, title, cardIntro,
  filterTags, slug, assetUrl, externalUrl, image}``. ``date`` is the board's
  single date field (``YYYY-MM-DD``); on the sampled ads it matches the body's
  application-deadline sentence (``Umsóknarfrestur er til og með ...`` /
  ``Last application date is ...``), so it is stored as ``closing_date``. A
  handful of posters enter their publish date in it instead; the raw value is
  kept in ``raw_payload`` rather than guessed at.
* ``title`` is ``"<role> - <employer>"``; an ad abroad is sometimes written
  ``"<role> - <employer> - <country>"`` and is tagged ``stoerf-erlendis``, so
  that trailing country token is split off from the employer.
* ``filterTags`` is the board's whole controlled vocabulary: the eight
  Icelandic regions, a work-percentage group (``100``..``10``), ``eures``,
  ``stoerf-erlendis`` (jobs abroad), ``sumarstarf`` (summer job) and
  ``vaktavinna`` (shift work). The ad page's ``__NEXT_DATA__`` carries the
  body as ``Html`` rich-text nodes referenced from the ``GenericListItem``.

Nothing is invented. There is no salary on the board, so every row is
``salary_disclosed=False``; there is no publish timestamp, so ``posting_date``
stays ``None`` (the store applies its scrape-date fallback); the work
percentage, when present, is the only signal for full/part time.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any

from job_market_intel.cleaning.common import CleanedJob

from .exceptions import VinnumalastofnunIsParseError
from .models import RawVinnumalastofnunIsJob

#: The eight Icelandic region tags. Their ``title`` is the human-readable
#: region name ("Höfuðborgarsvæðið", "Vesturland", ...), used verbatim as the
#: location label.
_REGION_SLUGS: frozenset[str] = frozenset(
    {
        "hoefudborgarsvaedid",
        "vesturlandi",
        "sudurland-vmst",
        "austurland",
        "nordurland-eystra",
        "nordurland-vestra",
        "vestfirdir",
        "sudurnes",
    }
)

#: "Störf erlendis" -- the ad is a job abroad, so a third title segment is a
#: country name rather than part of the employer.
_ABROAD_SLUG = "stoerf-erlendis"

#: Block-level rich-text nodes get a line break after their text.
_BLOCK_NODES = frozenset(
    {
        "paragraph",
        "heading-1",
        "heading-2",
        "heading-3",
        "heading-4",
        "list-item",
        "blockquote",
    }
)


def clean_text(value: Any) -> str:
    """Unescape entities and collapse whitespace to a single line."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split()).strip()


def normalize_description(raw: Any) -> str:
    """Unescape entities, normalize newlines, and collapse blank lines."""
    if raw is None:
        return ""
    text = html.unescape(str(raw))
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def rich_text_to_text(document: Any) -> str:
    """Flatten one island.is rich-text ``document`` node into plain text.

    The nodes are a small Slate-like tree: ``paragraph``/``heading-*``/
    ``list-item`` blocks hold ``text`` leaves (and ``hyperlink`` wrappers whose
    child leaves carry the visible words). Only ``value`` on a leaf is text;
    everything else is structure.
    """
    if not isinstance(document, dict):
        return ""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        node_type = node.get("nodeType")
        if node_type in ("text", None) and "value" in node and "content" not in node:
            parts.append(str(node["value"]))
        for child in node.get("content") or []:
            walk(child)
        if node_type in _BLOCK_NODES:
            parts.append("\n")

    walk(document)
    return normalize_description("".join(parts))


def parse_date(value: Any) -> datetime | None:
    """Parse the ISO dates the API writes (``"YYYY-MM-DD"``)."""
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None
    return parsed.replace(tzinfo=None)


def tag_slugs(item: dict[str, Any]) -> set[str]:
    """The slugs of every ``filterTags`` entry (region, ratio, flags)."""
    slugs: set[str] = set()
    for tag in item.get("filterTags") or []:
        if isinstance(tag, dict):
            slug = clean_text(tag.get("slug"))
            if slug:
                slugs.add(slug)
    return slugs


def region_title(item: dict[str, Any]) -> str:
    """The first Icelandic-region ``filterTags`` title, or ``""``."""
    for tag in item.get("filterTags") or []:
        if isinstance(tag, dict) and clean_text(tag.get("slug")) in _REGION_SLUGS:
            return clean_text(tag.get("title"))
    return ""


def work_percentage(item: dict[str, Any]) -> int | None:
    """The ``100``..``10`` work-ratio tag as an integer, or ``None``."""
    for tag in item.get("filterTags") or []:
        slug = clean_text(tag.get("slug")) if isinstance(tag, dict) else ""
        if slug.isdigit():
            return int(slug)
    return None


def map_employment_type(percentage: int | None) -> str | None:
    """A 100% position is full time; anything smaller is part time.

    The board does not publish an employment-type field, so this is only the
    work ratio it does publish; ``None`` (no ratio tag) stays unset rather than
    guessed.
    """
    if percentage is None:
        return None
    return "full_time" if percentage >= 100 else "part_time"


def build_location(item: dict[str, Any]) -> str:
    """``"<region>; IS"`` when a region tag exists, else the bare country."""
    region = region_title(item)
    return f"{region}; IS" if region else "IS"


def split_title_company(title: str, *, abroad: bool) -> tuple[str, str]:
    """Split ``"<role> - <employer>"`` (and the abroad country suffix).

    Every measured title carries at least one ``" - "`` separator. For an ad
    tagged ``stoerf-erlendis`` with three or more segments the last segment is
    the destination country, so the employer is the segment before it.
    """
    parts = [clean_text(part) for part in title.split(" - ")]
    parts = [part for part in parts if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    if abroad and len(parts) >= 3:
        return " - ".join(parts[:-2]), parts[-2]
    return " - ".join(parts[:-1]), parts[-1]


def card_intro_text(item: dict[str, Any]) -> str:
    """Flatten the list item's short ``cardIntro`` rich-text blocks."""
    chunks: list[str] = []
    for block in item.get("cardIntro") or []:
        if isinstance(block, dict) and block.get("document"):
            text = rich_text_to_text(block["document"])
            if text:
                chunks.append(text)
    return normalize_description("\n\n".join(chunks))


def _structured_summary(item: dict[str, Any]) -> str:
    """A labelled, non-invented summary for an ad with no usable body."""
    lines = ["Vacancy published on Vinnumalastofnun (island.is)."]
    for label, value in (
        ("Title", item.get("title")),
        ("Date", item.get("date")),
        ("Region", region_title(item)),
        ("Work ratio", f"{work_percentage(item)}%" if work_percentage(item) else None),
    ):
        text = clean_text(value)
        if text:
            lines.append(f"{label}: {text}")
    links = clean_text(item.get("externalUrl"))
    if links:
        lines.append(f"External URL: {links}")
    return "\n".join(lines)


class VinnumalastofnunIsParser:
    """Turns one island.is list item + detail into a validated ``CleanedJob``."""

    def parse_job(self, raw: RawVinnumalastofnunIsJob, *, today: date | None = None) -> CleanedJob:
        """Parse one vacancy into a ``CleanedJob``.

        ``today`` only guards the board's date field: ``core.jobs`` has a
        ``closing_date >= posting_date`` check and the store fills a missing
        posting_date with the scrape date, so a date the poster left in the
        past cannot be stored as a closing date. Such a row keeps the raw value
        in ``raw_payload`` and stores no closing date rather than inventing a
        posting date to make the check pass. Tests pin ``today``.
        """
        item = raw.list_item
        detail = raw.detail or {}

        full_title = clean_text(item.get("title"))
        if not full_title:
            raise VinnumalastofnunIsParseError(
                f"no title in Vinnumalastofnun vacancy {raw.job_id} ({raw.url})"
            )

        slugs = tag_slugs(item)
        role, company = split_title_company(full_title, abroad=_ABROAD_SLUG in slugs)
        if not company:
            company = "Confidential Employer"

        location = build_location(item)
        percentage = work_percentage(item)
        employment_code = map_employment_type(percentage)

        body = normalize_description(detail.get("body"))
        if len(body.split()) >= 5:
            description_source = "content"
        else:
            card = card_intro_text(item)
            if len(card.split()) >= 5:
                body = card
                description_source = "card_intro"
            else:
                body = _structured_summary(item)
                description_source = "structured_summary"

        closing_date = parse_date(item.get("date"))
        reference_day = today or date.today()
        if closing_date is not None and closing_date.date() < reference_day:
            closing_date = None
        words = len(body.split())

        score = 0.4
        score += 0.2 if words >= 60 else (0.1 if words >= 20 else 0.0)
        score += 0.1 if company != "Confidential Employer" else 0.0
        score += 0.1 if location != "IS" else 0.0
        score += 0.05 if closing_date else 0.0
        if description_source == "structured_summary":
            score = min(score, 0.6)

        raw_payload = {
            "url": raw.url,
            "slug": raw.slug,
            "list_position": raw.list_position,
            "list_total": raw.list_total,
            "description_source": description_source,
            "description_chars": len(body),
            "full_title": full_title,
            "work_percentage": percentage,
            "date_raw": clean_text(item.get("date")) or None,
            "closing_date_dropped": bool(parse_date(item.get("date")) and closing_date is None),
            "tags": [
                clean_text(tag.get("title"))
                for tag in item.get("filterTags") or []
                if isinstance(tag, dict) and clean_text(tag.get("title"))
            ],
            "external_url": clean_text(item.get("externalUrl")) or None,
            "list_item": item,
            "detail": detail or None,
        }

        return CleanedJob(
            source_job_id=raw.job_id,
            job_title=role or full_title,
            company_name=company,
            company_logo_url=None,
            skills=[],
            location_cleaned=location,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=body or None,
            word_count=words,
            apply_url=raw.url,
            original_url=raw.url,
            posting_date=None,
            closing_date=closing_date,
            data_quality_score=round(min(score, 0.95), 2),
            raw_payload=raw_payload,
            currency_iso_code="ISK",
            pay_period="monthly",
            employment_type_code=employment_code,
            remote_work_type_code=None,
        )

    def parse_jobs(self, raw_jobs: list[RawVinnumalastofnunIsJob]) -> list[CleanedJob]:
        """Parse a batch, skipping and logging individual failures."""
        from loguru import logger

        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                cleaned.append(self.parse_job(raw))
            except VinnumalastofnunIsParseError as exc:
                logger.warning("Skipping Vinnumalastofnun vacancy {}: {}", raw.job_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Unexpected parse error for Vinnumalastofnun vacancy {}: {}",
                    raw.job_id,
                    exc,
                )
        return cleaned
