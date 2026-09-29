"""Minimal shared HTTP GET helper.

Why this exists as its own module instead of scrapers calling ``requests``
directly: it draws one important line that every scraper needs — the
difference between a *transient* failure (worth retrying: dropped
connection, timeout, the server returned a 5xx "something went wrong on our
end") and a *permanent* failure (not worth retrying: a 404, a 400, a
response that isn't valid JSON at all). That distinction is encoded once,
here, as two separate exception types, so ``src/common/retry.py`` can be
told "only retry ``TransientHTTPError``" without every scraper needing to
re-derive which HTTP status codes mean what.
"""

from __future__ import annotations

from typing import Any

import requests

#: A default, honest User-Agent. This identifies the request as coming from
#: this research platform rather than pretending to be a browser. Some
#: sites reject requests with no User-Agent at all, so sending *something*
#: identifiable is both more transparent and more reliable than sending
#: nothing.
DEFAULT_USER_AGENT = "JobMarketIntelligencePlatform-Research/1.0 (+https://example-research-project.local)"


class HTTPClientError(Exception):
    """Base class for all errors raised by this module."""


class TransientHTTPError(HTTPClientError):
    """A failure that is likely to succeed if retried later.

    Raised for network-level errors (connection refused, DNS failure),
    timeouts, and HTTP 5xx responses (server-side errors that are usually
    temporary).
    """


class PermanentHTTPError(HTTPClientError):
    """A failure that will not be fixed by retrying.

    Raised for HTTP 4xx responses (the request itself is wrong — bad URL,
    unauthorized, not found) and for responses that claim success but
    don't actually contain valid JSON.
    """


def fetch_json(
    url: str,
    *,
    timeout_seconds: float = 15.0,
    user_agent: str = DEFAULT_USER_AGENT,
    extra_headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
) -> Any:
    """Perform an HTTP GET request and return the parsed JSON body.

    Args:
        url: The full URL to request.
        timeout_seconds: Maximum time to wait for a response before treating
            the request as failed. Applies to both connecting and reading
            the response.
        user_agent: The ``User-Agent`` header value to send. See
            ``DEFAULT_USER_AGENT`` for why this is set explicitly rather
            than left blank.
        extra_headers: Any additional headers to merge in (e.g.
            ``Accept``). ``Accept: application/json`` is always sent by
            default and does not need to be repeated here.
        auth: Optional ``(username, password)`` tuple for HTTP Basic
            authentication, passed straight through to ``requests.get``.
            ``None`` (the default) sends no auth header at all, so every
            existing caller of this function is unaffected. Added for the
            Reed scraper, whose API requires the API key as the Basic
            Auth username with an empty password on every request — no
            existing source needed this before.

    Returns:
        The response body, parsed from JSON (typically a ``list`` or
        ``dict`` depending on the API).

    Raises:
        TransientHTTPError: On connection errors, timeouts, HTTP 429
            (rate limited), or HTTP 5xx responses. Callers should retry
            these (see ``src/common/retry.py``).
        PermanentHTTPError: On other HTTP 4xx responses, or on a 2xx
            response whose body is not valid JSON. Callers should not
            retry these without changing something first.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)

    try:
        response = requests.get(url, headers=headers, timeout=timeout_seconds, auth=auth)
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise TransientHTTPError(f"Network error while requesting {url}: {exc}") from exc
    except requests.RequestException as exc:
        # Any other requests-library failure we didn't anticipate specifically.
        # Treated as permanent by default since we don't know it's safe to retry.
        raise PermanentHTTPError(f"Unexpected request failure for {url}: {exc}") from exc

    if response.status_code >= 500:
        raise TransientHTTPError(
            f"{url} returned server error status {response.status_code}: {response.text[:500]!r}"
        )
    # 429 (Too Many Requests) is a 4xx status but, unlike the others, IS
    # worth retrying after a cooldown -- added for Reed, whose API can be
    # rate limited with no documented ceiling to plan around in advance
    # (see scrapers/reed/client.py's module docstring). No existing
    # source has ever been observed to return 429, so this is additive.
    if response.status_code == 429:
        raise TransientHTTPError(
            f"{url} returned 429 (rate limited): {response.text[:500]!r}"
        )
    if response.status_code >= 400:
        raise PermanentHTTPError(
            f"{url} returned client error status {response.status_code}: {response.text[:500]!r}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise PermanentHTTPError(
            f"{url} returned a 2xx response that was not valid JSON: {exc}"
        ) from exc


def fetch_html(
    url: str,
    *,
    timeout_seconds: float = 15.0,
    user_agent: str = DEFAULT_USER_AGENT,
    extra_headers: dict[str, str] | None = None,
) -> str:
    """Perform an HTTP GET request and return the response body as text.

    The HTML-scraping counterpart to ``fetch_json`` above, for sources
    whose data isn't available as a JSON API and has to be pulled out of
    rendered HTML instead. Deliberately kept as generic, source-agnostic
    plumbing here rather than inside any one scraper's own package -
    "fetch a URL and classify the failure as transient or permanent" is
    exactly the same problem whether the body ends up parsed as JSON or
    as HTML, so it belongs in the one shared
    place any scraper can use, same as ``fetch_json``.

    Unlike ``fetch_json``, this does not attempt to parse the body at all
    (HTML parsing is BeautifulSoup's job, done by the caller) - it only
    handles the network request and the transient/permanent error split.

    Args:
        url: The full URL to request.
        timeout_seconds: Maximum time to wait for a response before treating
            the request as failed.
        user_agent: The ``User-Agent`` header value to send.
        extra_headers: Any additional headers to merge in. ``Accept:
            text/html`` is sent by default and does not need to be repeated.

    Returns:
        The raw response body as a string (``response.text``), ready to
        hand to ``BeautifulSoup``.

    Raises:
        TransientHTTPError: On connection errors, timeouts, or HTTP 5xx
            responses. Callers should retry these.
        PermanentHTTPError: On HTTP 4xx responses.
    """
    headers = {"User-Agent": user_agent, "Accept": "text/html"}
    if extra_headers:
        headers.update(extra_headers)

    try:
        response = requests.get(url, headers=headers, timeout=timeout_seconds)
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise TransientHTTPError(f"Network error while requesting {url}: {exc}") from exc
    except requests.RequestException as exc:
        raise PermanentHTTPError(f"Unexpected request failure for {url}: {exc}") from exc

    if response.status_code >= 500:
        raise TransientHTTPError(
            f"{url} returned server error status {response.status_code}: {response.text[:500]!r}"
        )
    if response.status_code >= 400:
        raise PermanentHTTPError(
            f"{url} returned client error status {response.status_code}: {response.text[:500]!r}"
        )

    return response.text
