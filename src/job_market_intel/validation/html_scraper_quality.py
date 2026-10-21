"""Decides whether a parsed page is a job posting or a navigation link.

The generic HTML framework accepts whatever the listing page links to. With a
hand-written selector that is fine. With the auto-generated configs the listing
path is ``/`` and the link selector is loose, so the "postings" turn out to be
the site's own navigation: ``/job-search/operations-jobs``, ``/jobs/today/``,
``/news/...``, ``/blog/...``. A sweep that only counted parsed records called
those a success -- 578 rows were stored that way on 2026-10-21, and a title
built from the URL slug made them look plausible in the database.

This module is the check the sweep should have had. It runs on the parsed record
before validation, so a navigation link is dropped as a *skip* rather than
stored and discovered months later.

The signals are deliberately conservative: a rejection needs positive evidence
that the URL is a listing/advice/news page, that the link points off-site, or
that the page carries no job description at all. An unfamiliar URL shape is
kept, because a false reject silently loses a real posting while a false accept
is visible in the audit.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

#: Path segments that name a section rather than a posting.
SECTION_SEGMENTS: frozenset[str] = frozenset(
    {
        "about",
        "about-us",
        "advice",
        "article",
        "articles",
        "blog",
        "blogs",
        "browse",
        "browse-jobs",
        "career",
        "career-advice",
        "careers",
        "candidate",
        "candidates",
        "candidat",
        "category",
        "categories",
        "companies",
        "company",
        "contact",
        "cookie",
        "cookies",
        "discover",
        "employer",
        "employers",
        "faq",
        "featured",
        "focus-on",
        "help",
        "home",
        "job",
        "job-category",
        "job-search",
        "job-tag",
        "jobs",
        "login",
        "menu",
        "news",
        "newsletter",
        "privacy",
        "register",
        "saved",
        "saved-jobs",
        "savjet",
        "search",
        "signin",
        "sign-in",
        "signup",
        "sign-up",
        "support",
        "tag",
        "tags",
        "terms",
        "terms-of-service",
        "today",
        "vacancies",
        "vacancy",
    }
)

#: Path fragments that are never a single posting.
SECTION_FRAGMENTS: tuple[str, ...] = (
    "/news/",
    "/blog/",
    "/article/",
    "/articles/",
    "/advice/",
    "/career-advice/",
    "/focus-on/",
    "/site-highlight/",
    "/savjet/",
    "/discover/",
    "/category/",
    "/job-category/",
    "/job-tag/",
    "/job-search/",
    "/companies/",
    "/company/",
    "/employers/",
    "/employer/",
    "/help/",
    "/support/",
    "/privacy",
    "/terms",
    "/cookie",
    "/login",
    "/signin",
    "/sign-in",
    "/signup",
    "/sign-up",
    "/register",
    "/search",
    "/browse-jobs",
    "/saved-jobs",
    "/classifieds",
)

#: Titles that are page furniture rather than a job title.
NAV_TITLES: frozenset[str] = frozenset(
    {
        "home",
        "menu",
        "search",
        "log in",
        "login",
        "sign in",
        "sign up",
        "register",
        "saved jobs",
        "jobs",
        "job",
        "careers",
        "career",
        "jobs in",
        "find jobs",
        "job search",
        "browse jobs",
        "all jobs",
        "chat",
        "choose language:",
        "skip to content",
        "loading",
        "chargement",
        "position summary",
        "about us",
        "contact",
        "privacy policy",
        "terms of service",
        "cookie settings",
        "administrare cookies",
        "english version",
        "top-anzeigen",
        "news",
        "classifieds",
        # Bot walls that return 200 with a challenge page.
        "just a moment",
        "attention required",
        "pardon our interruption",
        "access denied",
        "captcha",
        "安全验证",
        "slím top",
        "slim top",
    }
)

#: Titles ending like this are category pages ("Marketing jobs in India").
CATEGORY_TITLE_SUFFIXES: tuple[str, ...] = (
    " jobs",
    " job",
    " jobs in",
    " vacancies",
    " careers",
    " job search",
    " recruitment",
)

#: Hosts that are never the board itself.
OFFSITE_HOSTS: tuple[str, ...] = (
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "apps.apple.com",
    "play.google.com",
    "t.me",
    "whatsapp.com",
)

DEFAULT_MIN_DESCRIPTION_CHARS = 80

#: ``/2026/10/21/some-headline/`` is a news article on every CMS that uses it.
DATED_ARTICLE_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/")


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _same_site(host: str, site_host: str) -> bool:
    if not host or not site_host:
        return False
    return host == site_host or host.endswith("." + site_host)


def _last_segment(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1].lower()


def _url_reason(url: str, site_host: str) -> str | None:
    """Reject when the URL names a section, an article, or another site."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    segments = [s for s in path.split("/") if s]

    if not segments:
        return "site root, not a posting"

    host = _host(url)
    if site_host and host and not _same_site(host, site_host):
        if any(host == h or host.endswith("." + h) for h in OFFSITE_HOSTS):
            return f"offsite link ({host})"

    for fragment in SECTION_FRAGMENTS:
        if fragment in path:
            return f"section path ({fragment.strip('/')})"

    if DATED_ARTICLE_RE.search(path):
        return "news article path (dated)"

    last = _last_segment(path)
    if any(seg in SECTION_SEGMENTS for seg in segments[:-1]) and last in SECTION_SEGMENTS:
        return f"listing page (/{last})"

    # "/jobs/today", "/ikman.lk/en/ads/sri-lanka/driver-jobs"
    if last.endswith(("-jobs", "-job", "_jobs")) and last not in {"saved-jobs"}:
        return "category path (ends in -jobs)"
    return None


def _text_reason(
    title: str | None, description: str | None, min_description_chars: int
) -> str | None:
    """Reject when the page text is furniture or carries no room for a body."""
    clean_title = (title or "").strip()
    if not clean_title:
        return "no title"

    lowered = clean_title.lower().strip(" .:!-–—")
    if lowered in NAV_TITLES:
        return f"navigation title ({clean_title[:40]!r})"
    if lowered.endswith(CATEGORY_TITLE_SUFFIXES):
        return f"category title ({clean_title[:40]!r})"
    if len(clean_title) < 3:
        return "title too short"

    body = (description or "").strip()
    if len(body) < min_description_chars:
        return f"no job description ({len(body)} chars)"
    return None


def reject_reason(
    url: str | None,
    title: str | None,
    description: str | None,
    *,
    site_host: str = "",
    min_description_chars: int = DEFAULT_MIN_DESCRIPTION_CHARS,
) -> str | None:
    """Return why this record is not a posting, or ``None`` when it looks like one."""
    if not url:
        return "no url"
    return _url_reason(url, site_host) or _text_reason(title, description, min_description_chars)


def filter_postings(
    jobs,
    *,
    site_host: str = "",
    min_description_chars: int = DEFAULT_MIN_DESCRIPTION_CHARS,
):
    """Split parsed records into real postings and rejects.

    Returns ``(kept, rejected)`` where ``rejected`` pairs the record with the
    reason, so the run log can say *why* a board yielded nothing.
    """
    kept = []
    rejected = []
    for job in jobs:
        reason = reject_reason(
            job.url,
            job.title,
            job.description,
            site_host=site_host,
            min_description_chars=min_description_chars,
        )
        if reason is None:
            kept.append(job)
        else:
            rejected.append((job, reason))
    return kept, rejected
