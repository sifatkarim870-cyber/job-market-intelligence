"""Configuration for the Vinnumalastofnun (Iceland) scraper.

Vinnumalastofnun is Iceland's public employment service. The old
``vinnumalastofnun.is`` host no longer serves its own site: every path 301/302
redirects to ``island.is``, where the directorate has a hosted section at
``https://island.is/s/vinnumalastofnun``. The vacancy list lives at
``.../laus-storf`` ("open jobs") and is a Next.js page backed by a small Apollo
GraphQL endpoint -- so this is a bespoke client, not the generic
``html_scraper``.

**robots.txt** (``https://island.is/robots.txt``, HTTP 404 on 2026-11-28).
RFC 9309 sec. 2.3.1.3: a 4xx answer means the robots file is unavailable and
the crawler may access the site, so both ``/api/graphql`` and the
``/s/vinnumalastofnun/...`` pages are allowed. No ``Crawl-delay`` is
advertised (there is no robots file at all); a polite sub-second gap between
requests is kept anyway.

**The API.** The listing page calls one persisted GraphQL query,:

    GET https://island.is/api/graphql
        ?operationName=GetGenericListItems
        &variables={"input":{"genericListId":"2JaZ1n1FDssBF7MskxfPDq",...}}
        &extensions={"persistedQuery":{"version":1,"sha256Hash":"80b5..."}}

The request must carry ``Content-Type: application/json`` or Apollo's CSRF
filter answers HTTP 400 ("This operation has been blocked as a potential
Cross-Site Request Forgery"). With that header the query returns the whole
board -- 26 open vacancies on 2026-11-28 -- as a ``getGenericListItems``
object with ``items`` and a ``total``.

**The detail.** Each item's public page is
``https://island.is/s/vinnumalastofnun/laus-storf/{slug}``. It is server
rendered, but its body is not in the visible markup in a scrapeable block: the
page ships a ``__NEXT_DATA__`` JSON blob whose ``props.pageProps.apolloState``
contains the ``GenericListItem`` for the ad plus the ``Html`` rich-text nodes
its ``content`` list references. Reading that blob gives the full description
without a browser, one request per vacancy.

**Coverage.** The board is small and fully paginated by ``size``; the client
asks for ``page_size`` items per page and walks every page (bounded by
``max_pages_scanned``), so a run sees the whole board rather than a rotating
window. The one date the source exposes is the application deadline
(``Umsóknarfrestur`` / "Last application date"), shown in the list item's
``date`` field; no publish timestamp is published, so ``posting_date`` is left
NULL and the store applies its normal scrape-date fallback.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_API = "https://island.is/api/graphql"

#: The Apollo persisted-query id for the "laus storf" generic list. It is tied
#: to the operation text the island.is front-end ships; if that text changes
#: the hash rotates and the endpoint answers a GraphQL error, which the client
#: surfaces instead of returning an empty board.
_LIST_ID = "2JaZ1n1FDssBF7MskxfPDq"
_PERSISTED_HASH = "80b5ba9c2276b01cfab45711d4a9df5bda21c9b2db42a44b3ebe32819611da7f"


class VinnumalastofnunIsSettings(BaseSettings):
    """Runtime configuration for the Vinnumalastofnun (Iceland) scraper."""

    model_config = SettingsConfigDict(
        env_prefix="VINNUMALASTOFNUN_IS_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://island.is", description="Site root.")
    listing_page_url: str = Field(
        default="https://island.is/s/vinnumalastofnun/laus-storf",
        description="Human-facing vacancy list page (also the Referer).",
    )
    graphql_url: str = Field(default=_API, description="Apollo GraphQL endpoint.")
    generic_list_id: str = Field(
        default=_LIST_ID, description="Persisted id of the 'laus storf' generic list."
    )
    persisted_query_hash: str = Field(
        default=_PERSISTED_HASH,
        description="Apollo persisted-query sha256 used by the listing page.",
    )
    detail_url_template: str = Field(
        default="https://island.is/s/vinnumalastofnun/laus-storf/{slug}",
        description="Server-rendered ad page; carries __NEXT_DATA__ with the body.",
    )
    page_size: int = Field(
        default=100,
        ge=1,
        description="Items per GraphQL page; the board is small enough for one page.",
    )
    max_jobs_per_run: int = Field(
        default=100,
        ge=1,
        description="Cap on detail pages fetched and postings persisted in one run.",
    )
    max_pages_scanned: int = Field(
        default=20,
        ge=1,
        description="Hard ceiling on listing pages (the measured board is 1 page).",
    )
    fetch_details: bool = Field(
        default=True,
        description="Fetch each ad page for its description. The list item alone has "
        "no body, so a run is far less useful without it; the switch keeps tests offline.",
    )

    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        description="Browser user agent; island.is has no robots file to honour a token.",
    )
    request_timeout_seconds: float = Field(default=45.0, gt=0)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=2.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=20.0, ge=0.0)

    #: No robots file exists, so no Crawl-delay. Half a second keeps a run under
    #: a minute while staying polite to a public employment service.
    inter_request_delay_seconds: float = Field(default=0.5, ge=0.0)
