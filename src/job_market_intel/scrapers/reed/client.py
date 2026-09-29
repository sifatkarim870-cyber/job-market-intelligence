"""Fetches raw job data from Reed's Jobseeker API.

This module's only responsibility is: make the HTTP requests (with
retries for transient failures, and Basic Auth on every request), confirm
each response looks like what it should, and hand back raw dictionaries.
It does not validate individual job fields (``parser.py``'s job) and it
does not decide WHICH jobs need a Details call (``pipeline.py``'s job,
since that decision needs to consult the database — see that module's
docstring). Same fetch/validate/decide separation
``RemotiveClient``/``RemoteOKClient`` already establish, extended by one
more layer because Reed is a two-endpoint API.

Two endpoints, confirmed live during scoping, not assumed from Reed's own
(thinner) documentation
--------------------------------------------------------------------------
- Search (``fetch_search_page``): paginated via ``resultsToTake``
  (max 100)/``resultsToSkip``. Reliably returns
  ``jobId``/``employerName``/``jobTitle``/``locationName``/``jobUrl``/
  dates/``minimumSalary``/``maximumSalary``, but NOT reliable
  ``currency``/``salaryType``/``contractType``/``fullTime``/``partTime``
  — confirmed live returning ``null`` for these even on jobs whose
  Details response had real values.
- Details (``fetch_job_details``): one job at a time, by ``jobId``. The
  only place ``currency``/``salaryType``/``contractType``/``fullTime``/
  ``partTime``/``externalUrl`` are reliably available.

Auth: HTTP Basic, API key as username, empty password — Reed's own
documented scheme, confirmed against ``reed.co.uk/developers/jobseeker``
and against real API calls (a wrong/missing key returns 401, caught below
as ``ReedAuthenticationError``).

No documented rate limit exists anywhere (confirmed: neither Reed's own
docs page nor any response header observed live during scoping states
one) — see ``config.py``'s module docstring for how this scraper responds
to that uncertainty (a conservative, tunable per-run Details cap) rather
than assuming a number.
"""

from __future__ import annotations

from loguru import logger

from job_market_intel.common.http_client import PermanentHTTPError, TransientHTTPError, fetch_json
from job_market_intel.common.retry import call_with_retry

from .config import ReedSettings
from .exceptions import ReedAuthenticationError, ReedFetchError, ReedResponseError
from .search_queries import ReedSearchQuery


class ReedClient:
    """Fetches job search results and per-job details from Reed's Jobseeker API."""

    def __init__(self, settings: ReedSettings | None = None) -> None:
        """Create a client.

        Args:
            settings: Configuration to use. If omitted, ``ReedSettings()``
                is constructed from the environment/``.env`` file —
                raises immediately if ``REED_API_KEY`` isn't set, see
                ``config.py``'s module docstring for why that's
                deliberate.
        """
        self._settings = settings or ReedSettings()

    def _get(self, url: str) -> object:
        """Shared GET-with-auth-and-retry logic for both endpoints."""
        try:
            return call_with_retry(
                fetch_json,
                url,
                retry_exception_types=TransientHTTPError,
                max_attempts=self._settings.max_retry_attempts,
                initial_wait_seconds=self._settings.retry_initial_wait_seconds,
                max_wait_seconds=self._settings.retry_max_wait_seconds,
                timeout_seconds=self._settings.request_timeout_seconds,
                user_agent=self._settings.user_agent,
                auth=(self._settings.api_key, ""),
            )
        except TransientHTTPError as exc:
            raise ReedFetchError(
                f"Could not reach {url} after {self._settings.max_retry_attempts} attempts: {exc}"
            ) from exc
        except PermanentHTTPError as exc:
            if "status 401" in str(exc) or "status 403" in str(exc):
                raise ReedAuthenticationError(
                    f"Reed rejected the configured REED_API_KEY (request to {url}): {exc}"
                ) from exc
            raise ReedFetchError(f"Request to {url} failed permanently: {exc}") from exc

    def fetch_search_page(
        self, query: ReedSearchQuery, *, results_to_skip: int = 0
    ) -> tuple[list[dict], int]:
        """Fetch one page of Search results for a query.

        Args:
            query: The search filter parameters for this page.
            results_to_skip: Reed's ``resultsToSkip`` paging offset.

        Returns:
            A ``(results, total_results)`` tuple: this page's raw job
            dictionaries (Reed's ``results`` list), and Reed's own
            reported ``totalResults`` for the query as a whole (used by
            ``fetch_search_results`` to know when to stop paging).

        Raises:
            ReedAuthenticationError: If the configured API key was
                rejected (HTTP 401/403).
            ReedFetchError: If the request could not be completed after
                exhausting all retries, or failed permanently for a
                reason other than authentication.
            ReedResponseError: If the response was valid JSON but not
                shaped like a Search response.
        """
        params = {
            "resultsToTake": str(self._settings.results_per_page),
            "resultsToSkip": str(results_to_skip),
        }
        if query.keywords:
            params["keywords"] = query.keywords
        if query.location_name:
            params["locationName"] = query.location_name
        if query.distance_from_location is not None:
            params["distanceFromLocation"] = str(query.distance_from_location)

        query_string = "&".join(f"{key}={_url_encode(value)}" for key, value in params.items())
        url = f"{self._settings.search_url}?{query_string}"

        logger.info(
            "Fetching Reed search page (keywords={!r}, location={!r}, skip={}).",
            query.keywords,
            query.location_name,
            results_to_skip,
        )
        response = self._get(url)

        if not isinstance(response, dict):
            raise ReedResponseError(
                f"Expected Reed Search's response to be a JSON dict, got "
                f"{type(response).__name__} instead. The API's shape may have changed."
            )
        results = response.get("results")
        if not isinstance(results, list):
            raise ReedResponseError(
                "Expected Reed Search's response to contain a 'results' list. "
                "The API's shape may have changed."
            )
        total_results = response.get("totalResults")
        if not isinstance(total_results, int):
            raise ReedResponseError(
                "Expected Reed Search's response to contain an integer 'totalResults'. "
                "The API's shape may have changed."
            )
        job_records = [entry for entry in results if isinstance(entry, dict)]
        return job_records, total_results

    def fetch_search_results(self, query: ReedSearchQuery) -> list[dict]:
        """Fetch every Search result page for one query, up to the configured safety cap.

        Pages via ``resultsToSkip`` until either Reed reports no more
        results (``resultsToSkip >= totalResults``), a page comes back
        empty, or ``ReedSettings.max_search_pages_per_query`` is reached
        — whichever comes first. See ``config.py``'s module docstring for
        why that cap exists (no confirmed total-results ceiling from Reed
        itself).

        Returns:
            All raw job dictionaries across every page fetched for this
            query. May be a truncated subset of Reed's real total if the
            page cap was reached — logged when this happens, not silent.
        """
        all_results: list[dict] = []
        results_to_skip = 0

        for _page_number in range(self._settings.max_search_pages_per_query):
            page_results, total_results = self.fetch_search_page(
                query, results_to_skip=results_to_skip
            )
            if not page_results:
                break
            all_results.extend(page_results)
            results_to_skip += len(page_results)
            if results_to_skip >= total_results:
                break
        else:
            logger.warning(
                "Reed search for keywords={!r}, location={!r} hit the "
                "max_search_pages_per_query cap ({}) with more results "
                "possibly still available — fetched {} of {} reported total.",
                query.keywords,
                query.location_name,
                self._settings.max_search_pages_per_query,
                len(all_results),
                total_results,
            )

        logger.info(
            "Fetched {} total search results for keywords={!r}, location={!r}.",
            len(all_results),
            query.keywords,
            query.location_name,
        )
        return all_results

    def fetch_job_details(self, job_id: str) -> dict:
        """Fetch the Details response for a single job.

        Args:
            job_id: Reed's ``jobId`` for the job to fetch.

        Returns:
            The raw Details response dictionary.

        Raises:
            ReedAuthenticationError: If the configured API key was
                rejected.
            ReedFetchError: If the request could not be completed after
                exhausting all retries, or failed permanently for a
                reason other than authentication (including a 404 for a
                job ID Reed no longer recognizes — a posting can be
                removed between being seen in Search and this call).
            ReedResponseError: If the response was valid JSON but not
                shaped like a Details response (missing ``jobId``).
        """
        url = f"{self._settings.details_url}/{job_id}"
        response = self._get(url)
        if not isinstance(response, dict) or "jobId" not in response:
            raise ReedResponseError(
                f"Expected Reed Details response for job {job_id} to be a JSON dict "
                "containing 'jobId'. The API's shape may have changed."
            )
        return response


def _url_encode(value: str) -> str:
    """Percent-encode one query-parameter value.

    ``requests`` itself would handle this automatically via its ``params``
    kwarg, but ``common.http_client.fetch_json`` takes a single pre-built
    URL string (see that module's docstring) rather than a separate params
    dict — this is the small amount of encoding that shifts onto this
    client as a result.
    """
    from urllib.parse import quote

    return quote(value, safe="")
