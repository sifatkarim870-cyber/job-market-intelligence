"""Defines WHAT the Reed pipeline searches for — genuinely open, not yet confirmed.

Every other live source (RemoteOK, Remotive, We Work Remotely) exposes a
single "give me everything currently active" feed with no query concept
at all — ``fetch_raw_jobs()`` takes no search parameters anywhere in this
codebase before Reed. Reed's API has no such endpoint: every Search call
requires (or at least meaningfully narrows around) ``keywords``/
``locationName``, there is no "all UK jobs" call to make instead.

This means "what do we search for" is a real, consequential scope
decision for a research platform aiming to be representative of the job
market — not an implementation detail — and it was NOT part of the
confirmed design (field mapping, CleanedJob diff, job_repository diff,
pipeline shape, request-budget approach). This module makes that decision
visible and easy to change, rather than burying an assumption inside
``pipeline.py``, and defaults to exactly ONE placeholder query so the
scraper is runnable for dry-run/testing purposes without silently scoping
real production data collection.

DO NOT treat DEFAULT_SEARCH_QUERIES below as the real, intended query
list for scheduled production runs — confirm the actual list (which
keywords, which locations, how many queries per run) before wiring this
into the scheduler, given each query's Search pagination plus its
per-job Details calls all draw against the same still-unverified daily
request budget (see ``config.py``'s module docstring).
"""

from __future__ import annotations

from pydantic import BaseModel


class ReedSearchQuery(BaseModel):
    """One Reed Search request's worth of filter parameters.

    Attributes:
        keywords: Free-text search terms, passed as Search's ``keywords``
            parameter. ``None`` omits the parameter entirely (Reed treats
            an omitted parameter as "no filter", not as "match nothing").
        location_name: A place name, passed as Search's ``locationName``
            parameter. ``None`` omits the parameter (nationwide UK
            search).
        distance_from_location: Search radius in miles around
            ``location_name``, passed as Search's ``distanceFromLocation``
            parameter. Reed's own default is 10 when a location is given;
            left as ``None`` here to mean "let Reed apply its own
            default" rather than this codebase silently picking a
            different one.
    """

    keywords: str | None = None
    location_name: str | None = None
    distance_from_location: int | None = None


#: PLACEHOLDER — see module docstring. One narrow, low-volume query so the
#: scraper is exercisable end-to-end (dry run, real run against a test
#: database, CI) without pulling anything close to Reed's full UK listing
#: volume by accident. Confirm the real query list before scheduling this
#: pipeline for unattended, recurring production runs.
DEFAULT_SEARCH_QUERIES: list[ReedSearchQuery] = [
    ReedSearchQuery(keywords="data scientist", location_name="London"),
]
