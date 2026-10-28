"""Configuration for the generic HTML scraper framework.

Each site is configured via a JSON file in sites/ directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The link selector the config generator writes for every site it cannot
#: inspect. It is a hypothesis, not a verified selector, so discovery applies
#: the same URL test to its matches that auto-detection uses.
GENERIC_LINK_SELECTOR = (
    "a[href*='/job/'], a[href*='/vacancy/'], a[href*='/listing/'], a[href*='/career/']"
)


class SelectorConfig(BaseModel):
    job_card: str = Field(default="", description="CSS selector for job listing cards")
    job_link: str = Field(default="", description="CSS selector for job detail link")
    job_title: str = Field(default="", description="CSS selector for job title")
    company: str = Field(default="", description="CSS selector for company name")
    location: str = Field(default="", description="CSS selector for location")
    description: str = Field(default="", description="CSS selector for job description")
    posted_date: str = Field(default="", description="CSS selector for posting date")
    salary: str = Field(default="", description="CSS selector for salary")
    skills: str = Field(default="", description="CSS selector for skills list")
    employment_type: str = Field(default="", description="CSS selector for employment type")


class SiteConfig(BaseModel):
    source_code: str = Field(..., description="Unique source code")
    source_name: str = Field(..., description="Human-readable source name")
    country: str = Field(..., description="Country name")
    base_url: str = Field(..., description="Site base URL")
    listing_path: str = Field(default="/jobs", description="Listing page path")
    listing_pagination: str = Field(default="?page={page}", description="Pagination URL pattern")
    max_pages: int = Field(default=10, ge=1, description="Max listing pages")
    max_jobs_per_run: int = Field(default=60, ge=1, description="Max jobs per run")
    min_expected_jobs: int = Field(
        default=1, ge=1, description="Minimum expected jobs per run for validation"
    )
    selectors: SelectorConfig = Field(default_factory=SelectorConfig)
    #: Which title source to trust, most-trusted first. "h1" is the job's name
    #: on a rendered posting page; "og:title" is the SEO string, which on
    #: some boards is the *posting's* title and on others is a category
    #: heading with the site name appended. A site that knows which is which
    #: says so here.
    title_priority: str = Field(
        default="h1,og:title,title-tag,selector",
        description="Comma-separated title sources, most trusted first.",
    )
    #: Some boards put a badge inside the heading itself (Empleos.net renders
    #: ``<h3>Contador <small>Vacante Fresca</small></h3>``), which would end up
    #: in the stored title. Elements matching this selector are removed from
    #: the heading before its text is read.
    title_strip_selector: str = Field(
        default="", description="Child elements to remove from the title heading"
    )
    #: Some boards print a label and the date in one node ("Publicado el:
    #: 23-10-2026,"), which no CSS selector can split. When set, this regex's
    #: first match inside the posted-date text is the part to parse.
    posted_date_regex: str = Field(
        default="", description="Regex whose match inside the date text is the date"
    )
    #: Classifieds boards let an advertiser publish without a title; the page
    #: then has an empty heading and the URL slug names nothing ("-Recruitment
    #: 29693"). When set, the opening sentence of the description is used as the
    #: title instead of that slug.
    title_from_description: bool = Field(
        default=False, description="Use the description's first sentence when no title exists"
    )
    detail_url_pattern: str = Field(default="", description="Detail URL pattern")
    id_from_url: bool = Field(default=True, description="Extract job ID from URL")
    #: Boards such as zaplata.bg put the stable numeric ID before a free-form
    #: slug (``/<category>/<city>/703291/servizen-tehnik/``). The last URL
    #: segment is empty for trailing-slash URLs and the slug repeats across
    #: cities, so this regex's first group is used as the job ID when set.
    id_url_regex: str = Field(
        default="", description="Regex whose first group is the job ID in a detail URL"
    )
    #: Next.js boards embed the rendered job list in the page's
    #: ``__NEXT_DATA__`` JSON while rendering zero anchors server-side. When
    #: set, this dotted path (e.g. ``props.pageProps.jobs``) is read from that
    #: JSON instead of the CSS link selector, and each item is turned into a
    #: detail URL by :attr:`listing_json_url_template`.
    listing_json_path: str = Field(
        default="", description="Dotted path to the job list inside __NEXT_DATA__"
    )
    listing_json_url: str = Field(
        default="", description="Absolute JSON endpoint that returns the job list"
    )
    #: Some gateways answer a search only to POST (Karir's
    #: ``/v2/search/opportunities`` returns 405 for every GET). When this is
    #: ``POST``, :attr:`listing_json_body` is sent as the JSON request body.
    listing_json_method: str = Field(
        default="GET", description="HTTP method for listing_json_url (GET or POST)"
    )
    #: JSON body for a POST listing endpoint. ``{limit}``, ``{offset}``,
    #: ``{zero_page}`` and ``{page}`` are substituted textually, so the body's
    #: own braces stay part of the JSON.
    listing_json_body: str = Field(
        default="", description="JSON template sent to a POST listing endpoint"
    )
    listing_json_id_field: str = Field(
        default="id", description="Dotted field in each JSON job that holds its ID"
    )
    listing_json_url_template: str = Field(
        default="", description="Detail URL template for JSON jobs, e.g. /jobs/{id}"
    )
    #: Some pages embed the listing as a JSON attribute on a custom element
    #: instead of shipping anchors or a ``__NEXT_DATA__`` script (Sapo Emprego:
    #: ``<search-results-component :offers='[...]'>``). This selector names
    #: that element and :attr:`listing_json_attr` the attribute holding JSON.
    listing_json_selector: str = Field(
        default="", description="CSS selector for an element carrying embedded listing JSON"
    )
    listing_json_attr: str = Field(
        default="", description="Attribute on listing_json_selector that holds the JSON"
    )
    #: A feed that already carries an absolute detail URL (``link``) needs no
    #: template. When set, this dotted field is used verbatim.
    listing_json_url_field: str = Field(
        default="", description="Dotted field in each JSON job holding its detail URL"
    )
    #: JSON APIs often page by offset rather than page number. When
    #: ``listing_pagination`` contains ``{offset}``, the client substitutes
    #: ``(page - 1) * listing_page_size`` instead of ``{page}``.
    listing_page_size: int = Field(
        default=20, ge=1, description="Items per page, used to compute {offset}"
    )
    #: Some boards only serve a detail page as JSON. When set, the client fetches
    #: this template (``{id}`` substituted) and renders the mapped fields as a
    #: minimal HTML document, so the existing parser and validator keep working.
    detail_json_url: str = Field(
        default="", description="Absolute JSON detail URL template, e.g. https://api/jobs/{id}"
    )
    #: Some APIs address a posting in one language and answer 404 for another
    #: (Jobbnorge publishes each ad in only one of nb/en/nn/se). When set, and
    #: :attr:`detail_json_url` includes ``{language}``, these IDs are tried in
    #: order until one returns a payload.
    detail_json_languages: list[int] = Field(
        default_factory=list,
        description="Language IDs tried in order when detail_json_url has {language}",
    )
    #: Laravel/Inertia apps render nothing server-side but carry the whole page
    #: payload as JSON in an attribute (``<div id="app" data-page='{...}'>``).
    #: This selector/attribute pair names that element, and
    #: :attr:`detail_json_path` the dotted path to the posting object inside it.
    detail_json_selector: str = Field(
        default="", description="CSS selector for an element carrying embedded detail JSON"
    )
    detail_json_attr: str = Field(
        default="", description="Attribute on detail_json_selector that holds the JSON"
    )
    detail_json_path: str = Field(
        default="", description="Dotted path inside the embedded detail JSON, e.g. props.offre"
    )
    #: Many boards publish a schema.org ``JobPosting`` block in the detail page's
    #: ``application/ld+json`` script, while the visible markup wraps the same
    #: fields in unlabelled layout divs. When set, the client reads that block and
    #: maps it through :attr:`detail_json_map` instead of using CSS selectors.
    detail_json_ld: bool = Field(
        default=False, description="Read the detail page's JobPosting JSON-LD block"
    )
    detail_json_map: dict[str, str | list[str]] = Field(
        default_factory=dict,
        description="Output field -> dotted JSON path (or list of paths to concatenate)",
    )
    #: Some boards print each fact as a label beside its value in an unlabelled
    #: container (``<li><span>Töökoha asukoht</span><span>Harju maakond</span></li>``
    #: or ``<dt>Location</dt><dd>Tallinn</dd>``), which no CSS selector can
    #: address without pinning Tailwind class names that change on every deploy.
    #: This maps a field name (company, location, employment_type, salary,
    #: posted_date) to the visible label whose sibling carries the value, and is
    #: consulted only when the normal selector produced nothing.
    detail_label_map: dict[str, str] = Field(
        default_factory=dict,
        description="Output field -> visible label whose sibling holds the value",
    )
    #: Some feeds return the complete posting in the listing payload, so the
    #: detail page adds nothing. When set, each listing item is mapped through
    #: :attr:`detail_json_map` directly instead of being fetched again.
    detail_json_from_listing: bool = Field(
        default=False, description="Build the record from the listing JSON item"
    )
    #: Extra request headers, for APIs that require a custom token or flag
    #: (Jobnet's BFF rejects requests without ``x-csrf``).
    extra_headers: dict[str, str] = Field(
        default_factory=dict, description="Extra HTTP headers sent with every request"
    )
    user_agent: str = Field(
        default="job-market-intel-research (research@example.org)",
        description="Identifying UA",
    )
    request_timeout_seconds: int = Field(default=30, ge=1)
    inter_request_delay_seconds: float = Field(default=0.1, ge=0.0)
    currency_iso_code: str = Field(default="USD", description="Default currency")
    pay_period: str = Field(default="monthly", description="Default pay period")
    country_fallback: str = Field(default="", description="Fallback country name")


class HtmlScraperSettings(BaseSettings):
    """Global settings for the HTML scraper framework."""

    model_config = SettingsConfigDict(env_prefix="HTML_SCRAPER_", extra="ignore")

    @property
    def sites_dir(self) -> str:
        """Absolute path to the sites config directory."""
        # __file__ is scrapers/html_scraper/config.py; parents[4] is the project root.
        project_root = Path(__file__).resolve().parents[4]
        return str(
            project_root / "src" / "job_market_intel" / "scrapers" / "html_scraper" / "sites"
        )


def load_site_config(source_code: str, sites_dir: str | None = None) -> SiteConfig:
    """Load a site config from JSON file.

    ``sites_dir`` used to default to the relative string
    ``scrapers/html_scraper/sites``, which only exists if the process happens to
    run from inside ``src/``. Every caller passed the absolute settings path, so
    the broken default was never exercised -- calling it without an argument
    raised ``FileNotFoundError``. It now resolves through the settings object.
    """
    config_path = Path(sites_dir or HtmlScraperSettings().sites_dir) / f"{source_code}.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Site config not found: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    return SiteConfig(**data)


def list_available_sites(sites_dir: str | None = None) -> list[str]:
    """List all available site config files."""
    sites_path = Path(sites_dir or HtmlScraperSettings().sites_dir)
    if not sites_path.exists():
        return []
    return sorted(p.stem for p in sites_path.glob("*.json"))
