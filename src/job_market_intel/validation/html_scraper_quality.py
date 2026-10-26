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
    "/mot-cle",
    "/categorie_",
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
    "itunes.apple.com",
    "music.apple.com",
    "play.google.com",
    "t.me",
    "whatsapp.com",
)

DEFAULT_MIN_DESCRIPTION_CHARS = 80

#: Path keywords that name a posting, across the languages in scope. Shared with
#: the discovery pass so both agree on what looks like a job URL.
JOB_PATH_KEYWORDS: tuple[str, ...] = (
    "job",
    "career",
    "vacancy",
    "vacante",
    "position",
    "opening",
    "listing",
    "offer",
    "emploi",
    "offre",
    "trabajo",
    "empleo",
    "rabota",
    "praca",
    "prace",
    "pracovni",
    "posao",
    "oglas",
    "nabidka",
    "vakansiya",
    "vacature",
    "stelle",
    "lavoro",
    "annonce",
    "oferta",
    "oferty",
    "anuncio",
    "convocatoria",
    "arbs",
    "darbs",
    "darbo",
    "skelbim",
    "tyopaikat",
    "tuyen-dung",
)

#: ``/2026/10/21/some-headline/`` is a news article on every CMS that uses it.
DATED_ARTICLE_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/")


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _same_site(host: str, site_host: str) -> bool:
    host = _host(f"//{host}")
    site_host = _host(f"//{site_host}")
    if not host or not site_host:
        return False
    return host == site_host or host.endswith("." + site_host)


def has_job_keyword(path: str) -> bool:
    """True when a path *word* is job vocabulary.

    Substring matching was too loose: willhaben.at's ``/taschen-koffer/``
    matched ``offer`` and the handbag category passed as a posting.
    """
    tokens = [token for token in re.split(r"[/\-_.]+", path) if token]
    return any(token.startswith(keyword) for token in tokens for keyword in JOB_PATH_KEYWORDS)


def _last_segment(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1].lower()


def _url_reason(url: str, site_host: str, detail_pattern: str = "") -> str | None:
    """Reject when the URL names a section, an article, or another site."""
    path = urlparse(url).path.lower()
    segments = [s for s in path.split("/") if s]
    if not segments:
        return "site root, not a posting"

    host = _host(url)
    if site_host and host and not _same_site(host, site_host):
        # Postings live on the board or its subdomains. Off-site links are the
        # board pointing at a subsidy page, a news story, or a social profile.
        return f"offsite link ({host})"

    # A site that declares its detail URL shape has already answered the
    # question the remaining heuristics guess at. kosovajob.com posts live at
    # "/<company>/<slug>" with no job vocabulary anywhere in the path,
    # jobthai.com posts live at "/th/company/job/<id>" which contains "/company/",
    # and dubizzle.com files ads under "/jobs/<category>/<year>/<month>/<day>/<slug>---<uuid>/",
    # which the dated-article rule would otherwise reject as a news story.
    if detail_pattern and (
        re.search(detail_pattern, path, re.IGNORECASE)
        or re.search(detail_pattern, url, re.IGNORECASE)
    ):
        return None

    for fragment in SECTION_FRAGMENTS:
        if fragment in path:
            return f"section path ({fragment.strip('/')})" 

    if DATED_ARTICLE_RE.search(path):
        return "news article path (dated)"

    # A posting URL says so in its own path. Without this, willhaben.at's
    # handbag category and general classifieds pages pass every other check.
    if not has_job_keyword(path):
        return "path has no job keyword"

    last = _last_segment(path)
    if _is_listing_segment(last, segments):
        return f"listing page (/{last})"
    # "/jobs/today", "/ikman.lk/en/ads/sri-lanka/driver-jobs"
    if last.endswith(("-jobs", "-job", "_jobs")) and last not in {"saved-jobs"}:
        return "category path (ends in -jobs)"
    return None


def _is_listing_segment(last: str, segments: list[str]) -> bool:
    """True for "/jobs", "/obiavi-za-rabota", "/fr-fr/emploi.html"."""
    stem = last.rsplit(".", 1)[0] if "." in last else last
    if stem in SECTION_SEGMENTS:
        return True
    if len(segments) == 1 and any(kw in stem for kw in JOB_PATH_KEYWORDS):
        return True
    return any(seg in SECTION_SEGMENTS for seg in segments[:-1]) and stem in SECTION_SEGMENTS


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
    # "Operations jobs in India" is a category. "Front Desk/ Admin Associate
    # Jobs In Nepal | Kumari Job Pvt. Ltd." is a posting whose og:title ends
    # with the site name, so the suffix rule only applies to short titles.
    if len(clean_title) <= 60 and lowered.endswith(CATEGORY_TITLE_SUFFIXES):
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
    detail_pattern: str = "",
) -> str | None:
    """Return why this record is not a posting, or ``None`` when it looks like one."""
    if not url:
        return "no url"
    return _url_reason(url, site_host, detail_pattern) or _text_reason(
        title, description, min_description_chars
    )


def filter_postings(
    jobs,
    *,
    site_host: str = "",
    min_description_chars: int = DEFAULT_MIN_DESCRIPTION_CHARS,
    detail_pattern: str = "",
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
            detail_pattern=detail_pattern,
        )
        if reason is None:
            kept.append(job)
        else:
            rejected.append((job, reason))
    return kept, rejected
