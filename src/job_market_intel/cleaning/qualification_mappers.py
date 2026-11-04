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

# ============================================================================
# Visa & Relocation
# ============================================================================

_VISA_POS = re.compile(
    r"\b(visa\s*sponsorship\s*(?:is\s*)?(?:available|provided|offered|supported)|we\s*(?:can\s*)?sponsor\s*visas?|will\s*sponsor\s*visa|sponsoring\s*visas?)\b",
    re.IGNORECASE,
)
_VISA_NEG = re.compile(
    r"\b(no\s*visa\s*sponsorship|visa\s*sponsorship\s*(?:is\s*)?not\s*available|cannot\s*sponsor|unable\s*to\s*sponsor|not\s*providing\s*visa|must\s*have\s*valid\s*work\s*authorization|no\s*sponsorship)\b",
    re.IGNORECASE,
)

_RELOC_POS = re.compile(
    r"\b(relocation\s*(?:assistance|package|support|allowance|bonus|provided|covered|offered)|we\s*(?:will|can)\s*relocate|help\s*with\s*relocation)\b",
    re.IGNORECASE,
)
_RELOC_NEG = re.compile(
    r"\b(no\s*relocation|relocation\s*(?:assistance\s*)?(?:is\s*)?not\s*(?:provided|available|offered)|cannot\s*relocate)\b",
    re.IGNORECASE,
)


def map_visa_sponsorship(text: str | None) -> bool | None:
    """Map text to a visa_sponsorship boolean."""
    if not text:
        return None
    if _VISA_POS.search(text):
        return True
    if _VISA_NEG.search(text):
        return False
    return None


def map_relocation_support(text: str | None) -> bool | None:
    """Map text to a relocation_support boolean."""
    if not text:
        return None
    if _RELOC_POS.search(text):
        return True
    if _RELOC_NEG.search(text):
        return False
    return None

# ============================================================================
# Education Field of Study / Discipline
# ============================================================================

_RAW_EDU_PATTERNS = [
    re.compile(
        r"""(?ix)
        \b(?:
            (?:bachelor(?:['’]s)?|master(?:['’]s)?|ph\.?d\.?|doctorate|doctorat|associate(?:['’]s)?|undergraduate|graduate|university|college)?
            \s*(?:of\s+(?:science|arts|engineering|commerce|business|technology))?
            \s*(?:degree|diploma|licenciatura|t[ií]tulo(?:\s+universitario)?|dipl[oô]me|maestr[ií]a|doctorado|bac\s*\+\s*[345]|bsc|msc|b\.s\.|m\.s\.|b\.a\.|m\.a\.|ph\.?d\.?)
            |
            (?:bachelor(?:['’]s)?|master(?:['’]s)?|ph\.?d\.?|doctorate|doctorat|associate(?:['’]s)?|licenciatura|maestr[ií]a|doctorado|bac\s*\+\s*[345]|\bbs\b|\bms\b|\bba\b|bsc|msc|b\.s\.|m\.s\.|b\.a\.|m\.a\.)
        )
        \s+(?:in|of|en|de|d'|en\s+materia\s+de)\s+
        ([A-Za-z0-9\s,&/\-–\u00C0-\u017F]+?)
        (?=(?:\s+(?:or|o|ou)\s+(?:a\s+)?(?:closely\s+)?(?:related|relevant|af[ií]n|afines|connexe|equivalent|equivalente|[eé]quivalent|quantitative)(?:\s+(?:field|discipline|area|branche|domaine))?|[.;\n\r]|\Z|\s+is\s+required|\s+required\b|\s+preferred\b|\s+with\b|\s+and\s+\d+\+?\s+years))
        """
    ),
    re.compile(
        r"""(?ix)
        \b(?:degree|major|discipline|field\s+of\s+study|formation|t[ií]tulo)\s*(?:required|needed)?\s*[:\-]\s*
        ([A-Za-z0-9\s,&/\-–\u00C0-\u017F]+?)
        (?=(?:\s+(?:or|o|ou)\s+(?:a\s+)?(?:related|af[ií]n|connexe|equivalent)\b|[.;\n\r]|\Z|\s+is\s+required|\s+required\b|\s+preferred\b))
        """
    ),
]

_DISCIPLINE_TAXONOMY: list[tuple[str, re.Pattern[str]]] = [
    (
        "computer_science",
        re.compile(
            r"\b(computer\s*sciences?|software(?:\s*engineering)?|informatique|inform[aá]tica|computer\s*engineering|g[eé]nie\s*logiciel|computaci[oó]n|ciencias\s*de\s*la\s*computaci[oó]n|\bcs\b)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "information_technology",
        re.compile(
            r"\b(information\s*technolog(?:y|ies)|information\s*systems?|cyber\s*security|cybersecurity|network(?:ing)?|sysadmin|syst[eè]mes\s*d'information|tecnolog[ií]a\s*de\s*la\s*informaci[oó]n|\bit\b)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "data_science_statistics",
        re.compile(
            r"\b(data\s*sciences?|data\s*analytics?|statistics?|statistical|statistiques?|estad[ií]sticas?|biostatistics?|business\s*analytics?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "mathematics",
        re.compile(
            r"\b(mathematics?|applied\s*math(?:ematics)?|math[eé]matiques?|matem[aá]ticas?|actuarial(?:\s*science)?|\bmath\b)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "engineering_electrical",
        re.compile(
            r"\b(electrical|electronics?|g[eé]nie\s*[eé]lectrique|ingenier[ií]a\s*[eé]l[eé]ctrica|telecom(?:munications?)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "engineering_mechanical",
        re.compile(
            r"\b(mechanical(?:\s*engineering)?|m[eé]canique|mec[aá]nica|mechatronics?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "engineering_civil",
        re.compile(
            r"\b(civil(?:\s*engineering)?|construction(?:\s*management)?|g[eé]nie\s*civil|ingenier[ií]a\s*civil|structural(?:\s*engineering)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "engineering_chemical",
        re.compile(
            r"\b(chemical\s*engineering|g[eé]nie\s*chimique|ingenier[ií]a\s*qu[ií]mica)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "engineering_general",
        re.compile(
            r"\b(engineering|ing[eé]nierie|ingenier[ií]a|industrial\s*engineering)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "business_administration",
        re.compile(
            r"\b(business\s*administration|business\s*management|gesti[oó]n|administraci[oó]n(?:\s*de\s*empresas)?|management|commerce|\bmba\b)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "finance_accounting",
        re.compile(
            r"\b(finance|financial|accounting|accountancy|economics?|comptabilit[eé]|finanzas|contabilidad|econom[ií]a|audit|banking)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "marketing_communications",
        re.compile(
            r"\b(marketing|communications?|advertising|journalism|public\s*relations?|relaciones\s*p[uú]blicas|media(?:\s*studies)?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "human_resources",
        re.compile(
            r"\b(human\s*resources?|ressources\s*humaines|recursos\s*humanos|\bhr\b|talent\s*management)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "healthcare_nursing",
        re.compile(
            r"\b(nursing|medicine|pharmacy|public\s*health|sant[eé]|enfermer[ií]a|medicina|pharmacology|healthcare)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "natural_sciences",
        re.compile(
            r"\b(physics|chemistry|biology|biotechnology|biotech|biochemistry|physique|chimie|biologie|f[ií]sica|qu[ií]mica|environmental\s*science)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "social_sciences",
        re.compile(
            r"\b(psychology|sociology|political\s*science|international\s*relations?|psychologie|sociologie|psicolog[ií]a|ciencias\s*sociales)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "law_legal",
        re.compile(
            r"\b(law|legal(?:\s*studies)?|droit|derecho|jurisprudence|\bllb\b|\bllm\b|\bjd\b)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "education_teaching",
        re.compile(
            r"\b(education|[eé]ducation|teaching|pedagogy|enseignement|pedagog[ií]a)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "arts_design",
        re.compile(
            r"\b(design|architecture|fine\s*arts?|graphic(?:\s*design)?|visual\s*arts?|dise[nñ]o)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "agriculture",
        re.compile(
            r"\b(agriculture|agronomy|forestry|veterinary|agronome|agronom[ií]a)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "logistics_supply_chain",
        re.compile(
            r"\b(supply\s*chain|logistics?|procurement|log[ií]stica|approvisionnement)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "stem_general",
        re.compile(
            r"\b(stem|quantitative(?:\s*field)?|scientific\s*discipline|technical\s*field)\b",
            re.IGNORECASE,
        ),
    ),
]

_DISQUALIFIED_RAW_WORDS = re.compile(
    r"\b(nuevo|alert|cookie|apply|click|terms|privacy|equal opportunity|job|position|employment|candidate|experience|years|work|customer|country|client|account|accounts|countries|breakthrough|reality|spoken|written|english|spanish|french)\b",
    re.IGNORECASE,
)

_EDU_SENTENCE_TRIGGER = re.compile(
    r"\b(degree|diploma|dipl[oô]me|licenciatura|bac\s*\+\s*[345]|bachelor|master|ph\.?d\.?|doctorate|doctorat|associate|bsc|msc|b\.s\.|m\.s\.|b\.a\.|m\.a\.)\b",
    re.IGNORECASE,
)


def extract_education_field_raw(text: str | None) -> str | None:
    """Extract raw degree discipline text phrase from requirements/description text."""
    if not text:
        return None
    for pat in _RAW_EDU_PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(1).strip(" \t\r\n,.;:-")
            if 3 <= len(raw) <= 80:
                words = raw.split()
                if len(words) <= 10 and not _DISQUALIFIED_RAW_WORDS.search(raw):
                    return raw
    return None


def map_education_discipline(text: str | None) -> str | None:
    """Map text (either extracted raw field or description block) to comma-separated discipline tags."""
    if not text:
        return None
    matched = []
    for code, pat in _DISCIPLINE_TAXONOMY:
        if pat.search(text):
            matched.append(code)
    return ",".join(matched) if matched else None


def extract_education_discipline_context(text: str | None) -> tuple[str | None, str | None]:
    """Extract both raw field and normalized discipline from text with strict sentence scoping."""
    if not text:
        return None, None
    raw = extract_education_field_raw(text)
    if raw:
        norm = map_education_discipline(raw)
        if norm:
            return raw, norm

    # If raw didn't map or was missing, check sentences that explicitly mention degree/diploma
    sentences = re.split(r"[.\n\r;]", text)
    edu_phrases = [s.strip() for s in sentences if _EDU_SENTENCE_TRIGGER.search(s) and len(s.strip()) <= 200]
    if edu_phrases:
        scoped_text = " ".join(edu_phrases)
        norm = map_education_discipline(scoped_text)
        return raw, norm

    return raw, None


# ---------------------------------------------------------------------------
# Experience years extraction
# ---------------------------------------------------------------------------

_YEARS_RANGE = re.compile(
    r'\b(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*(?:\+)?\s*(?:years?|yrs?)(?:\s+(?:of\s+)?(?:relevant\s+|direct\s+)?experience)?\b',
    re.IGNORECASE,
)
_YEARS_MIN = re.compile(
    r'\b(?:at\s+least|minimum|min\.?|more\s+than|>|\+)?\s*(\d{1,2})\s*(?:\+)?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+|direct\s+)?experience\b',
    re.IGNORECASE,
)
_YEARS_PLUS = re.compile(
    r'\b(\d{1,2})\s*\+\s*(?:years?|yrs?)(?:\s+(?:of\s+)?(?:relevant\s+|direct\s+)?experience)?\b',
    re.IGNORECASE,
)


def extract_experience_years(text: str | None) -> tuple[int | None, int | None]:
    """Extract numeric min and max years of experience from text."""
    if not text:
        return None, None

    m = _YEARS_RANGE.search(text)
    if m:
        low, high = int(m.group(1)), int(m.group(2))
        if 0 <= low <= high <= 30:
            return low, high

    m = _YEARS_PLUS.search(text)
    if m:
        val = int(m.group(1))
        if 0 <= val <= 30:
            return val, None

    m = _YEARS_MIN.search(text)
    if m:
        val = int(m.group(1))
        if 0 <= val <= 30:
            return val, None

    return None, None


# ---------------------------------------------------------------------------
# Seniority and management extraction
# ---------------------------------------------------------------------------

_EXECUTIVE_TITLES = re.compile(
    r'\b(?:c[etfomio]o|chief\s+\w+\s+officer|vice\s+president|vp\b|managing\s+director|executive\s+director|partner|founder)\b',
    re.IGNORECASE,
)
_DIRECTOR_TITLES = re.compile(
    r'\b(?:director(?:\s+of)?|head\s+of|group\s+head)\b',
    re.IGNORECASE,
)
_MANAGER_TITLES = re.compile(
    r'\b(?:manager|general\s+manager|supervisor|superintendent)\b',
    re.IGNORECASE,
)
_LEAD_TITLES = re.compile(
    r'\b(?:team\s+lead|tech\s+lead|lead\s+(?:engineer|developer|designer|analyst|architect|consultant)|lead)\b',
    re.IGNORECASE,
)
_IC_TITLES = re.compile(
    r'\b(?:intern|junior|entry\s*level|associate|specialist|engineer|developer|analyst|consultant|coordinator|officer|staff|principal|senior)\b',
    re.IGNORECASE,
)
_MANAGEMENT_TEXT = re.compile(
    r'\b(?:manage\s+(?:a\s+)?team|direct\s+reports|supervise\s+(?:staff|team|employees)|leading\s+a\s+team\s+of)\b',
    re.IGNORECASE,
)


def extract_seniority_and_management(
    title: str | None, text: str | None = None
) -> tuple[str | None, bool | None]:
    """Extract seniority role type and is_managerial boolean flag."""
    if not title:
        return None, None

    t_lower = title.lower()

    if _EXECUTIVE_TITLES.search(t_lower):
        return "executive", True
    if _DIRECTOR_TITLES.search(t_lower):
        return "director", True
    if _MANAGER_TITLES.search(t_lower):
        return "manager", True
    if _LEAD_TITLES.search(t_lower):
        is_mgr = True if (text and _MANAGEMENT_TEXT.search(text)) else None
        return "team_lead", is_mgr
    if _IC_TITLES.search(t_lower):
        return "individual_contributor", False

    if text and _MANAGEMENT_TEXT.search(text):
        return "manager", True

    return None, None


# ---------------------------------------------------------------------------
# Work schedule extraction
# ---------------------------------------------------------------------------

_SCHEDULE_PATTERNS = [
    ("night_shift", re.compile(r'\b(?:night\s*shift|third\s*shift|graveyard\s*shift|overnights?)\b', re.IGNORECASE)),
    ("weekend", re.compile(r'\b(?:weekend\s*shift|weekends?\s*only|weekend\s*work)\b', re.IGNORECASE)),
    ("rotational", re.compile(r'\b(?:rotational\s*shift|rotating\s*shift|shift\s*work)\b', re.IGNORECASE)),
    ("flexible", re.compile(r'\b(?:flexible\s*(?:working\s*)?(?:hours|schedule)|flexitime|flextime)\b', re.IGNORECASE)),
    ("standard_day", re.compile(r'\b(?:day\s*shift|standard\s*business\s*hours|9\s*(?:am)?\s*(?:-|to)\s*5\s*(?:pm)?|monday\s*(?:-|to)\s*friday)\b', re.IGNORECASE)),
]


def extract_work_schedule(text: str | None) -> str | None:
    """Extract standard work schedule taxonomy tag."""
    if not text:
        return None
    for code, pat in _SCHEDULE_PATTERNS:
        if pat.search(text):
            return code
    return None


# ---------------------------------------------------------------------------
# Benefits normalization
# ---------------------------------------------------------------------------

_BENEFIT_TAXONOMY = [
    ("health_insurance", re.compile(r'\b(?:health|medical)\s+(?:insurance|coverage|care|plan|benefits?)\b', re.IGNORECASE)),
    ("dental_vision", re.compile(r'\b(?:dental|vision)\s+(?:insurance|coverage|plan|benefits?)\b', re.IGNORECASE)),
    ("retirement_401k", re.compile(r'\b(?:401\(?k\)?|pension|retirement\s*(?:plan|fund|benefits?)|superannuation)\b', re.IGNORECASE)),
    ("paid_time_off", re.compile(r'\b(?:paid\s+time\s+off|pto|vacation\s+days|annual\s+leave)\b', re.IGNORECASE)),
    ("equity_stock_options", re.compile(r'\b(?:equity|stock\s+options|esop|rsu|company\s+shares)\b', re.IGNORECASE)),
    ("parental_leave", re.compile(r'\b(?:parental|maternity|paternity)\s+leave\b', re.IGNORECASE)),
    ("tuition_reimbursement", re.compile(r'\b(?:tuition\s+(?:reimbursement|assistance)|education\s+stipend|learning\s+budget)\b', re.IGNORECASE)),
    ("relocation_assistance", re.compile(r'\b(?:relocation\s+(?:assistance|package|support|allowance))\b', re.IGNORECASE)),
    ("wellness_perks", re.compile(r'\b(?:gym\s+membership|wellness\s+stipend|mental\s+health\s+support)\b', re.IGNORECASE)),
]


def extract_normalized_benefits(text: str | None) -> str | None:
    """Extract comma-separated normalized benefit tags."""
    if not text:
        return None
    matched = []
    for code, pat in _BENEFIT_TAXONOMY:
        if pat.search(text):
            matched.append(code)
    return ",".join(matched) if matched else None


# ---------------------------------------------------------------------------
# Skills normalization
# ---------------------------------------------------------------------------

_SKILL_TAXONOMY = [
    ("python", re.compile(r'\bpython\b', re.IGNORECASE)),
    ("sql", re.compile(r'\bsql\b', re.IGNORECASE)),
    ("javascript", re.compile(r'\b(?:javascript|js)\b', re.IGNORECASE)),
    ("typescript", re.compile(r'\b(?:typescript|ts)\b', re.IGNORECASE)),
    ("java", re.compile(r'\bjava\b(?!\s*script)', re.IGNORECASE)),
    ("c_cpp", re.compile(r'\b(?:c\+\+|cpp)\b', re.IGNORECASE)),
    ("c_sharp", re.compile(r'\b(?:c#|csharp)\b', re.IGNORECASE)),
    ("go_golang", re.compile(r'\b(?:golang|go\s+programming)\b', re.IGNORECASE)),
    ("rust", re.compile(r'\brust\b(?!\s*(?:stain|iron))', re.IGNORECASE)),
    ("ruby", re.compile(r'\bruby(?:\s+on\s+rails)?\b', re.IGNORECASE)),
    ("php", re.compile(r'\bphp\b', re.IGNORECASE)),
    ("swift", re.compile(r'\bswift\b(?!\s*code)', re.IGNORECASE)),
    ("kotlin", re.compile(r'\bkotlin\b', re.IGNORECASE)),
    ("r_lang", re.compile(r'\b(?:r\s+programming|r\s+language)\b', re.IGNORECASE)),
    ("scala", re.compile(r'\bscala\b', re.IGNORECASE)),
    ("react", re.compile(r'\breact(?:\.js|js)?\b', re.IGNORECASE)),
    ("angular", re.compile(r'\bangular(?:\.js|js)?\b', re.IGNORECASE)),
    ("vue", re.compile(r'\bvue(?:\.js|js)?\b', re.IGNORECASE)),
    ("node_js", re.compile(r'\bnode(?:\.js|js)?\b', re.IGNORECASE)),
    ("django", re.compile(r'\bdjango\b', re.IGNORECASE)),
    ("fastapi", re.compile(r'\bfastapi\b', re.IGNORECASE)),
    ("flask", re.compile(r'\bflask\b', re.IGNORECASE)),
    ("spring_boot", re.compile(r'\bspring\s*boot\b', re.IGNORECASE)),
    ("dotnet", re.compile(r'\b(?:\.net|dotnet)\b', re.IGNORECASE)),
    ("aws", re.compile(r'\baws\b|\bamazon\s+web\s+services\b', re.IGNORECASE)),
    ("azure", re.compile(r'\b(?:azure|microsoft\s+azure)\b', re.IGNORECASE)),
    ("gcp", re.compile(r'\b(?:gcp|google\s+cloud)\b', re.IGNORECASE)),
    ("docker", re.compile(r'\bdocker\b', re.IGNORECASE)),
    ("kubernetes", re.compile(r'\b(?:kubernetes|k8s)\b', re.IGNORECASE)),
    ("terraform", re.compile(r'\bterraform\b', re.IGNORECASE)),
    ("linux", re.compile(r'\blinux\b', re.IGNORECASE)),
    ("git", re.compile(r'\bgit\b|\bgithub\b|\bgitlab\b', re.IGNORECASE)),
    ("ci_cd", re.compile(r'\bci[/-]?cd\b', re.IGNORECASE)),
    ("postgresql", re.compile(r'\b(?:postgres|postgresql)\b', re.IGNORECASE)),
    ("mysql", re.compile(r'\bmysql\b', re.IGNORECASE)),
    ("mongodb", re.compile(r'\bmongodb\b', re.IGNORECASE)),
    ("redis", re.compile(r'\bredis\b', re.IGNORECASE)),
    ("elasticsearch", re.compile(r'\belasticsearch\b', re.IGNORECASE)),
    ("snowflake", re.compile(r'\bsnowflake\b', re.IGNORECASE)),
    ("bigquery", re.compile(r'\bbigquery\b', re.IGNORECASE)),
    ("pandas", re.compile(r'\bpandas\b', re.IGNORECASE)),
    ("numpy", re.compile(r'\bnumpy\b', re.IGNORECASE)),
    ("pytorch", re.compile(r'\bpytorch\b', re.IGNORECASE)),
    ("tensorflow", re.compile(r'\btensorflow\b', re.IGNORECASE)),
    ("scikit_learn", re.compile(r'\bscikit[-_]?learn\b', re.IGNORECASE)),
    ("spark", re.compile(r'\b(?:apache\s+spark|pyspark|spark)\b', re.IGNORECASE)),
    ("tableau", re.compile(r'\btableau\b', re.IGNORECASE)),
    ("power_bi", re.compile(r'\bpower\s*bi\b', re.IGNORECASE)),
    ("excel", re.compile(r'\b(?:microsoft\s+excel|advanced\s+excel)\b', re.IGNORECASE)),
    ("machine_learning", re.compile(r'\bmachine\s+learning\b|\bml\b', re.IGNORECASE)),
    ("deep_learning", re.compile(r'\bdeep\s+learning\b', re.IGNORECASE)),
    ("nlp", re.compile(r'\bnatural\s+language\s+processing\b|\bnlp\b', re.IGNORECASE)),
    ("computer_vision", re.compile(r'\bcomputer\s+vision\b', re.IGNORECASE)),
    ("agile_scrum", re.compile(r'\b(?:agile|scrum)\b', re.IGNORECASE)),
    ("project_management", re.compile(r'\bproject\s+management\b', re.IGNORECASE)),
    ("salesforce", re.compile(r'\bsalesforce\b', re.IGNORECASE)),
    ("jira", re.compile(r'\bjira\b', re.IGNORECASE)),
]


def extract_normalized_skills(text: str | None) -> str | None:
    """Extract comma-separated normalized skill tags."""
    if not text:
        return None
    matched = []
    for code, pat in _SKILL_TAXONOMY:
        if pat.search(text):
            matched.append(code)
    return ",".join(matched) if matched else None
