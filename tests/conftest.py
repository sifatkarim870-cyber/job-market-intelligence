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
from datetime import UTC, datetime
from typing import Any

import pytest

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.scrapers.glints.models import RawGlintsJob
from job_market_intel.scrapers.hrge.models import RawHRGeJob
from job_market_intel.scrapers.jobinja.models import RawJobinjaJob
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


@pytest.fixture()
def make_raw_hrge_job() -> Callable[..., RawHRGeJob]:
    """Factory fixture: build a minimally-valid ``RawHRGeJob``, any field overridable.

    Defaults are a faithful snapshot of what HR.ge returned for announcement
    496982 with ``Accept-Language: en`` during scoping (2026-10-07): English
    title and taxonomy, a Georgian description body, undisclosed salary
    (``showSalary: false``), and the slug-less canonical URL — so a
    "healthy job" needs zero overrides, same convention as the other
    factories above.
    """

    def _make(**overrides: Any) -> RawHRGeJob:
        defaults: dict[str, Any] = {
            "source_job_id": "496982",
            "job_title": "Online Game Host",
            "company_name": "AMBER STUDIOS",
            "company_logo_url": None,
            "category_raw": "Casino / Gambling",
            "industry_raw": "Recreation & Travel",
            "seniority_raw": "Mid-Level",
            "contract_type_raw": "Fixed-term contract",
            "work_schedule_raw": "Full-time",
            "work_form_raw": "On site",
            "location_raw": "Tbilisi",
            "salary_from_raw": None,
            "salary_to_raw": None,
            "show_salary": False,
            "hide_salary": None,
            "is_work_from_home": False,
            "tags": ["Casino / Gambling", "Recreation & Travel"],
            "description_raw": "<div>ჩვენ ვეძებთ პოზიტიურ თანამშრომლებს</div>",
            "original_url": "https://www.hr.ge/announcement/496982",
            "posting_date": datetime(2026, 10, 6, 17, 17, 3, tzinfo=UTC),
            "closing_date": None,
            "raw_payload": {},
        }
        defaults.update(overrides)
        return RawHRGeJob.model_validate(defaults)

    return _make


@pytest.fixture()
def make_raw_glints_job() -> Callable[..., RawGlintsJob]:
    """Factory fixture: build a minimally-valid ``RawGlintsJob``, any field overridable.

    Defaults are a faithful snapshot of what Glints returned for job
    94d7e90f-f53b-4718-8601-ff4e7d623725 ("Penjaga Rumah", Indonesia)
    during scoping (2026-10-07): FULL_TIME, disclosed IDR 1–2M monthly
    salary, Draft.js description JSON, category+industry tags (that job
    carried no ``JobSkills``), and the sitemap's canonical local-locale
    URL — so a "healthy job" needs zero overrides, same convention as
    the other factories above.
    """

    def _make(**overrides: Any) -> RawGlintsJob:
        defaults: dict[str, Any] = {
            "source_job_id": "94d7e90f-f53b-4718-8601-ff4e7d623725",
            "job_title": "Penjaga Rumah",
            "company_name": "PT Akari Beauty Group",
            "country_code": "ID",
            "category_raw": "Store Crew",
            "industry_raw": "Accounting",
            "contract_type_raw": "FULL_TIME",
            "work_arrangement_raw": "ONSITE",
            "location_raw": "Penjaringan, Jakarta Utara, DKI Jakarta, Indonesia",
            "salary_from_raw": 1000000,
            "salary_to_raw": 2000000,
            "salary_currency": "IDR",
            "salary_mode": "MONTH",
            "payment_frequency": None,
            "should_show_salary": True,
            "is_work_from_home": False,
            "tags": ["Store Crew", "Accounting"],
            "description_raw": (
                '{"blocks": [{"text": "PT Akari Beauty Group adalah perusahaan '
                'yang bergerak di bidang kecantikan."}], "entityMap": {}}'
            ),
            "original_url": (
                "https://glints.com/id/opportunities/jobs/penjaga-rumah/"
                "94d7e90f-f53b-4718-8601-ff4e7d623725"
            ),
            "posting_date": datetime(2026, 10, 6, 21, 19, 26, tzinfo=UTC),
            "closing_date": datetime(2026, 11, 6, tzinfo=UTC),
            "status": "OPEN",
            "job_source": "EMPLOYER",
            "external_apply_url": None,
            "raw_payload": {},
        }
        defaults.update(overrides)
        return RawGlintsJob.model_validate(defaults)

    return _make


@pytest.fixture()
def make_raw_jobinja_job() -> Callable[..., RawJobinjaJob]:
    """Factory fixture: build a minimally-valid ``RawJobinjaJob``, any field overridable.

    Defaults are a faithful snapshot of what Jobinja returned for job
    1118910 ("کارشناس فروش بین المللی", Maron System, Tehran) during the
    live smoke (2026-10-07): FULL_TIME, IRT 45,000,000 monthly with the
    visible "از ۴۵,۰۰۰,۰۰۰ تومان" (from-45M) disclosure text, real
    skill chips, category chip, IR country, TELECOMMUTE — so a "healthy
    job" needs zero overrides, same convention as the other factories
    above.
    """

    def _make(**overrides: Any) -> RawJobinjaJob:
        defaults: dict[str, Any] = {
            "source_job_id": "1118910",
            "job_title": "کارشناس فروش بین المللی",
            "company_name": "توسعه نرم افزار مارون | Maron System",
            "company_logo_url": (
                "https://thumb2.jobinjacdn.com/VVDDoDUyXHmU8e51D5PaI661NlY="
                "/fit-in/200x200/filters:strip_exif():fill(transparent)"
                ":quality(100)/https://mstorage2.jobinjacdn.com/other/files/"
                "uploads/images/c525b2ce-d365-4813-b957-c586a72f1c20/main.png"
            ),
            "description_html": (
                '<div dir="rtl">ما به دنبال فردی با مهارت های '
                "<strong>کارشناس فروش، نتیجه‌گرا، پیگیر و مسلط به زبان "
                "انگلیسی و عربی</strong> هستیم.</div>"
            ),
            "posting_date": datetime(2026, 10, 6, tzinfo=UTC),
            "closing_date": None,
            "employment_type_raw": "FULL_TIME",
            "base_salary_value": 45000000,
            "salary_currency": "IRT",
            "salary_unit": "MONTH",
            "location_spans": ["تهران ، تهران"],
            "salary_text_spans": ["از ۴۵,۰۰۰,۰۰۰ تومان"],
            "skills_spans": ["فروش بین المللی", "فروش B2B", "اصول و فنون مذاکره"],
            "category_spans": ["فروش و بازاریابی"],
            "country_code": "IR",
            "is_telecommute": True,
            "original_url": (
                "https://jobinja.ir/companies/maron-system/jobs/tuti/"
                "%D8%A7%D8%B3%D8%AA%D8%AE%D8%AF%D8%A7%D9%85-%DA%A9%D8%A7%D8%B1"
                "%D8%B4%D9%86%D8%A7%D8%B3-%D9%81%D8%B1%D9%88%D8%B4-%D8%A8%DB%8C"
                "%D9%86-%D8%A7%D9%84%D9%85%D9%84%D9%84%DB%8C-%D8%AF%D8%B1-"
                "%D8%AA%D9%88%D8%B3%D8%B9%D9%87-%D9%86%D8%B1%D9%85-%D8%A7%D9"
                "%81%D8%B2%D8%A7%D8%B1-%D9%85%D8%A7%D8%B1%D9%88%D9%86"
            ),
            "raw_payload": {
                "ld": {"@type": "JobPosting", "identifier": {"value": "1118910"}},
                "sections": {
                    "دسته‌بندی شغلی": ["فروش و بازاریابی"],
                    "موقعیت مکانی": ["تهران ، تهران"],
                    "حقوق": ["از ۴۵,۰۰۰,۰۰۰ تومان"],
                    "مهارت‌های مورد نیاز": [
                        "فروش بین المللی",
                        "فروش B2B",
                        "اصول و فنون مذاکره",
                    ],
                },
            },
        }
        defaults.update(overrides)
        return RawJobinjaJob.model_validate(defaults)

    return _make
