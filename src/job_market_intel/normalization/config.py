"""Configuration for cross-source duplicate detection (Step 19).

Mirrors ``scrapers/remotive/config.py``/etc.'s reasoning exactly: values
live here, loaded via ``pydantic-settings``, so tuning the matching
window is a one-line ``.env`` edit, not a code change. Every setting has
a sensible default, so the dedup batch job works out-of-the-box with no
``.env`` entries at all. Add entries prefixed with ``DEDUP_`` to override
a default, e.g.::

    DEDUP_POSTING_DATE_WINDOW_DAYS=5

Scope note: this project is intentionally conservative for Step 19 (per
the confirmed design decision) — matching is exact-normalized
title+company within a date window, not fuzzy. There is deliberately no
similarity-threshold setting here yet; add one only when fuzzy matching
is actually introduced, rather than exposing an unused knob now.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DedupSettings(BaseSettings):
    """Configuration for the cross-source duplicate-detection batch job.

    Attributes:
        posting_date_window_days: Two active jobs from different sources
            with an identical normalized (title, company) are only
            considered a duplicate pair if their ``posting_date`` values
            are within this many days of each other. Exists because
            "posting date" isn't guaranteed to be recorded with identical
            granularity or timezone handling across sources — see
            ``normalization/dedup.py``'s module docstring for the fuller
            rationale. Default of 3 is a starting point, not calibrated
            against real cross-source duplicate volume (current source
            volume is low); revisit once real matches/false-positives
            are observed in production.
    """

    model_config = SettingsConfigDict(
        env_prefix="DEDUP_",
        case_sensitive=False,
        extra="ignore",
    )

    posting_date_window_days: int = Field(default=3, ge=0)


def get_dedup_settings() -> DedupSettings:
    """Returns a fresh ``DedupSettings`` instance (env/`.env`-backed).

    Not cached (unlike ``common.config.get_settings()``) since nothing in
    this project's dedup batch job runs hot enough for repeated
    construction to matter, and tests benefit from being able to
    construct fresh instances with different env overrides without
    fighting an ``lru_cache``.
    """
    return DedupSettings()


class CompanyResolutionSettings(BaseSettings):
    """Configuration for the company-alias candidate-generation batch job
    (Step 25 -- see ``normalization/company_resolution.py``).

    Attributes:
        similarity_threshold: Minimum ``pg_trgm`` ``similarity()`` score
            (0-1) between two ``core.companies.normalized_name`` values
            for the pair to be proposed as a candidate alias. Default of
            0.5 is a starting point, not calibrated against real
            near-duplicate volume (confirmed against real data: at 212
            companies, exactly one genuine pair -- "Dexterra" /
            "Dexterra Group" -- was found by eye; revisit this default
            once more candidates/false-positives are observed at higher
            company volume). Add ``COMPANY_RESOLUTION_SIMILARITY_THRESHOLD``
            to ``.env`` to override without a code change.
    """

    model_config = SettingsConfigDict(
        env_prefix="COMPANY_RESOLUTION_",
        case_sensitive=False,
        extra="ignore",
    )

    similarity_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


def get_company_resolution_settings() -> CompanyResolutionSettings:
    """Returns a fresh ``CompanyResolutionSettings`` instance (env/`.env`-backed).

    Not cached, for the same reason as ``get_dedup_settings()`` -- see
    that function's docstring.
    """
    return CompanyResolutionSettings()
