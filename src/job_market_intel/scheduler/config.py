"""scheduler.config
=================

Configuration for the platform's pipeline schedulers (Step 12: RemoteOK;
extended here to also cover the Indeed scraper).

Why this is its own settings class rather than folding these fields into
an existing one: the scheduler has its own concern (how often to run, and
how to behave around missed/overlapping runs) that none of the platform's
other config classes have any reason to know about. It gets its own
env-var namespace (``SCHEDULER_*``), mirroring the pattern already
established by ``RemoteOKSettings`` (``REMOTEOK_*``) and
``RemoteOKValidationSettings`` (``REMOTEOK_VALIDATION_*``) elsewhere in
this codebase - one settings class per concern, not one giant shared one.

``SCHEDULER_SCRAPE_INTERVAL_HOURS`` has been a reserved-but-unused slot in
``.env.example`` since Step 3; this is the class that finally reads it.

Two pipelines, one settings class: RemoteOK and Indeed each get their own
interval field (``scrape_interval_hours`` / ``indeed_scrape_interval_hours``)
since they're fundamentally different cadences to reason about
independently, but share ``run_immediately_on_start`` /
``misfire_grace_time_seconds`` / ``coalesce_missed_runs`` - those are
generic scheduler-behavior knobs, not pipeline-specific ones, and splitting
them per-pipeline would add a second interval-shaped decision (should
Indeed's misfire grace differ from RemoteOK's?) that nothing so far has
asked for. ``scrape_interval_hours`` keeps its original (not
``remoteok_``-prefixed) name deliberately, even though it's now one of two
pipeline intervals - renaming it would be a breaking change to an
already-deployed ``.env`` variable name for no functional benefit.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SchedulerSettings(BaseSettings):
    """Configurable behavior for the automated RemoteOK and Indeed pipeline
    schedules.

    Attributes:
        scrape_interval_hours: How often to run the RemoteOK pipeline, in
            hours. Defaults to 12 per the current build plan (Step 12).
            Accepts fractional values (e.g. ``0.05`` for a ~3-minute
            interval) so the schedule can be shortened for manual testing
            without touching code.
        indeed_scrape_interval_hours: How often to run the Indeed
            pipeline, in hours. Defaults to 12, the same cadence as
            RemoteOK - confirmed decision from scoping the Indeed
            scraper, not a value RemoteOK's default happened to share by
            coincidence.
        run_immediately_on_start: If True, the first run of BOTH pipelines
            fires as soon as the scheduler process starts, rather than
            waiting a full interval before the platform has any fresh
            data. True is almost always what you want operationally - but
            worth knowing this now also means a real Indeed browser
            session (visible, not headless, by that scraper's own
            default) starts immediately when this process launches, not
            just RemoteOK's plain HTTP fetch.
        misfire_grace_time_seconds: How late a missed run is still allowed
            to fire - e.g. the machine was asleep or powered off at the
            scheduled time. Past this window, the missed run is skipped
            entirely rather than firing a stale catch-up scrape. Defaults
            to one hour. Shared by both pipelines' jobs.
        coalesce_missed_runs: If multiple scheduled runs were missed while
            the process wasn't running, execute a single combined
            catch-up run instead of firing once per missed occurrence.
            Prevents a burst of back-to-back scrapes after the machine was
            off for a while. Shared by both pipelines' jobs.
    """

    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    scrape_interval_hours: float = Field(default=12.0, gt=0)
    indeed_scrape_interval_hours: float = Field(default=12.0, gt=0)
    run_immediately_on_start: bool = Field(default=True)
    misfire_grace_time_seconds: int = Field(default=3600, ge=0)
    coalesce_missed_runs: bool = Field(default=True)
