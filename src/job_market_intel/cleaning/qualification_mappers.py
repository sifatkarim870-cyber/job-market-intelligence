"""Standardized mappers for job qualifications and categorizations.

Maps raw scraped strings or extracted text fragments into canonical foreign key codes:
- ref.education_levels.code ('none', 'high_school', 'associate', 'bachelor', 'master', 'phd', 'professional_certification')
- ref.experience_levels.code ('entry', 'junior', 'mid', 'senior', 'lead', 'principal', 'executive')
- ref.remote_work_types.code ('on_site', 'hybrid', 'remote_city', 'remote_country', 'remote_region', 'remote_global')
- ref.job_categories.code (108 categories matching ref.job_categories)
"""

from __future__ import annotations

import re

# ============================================================================
# Education Level
# ============================================================================

_EDU_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("phd", re.compile(r"\b(ph\.?d|doctorat|doctorate|doctorado|dr\.)\b", re.IGNORECASE)),
    (
        "master",
        re.compile(
            r"\b(master'?s?|magister|msc|m\.s\.|mba|maestr[ií]a|bac\s*\+\s*5|postgraduate|graduate degree)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "bachelor",
        re.compile(
            r"\b(bachelor'?s?|licence|licenciatura|bac\s*\+\s*[34]|bsc|b\.s\.|b\.a\.|grado universitario|undergraduate|degree in|college degree|university degree)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "high_school",
        re.compile(
            r"\b(high\s*school|baccalaur[eé]at|\bbac\b|secundaria|bachiller|bachillerato|ged|secondary education)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "associate",
        re.compile(
            r"\b(associate'?s?|dut|bts|t[eé]cnico superior|foundation degree|college diploma)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "professional_certification",
        re.compile(
            r"\b(pmp|cpa|cfa|chartered|barreau|certification professionnelle)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "none",
        re.compile(
            r"\b(no degree|sin estudios|aucun dipl[oô]me|sans dipl[oô]me|no formal education)\b",
            re.IGNORECASE,
        ),
    ),
]


def map_education_level(text: str | None) -> str | None:
    """Map a raw education string or requirements block to a ref.education_levels.code."""
    if not text:
        return None
    for code, pattern in _EDU_PATTERNS:
        if pattern.search(text):
            return code
    return None


# ============================================================================
# Experience Level
# ============================================================================

_EXP_YEARS_REGEX = re.compile(
    r"(?:(\d+)\s*(?:to|-)\s*)?(\d+)\+?\s*(?:years?|yrs?|ans|a[nñ]os?)\s*(?:of)?\s*(?:exp|experience|d'exp[eé]rience|de experiencia)",
    re.IGNORECASE,
)

_EXP_TITLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "executive",
        re.compile(
            r"\b(c-level|chief executive|ceo|cto|cfo|coo|cmo|vice president|\bvp\b|president)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "principal",
        re.compile(
            r"\b(principal|staff\s+(?:engineer|developer)|distinguished|director)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "lead",
        re.compile(
            r"\b(team\s*lead|lead|tech\s*lead|chef d'[eé]quipe|architect|manager)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "senior",
        re.compile(
            r"\b(senior|\bsr\.?\b|s[eé]nior|avanc[eé]|experto)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "mid",
        re.compile(
            r"\b(mid[-\s]?level|intermediate|confirm[eé]|medior)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "junior",
        re.compile(
            r"\b(junior|\bjr\.?\b|d[eé]butant)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "entry",
        re.compile(
            r"\b(entry[-\s]?level|trainee|stagiaire|intern|internship|pr[aá]cticas|practicante|fresh graduate|apprentice)\b",
            re.IGNORECASE,
        ),
    ),
]


def map_experience_level(
    text: str | None,
    title: str | None = None,
    years: float | int | None = None,
) -> str | None:
    """Map job title, description, or explicit experience facts to ref.experience_levels.code."""
    # 1. Try title first (high precision indicator)
    if title:
        for code, pattern in _EXP_TITLE_PATTERNS:
            if pattern.search(title):
                return code

    # 2. If years specified or extractable from text
    y = years
    if y is None and text:
        match = _EXP_YEARS_REGEX.search(text)
        if match:
            # If range (e.g. 3 to 5), use the lower bound
            val = match.group(1) or match.group(2)
            try:
                y = float(val)
            except ValueError:
                pass

    if y is not None:
        if y >= 12:
            return "principal"
        if y >= 8:
            return "lead"
        if y >= 5:
            return "senior"
        if y >= 3:
            return "mid"
        if y >= 1:
            return "junior"
        return "entry"

    # 3. Keyword scan in text
    if text:
        for code, pattern in _EXP_TITLE_PATTERNS:
            if pattern.search(text):
                return code

    return None


# ============================================================================
# Remote Work Type
# ============================================================================

_HYBRID_PATTERN = re.compile(
    r"\b(hybrid|hybride|h[ií]brido|semi[-\s]?presencial|mixto)\b",
    re.IGNORECASE,
)
_REMOTE_GLOBAL_PATTERN = re.compile(
    r"\b(worldwide|globally|anywhere|global|international)\b",
    re.IGNORECASE,
)
_REMOTE_PATTERN = re.compile(
    r"\b(remote|teletrabajo|t[eé]l[eé]travail|home[-\s]?office|work from home|wfh|telework)\b",
    re.IGNORECASE,
)
_ONSITE_PATTERN = re.compile(
    r"\b(on[-\s]?site|presencial|sur[-\s]?site|in[-\s]?office|in[-\s]?person)\b",
    re.IGNORECASE,
)


def map_remote_work_type(text: str | None) -> str | None:
    """Map location or remote work indicator to ref.remote_work_types.code."""
    if not text:
        return None
    if _HYBRID_PATTERN.search(text):
        return "hybrid"
    if _REMOTE_PATTERN.search(text):
        if _REMOTE_GLOBAL_PATTERN.search(text):
            return "remote_global"
        return "remote_country"
    if _ONSITE_PATTERN.search(text):
        return "on_site"
    return None


# ============================================================================
# Job Category
# ============================================================================

_CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "data_ai",
        re.compile(
            r"\b(data\s*(?:analyst|scientist|engineer)|machine\s*learning|deep\s*learning|\bai\b|artificial\s*intelligence|nlp|computer\s*vision|business\s*intelligence|\bbi\b)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "swe_backend",
        re.compile(
            r"\b(backend|back-end|python|java|golang|\bgo\b|c\+\+|c\#|\.net|node\.?js|django|fastapi|spring)\s+(?:developer|engineer|dev)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "swe_frontend",
        re.compile(
            r"\b(frontend|front-end|react|vue|angular|javascript|typescript)\s+(?:developer|engineer|dev)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "swe_fullstack",
        re.compile(
            r"\b(full[-\s]?stack|software\s*(?:developer|engineer)|d[eé]veloppeur|desarrollador|programmer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "design",
        re.compile(
            r"\b(product\s*designer|ui\s*/\s*ux|ux|ui|graphic\s*designer|dise[nñ]ador|graphiste)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "product",
        re.compile(
            r"\b(product\s*manager|product\s*owner|\bpm\b)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "sales",
        re.compile(
            r"\b(sales|account\s*exec|account\s*manager|commercial|ventas|vendeur|business\s*development)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "marketing",
        re.compile(
            r"\b(marketing|seo|growth|content\s*creator|community\s*manager|mercadeo)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "customer_support",
        re.compile(
            r"\b(customer\s*(?:service|support|success)|support\s*technique|soporte\s*t[eé]cnico|helpdesk|call\s*center)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "finance",
        re.compile(
            r"\b(finance|financial|accountant|comptable|contador|auditor|payroll|tr[eé]sorerie)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hr_people",
        re.compile(
            r"\b(human\s*resources|\bhr\b|recruiter|talent\s*acquisition|recursos\s*humanos|\brh\b)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "legal",
        re.compile(
            r"\b(legal|counsel|lawyer|avocat|juriste|abogado|compliance)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "it_security",
        re.compile(
            r"\b(cybersecurity|infosec|security\s*engineer|s[eé]curit[eé]\s*informatique|seguridad\s*inform[aá]tica)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "operations",
        re.compile(
            r"\b(operations|logistics|supply\s*chain|logistique|operaciones)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "engineering",
        re.compile(
            r"\b(engineer|ing[eé]nieur|ingeniero|engineering)\b",
            re.IGNORECASE,
        ),
    ),
]


def map_job_category(title: str | None, raw_category: str | None = None) -> str | None:
    """Map job title or raw source category to a ref.job_categories.code."""
    if raw_category:
        for code, pattern in _CATEGORY_PATTERNS:
            if pattern.search(raw_category):
                return code
    if title:
        for code, pattern in _CATEGORY_PATTERNS:
            if pattern.search(title):
                return code
    return None
