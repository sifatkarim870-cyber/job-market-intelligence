"""Configuration for the Empléate (Spain) scraper.

Empléate is Spain's public employment service portal
(``www.empleate.gob.es``). Its AngularJS front end is driven by a public
Solr endpoint that needs no key, no registration and no proxy. Every
property below was measured against the live API on 2026-11-20 rather
than assumed.

**Discovery** is one Solr query::

    GET /empleate/open/offersearch/selectBuscador
        ?q.op=AND&q=*&wt=json&fq=checkVisible:true
        &rows=100&start=<offset>&sort=fechaCreacion desc,id desc
        &fl=<field list>

Measured facts:

* ``numFound`` was **26,073** visible ads (facet ``paisF``: 23,801 ES and
  ~20 foreign, mostly the Netherlands, France and Andorra).
* ``rows`` is capped at **100** server-side: ``rows=200`` silently returns
  100 docs, so ``page_size`` is clamped to 100 rather than trusting a
  larger request to work.
* ``start`` pages all the way to the end: ``start=26072`` returned the
  single last document, so the whole corpus is addressable by offset.
* The default order is by **relevance**, not date, so a run must pass
  ``sort`` explicitly. ``fechaCreacion desc`` alone is not deterministic
  because hundreds of ads share the same timestamp (the nightly SNE batch
  inserts dozens per second); adding ``id desc`` was measured to give
  stable, non-overlapping page boundaries, so the tie-breaker is part of
  the URL.
* The listing document already carries the full posting: ``titulo``,
  ``creador`` (employer), ``contenido`` (the description, HTML or plain
  text), ``ciudadF``/``provinciaF``/``paisF``, ``fechaCreacion``,
  ``salarioMin``/``salarioMax``, ``tipoContrato``/``tipoContratoN``,
  ``jornada``/``jornadaF``, ``modality``, ``horario``,
  ``educacionReqF`` and ``experienciaF``. No per-ad detail request is
  needed; the SPA's ``open/offer/load/<id>`` endpoint adds only
  formatting (a display salary string and the contract label), so a run
  costs one request per 100 postings.

**Freshness and coverage.** 760 ads were created in the 24 hours before
measurement and 3,636 in the previous seven days. Almost all of them
arrive in one nightly SNE batch just after midnight: the newest 12,000
documents are that feed, and they carry no ``creador``, ``experienciaF``
or ``horario`` at all, while older documents do. A "newest N" window
smaller than the nightly batch would therefore re-read the same ads all
day and never reach the rest of the batch, so ``fresh_rows`` is sized
above the measured daily volume (800) and the default budget is 1,000.

The remaining budget comes from an archive window that advances one
window-width per **hour**, so the four scheduled runs each read a
different slice and the older 25k ads are tiled over successive days
instead of the same first page being re-read forever.

**robots.txt** at ``/empleate/robots.txt`` is ``User-agent: *`` /
``Allow: /``; only the logged-in employer/candidate areas are disallowed,
and this scraper touches none of them. There is no ``Crawl-delay``; a
polite 1.5 s gap between the few listing requests is kept anyway.

**TLS note.** The host sends only its leaf certificate; see ``tls.py``
for the measured chain, the shipped intermediate and why verification
stays enabled.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmpleateEsSettings(BaseSettings):
    """Runtime configuration for the Empléate (Spain) scraper."""

    model_config = SettingsConfigDict(
        env_prefix="EMPLEATE_ES_",
        case_sensitive=False,
        extra="ignore",
    )

    base_url: str = Field(default="https://www.empleate.gob.es", description="Site root.")
    search_url: str = Field(
        default="https://www.empleate.gob.es/empleate/open/offersearch/selectBuscador",
        description="Public Solr search endpoint used for discovery.",
    )
    site_offer_url_template: str = Field(
        default="https://www.empleate.gob.es/empleo/#/oferta/{job_id}",
        description="Canonical, user-facing offer URL (the SPA route).",
    )

    page_size: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Documents per request. The API silently caps this at 100.",
    )
    max_jobs_per_run: int = Field(
        default=1000,
        ge=1,
        description="Cap on postings fetched and persisted in one run.",
    )

    #: The newest rows are always taken so a run never misses what was just
    #: posted. Sized above the measured daily volume of 760 ads because one
    #: nightly SNE batch alone can exceed 700; a smaller window would re-read
    #: the same rows all day and never reach the rest of that batch.
    fresh_rows: int = Field(
        default=800,
        ge=0,
        description="Newest listing rows always sampled, ahead of the rotating window.",
    )
    #: ``None`` = derive the tail start from the clock, advancing one
    #: budget-width per hour. Pinning it makes a run reproducible (tests and
    #: manual runs use it); CI leaves it unset.
    start_offset: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Absolute corpus offset (not pool-relative) for the rotating tail "
            "window; page-aligned and pushed past the fresh region."
        ),
    )

    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        description="Browser user agent; the public API answers it with JSON.",
    )
    request_timeout: float = Field(default=30.0, gt=0)
    max_retry_attempts: int = Field(default=3, ge=1)
    retry_initial_wait_seconds: float = Field(default=5.0, ge=0.0)
    retry_max_wait_seconds: float = Field(default=30.0, ge=0.0)

    #: No Crawl-delay is advertised; this is a politeness gap between the few
    #: listing requests a run makes, not a robots requirement.
    rate_limit_delay: float = Field(default=1.5, ge=0.0)

    #: Optional override for the CA bundle. When unset, ``tls.build_ca_bundle``
    #: composes certifi's roots plus the intermediate the host omits.
    ca_bundle_path: str | None = Field(
        default=None,
        description="Explicit CA bundle path; defaults to certifi + shipped intermediate.",
    )
