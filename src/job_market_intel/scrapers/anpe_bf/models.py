"""Typed model for a single raw ANPE Burkina Faso job record.

The site is a WordPress install, so one REST post object is the whole
record -- there is no separate detail call to merge. The model mirrors the
raw, source-specific shape every other scraper produces, one step before
``cleaning/anpe_bf_cleaner.py`` maps it onto the shared ``CleanedJob``.

Field facts confirmed live (2026-11-21; post ``11638`` -- "Avis de
recrutement/ Mairie Pibaore" -- is the worked example in
``tests/unit/scrapers/test_anpe_bf.py``):

* **Identity** -- ``id`` is the WordPress post id and the stable
  ``source_job_id``; ``link`` is the public page URL. Older duplicate
  notices exist (the same mairie posting again next season), so the id,
  not the title, is the identity.
* **Titles** -- ``title.rendered`` is HTML-escaped text. A few posts use
  Unicode mathematical-bold letters ("COMMUNIQUE" spelled with U+1D5D4
  and friends); the model applies NFKC so titles read as plain
  "COMMUNIQUE" rather than an unsearchable glyph run.
* **Body** -- ``content.rendered`` is the full HTML notice (average
  ~2,554 visible chars, 97 of 97 non-empty). ``excerpt.rendered`` is a
  short truncated copy, kept as a fallback only.
* **Company** -- there is NO employer field. The publisher is always the
  agency, and client employers (mairies, LONAB, ...) appear only inside
  the prose. The model therefore records the publisher as
  ``company_name`` rather than guessing an employer from a title.
* **Location / salary / contract** -- free prose only; no fields exist.
  The cleaner extracts what it can and leaves the rest unset. Salary is
  never stated anywhere in the category (see ``config.py``).
* **Dates** -- ``date`` is the WordPress post timestamp (site timezone
  "Europe/Paris" is misconfigured for Burkina Faso, but the date part is
  the posting day and is not shifted); ``modified`` is the last edit.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

#: The agency that publishes every post. Used when no employer is stated
#: (the model never guesses a client from the title -- see docstring).
DEFAULT_COMPANY_NAME = "Agence Burkinabè Pour l'Emploi (ABPE)"


def _text(value: object) -> str | None:
    """Trimmed non-empty string, or None -- tolerates ``"None"``/blank."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _nfkc(value: str | None) -> str | None:
    """Normalize compatibility characters (math-bold letters, ligatures)."""
    return unicodedata.normalize("NFKC", value) if value else value


def _iso_datetime(value: object) -> datetime | None:
    """Parse a WordPress ``date``/``modified`` timestamp as aware UTC.

    WordPress returns a naive local timestamp (its configured timezone);
    the documented repo convention for naive source timestamps is UTC, and
    the posting *day* is what is persisted.
    """
    if value is None or value == "" or value == "None":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _rendered(value: object) -> str | None:
    """The ``rendered`` field of a WordPress ``{rendered, protected}`` pair."""
    if isinstance(value, dict):
        return _text(value.get("rendered"))
    return _text(value)


class RawAnpeBfJob(BaseModel):
    """A single validated ANPE Burkina Faso job record (one WP post).

    Attributes:
        source_job_id: WordPress post ``id``, stringified.
        job_title: ``title.rendered``, NFKC-normalized and trimmed.
        company_name: The publishing agency (no employer field exists).
        description_html: ``content.rendered`` -- the full notice HTML.
        excerpt_html: ``excerpt.rendered`` -- truncated fallback copy.
        posting_date: ``date`` parsed as aware UTC.
        modified_date: ``modified`` parsed as aware UTC.
        original_url: ``link`` -- the public notice page.
        raw_payload: The complete post object, for audit.
    """

    source_job_id: str
    job_title: str
    company_name: str = DEFAULT_COMPANY_NAME
    description_html: str | None = None
    excerpt_html: str | None = None
    posting_date: datetime | None = None
    modified_date: datetime | None = None
    original_url: str
    raw_payload: dict

    @field_validator("source_job_id", "job_title", mode="after")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("original_url", mode="after")
    @classmethod
    def _url_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("original_url must be a non-empty string")
        return value

    @classmethod
    def from_payload(cls, post: object) -> RawAnpeBfJob:
        """Build the model from one WordPress REST post object.

        Raises:
            ValueError: If ``post`` is not a JSON object or lacks a usable
                id/title/link (the parser turns that into a skip).
        """
        if not isinstance(post, dict):
            raise ValueError(f"post must be a JSON object, got {type(post).__name__}")

        post_id = _text(post.get("id"))
        if post_id is None:
            raise ValueError("post carries no id")

        title = _nfkc(_rendered(post.get("title")))
        # Older notices put the escaped HTML entity straight into the
        # title field; decode it once here so the title is human text.
        if title is not None:
            from html import unescape

            title = unescape(title)

        return cls(
            source_job_id=post_id,
            job_title=title or "",
            description_html=_rendered(post.get("content")),
            excerpt_html=_rendered(post.get("excerpt")),
            posting_date=_iso_datetime(post.get("date")),
            modified_date=_iso_datetime(post.get("modified")),
            original_url=_text(post.get("link")) or "",
            raw_payload=post,
        )
