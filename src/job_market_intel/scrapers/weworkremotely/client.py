"""Fetches and parses the raw job feed from We Work Remotely's public RSS feed.

This module's only responsibility mirrors ``scrapers/remoteok/client.py``
exactly: make the HTTP request (with retries for transient failures),
confirm the response looks like a job feed, and hand back raw
dictionaries. It does not validate individual job fields or attempt any
interpretation beyond flattening XML into plain strings — that is
``models.py``'s and ``parser.py``'s job.

Why ``xml.etree.ElementTree`` and not a new dependency: the project's
``pyproject.toml`` explicitly documents a "no business-logic packages
added until the step that actually needs them" philosophy. WWR's feed is
well-formed RSS 2.0 with one namespaced element
(``<media:content>``) — the standard library's ``ElementTree`` handles
namespaces natively and needs nothing beyond what's already installed, so
there was no genuine need to add ``feedparser`` or ``lxml`` for this.

Why ``fetch_html``, not a new fetch function: RSS is XML text, not JSON —
``common/http_client.py``'s ``fetch_html`` already exists specifically
for "sources whose data isn't available as a JSON API" (its own
docstring says so) and returns the raw response body unparsed, exactly
what's needed here.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError, fetch_html
from job_market_intel.common.retry import call_with_retry

from .config import WWRSettings
from .exceptions import WWRFetchError, WWRResponseError

#: RSS 2.0's standard Media RSS namespace, used by WWR's optional
#: per-item company-logo element (``<media:content url="..." />``).
#: ElementTree requires namespaces to be resolved explicitly via a dict
#: like this one rather than resolving them automatically from the
#: document's own ``xmlns:media`` declaration.
_MEDIA_NAMESPACE = {"media": "http://search.yahoo.com/mrss"}


def _text_or_none(item: ET.Element, tag: str) -> str | None:
    """Return a child element's text, or None if absent, empty, or blank.

    We Work Remotely's feed frequently includes empty elements for unset
    fields (e.g. ``<country></country>``) rather than omitting the tag
    entirely. Normalizing both cases to ``None`` here means every
    downstream consumer can use a single "is this field present?" check
    (``is not None``) rather than also having to separately check for
    empty strings.
    """
    child = item.find(tag)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


class WWRClient:
    """Fetches and parses the current We Work Remotely job listing RSS feed."""

    def __init__(self, settings: WWRSettings | None = None) -> None:
        """Create a client.

        Args:
            settings: Configuration to use. If omitted, ``WWRSettings()``
                is constructed with its defaults (and any overrides
                present in the environment/``.env`` file), matching the
                project's existing configuration pattern.
        """
        self._settings = settings or WWRSettings()

    def fetch_raw_jobs(self) -> list[dict]:
        """Fetch the current We Work Remotely RSS feed and return raw job dictionaries.

        Each returned dictionary uses WWR's own raw field vocabulary
        (``title``, ``guid``, ``link``, ``region``, ``country``,
        ``state``, ``skills``, ``category``, ``type``, ``description``,
        ``pubdate``, ``expires_at``, ``media_content_url``) — the same
        "hand back the source's own shape, validate nothing" boundary
        ``RemoteOKClient.fetch_raw_jobs()`` keeps, just extracted from XML
        elements instead of a JSON object.

        Returns:
            A list of raw job dictionaries, one per ``<item>`` in the feed.

        Raises:
            WWRFetchError: If the feed could not be reached after
                exhausting all configured retry attempts, or if a
                permanent (non-retryable) HTTP error occurred.
            WWRResponseError: If the response was not valid XML, or was
                valid XML but contained zero ``<item>`` entries.
        """
        logger.info("Fetching We Work Remotely job feed from {}", self._settings.feed_url)

        try:
            raw_xml = call_with_retry(
                fetch_html,
                self._settings.feed_url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=self._settings.request_timeout_seconds,
                user_agent=self._settings.user_agent,
                extra_headers={"Accept": "application/rss+xml, application/xml, text/xml"},
            )
        except TransientHTTPError as exc:
            raise WWRFetchError(
                f"Could not reach We Work Remotely after "
                f"{self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            raise WWRFetchError(f"We Work Remotely request failed permanently: {exc}") from exc

        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as exc:
            raise WWRResponseError(
                f"We Work Remotely's response was not valid XML: {exc}. "
                "The feed's shape may have changed."
            ) from exc

        items = root.findall(".//item")
        if not items:
            raise WWRResponseError(
                "We Work Remotely returned a feed with zero <item> entries. "
                "The feed's shape may have changed, or this may be an empty/rate-limited response."
            )

        job_records = [self._extract_item(item) for item in items]

        logger.info("Fetched {} job records from We Work Remotely.", len(job_records))
        return job_records

    @staticmethod
    def _extract_item(item: ET.Element) -> dict:
        """Flatten one ``<item>`` element into a raw, uninterpreted dict.

        Deliberately does no cleaning, splitting, or type coercion —
        every value is either a plain string or ``None``. That work
        belongs to ``RawWWRJob``'s validators (``models.py``), keeping
        this method a pure "XML -> dict" translation, same boundary
        ``RemoteOKClient`` keeps around raw JSON dicts.
        """
        media_elem = item.find("media:content", _MEDIA_NAMESPACE)
        return {
            "title": _text_or_none(item, "title"),
            "guid": _text_or_none(item, "guid"),
            "link": _text_or_none(item, "link"),
            "region": _text_or_none(item, "region"),
            "country": _text_or_none(item, "country"),
            "state": _text_or_none(item, "state"),
            "skills": _text_or_none(item, "skills"),
            "category": _text_or_none(item, "category"),
            "type": _text_or_none(item, "type"),
            "description": _text_or_none(item, "description"),
            "pubdate": _text_or_none(item, "pubDate"),
            "expires_at": _text_or_none(item, "expires_at"),
            "media_content_url": media_elem.get("url") if media_elem is not None else None,
        }
