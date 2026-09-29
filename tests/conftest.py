"""tests/conftest.py

Root-level pytest fixtures, auto-available to every test under both
``tests/unit`` and ``tests/integration`` without any import — that's the
whole point of putting them here rather than in a plain helper module.

Step 16 background
-------------------
Before this file existed, the two shared, source-agnostic contracts every
scraper's tests build against — ``RawRemoteOKJob``-style raw records and
the ``CleanedJob`` output contract — each had *two* independent hand-rolled
factory functions living in different test modules (one in
``cleaning/test_common.py``, another inside
``integration/test_remoteok_pipeline.py``; similarly for the raw-job
builder in ``cleaning/test_remoteok_cleaner.py`` vs.
``validation/test_remoteok_validator.py``). That duplication was fine at
one source; it does not scale to the ~50 planned scrapers, each of which
will want the same pattern. These two fixtures are the canonical builders
going forward — see ``tests/README.md`` for the conventions.

Both are *factory fixtures*: the fixture itself returns a callable, so
call sites keep the familiar ``make_x(**overrides)`` shape (matching the
override-any-field pattern the old local factories already used) rather
than pytest injecting a single fixed object.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.scrapers.remoteok.models import RawRemoteOKJob
from job_market_intel.scrapers.remotive.models import RawRemotiveJob
from job_market_intel.scrapers.weworkremotely.models import RawWWRJob


@pytest.fixture()
def make_cleaned_job() -> Callable[..., CleanedJob]:
    """Factory fixture: build a minimally-valid ``CleanedJob``, any field overridable.

    ``CleanedJob`` is the shared, source-agnostic output contract every
    scraper's cleaner must produce (see ``cleaning/common.py``'s module
    docstring). A new source's tests should reuse this fixture rather than
    hand-rolling another ``CleanedJob`` builder.
    """

    def _make(**overrides: Any) -> CleanedJob:
        defaults: dict[str, Any] = {
            "source_job_id": "1",
            "job_title": "Engineer",
            "company_name": "Acme",
            "company_logo_url": None,
            "skills": [],
            "location_cleaned": None,
            "salary_min": None,
            "salary_max": None,
            "salary_disclosed": False,
            "description_clean": None,
            "word_count": 0,
            "apply_url": None,
            "original_url": "https://x.test/1",
            "posting_date": None,
            "data_quality_score": 0.0,
            "raw_payload": {},
            # USD/yearly matches every live source's actual stored
            # behavior today (RemoteOK, Remotive, We Work Remotely) --
            # see db.job_repository's "Reed scraper note" for why these
            # became required, per-record fields instead of a hardcoded
            # repository-level assumption.
            "currency_iso_code": "USD",
            "pay_period": "yearly",
        }
        defaults.update(overrides)
        return CleanedJob(**defaults)

    return _make


@pytest.fixture()
def make_raw_remoteok_job() -> Callable[..., RawRemoteOKJob]:
    """Factory fixture: build a minimally-valid ``RawRemoteOKJob``, any field overridable.

    Defaults are deliberately the *richer* of the two field sets the old
    duplicate factories used (adds ``location``, ``salary_min``,
    ``salary_max``, ``description``, ``tags``, ``date`` on top of the
    required ``id``/``position``/``company``/``url``) so both the cleaner
    suite and the validator suite can build a fully-populated "healthy"
    job with zero overrides, same as before.
    """

    def _make(**overrides: Any) -> RawRemoteOKJob:
        defaults: dict[str, Any] = {
            "id": "1",
            "position": "Engineer",
            "company": "Acme",
            "url": "https://x.test/1",
            "location": "Worldwide",
            "salary_min": 100000,
            "salary_max": 150000,
            "description": "<p>Do engineering things.</p>",
            "tags": ["python"],
            "date": "2026-01-15T09:00:00+00:00",
        }
        defaults.update(overrides)
        return RawRemoteOKJob.model_validate(defaults)

    return _make


@pytest.fixture()
def make_raw_wwr_job() -> Callable[..., RawWWRJob]:
    """Factory fixture: build a minimally-valid ``RawWWRJob``, any field overridable.

    Defaults use We Work Remotely's own raw dict shape (as
    ``WWRClient.fetch_raw_jobs()`` produces it from the RSS feed) — a
    combined ``"Company: Job Title"`` string, ``guid``/``link`` as the
    identity/URL fields, and WWR's own region/country/state/skills
    vocabulary — so a "healthy job" needs zero overrides, same convention
    as ``make_raw_remoteok_job`` above. Individual tests can still
    override with direct ``job_title=``/``company_name=`` kwargs instead
    of a combined ``title=`` string if that's more convenient — see
    ``RawWWRJob._split_company_and_title``'s docstring for why both work.
    """

    def _make(**overrides: Any) -> RawWWRJob:
        defaults: dict[str, Any] = {
            "title": "Acme Corp: Engineer",
            "guid": "https://weworkremotely.com/remote-jobs/acme-corp-engineer",
            "link": "https://weworkremotely.com/remote-jobs/acme-corp-engineer",
            "region": "Anywhere in the World",
            "country": "Argentina, Brazil",
            "state": "Texas",
            "skills": "python, django",
            "category": "Programming",
            "type": "Full-Time",
            "description": "<p>Do engineering things.</p>",
            "pubdate": "Tue, 25 Aug 2026 07:31:11 +0000",
            "expires_at": "Thu, 24 Sep 2026 07:31:11 +0000",
            "media_content_url": "https://wwr-pro.s3.amazonaws.com/logos/example/logo.gif",
        }
        defaults.update(overrides)
        return RawWWRJob.model_validate(defaults)

    return _make


@pytest.fixture()
def make_raw_remotive_job() -> Callable[..., RawRemotiveJob]:
    """Factory fixture: build a minimally-valid ``RawRemotiveJob``, any field overridable.

    Defaults use Remotive's own raw dict shape (as
    ``RemotiveClient.fetch_raw_jobs()`` produces it from the JSON API) —
    a numeric ``id``, ``title``/``company_name`` as separate fields (no
    combined-string split needed, unlike WWR), and a free-text ``salary``
    string in the unambiguous "$X - $Y" shape ``RawRemotiveJob`` parses —
    so a "healthy job" needs zero overrides, same convention as
    ``make_raw_remoteok_job``/``make_raw_wwr_job`` above.
    """

    def _make(**overrides: Any) -> RawRemotiveJob:
        defaults: dict[str, Any] = {
            "id": 1,
            "title": "Engineer",
            "company_name": "Acme",
            "company_logo": "https://x.test/logo.png",
            "category": "Software Development",
            "job_type": "full_time",
            "candidate_required_location": "Worldwide",
            "tags": ["python"],
            "salary": "$100,000 - $150,000",
            "description": "<p>Do engineering things.</p>",
            "url": "https://remotive.com/remote-jobs/1",
            "publication_date": "2026-01-15T09:00:00",
        }
        defaults.update(overrides)
        return RawRemotiveJob.model_validate(defaults)

    return _make
