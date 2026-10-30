"""Fetches raw postings using the generic HTML scraper framework.

Uses plain HTTP (requests) + CSS selectors configured per site. No browser needed.
"""

from __future__ import annotations

import codecs
import json
import re
import time
import zlib
from html import escape, unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from curl_cffi.requests import exceptions as curl_exceptions
from loguru import logger

from .config import (
    GENERIC_LINK_SELECTOR,
    HtmlScraperSettings,
    SiteConfig,
    load_site_config,
)
from .exceptions import HtmlScraperFetchError, HtmlScraperResponseError

#: Both HTTP libraries raise their own transport error, and curl_cffi's
#: ``CurlError`` is not a ``RequestException``, so a fetch that may go through
#: either transport has to catch both (see jobam's client for the MRO note).
_FETCH_ERRORS = (
    requests.RequestException,
    curl_exceptions.RequestException,
    curl_exceptions.CurlError,
)

#: Errors that mean no HTTP status was ever received, so the same request can be
#: sent again.
#:
#: minajobs.net closes the TLS connection on roughly one request in five
#: (``Connection closed abruptly`` / ``Connection timed out``) while serving the
#: same URL with HTTP 200 on the next attempt. Without a retry a single dropped
#: connection becomes a detail-page failure, and a dropped listing request
#: becomes a whole empty run.
_TRANSPORT_ERRORS = (
    requests.ConnectionError,  # also covers requests.exceptions.SSLError
    requests.Timeout,
    curl_exceptions.RequestException,
    curl_exceptions.CurlError,
)

#: HTTP *statuses* worth a bounded retry because they mean "the server is having
#: a moment", not "your request is wrong". A 4xx (except 429) is definitive and
#: is returned to the caller unchanged: repeating it only triples the load.
#:
#: educarriere.ci intermittently answers the listing with 500 from a GitHub
#: runner IP while serving 200 from a residential IP and passing whole scheduled
#: runs; a single 500 used to end the run (CI 41112360639, 2026-10-30). RFC 9110
#: names 500/502/503/504 as retryable server conditions. The 520-524 codes are
#: Cloudflare's origin-error band and behave the same way.
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504, 520, 521, 522, 523, 524})

#: Three attempts with 2s then 4s between them. Long enough to ride out one
#: dropped connection or a transient 5xx, short enough that a board which is
#: really down still fails the listing page well inside the job timeout.
_TRANSPORT_ATTEMPTS = 3
_TRANSPORT_RETRY_DELAYS = (2.0, 4.0)

#: Phrases that identify an anti-bot interstitial rather than a board's own
#: listing markup. Used only to explain an empty listing page in the logs.
_CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "enable javascript",
    "captcha",
    "ddos-guard",
    "qrator",
    "access denied",
    "attention required",
)


def _extract_attr(element, attr: str) -> str | None:
    """Extract an attribute value from a BeautifulSoup element."""
    if element is None:
        return None
    val = element.get(attr)
    return val.strip() if val else None


def _extract_text(element) -> str | None:
    """Extract cleaned text from a BeautifulSoup element."""
    if element is None:
        return None
    text = element.get_text(" ", strip=True)
    return text.strip() if text else None


def _is_offsite_social(url: str) -> bool:
    """Social/profile links are never a posting on the board being scraped."""
    from job_market_intel.validation.html_scraper_quality import OFFSITE_HOSTS

    host = urlparse(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == h or host.endswith("." + h) for h in OFFSITE_HOSTS)


def _is_job_url(url: str) -> bool:
    """Heuristic: does this URL look like a job detail page?

    Section URLs are rejected explicitly. Without that, the auto-detect pass
    happily returns ``/job-search/operations-jobs`` and ``/jobs/today/`` --
    category pages that mention "job" and were stored as postings.
    """
    from job_market_intel.validation.html_scraper_quality import (
        SECTION_FRAGMENTS,
        SECTION_SEGMENTS,
        has_job_keyword,
    )

    path = urlparse(url).path.lower()
    if len(path) <= 1:  # just "/"
        return False
    if not has_job_keyword(path):
        return False
    for fragment in SECTION_FRAGMENTS:
        if fragment in path:
            return False
    segments = [s for s in path.split("/") if s]
    last = segments[-1]
    if last in SECTION_SEGMENTS:
        return False
    # "/en/ads/sri-lanka/driver-jobs", "/jobs-in-nepal/marketing-sales-jobs-in-nepal"
    return not (last.endswith(("-jobs", "-job")) or "-jobs-in-" in last)


def _json_ld_job_posting(html: str) -> dict | None:
    """Return the schema.org ``JobPosting`` block embedded in a detail page.

    Boards such as Qatar Living render the visible page as unlabelled layout
    divs but publish the same record in ``<script type="application/ld+json">``.
    The block can be a dict, a list of dicts, or a ``@graph`` container, so all
    three shapes are accepted.
    """
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Some boards (Chile's BNE) emit raw line breaks inside the
            # description string, which strict JSON rejects. Keep the record
            # instead of discarding the only structured copy of the ad.
            try:
                payload = json.loads(raw, strict=False)
            except json.JSONDecodeError:
                continue

        candidates: list = []
        if isinstance(payload, dict):
            candidates = payload.get("@graph") or [payload]
        elif isinstance(payload, list):
            candidates = payload
        for item in candidates:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


class _LinkExtractor(HTMLParser):
    """Collect every anchor whose URL looks like a job detail page."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []  # (url, text)
        self._current_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        self._current_href = dict(attrs).get("href")
        self._text_parts = []

    def handle_data(self, data):
        if self._current_href:
            self._text_parts.append(data.strip())

    def handle_endtag(self, tag):
        if tag != "a" or not self._current_href:
            return
        full_url = urljoin(self.base_url, self._current_href)
        text = " ".join(self._text_parts).strip()
        if _is_job_url(full_url):
            self.links.append((full_url, text))
        self._current_href = None
        self._text_parts = []


def _extract_links_from_html(html: str, base_url: str) -> list[tuple[str, str]]:
    """Extract all job-looking links from HTML."""
    parser = _LinkExtractor(base_url)
    parser.feed(html)
    return parser.links


_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?([-\w.:]+)""",
    re.IGNORECASE,
)


def _document_charset(content: bytes) -> str | None:
    """The charset a page declares about itself in its ``<meta>`` tags.

    Empleos.net sends ``Content-Type: text/html; charset=`` (note the empty
    value), which requests treats as a real but empty encoding and decodes as
    ASCII, turning every Spanish accent into ``?``. The document itself says
    ``<meta charset="windows-1252">``, so read that instead.
    """
    match = _META_CHARSET.search(content[:4096])
    if not match:
        return None
    name = match.group(1).decode("ascii", "ignore").strip().lower()
    try:
        codecs.lookup(name)
    except LookupError:
        return None
    return name


def _response_text(resp: requests.Response) -> str:
    """Decode a response, honouring the page's own charset declaration.

    ikman.lk returns ``Content-Type: text/html`` with no charset and no meta
    charset, so requests falls back to ISO-8859-1 and Sinhala titles arrive as
    mojibake. Override that fallback only when the bytes really are UTF-8, so a
    page that is genuinely Latin-1 is left alone.
    """
    ctype = resp.headers.get("content-type", "").lower()
    declared = ""
    if "charset=" in ctype:
        declared = ctype.split("charset=", 1)[1].split(";")[0].strip(" '\"")
    encoding = (resp.encoding or "").strip()
    if not declared or not encoding:
        document = _document_charset(resp.content)
        if document:
            resp.encoding = document
        elif not encoding or encoding.lower() == "iso-8859-1":
            try:
                resp.content.decode("utf-8")
            except UnicodeDecodeError:
                if not encoding:
                    resp.encoding = resp.apparent_encoding
            else:
                resp.encoding = "utf-8"
    return resp.text


def mapped_json_html(
    site_config: SiteConfig, payload: Any, url: str, listing: dict | None = None
) -> str:
    """Render mapped JSON fields into the minimal HTML the parser expects.

    Two frameworks reach this point: the HTTP client when a board's data lives
    at an API or in an attribute, and the browser client when the rendered page
    publishes a schema.org ``JobPosting`` block instead of usable markup.
    Rendering the mapped fields keeps the parser, quality filter and validator
    on one path instead of growing a second JSON-to-model mapper.
    """
    mapping = site_config.detail_json_map
    if not mapping:
        return ""

    def text_of(value: str | list[str]) -> str:
        paths = value if isinstance(value, list) else [value]
        parts = []
        for path in paths:
            found = _mapped_value(payload, path, listing)
            if isinstance(found, list):
                parts.extend(str(item) for item in found if item not in (None, ""))
            elif found not in (None, ""):
                parts.append(str(found))
        return "\n".join(parts)

    # A feed that splits the place into fields (Gupy sends ``city`` and
    # ``state``) still means one location line, so its parts are comma-joined;
    # a multi-part description stays a sequence of blocks separated by newlines.
    def location_of(value: str | list[str]) -> str:
        parts = [part.strip() for part in text_of(value).split("\n") if part.strip()]
        return ", ".join(parts)

    # Feeds often deliver already HTML-escaped text ("Copiap&oacute;");
    # unescape first, then escape for the wrapper, so the parser sees the
    # real character instead of a literal entity.
    def plain(value: str | list[str]) -> str:
        return escape(unescape(text_of(value)))

    title = plain(mapping.get("title", ""))
    company = plain(mapping.get("company", ""))
    location = escape(unescape(location_of(mapping.get("location", ""))))
    employment_type = plain(mapping.get("employment_type", ""))
    description = text_of(mapping.get("description", ""))
    posted_date = plain(mapping.get("posted_date", ""))
    salary = plain(mapping.get("salary", ""))
    salary_attrs, salary_text = _structured_salary_html(site_config, payload, listing)
    if not salary:
        salary = salary_text
    return (
        "<html><body>"
        f"<h1>{title}</h1>"
        f"<div id='company'>{company}</div>"
        f"<div id='location'>{location}</div>"
        f"<div id='employment_type'>{employment_type}</div>"
        f"<div id='description'>{description}</div>"
        f"<div id='posted_date'>{posted_date}</div>"
        f"<div id='salary'{salary_attrs}>{salary}</div>"
        f"<a href='{escape(url)}'>apply</a>"
        "</body></html>"
    )


def _structured_salary_html(
    site_config: SiteConfig, payload: Any, listing: dict | None
) -> tuple[str, str]:
    """Render a mapped ``baseSalary`` as node attributes plus readable text.

    The framework hands the parser text, so a numeric salary would otherwise
    reach the cleaner as an unparsed string. Boards that declare
    ``detail_json_salary`` get the numbers back as ``data-salary-*`` attributes
    on the ``#salary`` node, which the parser lifts into the raw record; the
    text beside them is what a human reading the rendered page sees.
    """
    mapping = site_config.detail_json_salary
    if not mapping:
        return "", ""
    band = _salary_band(mapping, payload, listing)
    if band is None:
        return "", ""
    currency, unit, minimum, maximum = band

    attributes = []
    if currency:
        attributes.append(("data-salary-currency", currency))
    attributes.append(("data-salary-min", f"{minimum:g}"))
    attributes.append(("data-salary-max", f"{maximum:g}"))
    if unit:
        attributes.append(("data-salary-unit", unit))
    rendered = "".join(f" {name}='{escape(value)}'" for name, value in attributes)

    if minimum == maximum:
        band_text = f"{minimum:g}"
    else:
        band_text = f"{minimum:g} - {maximum:g}"
    text = " ".join(part for part in (currency, band_text, unit) if part)
    return rendered, escape(text)


def _salary_band(
    mapping: dict[str, str], payload: Any, listing: dict | None
) -> tuple[str, str, float, float] | None:
    """Resolve a mapped salary to ``(currency, unit, min, max)``.

    ``baseSalary`` carries a min/max pair on most ads and a single ``value`` on
    the rest, and the two are levelled here so the caller sees one shape.
    ``None`` means the payload published no usable figure.
    """

    def part(name: str) -> str:
        path = mapping.get(name, "")
        if not path.strip():
            return ""
        return _string_of(_mapped_value(payload, path, listing))

    def number(name: str) -> float | None:
        return _as_number(_mapped_value(payload, mapping.get(name, ""), listing))

    minimum = number("min")
    maximum = number("max")
    if minimum is None and maximum is None:
        minimum = maximum = number("value")
    if minimum is None or maximum is None:
        return None
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    return part("currency"), part("unit"), minimum, maximum


def _string_of(value: Any) -> str:
    """One resolved value as text; a list is flattened, as the mapper does."""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "" if value in (None, "") else str(value)


def _as_number(value: Any) -> float | None:
    """A payload value as a finite float, or ``None`` when it is not one."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _mapped_value(payload: Any, path: str, listing: dict | None) -> Any:
    """Resolve a ``detail_json_map`` path, allowing ``listing.`` fields.

    APIs that keep the posting body separate from its metadata (Jobbnorge
    sends employer and place in the search feed but the ad body from
    another host) need both payloads in one record.

    A path holding ``{...}`` placeholders is a template: each placeholder is
    resolved like a path and the result is one string. Feeds that split pay
    into ``minimumPay`` and ``payType`` (MSD) have no single field a map entry
    could point at, and "30.0 Hourly rate" is what the ad itself says.
    """
    # An unmapped field is written as an empty string in the site config, and
    # a blank path walks into ``_dotted`` with no keys, which returns the whole
    # payload. That put the entire API response into MSD's ``company`` div and
    # the parser stored it as the employer name.
    if not path.strip():
        return None
    if "{" in path and "}" in path:
        return _fill_json_template(payload, path, listing)
    if path.startswith("listing.") and listing is not None:
        return HtmlScraperClient._dotted(listing, path[len("listing.") :])
    return HtmlScraperClient._dotted(payload, path)


def _fill_json_template(payload: Any, template: str, listing: dict | None) -> str:
    """Render ``{dotted.path}`` placeholders against a JSON payload."""

    def resolve(path: str) -> str:
        if not path.strip():
            return ""
        if path.startswith("listing."):
            found = HtmlScraperClient._dotted(listing or {}, path[len("listing.") :])
        else:
            found = HtmlScraperClient._dotted(payload, path)
        if isinstance(found, list):
            return ", ".join(str(item) for item in found if item not in (None, ""))
        if isinstance(found, float) and found.is_integer():
            # JSON has no integers, so a rate of 25 arrives as 25.0 and would
            # render "Hourly rate 25.0" where the ad says 25.
            return str(int(found))
        return "" if found in (None, "") else str(found)

    resolved: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        value = resolve(match.group(1).strip())
        resolved.append(value)
        return value

    rendered = re.sub(r"\{([^{}]+)\}", substitute, template)
    # A template is the shape of one fact ("{payType} {minimumPay}"). When the
    # board publishes none of its parts, the literal punctuation would survive
    # as a salary reading " -  por Mes ()" on an ad that discloses no pay.
    if resolved and not any(resolved):
        return ""
    return rendered


def _discovery_key(job: dict) -> str:
    """The identity two discovered records are compared on.

    Listings are normally deduplicated by URL, but a board with no per-posting
    page gives every record the same URL (MIFOTRA lists all open ads on one
    screen), so identity there is the posting id the feed carries. It is also
    the record's ``source_job_id``, which is what the database dedupes on.
    """
    job_id = job.get("id")
    if job_id not in (None, ""):
        return f"id:{job_id}"
    return f"url:{job.get('url', '')}"


def _inflate_indexed_zlib(payload: Any) -> Any:
    """Decode a ``{"_data_": {"0": 120, "1": 156, ...}}`` zlib envelope.

    The Rwandan e-recruitment API ships its JSON compressed: each byte of a
    zlib stream becomes one value keyed by its position, and the board's own
    bundle reassembles and inflates the bytes with pako before parsing. A
    payload that is not that envelope is returned untouched, so the option
    stays harmless on boards that compress only some responses.
    """
    if not isinstance(payload, dict) or set(payload) != {"_data_"}:
        return payload
    data = payload["_data_"]
    if not isinstance(data, dict) or not data:
        return payload
    try:
        raw = bytes(int(data[str(index)]) for index in range(len(data)))
    except (KeyError, TypeError, ValueError):
        return payload
    try:
        return json.loads(zlib.decompress(raw))
    except (zlib.error, json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("html_scraper: _data_ envelope did not inflate to JSON")
        return payload


class HtmlScraperClient:
    """Fetches postings using plain HTTP and CSS selectors."""

    def __init__(
        self,
        source_code: str,
        settings: HtmlScraperSettings | None = None,
        site_config: SiteConfig | None = None,
    ) -> None:
        self._settings = settings or HtmlScraperSettings()
        self._site_config = site_config or load_site_config(source_code, self._settings.sites_dir)
        self._listing_cursor = ""
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self._site_config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                **self._site_config.extra_headers,
            }
        )

    def listing_url(self, page: int = 1) -> str:
        base = f"{self._site_config.base_url}{self._site_config.listing_path}"
        if page <= 1:
            return base
        pagination = self._site_config.listing_pagination
        if "{cursor}" in pagination:
            # A cursor board has no page numbers: the next page is whatever the
            # previous response's cursor names, and there is none until then.
            if not self._listing_cursor:
                return base
            return base + pagination.replace("{cursor}", quote(self._listing_cursor, safe=""))
        page_str = pagination.format(page=page)
        return base + page_str

    def detail_url(self, path_or_id: str) -> str:
        if self._site_config.detail_url_pattern:
            pattern = self._site_config.detail_url_pattern.format(id=path_or_id)
            return f"{self._site_config.base_url}{pattern}"
        return f"{self._site_config.base_url}{path_or_id}"

    def _job_id_from_url(self, url: str) -> str:
        """Stable job ID for a detail URL.

        Trailing-slash URLs would otherwise yield an empty ID, and slug-only
        IDs repeat across categories on boards such as zaplata.bg, so a
        configured ``id_url_regex`` wins when it matches.
        """
        pattern = self._site_config.id_url_regex.strip()
        if pattern:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return url.rstrip("/").rsplit("/", 1)[-1]

    def _transport(self, method: str, url: str, headers: dict[str, str] | None = None, data=None):
        """Send one request through the board's transport.

        Every source gets plain ``requests`` unless the site config names a
        ``curl_cffi`` impersonation profile (see :attr:`SiteConfig.impersonate`),
        in which case the request is re-sent with a real browser's TLS/HTTP2
        fingerprint.
        """
        impersonate = self._site_config.impersonate.strip()
        timeout = self._site_config.request_timeout_seconds
        request_headers = dict(self._session.headers)
        if headers:
            request_headers.update(headers)
        if impersonate:
            return curl_requests.request(
                method,
                url,
                impersonate=impersonate,
                headers=request_headers,
                data=data,
                timeout=timeout,
            )
        if method == "POST":
            return self._session.post(url, headers=request_headers, data=data, timeout=timeout)
        return self._session.get(url, headers=request_headers, timeout=timeout)

    def _transport_with_retry(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        data=None,
    ):
        """Send a request, retrying transient failures a bounded number of times.

        Two things are retried: a failure that never reached the server (a
        dropped connection or a timeout, see :data:`_TRANSPORT_ERRORS`), and a
        response whose status is in :data:`_RETRYABLE_STATUS_CODES` (429 and the
        5xx band). Any other response -- notably a 4xx -- is returned to the
        caller unchanged, because ``raise_for_status`` is what decides a status
        is fatal.
        """
        last_error: Exception | None = None
        for attempt in range(1, _TRANSPORT_ATTEMPTS + 1):
            try:
                resp = self._transport(method, url, headers=headers, data=data)
            except _TRANSPORT_ERRORS as exc:
                last_error = exc
                if attempt >= _TRANSPORT_ATTEMPTS:
                    break
                self._log_retry(url, attempt, str(exc))
                continue
            if resp.status_code in _RETRYABLE_STATUS_CODES and attempt < _TRANSPORT_ATTEMPTS:
                self._log_retry(url, attempt, f"HTTP {resp.status_code}")
                continue
            return resp
        assert last_error is not None  # _TRANSPORT_ATTEMPTS >= 1
        raise last_error

    def _log_retry(self, url: str, attempt: int, reason: str) -> None:
        """Warn about a retry and sleep before the next attempt."""
        delay = _TRANSPORT_RETRY_DELAYS[attempt - 1]
        logger.warning(
            "html_scraper transient failure for {} (attempt {}/{}): {}; retrying in {:.0f}s",
            url,
            attempt,
            _TRANSPORT_ATTEMPTS,
            reason,
            delay,
        )
        time.sleep(delay)

    def _get(self, url: str) -> str:
        try:
            resp = self._transport_with_retry("GET", url)
            resp.raise_for_status()
            return _response_text(resp)
        except _FETCH_ERRORS as exc:
            raise HtmlScraperFetchError(f"HTTP request failed for {url}: {exc}") from exc

    def _post_json(self, url: str, body: str) -> str:
        """POST a JSON body and return the response text.

        Search gateways that answer 405 to every GET (Karir's
        ``/v2/search/opportunities``) still return the listing to a POST, so
        the fetch has to carry a body rather than query parameters.
        """
        try:
            resp = self._transport_with_retry(
                "POST",
                url,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                data=body.encode("utf-8"),
            )
            resp.raise_for_status()
            return _response_text(resp)
        except _FETCH_ERRORS as exc:
            raise HtmlScraperFetchError(f"HTTP POST failed for {url}: {exc}") from exc

    def _select(self, soup: BeautifulSoup, selector: str) -> list:
        """Run a CSS selector, returning elements."""
        if not selector:
            return []
        try:
            return soup.select(selector)
        except Exception:
            return []

    def _select_one(self, soup: BeautifulSoup, selector: str):
        """Run a CSS selector, returning the first element."""
        if not selector:
            return None
        try:
            return soup.select_one(selector)
        except Exception:
            return None

    @staticmethod
    def _dotted(value: Any, path: str) -> Any:
        """Walk a dotted ``a.b.c`` path through nested dicts.

        A segment ending in ``[]`` maps the rest of the path over a list, so
        ``components[].text`` returns the text of every component. This is how
        feeds that split an ad into blocks (Jobbnorge) expose one description.
        """
        keys = [key.strip() for key in path.split(".") if key.strip()]
        return HtmlScraperClient._walk_dotted(value, keys)

    @staticmethod
    def _walk_dotted(node: Any, keys: list[str]) -> Any:
        if not keys:
            return node
        key, rest = keys[0], keys[1:]
        if key.endswith("[]"):
            key = key[:-2]
            if key:
                if not isinstance(node, dict):
                    return None
                node = node.get(key)
            if node is None:
                return None
            # ``jobLocation`` is a list on most ads of a board and a single
            # object on the rest (Bundesagentur für Arbeit), and the mapping
            # should not have to guess which one this ad used.
            if not isinstance(node, list):
                node = [node]
            values = [HtmlScraperClient._walk_dotted(item, rest) for item in node]
            return [value for value in values if value not in (None, "")]
        if not isinstance(node, dict):
            return None
        return HtmlScraperClient._walk_dotted(node.get(key), rest)

    def _jobs_from_payload(self, payload: Any) -> list[dict]:
        """Turn the JSON job list into discovery records with detail URLs."""
        path = self._site_config.listing_json_path.strip()
        template = self._site_config.listing_json_url_template.strip()
        url_field = self._site_config.listing_json_url_field.strip()
        if not template and not url_field:
            return []

        # Some public APIs (Jobbnorge) return a bare array instead of wrapping
        # it in an object, which leaves no path to point at.
        items = payload if path in ("", "$") else self._dotted(payload, path)
        if not isinstance(items, list):
            logger.warning("html_scraper listing JSON path {} is not a list", path)
            return []

        field = self._site_config.listing_json_id_field.strip() or "id"
        jobs = []
        for item in items:
            if not isinstance(item, dict):
                continue
            job_id = self._dotted(item, field)
            if job_id in (None, ""):
                continue
            if url_field:
                detail = self._dotted(item, url_field)
                if detail in (None, ""):
                    continue
                url = urljoin(self._site_config.base_url, str(detail))
            else:
                url = urljoin(self._site_config.base_url, template.format(id=job_id))
            if _is_offsite_social(url):
                continue
            job = {"url": url, "title": "", "id": job_id, "listing": item}
            # The URL was built from the feed's own id, so that id — not a
            # regex over the URL — names the posting. It is also the only
            # identity a board with no per-posting page can offer.
            job["url_from_id"] = not url_field
            # Some feeds (the Danish Jobnet BFF among them) return the whole
            # posting, description included, so the detail page is redundant.
            if self._site_config.detail_json_from_listing:
                job["payload"] = item
            jobs.append(job)
        return jobs

    def _json_listing_jobs(self, html: str) -> list[dict]:
        """Read a job list out of the listing page's embedded Next.js JSON.

        Next.js boards such as Jobzella render the list client-side but ship
        the same records inside ``<script id="__NEXT_DATA__">``. The CSS link
        selector sees no anchors there, so this opt-in path is the only way to
        discover postings without a browser.
        """
        if not self._site_config.listing_json_path.strip():
            return []

        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            logger.warning("html_scraper listing JSON missing (__NEXT_DATA__)")
            return []
        try:
            payload = json.loads(script.string)
        except json.JSONDecodeError as exc:
            logger.warning("html_scraper listing JSON is not valid JSON: {}", exc)
            return []

        self._remember_listing_cursor(payload)
        return self._jobs_from_payload(payload)

    def _remember_listing_cursor(self, payload: Any) -> None:
        """Keep the payload's next-page cursor for the following request.

        Cursor boards (BestJobs) answer page 2 to the same URL plus the cursor
        the previous response carried; ``listing_json_cursor_path`` names it.
        """
        path = self._site_config.listing_json_cursor_path.strip()
        if not path:
            return
        found = self._dotted(payload, path)
        self._listing_cursor = "" if found in (None, "") else str(found)

    def _embedded_json_payload(self, html: str, selector: str, attr: str, label: str) -> Any:
        """Parse the JSON an element carries in one of its attributes."""
        soup = BeautifulSoup(html, "html.parser")
        element = self._select_one(soup, selector)
        if element is None:
            raise HtmlScraperResponseError(
                f"embedded {label} element {selector} is missing from the page"
            )
        raw = element.get(attr)
        if isinstance(raw, list):
            raw = next((value for value in raw if value), None)
        # Next.js ships the payload as the *text* of
        # ``<script id="__NEXT_DATA__">`` rather than as an attribute.
        if not raw and attr.strip().lower() in {"text", "string"}:
            raw = element.string or element.get_text()
        if not raw:
            raise HtmlScraperResponseError(
                f"embedded {label} attribute {attr} is empty on {selector}"
            )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            try:
                return json.loads(raw, strict=False)
            except json.JSONDecodeError as exc:
                raise HtmlScraperResponseError(
                    f"embedded {label} JSON on {selector} is invalid: {exc}"
                ) from exc

    def _embedded_json_jobs(self, html: str) -> list[dict]:
        """Read listing records from a JSON attribute on a custom element.

        Sapo Emprego renders the list client-side but ships the same 11 records
        in ``<search-results-component :offers='[...]'>``. Missing or malformed
        JSON is an error here, not an empty page, so a layout change is visible
        instead of silently producing zero postings.
        """
        payload = self._embedded_json_payload(
            html,
            self._site_config.listing_json_selector.strip(),
            self._site_config.listing_json_attr.strip(),
            "listing",
        )
        return self._jobs_from_payload(payload)

    def _embedded_detail_json(self, html: str) -> Any:
        """Read a posting object from JSON carried by the detail page itself.

        Laravel/Inertia boards such as agenceemploijeunes.ci render the page
        only in the browser but ship the whole payload in
        ``<div id="app" data-page='{"props": {...}}'>``. Missing or malformed
        JSON is an error so a layout change is visible rather than silent.
        """
        payload = self._embedded_json_payload(
            html,
            self._site_config.detail_json_selector.strip(),
            self._site_config.detail_json_attr.strip(),
            "detail",
        )
        path = self._site_config.detail_json_path.strip()
        if not path:
            return payload
        found = self._dotted(payload, path)
        if found in (None, ""):
            raise HtmlScraperResponseError(
                f"embedded detail JSON path {path} is missing from the page"
            )
        return found

    def _next_data_detail_json(self, html: str) -> Any:
        """Read a posting object from the page's Next.js ``__NEXT_DATA__``.

        The mirror of :meth:`_json_listing_jobs` for a detail page: boards such
        as BestJobs render the ad in the browser but ship the whole record in
        ``<script id="__NEXT_DATA__">``, addressed by :attr:`detail_json_path`.
        Missing or malformed JSON is an error so a layout change is visible.
        """
        soup = BeautifulSoup(html or "", "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            raise HtmlScraperResponseError(
                f"{self._site_config.source_code} detail page has no __NEXT_DATA__"
            )
        try:
            payload = json.loads(script.string)
        except json.JSONDecodeError as exc:
            raise HtmlScraperResponseError(
                f"{self._site_config.source_code} __NEXT_DATA__ is not valid JSON: {exc}"
            ) from exc
        path = self._site_config.detail_json_path.strip()
        if not path:
            return payload
        found = self._dotted(payload, path)
        if found in (None, ""):
            raise HtmlScraperResponseError(
                f"__NEXT_DATA__ path {path} is missing from the detail page"
            )
        return found

    def listing_data_url(self, page: int = 1) -> str:
        """The JSON listing endpoint for a 1-based page number."""
        base = self._site_config.listing_json_url.strip()
        # A few APIs number their first page zero (Jobbnorge's Jobs endpoint).
        if "{zero_page}" in base:
            return base.format(zero_page=page - 1)
        # Some APIs page from zero; ``{offset}`` keeps the framework's 1-based
        # page numbers and lets the site describe its own numbering.
        if "{offset}" in base:
            offset = (page - 1) * self._site_config.listing_page_size
            return base.format(offset=offset)
        if "{page}" in base:
            return base.format(page=page)
        if page <= 1:
            return base
        pagination = self._site_config.listing_pagination
        if "{offset}" in pagination:
            offset = (page - 1) * self._site_config.listing_page_size
            return base + pagination.format(offset=offset)
        return base + pagination.format(page=page)

    def _listing_body(self, page: int) -> str:
        """Render the JSON body for a POST listing endpoint.

        Substituted textually rather than with ``str.format`` because the body
        is itself JSON: ``{"limit":{limit},...}`` has to keep every brace that
        is not a placeholder.
        """
        template = self._site_config.listing_json_body
        if not template:
            return ""
        offset = (page - 1) * self._site_config.listing_page_size
        return (
            template.replace("{limit}", str(self._site_config.listing_page_size))
            .replace("{offset}", str(offset))
            .replace("{zero_page}", str(page - 1))
            .replace("{page}", str(page))
        )

    def _mapped_value(self, payload: Any, path: str, listing: dict | None) -> Any:
        """Resolve a ``detail_json_map`` path, allowing ``listing.`` fields."""
        return _mapped_value(payload, path, listing)

    def _json_detail_as_html(self, payload: Any, url: str, listing: dict | None = None) -> str:
        """Render mapped JSON fields into the minimal HTML the parser expects."""
        return mapped_json_html(self._site_config, payload, url, listing)

    def _html_listing_jobs(self, html: str, soup: BeautifulSoup) -> list[dict]:
        """Discover links on a server-rendered listing page."""
        jobs: list[dict] = []

        if self._site_config.listing_json_path.strip():
            jobs = self._json_listing_jobs(html)

        # Try configured CSS selector first
        link_els = [] if jobs else self._select(soup, self._site_config.selectors.job_link)
        generic_selector = self._site_config.selectors.job_link.strip() == GENERIC_LINK_SELECTOR
        for el in link_els:
            link = _extract_attr(el, "href")
            title = _extract_text(el)
            if link:
                link = urljoin(self._site_config.base_url, link)
                if _is_offsite_social(link):
                    continue
                # Every auto-generated config carries the same guess
                # ("a[href*='/job/']..."), and on most sites it matches the
                # navigation (/careers, /vacancy-list). A guess does not get to
                # skip the URL test that auto-detection must pass.
                if generic_selector and not _is_job_url(link):
                    continue
                jobs.append({"url": link, "title": title or ""})

        # If selector found nothing, auto-extract all job-looking links
        if not jobs:
            raw_links = _extract_links_from_html(html, self._site_config.base_url)
            jobs = [{"url": u, "title": t} for u, t in raw_links if not _is_offsite_social(u)]
        return jobs

    def fetch_listing_page(self, page: int = 1) -> tuple[str, list[dict]]:
        """Fetch one listing page. Returns (html, [job_links_with_titles])."""
        if self._site_config.listing_json_url.strip():
            url = self.listing_data_url(page)
            if self._site_config.listing_json_method.strip().upper() == "POST":
                html = self._post_json(url, self._listing_body(page))
            else:
                html = self._get(url)
            try:
                payload = self._maybe_inflate(json.loads(html))
            except json.JSONDecodeError as exc:
                raise HtmlScraperResponseError(
                    f"listing JSON endpoint returned non-JSON for page {page}: {exc}"
                ) from exc
            self._remember_listing_cursor(payload)
            jobs = self._jobs_from_payload(payload)
        elif (
            self._site_config.listing_json_selector.strip()
            and self._site_config.listing_json_attr.strip()
        ):
            html = self._get(self.listing_url(page))
            jobs = self._embedded_json_jobs(html)
        else:
            html = self._get(self.listing_url(page))
            soup = BeautifulSoup(html, "html.parser")
            jobs = self._html_listing_jobs(html, soup)

        # Deduplicate by posting identity: the URL where the board has one
        # per posting, the feed's id where it does not.
        seen = set()
        unique_jobs = []
        for j in jobs:
            key = _discovery_key(j)
            if key not in seen:
                seen.add(key)
                unique_jobs.append(j)

        logger.info("html_scraper listing page {}: {} job link(s)", page, len(unique_jobs))
        if not unique_jobs and page == 1:
            self._warn_empty_listing(html)
        return html, unique_jobs

    def _warn_empty_listing(self, html: str) -> None:
        """Say *what* the runner actually received when page 1 has no links.

        A 200 response with none of the expected anchors is ambiguous: the
        board may have changed its markup, or it may be serving an anti-bot
        interstitial. ``listing page 1: 0 job link(s)`` alone cannot tell them
        apart, which is what made lucru_md's CI-only failure undiagnosable on
        2026-10-30. Log the title, size, a text sample and any known challenge
        marker, so the next run explains itself.
        """
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else "<no title>"
        sample = " ".join(soup.get_text(" ", strip=True).split())[:240]
        lowered = html.lower()
        marker = next((m for m in _CHALLENGE_MARKERS if m in lowered), "")
        logger.warning(
            "html_scraper listing page 1 yielded no links: title={!r} bytes={} sample={!r}"
            + (" challenge_marker={!r}" if marker else ""),
            title,
            len(html),
            sample,
            *([marker] if marker else []),
        )

    def discover_detail_paths(
        self, max_jobs: int | None = None
    ) -> tuple[list[dict], dict[str, str]]:
        """Walk listing pages, collecting detail URLs."""
        found: list[dict] = []
        failures: dict[str, str] = {}
        seen_keys: set[str] = set()
        budget = max_jobs or self._site_config.max_jobs_per_run

        for page in range(1, self._site_config.max_pages + 1):
            try:
                _, jobs = self.fetch_listing_page(page)
            except HtmlScraperFetchError as exc:
                failures[f"page={page}"] = str(exc)
                logger.warning("html_scraper listing page {} failed: {}", page, exc)
                break
            if not jobs:
                break
            new = 0
            for job in jobs:
                key = _discovery_key(job)
                if key not in seen_keys:
                    seen_keys.add(key)
                    found.append(job)
                    new += 1
            logger.info("html_scraper page {}: {} new ({} total)", page, new, len(found))
            if len(found) >= budget:
                break
            if new == 0:
                # A page that adds nothing means the listing is repeating
                # itself -- an exhausted cursor, or a pager that ignores its
                # own parameter -- and later pages would only re-read it.
                break
            time.sleep(self._site_config.inter_request_delay_seconds)

        if not found and not failures:
            raise HtmlScraperResponseError(
                "no postings found. The listing markup may have changed."
            )
        return found, failures

    def fetch_detail(self, url: str) -> str:
        """Fetch one detail page HTML."""
        return self._get(url)

    def _mapped_json_html(self, payload: Any, url: str, listing: dict | None = None) -> str:
        """Render a mapped JSON payload, refusing an empty field map."""
        html = self._json_detail_as_html(payload, url, listing)
        if not html:
            raise HtmlScraperFetchError(
                f"detail_json_map is empty for {self._site_config.source_code}"
            )
        return html

    def _maybe_inflate(self, payload: Any) -> Any:
        """Inflate a board's ``_data_`` envelope, leaving other payloads alone."""
        if not self._site_config.json_inflate:
            return payload
        return _inflate_indexed_zlib(payload)

    def _load_json(self, url: str) -> Any:
        """Fetch one JSON document, keeping the error message specific."""
        try:
            return self._maybe_inflate(json.loads(self._get(url)))
        except json.JSONDecodeError as exc:
            raise HtmlScraperFetchError(
                f"detail JSON endpoint returned non-JSON for {url}: {exc}"
            ) from exc

    def _detail_json_payload(self, job_id: Any) -> Any:
        """Fetch a posting's JSON, trying each configured language."""
        template = self._site_config.detail_json_url.strip()
        languages = self._site_config.detail_json_languages
        if "{language}" not in template or not languages:
            return self._load_json(template.format(id=job_id))

        failure: HtmlScraperFetchError | None = None
        for language in languages:
            try:
                return self._load_json(template.format(id=job_id, language=language))
            except HtmlScraperFetchError as exc:
                failure = exc
        if failure is not None:
            raise failure
        raise HtmlScraperFetchError(f"no language configured for {template}")

    def _detail_page(self, job: dict) -> tuple[str, str | None]:
        """The HTML the parser reads for one discovered posting, plus its URL.

        The URL is normally the discovered one. A listing API that knows only
        numeric ids (Navent) leaves the canonical ``/<section>/<slug>-<id>.html``
        to the detail payload, and :attr:`detail_json_url_path` names it.
        """

        def finish(html: str, payload: Any) -> tuple[str, str | None]:
            path = self._site_config.detail_json_url_path.strip()
            canonical = self._dotted(payload, path) if path else None
            if canonical in (None, ""):
                return html, None
            return html, urljoin(self._site_config.base_url, str(canonical))

        if self._site_config.detail_json_from_listing and job.get("payload"):
            payload = job["payload"]
            return finish(self._mapped_json_html(payload, job["url"], job.get("listing")), payload)
        if self._site_config.detail_json_url.strip():
            job_id = job.get("id") or self._job_id_from_url(job["url"])
            payload = self._detail_json_payload(job_id)
            return finish(self._mapped_json_html(payload, job["url"], job.get("listing")), payload)
        if (
            self._site_config.detail_json_selector.strip()
            and self._site_config.detail_json_attr.strip()
        ):
            page = self.fetch_detail(job["url"])
            payload = self._embedded_detail_json(page)
            return finish(self._mapped_json_html(payload, job["url"], job.get("listing")), payload)
        if self._site_config.detail_json_next_data:
            page = self.fetch_detail(job["url"])
            payload = self._next_data_detail_json(page)
            return finish(self._mapped_json_html(payload, job["url"], job.get("listing")), payload)
        if self._site_config.detail_json_ld:
            page = self.fetch_detail(job["url"])
            payload = _json_ld_job_posting(page)
            if payload is None:
                raise HtmlScraperFetchError(f"no JobPosting JSON-LD on {job['url']}")
            return finish(self._mapped_json_html(payload, job["url"], job.get("listing")), payload)
        return self.fetch_detail(job["url"]), None

    def fetch_raw_jobs(self, max_jobs: int | None = None) -> tuple[list[dict], dict[str, str]]:
        """Discover and fetch postings."""
        budget = self._site_config.max_jobs_per_run if max_jobs is None else max_jobs
        discovered, failures = self.discover_detail_paths(budget)

        selected = discovered[:budget]
        records = []
        for job in selected:
            try:
                html, canonical = self._detail_page(job)
                url = canonical or job["url"]
                if job.get("url_from_id"):
                    job_id = str(job["id"])
                elif self._site_config.id_from_url:
                    job_id = self._job_id_from_url(url)
                else:
                    job_id = url
                records.append(
                    {
                        "job_id": job_id,
                        "html": html,
                        "url": url,
                        "title_hint": job.get("title", ""),
                        "listing_page": None,
                    }
                )
            except HtmlScraperFetchError as exc:
                failures[job["url"]] = str(exc)
                logger.warning("html_scraper detail fetch failed for {}: {}", job["url"], exc)
            time.sleep(self._site_config.inter_request_delay_seconds)

        if not records and not failures:
            raise HtmlScraperResponseError(
                "discovery succeeded but every posting was dropped before fetching."
            )
        logger.info("html_scraper: {} record(s), {} failure(s)", len(records), len(failures))
        return records, failures
