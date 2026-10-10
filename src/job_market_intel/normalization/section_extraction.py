"""Fill the description-derived columns from the description text itself.

    ``core.job_descriptions.requirements``            0 / 112,781  (0.0%)
    ``core.job_descriptions.responsibilities``        0 / 112,781  (0.0%)
    ``core.job_descriptions.required_skills_text``    0 / 112,781  (0.0%)
    ``core.job_descriptions.preferred_skills_text``   0 / 112,781  (0.0%)
    ``core.job_descriptions.language_requirements_text`` 0 / 112,781  (0.0%)

Five columns that every scraper left NULL because no source publishes them as
structured fields, while 99.9% of ``description_clean`` is populated. The
information is in the description; it just was never split out.

Why this cannot use the obvious line-based approach
---------------------------------------------------
The text cleaner joins HTML block elements into spaces, so **no row in the
corpus contains a single newline** (verified: 0 of 112,639). Every technique
that keys on line structure -- "the line after the heading", markdown sections,
splitlines() -- returns nothing at all here.

The structure is nevertheless intact, just flattened onto one line:

    شرح وظایف: • مراجعه حضوری • معرفی محصولات شرایط احراز: • ساکن تهران

Headings survive as a phrase followed by a separator, and list items survive as
bullet-separated runs. So this module matches headings as substrings anywhere in
the flattened string and treats the text between consecutive headings as that
heading's section.

Persian ZWNJ
------------
Persian headings are written with ZERO WIDTH NON-JOINER (U+200C), and boards are
inconsistent: the same heading appears as ``مسئولیت‌ها`` and ``مسئولیتها``.
Matching is therefore done against a ZWNJ-stripped copy of the text. That copy
is only used to *locate* headings -- an offset map carries every match back to
the original string, so extracted content keeps its original characters.

Language coverage is driven by the heading vocabulary mined out of the corpus
itself, not by assumptions about English postings: fa (68% of rows), en, id,
vi, ka, he, zh, fr.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Section kinds
# --------------------------------------------------------------------------


class SectionKind:
    """Classification of a description section."""

    RESPONSIBILITIES = "responsibilities"
    REQUIREMENTS = "requirements"
    PREFERRED = "preferred"
    BENEFITS = "benefits"
    SKILLS = "skills"
    EDUCATION = "education"
    LANGUAGE = "language"
    OTHER = "other"


#: Which column each section kind is routed into. BENEFITS / EDUCATION / OTHER
#: have no destination column and are used only as context to stop a section
#: from bleeding into the next one.
KIND_TO_COLUMN = {
    SectionKind.RESPONSIBILITIES: "responsibilities",
    SectionKind.REQUIREMENTS: "requirements",
    SectionKind.PREFERRED: "preferred_skills_text",
    SectionKind.SKILLS: "required_skills_text",
    SectionKind.LANGUAGE: "language_requirements_text",
}


# --------------------------------------------------------------------------
# Heading vocabulary, mined from the corpus (see module docstring)
# --------------------------------------------------------------------------

#: heading (ZWNJ-stripped) -> SectionKind. Longest match wins, so "شرایط احراز"
#: is preferred over "شرایط" and "Key Responsibilities" over "Responsibilities".
HEADING_KINDS: dict[str, str] = {}


def _register(kind: str, *headings: str) -> None:
    for heading in headings:
        HEADING_KINDS[heading.replace("\u200c", "")] = kind


# -- Persian (fa): ~77k rows, the largest single language -------------------
_register(
    SectionKind.RESPONSIBILITIES,
    "شرح وظایف",
    "وظایف",
    "وظایف اصلی",
    "وظایف کلیدی",
    "وظایف و مسئولیت ها",
    "وظایف و مسئولیتها",
    "مسئولیت ها",
    "مسئولیتها",
    "مسئولیت های اصلی",
    "مسئولیتهای اصلی",
    "مسئولیت های کلیدی",
    "شرح مسئولیت ها",
    "شرح شغل",
    "شرح شغل و وظایف",
    "شرح وظایف و مسئولیت ها",
    "شرح موقعیت شغلی",
    "شرح فعالیت های شما",
    "وظایف روزانه",
    "وظایف اصلی شما",
)
_register(
    SectionKind.REQUIREMENTS,
    "شرایط احراز",
    "شرایط احراز شغل",
    "شرایط مورد نیاز",
    "شرایط موردنظر",
    "شرایط استخدام",
    "شرایط همکاری",
    "شرایط عمومی",
    "ویژگی های مورد نیاز",
    "ویژگی های فردی",
    "مهارت های مورد نیاز",
    "شرایط و مهارت های مورد نیاز",
    "شاخص های کلیدی",
    "الزامات",
    "الزامات شغل",
    "دیدگاه ما",
    "دیدگاه مورد نظر",
    "حداقل الزامات",
)
_register(
    SectionKind.SKILLS,
    "مهارت ها",
    "مهارت های تخصصی",
    "دانش فنی",
    "توانایی ها",
    "توانمندی ها",
    "آنچه نیاز داریم",
)
_register(
    SectionKind.PREFERRED,
    "موارد ترجیحی",
    "موارد مطلوب",
    "امتیازات",
    "امتیاز محسوب",
    "نقاط قوت",
    "مزیت",
)
_register(
    SectionKind.LANGUAGE,
    "زبان",
    "زبان های خارجی",
    "تسلط زبانی",
    "شرایط زبانی",
)
_register(
    SectionKind.EDUCATION,
    "تحصیلات",
    "مدرک تحصیلی",
    "حداقل مدرک تحصیلی",
    "رشته تحصیلی",
    "سابقه کار",
    "سابقه کاری",
    "سن",
    "جنسیت",
)
_register(SectionKind.BENEFITS, "مزایا", "مزایای همکاری", "تسهیلات", "حقوق و مزایا")

# -- English (en) ------------------------------------------------------------
_register(
    SectionKind.RESPONSIBILITIES,
    "responsibilities",
    "key responsibilities",
    "main responsibilities",
    "job responsibilities",
    "your responsibilities",
    "duties",
    "job duties",
    "what you'll do",
    "what you will do",
    "what you'll be doing",
    "the role",
    "about the role",
    "role overview",
    "job description",
    "job overview",
    "day to day",
    "day-to-day",
    "the day-to-day",
    "position overview",
    "your mission",
)
_register(
    SectionKind.REQUIREMENTS,
    "requirements",
    "job requirements",
    "minimum requirements",
    "minimum qualifications",
    "required qualifications",
    "qualifications",
    "basic qualifications",
    "who you are",
    "what we are looking for",
    "what we look for",
    "what you need",
    "who we're looking for",
    "must have",
    "must haves",
    "required",
    "your profile",
    "candidate profile",
    "required conditions and characteristics",
    "skills and experience",
    "skills & experience",
    "skills and qualifications",
)
_register(
    SectionKind.SKILLS,
    "required skills",
    "skills",
    "technical skills",
    "core skills",
    "what you'll bring",
    "what you bring",
    "your skills",
)
_register(
    SectionKind.PREFERRED,
    "nice to have",
    "nice to haves",
    "preferred",
    "preferred qualifications",
    "preferred experience",
    "bonus points",
    "bonus",
    "good to have",
    "good to haves",
    "pluses",
    "desirable",
    "advantageous",
    "we'd love to see",
    "extra credit",
)
_register(SectionKind.LANGUAGE, "languages", "language", "language requirements")
_register(
    SectionKind.EDUCATION,
    "education",
    "education requirements",
    "educational requirements",
    "academic requirements",
    "experience",
    "qualifications and experience",
)
_register(
    SectionKind.BENEFITS,
    "benefits",
    "benefits and growth",
    "perks",
    "what we offer",
    "what we offer you",
    "compensation",
)

# -- Indonesian (id) ---------------------------------------------------------
_register(
    SectionKind.RESPONSIBILITIES,
    "tanggung jawab",
    "tanggung jawab utama",
    "tanggung jawab pekerjaan",
    "tugas dan tanggung jawab",
    "tugas utama",
    "tugas",
    "jobdesc",
    "jobdesk",
    "deskripsi pekerjaan",
    "pekerjaan",
)
_register(
    SectionKind.REQUIREMENTS,
    "kualifikasi",
    "persyaratan",
    "persyaratan untuk peran ini",
    "syarat",
    "kriteria",
    "kebutuhan",
)
_register(SectionKind.SKILLS, "keahlian", "keterampilan", "skill")
_register(
    SectionKind.PREFERRED,
    "nilai tambah",
    "lebih baik jika",
    "diutamakan",
)
_register(SectionKind.LANGUAGE, "bahasa")
_register(
    SectionKind.EDUCATION,
    "pendidikan",
    "pengalaman",
    "pengalaman kerja",
)
_register(SectionKind.BENEFITS, "benefit", "benefits", "keuntungan", "fasilitas")

# -- Vietnamese (vi) ---------------------------------------------------------
_register(
    SectionKind.RESPONSIBILITIES,
    "mo ta cong viec",
    "nhiem vu",
    "mo ta cong viec chinh",
    "trai nghiem cong viec",
)
_register(
    SectionKind.REQUIREMENTS,
    "yeu cau",
    "yeu cau cong viec",
    "yeu cau ung vien",
    "yeu cau ve",
    "kiem tra",
)
_register(SectionKind.SKILLS, "ky nang", "ky nang chuyen mon", "ki nang")
_register(SectionKind.PREFERRED, "uu tien")
_register(SectionKind.LANGUAGE, "ngoai ngu")
_register(
    SectionKind.EDUCATION,
    "trinh do",
    "hoc van",
    "kinh nghiem",
    "bang cap",
)
_register(
    SectionKind.BENEFITS,
    "quyen loi",
    "phuc loi",
    "phuc loi cong viec",
    "thu nhap",
)

# -- Georgian (ka) -----------------------------------------------------------
_register(
    SectionKind.RESPONSIBILITIES,
    "dირითადი მოვალეობები",
    "ფუნქცია-მოვალეობები",
    "მოვალეობები",
    "სამუშაოს აღწერა",
)
_register(
    SectionKind.REQUIREMENTS,
    "საკვალიფიკაციო მოთხოვნები",
    "ძირითადი მოთხოვნები",
    "სამუშაო პირობები",
    "მოთხოვნები",
    "კვალიფიკაცია",
    "სამუშაო განაკვეთი",
)
_register(
    SectionKind.PREFERRED,
    "სასურთაო",
    "დამატებითი",
)
_register(
    SectionKind.EDUCATION,
    "განათლება",
    "კვალიფიკაციები",
)
_register(
    SectionKind.BENEFITS,
    "ანაზღაურება",
    "სარგებლი",
    "პირობები",
)

# -- Hebrew (he) -------------------------------------------------------------
_register(
    SectionKind.RESPONSIBILITIES,
    "אחריות",
    "תפקידים",
    "התפקיד כולל",
    "מה יהיה תפקידך",
)
_register(
    SectionKind.REQUIREMENTS,
    "דרישות",
    "דרישות המשרה",
    "הדרישות",
    "דרישות סמכות",
    "קווליפיקציות",
    "מה נדרש",
)
_register(SectionKind.SKILLS, "כישורים", "מיומנויות")
_register(
    SectionKind.PREFERRED,
    "יתרון",
    "יתרונות",
    "נוסף",
)
_register(SectionKind.LANGUAGE, "שפות", "שפה")
_register(SectionKind.EDUCATION, "השכלה", "ניסיון", "ותק")

# -- Chinese (zh) -----------------------------------------------------------
_register(
    SectionKind.RESPONSIBILITIES,
    "工作职责",
    "岗位职责",
    "职位描述",
    "工作内容",
    "职责描述",
    "岗位要求",
)
_register(
    SectionKind.REQUIREMENTS,
    "任职要求",
    "任职资格",
    "应聘要求",
    "职位要求",
    "基本要求",
    "我们希望你",
)
_register(SectionKind.SKILLS, "专业技能", "技能要求", "技能")
_register(SectionKind.PREFERRED, "加分项", "优先", "优先条件")
_register(SectionKind.LANGUAGE, "语言要求", "语言")
_register(SectionKind.EDUCATION, "学历要求", "教育背景", "工作经验")

# -- French (fr) -------------------------------------------------------------
_register(
    SectionKind.RESPONSIBILITIES,
    "responsabilites",
    "vos missions",
    "le poste",
    "description du poste",
)
_register(
    SectionKind.REQUIREMENTS,
    "exigences",
    "profil recherche",
    "qualifications",
    "requis",
    "competences recherchees",
)
_register(SectionKind.SKILLS, "competences", "savoir faire")
_register(
    SectionKind.PREFERRED,
    "atouts",
    "nice to have",
    "appreciable",
)
_register(SectionKind.LANGUAGE, "langues", "langue")
_register(SectionKind.EDUCATION, "formation", "experience", "niveau d etudes")

# -- Arabic (ar) -------------------------------------------------------------
_register(
    SectionKind.RESPONSIBILITIES,
    "المهام",
    "مسؤوليات",
    "وصف الوظيفة",
    "الوصف الوظيفي",
)
_register(
    SectionKind.REQUIREMENTS,
    "المتطلبات",
    "متطلبات الوظيفة",
    "الشروط",
    "المؤهلات",
    "ما نبحث عنه",
)
_register(SectionKind.SKILLS, "المهارات")
_register(SectionKind.PREFERRED, "مميزات", "ميزة", "يفضل")
_register(SectionKind.LANGUAGE, "اللغات", "اللغة")
_register(SectionKind.EDUCATION, "المؤهلات العلمية", "الخبرة", "الدرجة العلمية")


# --------------------------------------------------------------------------
# Locating headings inside flattened text
# --------------------------------------------------------------------------

#: Marks that carry no meaning for matching and differ between boards.
_STRIP_CHARS = "\u200c\u200f\u200e\u00ad\u200b"

#: Boundary block for Latin headings, so "skill" does not match inside
#: "skillset".
_LATIN = "a-z0-9"

#: Characters that end a sentence. A heading preceded by one of these sits at
#: the start of a block of text even when no punctuation follows it, which is
#: the case for every flattened newline in the corpus.
_SENTENCE_END = ".!?;؟۔。！"

#: A heading followed by one of these is unambiguous.
_FOLLOW_SEPARATORS = r":：\-–—•*·|/→»›"


def _fold(text: str) -> tuple[str, list[int]]:
    """Fold text for heading matching, keeping a map back to original offsets.

    Folding does four things, each of which a real posting forced:

    * **removes whitespace entirely** -- ``شرایط احراز`` and ``شرایط‌احراز`` must
      match identically. Boards write Persian inter-word ZWNJ as a space, a ZWNJ,
      or nothing at all, and ``شاخص‌های کلیدی`` appears with all three. Since the
      corpus contains no whitespace that matters for *matching*, dropping it lets
      one key match every spelling.
    * **removes ZWNJ / RTL marks / soft hyphen** -- same reason.
    * **strips diacritics** -- Vietnamese is 1,988 rows and headings are written
      ``Mô tả công việc`` / ``MÔ TẢ CÔNG VIỆC`` / ``Mo ta cong viec``, none of
      which match a plain ASCII key. NFD decomposition drops the combining
      marks, so all three fold to the same string.
    * **lowercases** -- so ``REQUIREMENTS`` and ``Requirements`` are one key.

    An earlier version collapsed whitespace to a sentinel instead of dropping
    it, to preserve "was there a space after this heading". That broke matching
    outright: the key "Key Responsibilities" folded to ``key\\x00responsibilities``
    while the text it was meant to match folded to the same thing, but the
    Persian key "شاخص های کلیدی" (written here with a space) folded to
    ``شاخص\\x00های\\x00کلیدی`` while the corpus wrote it with ZWNJ and folded to
    ``شاخصهایکلیدی``. Every such heading silently stopped matching. Whitespace is
    now dropped for matching, and the one place that genuinely needs to know
    whether a space followed a heading asks the ORIGINAL string instead -- see
    ``_is_heading_context``.

    The folded copy is used ONLY to locate headings. Every folded character
    remembers its index in the original string, so a match at folded position
    ``i`` maps back through ``offsets[i]`` and the extracted section text keeps
    its original diacritics and spacing.
    """
    import unicodedata

    folded: list[str] = []
    offsets: list[int] = []
    for index, ch in enumerate(text):
        if ch.isspace() or ch in _STRIP_CHARS:
            continue
        for piece in unicodedata.normalize("NFD", ch):
            if unicodedata.combining(piece):
                continue
            folded.append(piece.lower())
            offsets.append(index)
    return "".join(folded), offsets


#: Maps a folded heading back to its SectionKind.
_FOLDED_KINDS = {_fold(h)[0]: kind for h, kind in HEADING_KINDS.items()}


def _alternation(keys: list[str]) -> str:
    return "|".join(sorted((re.escape(k) for k in keys), key=len, reverse=True))


#: Latin headings need word-boundary guards so "skill" does not match inside
#: "skillset".
#:
#: Non-Latin headings must NOT have them. A Persian or Georgian heading
#: routinely follows a Latin word with nothing but a space between -- the real
#: corpus contains "DataTables وظایف اصلی:" and "SQL Server شرح وظایف:" -- and a
#: Latin-alnum guard rejects both, silently dropping the heading. Before this
#: split, jobvision extracted 2 headings instead of 3 and its sections ran
#: together ("...DataTables وظایف اصلی:" ended up inside a responsibilities
#: item). Those scripts have no ASCII boundary to assert against.
#: Latin headings get a LEADING word-boundary guard so "skill" does not match
#: inside "skillset".
#:
#: There is deliberately no TRAILING guard. Boards routinely fuse a heading to
#: the first item with no whitespace at all -- remoteok renders
#: ``Key ResponsibilitiesDistributor Management`` from ``</b>Distributor`` -- and
#: a ``(?![a-z0-9])`` lookahead rejected every such heading, because the next
#: item's first letter is a lowercase word character. That one lookahead also
#: broke ``Requirements 6+ years``, since "requirements6" fails it too. False
#: positives from dropping it are caught by ``_is_heading_context``, which
#: demands a block start and a capitalised or numeric next word.
#:
#: Non-Latin headings get NO guards. A Persian or Georgian heading routinely
#: follows a Latin word with nothing between -- the real corpus contains
#: "DataTables وظایف اصلی:" and "SQL Server شرح وظایف:" -- and a Latin-alnum
#: guard rejects both, silently dropping the heading. Before this split,
#: jobvision extracted 2 headings instead of 3 and its sections ran together
#: ("...DataTables وظایف اصلی:" ended up inside a responsibilities item).
#: Those scripts have no ASCII boundary to assert against.
_LATIN_KEYS = [k for k in _FOLDED_KINDS if k.isascii()]
_OTHER_KEYS = [k for k in _FOLDED_KINDS if not k.isascii()]

_LATIN_HEADING_RE = re.compile(rf"(?<![{_LATIN}])({_alternation(_LATIN_KEYS)})")
_OTHER_HEADING_RE = re.compile(f"({_alternation(_OTHER_KEYS)})") if _OTHER_KEYS else None


def _next_nonspace(text: str, index: int) -> str | None:
    """First non-whitespace character at or after ``index``."""
    while index < len(text) and text[index].isspace():
        index += 1
    return text[index] if index < len(text) else None


def _at_block_start(text: str, start: int) -> bool:
    """True when ``start`` sits at the beginning of a text block.

    That is the start of the description, or a sentence terminator with only
    whitespace between it and ``start``. This is what identifies a heading whose
    separator the cleaner destroyed: the original ``<h3>Responsibilities</h3>``
    or trailing-newline markup is gone, but the sentence before it still ends in
    a period.
    """
    index = start - 1
    while index >= 0 and text[index].isspace():
        index -= 1
    return index < 0 or text[index] in _SENTENCE_END


def _is_heading_context(text: str, orig_start: int, orig_end: int) -> bool:
    """Decide whether a heading match is a real section heading.

    Every check reads the ORIGINAL string. Folding lowercases and strips
    whitespace, so the capitalisation and spacing signals this function depends
    on do not survive it.

    Three ways a match qualifies, strongest first. Each exists because the naive
    "followed by a separator" rule alone threw away real headings:

    1. **Explicit separator** -- ``Requirements: Python`` or ``Kualifikasi -
       Minimal 3 tahun``. Unambiguous, needs no context.

    2. **Block start, then a new block's first word** -- the cleaner flattens
       ``<h3>Responsibilities</h3>End-to-end control`` and trailing-newline
       markup into a single line, so the separator is simply gone. What
       survives is the period ending the previous sentence, and the fact that
       the next word starts a fresh block. Greenhouse reads
       ``"...fast-paced environment. Responsibilities End-to-end
       controllership..."``; weworkremotely reads ``"conversion rates.
       Requirements Proven track record..."``.

    3. **Block start, fused to the next word** -- remoteok renders
       ``Key ResponsibilitiesDistributor Management`` with no whitespace at all,
       because the source markup was ``</b>Distributor``. Same block-start
       evidence, so it is accepted without a separator.

    What this rejects, and must keep rejecting:

    * ``3+ years of PM experience in developer tools`` -- ``experience`` is
      preceded by ``pm`` and followed by lowercase ``in``.
    * ``مزیت محسوب می‌شود`` -- Persian has no letter case, so the uppercase
      test cannot fire and the sentence never starts a block anyway.
    """
    after = _next_nonspace(text, orig_end)
    if after is None:
        return True  # end of text
    if after in _FOLLOW_SEPARATORS:
        return True  # rule 1
    if not _at_block_start(text, orig_start):
        return False
    return after.isupper() or after.isdigit()  # rules 2 and 3


#: What may sit between a heading and its first list item.
_SEPARATOR_RE = re.compile(r"^[\s:：\-–—•*·.\|/>→»›,،؛;]+")

#: Bullet glyphs that survive the cleaner, plus the ASCII stand-ins.
_BULLET_RE = re.compile(r"[•·‣▪◦●○⁃∙*]\s*|(?:^|\s)[\-–—]\s+")

#: A " - " separator is a list delimiter in jobinja-style postings, but is also
#: ordinary punctuation in prose, so it only splits text that has no bullets.
_DASH_RE = re.compile(r"\s+[\-–—]\s+")


#: Generic boilerplate headings that must not be literal keys because the
#: company name varies ("About Databricks", "About Stripe", "About Figma").
#:
#: These matter more than they look: without them a requirements section runs
#: straight on into the company blurb, because nothing ends it. A real
#: greenhouse posting stored this as one requirements item reading
#: "BS (or higher) in Computer Science ... About Databricks Databricks is the
#: Data and AI company. More than 20,000 organizations worldwide ... rely on the
#: Databricks Data + AI Platform...".
#:
#: Run against the ORIGINAL string, not the folded one, because ``about [A-Z]``
#: needs letter case to tell a heading from prose.
_EXTRA_HEADING_RULES: list[tuple[re.Pattern[str], str]] = [
    # ``(?i:about)`` makes only the trigger word case-insensitive. The company
    # name must stay case-SENSITIVE, because that capital is the whole signal:
    # "About Databricks" is a heading, "about databricks' homepage" is prose.
    # A blanket re.IGNORECASE flag would destroy that distinction.
    (
        re.compile(r"\b(?i:about)\s+[A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3}\b"),
        SectionKind.OTHER,
    ),
    (
        re.compile(r"\babout\s+(?:us|the\s+company|this\s+(?:role|position|team))\b"),
        SectionKind.OTHER,
    ),
    (re.compile(r"\bequal\s+opportunity\b[^.:\n]{0,40}", re.IGNORECASE), SectionKind.OTHER),
    (re.compile(r"\bprivacy\s+(?:policy|notice|guidelines?)\b", re.IGNORECASE), SectionKind.OTHER),
    (
        re.compile(r"\bwhy\s+(?:join|work\s+with)\s+us\b", re.IGNORECASE),
        SectionKind.OTHER,
    ),
    (
        re.compile(
            r"\b(?:our|who\s+we\s+are|company)\s+(?:mission|story|culture|values|overview)\b",
            re.IGNORECASE,
        ),
        SectionKind.OTHER,
    ),
    (re.compile(r"\bwhat\s+we\s+offer\s+you\b", re.IGNORECASE), SectionKind.BENEFITS),
]


def _extra_headings(text: str) -> list[Heading]:
    """Locate boilerplate headings whose wording is not in the fixed vocabulary."""
    found: list[Heading] = []
    for pattern, kind in _EXTRA_HEADING_RULES:
        for match in pattern.finditer(text):
            found.append(
                Heading(
                    kind=kind,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                )
            )
    return found


@dataclass(frozen=True)
class Heading:
    """One heading occurrence in the flattened description."""

    kind: str
    start: int  # offset in the ORIGINAL text
    end: int  # offset in the ORIGINAL text, just past the heading
    text: str


def _resolve_overlaps(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Keep the longest heading at each position, dropping anything that overlaps it.

    ``شرایط احراز`` must not be shadowed by the shorter ``شرایط`` prefix, and
    ``About Databricks`` must not be split by anything underneath it.
    """
    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    kept: list[tuple[int, int, str]] = []
    cursor = -1
    for start, end, kind in spans:
        if start >= cursor:
            kept.append((start, end, kind))
            cursor = end
    return kept


def find_headings(text: str) -> list[Heading]:
    """Locate every section heading in a flattened description.

    Sorted by position, with overlaps resolved longest-heading-first so that
    ``شرایط احراز`` is not shadowed by the shorter ``شرایط`` prefix.
    """
    folded, offsets = _fold(text)
    if not folded:
        return []

    # (start, end, kind) in ORIGINAL coordinates. Both regexes run, because a
    # description freely mixes scripts inside one posting.
    found: list[tuple[int, int, str]] = []
    patterns = [_LATIN_HEADING_RE]
    if _OTHER_HEADING_RE is not None:
        patterns.append(_OTHER_HEADING_RE)
    for pattern in patterns:
        for match in pattern.finditer(folded):
            # Map back to the original string before judging context: folding
            # lowercased the text and removed its whitespace, and both the
            # capitalisation and block-start tests depend on the original.
            orig_start = offsets[match.start()]
            orig_end = min(offsets[match.end() - 1] + 1, len(text))
            if not _is_heading_context(text, orig_start, orig_end):
                continue
            found.append((orig_start, orig_end, _FOLDED_KINDS[match.group(1)]))

    # Merge the pattern-matched boilerplate headings before resolving overlaps.
    found.extend(
        (heading.start, heading.end, heading.kind) for heading in _extra_headings(text)
    )

    return [
        Heading(kind=kind, start=start, end=end, text=text[start:end])
        for start, end, kind in _resolve_overlaps(found)
    ]


#: Characters trimmed from both ends of a list item. Written as an explicit set
#: rather than ``str.strip(" \t•·-–—•*|")`` because strip() treats its argument
#: as a set of characters silently -- a reader cannot tell that "•-" means "any
#: of these", and B005 flags it for good reason.
_ITEM_TRIM = " \t\r\n•·-–—*|"


def _trim_item(text: str) -> str:
    return text.strip(_ITEM_TRIM)


def _split_items(body: str) -> list[str]:
    """Split a section body into individual list items."""
    body = _SEPARATOR_RE.sub("", body).strip()
    if not body:
        return []

    items = [_trim_item(part) for part in _BULLET_RE.split(body) if part and part.strip()]
    if len(items) <= 1:
        # jobinja-style postings use " - " as the only delimiter.
        dashed = _DASH_RE.split(body)
        if len(dashed) > 1:
            items = [_trim_item(part) for part in dashed if part.strip()]
    return [item for item in items if item]


#: Cap on a single extracted item. Persian job postings occasionally glue a
#: whole paragraph after a heading with no bullets; that is not a requirement
#: item, and storing it would just duplicate description_clean.
MAX_ITEM_LENGTH = 600

#: Cap on items kept per section, to bound column size.
MAX_ITEMS_PER_SECTION = 40


# --------------------------------------------------------------------------
# Skill phrase extraction
# --------------------------------------------------------------------------

#: "<qualifier> <preposition> <skill>" -- the phrase that introduces a skill in
#: each language, e.g. Persian "مسلط به Excel", English "proficiency in Excel".
_SKILL_PATTERNS = [
    # Persian
    re.compile(
        r"(?:مسلط(?:ه)?|تسلط|آشنا(?:یی)?|آشنا|تجربه|توانایی|مهارت|کارآیی|اطلاع)\s+"
        r"(?:به|با|در|از)\s+(?P<skill>[^،؛•\n:()\[\]]{2,40})"
    ),
    # English
    re.compile(
        r"(?:proficient|proficiency|familiar|experience|knowledge|skilled|ability|"
        r"working knowledge|comfortable|hands-on|solid)\s+"
        r"(?:in|with|of|using)\s+(?P<skill>[^,;\n:()\[\]]{2,40})",
        re.IGNORECASE,
    ),
    # Indonesian
    re.compile(
        r"(?:menguasai|memahami|pengalaman|kemampuan|terbiasa)\s+"
        r"(?:dalam|di|pada|untuk)\s+(?P<skill>[^,;\n:()\[\]]{2,40})",
        re.IGNORECASE,
    ),
    # Vietnamese
    re.compile(
        r"(?:thanh thao|am hieu|kinh nghiem|ky nang)\s+"
        r"(?:voi|trong|ve)\s+(?P<skill>[^,;\n:()\[\]]{2,40})",
        re.IGNORECASE,
    ),
    # Georgian
    re.compile(
        r"(?:ფლობს|იცის|გამოცდილება|უნარებობა)\s+"
        r"(?:ში|თან|ზე)\s+(?P<skill>[^,;\n:()\[\]]{2,40})"
    ),
]

#: Trailing punctuation to trim off a captured skill.
#:
#: Whitespace must NOT be in this class. An earlier version had ``[\s،؛:•\-–—]``
#: and matched at the FIRST space, so "آشنایی با اصول SOLID و Design Pattern"
#   captured "اصول SOLID و Design Pattern" and then truncated it to "اصول" --
#: dropping the actual skill. A capture stops at clause punctuation already, so
#: this only needs to strip what follows that.
_SKILL_TAIL_RE = re.compile(r"[،؛:•\-–—]+.*$")


#: Captures that satisfy the skill pattern but are not skills.
#:
#: "7+ years of experience in one of: Python, Java, Scala" matches
#: ``experience in <skill>`` and captures "one of". The patterns are
#: requirement-flavored, so their captures are usually real, but the word after
#: "in" is occasionally a quantifier rather than a technology.
_SKILL_STOPWORDS = frozenset(
    {
        "one of",
        "one or more",
        "at least",
        "more than",
        "less than",
        "order of",
        "the use of",
        "addition to",
        "any of",
        "detail",
        "detail. ",
        "a range of",
        "terms of",
        "line with",
        "accordance with",
        "the field",
        "this role",
        "the role",
        "our team",
        "the team",
        "the company",
        "the product",
        "the business",
        "a minimum of",
        "the area",
        "the right",
        "them",
        "this",
        "that",
        "which",
        "who",
        "what",
        "our",
        "the",
        "a",
        "an",
    }
)


def _clean_skill(raw: str) -> str:
    """Normalize one captured skill phrase."""
    skill = _SKILL_TAIL_RE.sub("", raw).strip(_ITEM_TRIM)
    # A skill phrase that swallowed a conjunction is not one skill.
    skill = re.split(r"\s+(?:و|or|and|atau|یا)\s+", skill, maxsplit=1)[0].strip()
    return skill


# --------------------------------------------------------------------------
# Language requirements
# --------------------------------------------------------------------------

#: Language name -> the names it appears under, across the corpus's languages.
_LANGUAGE_NAMES: dict[str, tuple[str, ...]] = {
    "English": ("english", "انگلیسی", "inggris", "tieng anh", "anglais", "inglés"),
    "Persian": ("farsi", "persian", "فارسی", "زبان فارسی"),
    "Arabic": ("arabic", "عربی", "bhs", "bahasa arab"),
    "Hebrew": ("hebrew", "עברית"),
    "French": ("french", "français", "فرانسه", "francais"),
    "German": ("german", "deutsch", "آلمانی", "allemand"),
    "Spanish": ("spanish", "español", "اسپانیایی", "espanol"),
    "Russian": ("russian", "русский", "روسی"),
    "Chinese": ("chinese", "mandarin", "چینی", "中文"),
    "Turkish": ("turkish", "ترکی استانبولی", "türkçe"),
    "Italian": ("italian", "italiano", "ایتالیایی"),
    "Portuguese": ("portuguese", "português", "پرتغالی"),
    "Indonesian": ("indonesian", "bahasa indonesia"),
    "Vietnamese": ("vietnamese", "tiếng việt"),
    "Georgian": ("georgian", "ქართული"),
    "Dutch": ("dutch", "nederlands"),
    "Japanese": ("japanese", "ژاپنی", "日本語"),
    "Korean": ("korean", "کره ای", "한국어"),
}

#: Only consider a language mentioned inside an actual language section, or in a
#: phrase that reads like a requirement ("English is required", "زبان انگلیسی").
#:
#: No trailing \b: "Languages:" is the single most common way this appears, and
#: "language" followed by "s" has no word boundary after it, so a trailing \b
#: made the cue fail on the exact heading it was meant to detect.
_LANGUAGE_CONTEXT_RE = re.compile(r"زبان|language|linguas|baasa|dil|լեզու", re.IGNORECASE)


def _extract_languages(text: str) -> list[str]:
    """Find language requirements stated in a description."""
    found: list[str] = []
    lowered = text.lower()
    for canonical, aliases in _LANGUAGE_NAMES.items():
        for alias in aliases:
            index = lowered.find(alias)
            if index < 0:
                continue
            # Require a language-ish cue near the mention, so "English teacher"
            # or the board's own English UI text does not imply a requirement.
            window = lowered[max(0, index - 60) : index + 60]
            if _LANGUAGE_CONTEXT_RE.search(window):
                found.append(canonical)
                break
    return sorted(set(found))


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------


@dataclass
class ExtractionResult:
    """Column values extracted from one description."""

    requirements: str | None = None
    responsibilities: str | None = None
    required_skills_text: str | None = None
    preferred_skills_text: str | None = None
    language_requirements_text: str | None = None
    section_count: int = 0
    headings: list[str] = field(default_factory=list)

    @property
    def has_any(self) -> bool:
        return any(
            (
                self.requirements,
                self.responsibilities,
                self.required_skills_text,
                self.preferred_skills_text,
                self.language_requirements_text,
            )
        )


def _render(items: list[str]) -> str | None:
    """Join extracted items into the stored column value."""
    if not items:
        return None
    clipped = [item[:MAX_ITEM_LENGTH] for item in items[:MAX_ITEMS_PER_SECTION]]
    return "\n".join(f"- {item}" for item in clipped)


def _route_sections(text: str, headings: list[Heading], buckets: dict[str, list[str]]) -> None:
    """Fill ``buckets`` with each section's items, keyed by the column they feed."""
    for position, heading in enumerate(headings):
        stop = headings[position + 1].start if position + 1 < len(headings) else len(text)
        body = text[heading.end : stop]
        items = _split_items(body)
        skills = _collect_skills(" ".join(items))

        if heading.kind == SectionKind.PREFERRED:
            # A "nice to have" section is preferred *qualifications*: both the
            # whole items and the skills named inside them are preferred.
            buckets["preferred_skills_text"].extend(items)
            buckets["preferred_skills_text"].extend(skills)
            continue

        if heading.kind == SectionKind.LANGUAGE:
            # The cue word lives in the HEADING ("Languages:", "زبان:"), not the
            # body -- "Languages: English (fluent)" has no cue anywhere in
            # "English (fluent)". Scan from the heading's own offset.
            languages = _extract_languages(text[heading.start : stop])
            if languages:
                buckets["language_requirements_text"].extend(languages)
            continue

        if heading.kind == SectionKind.SKILLS:
            buckets["required_skills_text"].extend(items)
            buckets["required_skills_text"].extend(skills)
            continue

        if heading.kind in (SectionKind.REQUIREMENTS, SectionKind.EDUCATION):
            # EDUCATION joins REQUIREMENTS deliberately, and this is the single
            # most important routing decision in the module.
            #
            # Age, gender, degree and experience are not a separate kind of
            # content -- in Iranian postings they are sub-fields of the
            # requirements that precedes them:
            #
            #     شرایط احراز: سن: 20 تا 35 سال تحصیلات: حداقل دیپلم
            #
            # where "سن:" (age) starts two characters after the "شرایط احراز"
            # heading ends. Routing EDUCATION anywhere else gave the
            # requirements heading an empty body and threw away everything that
            # followed, which is why the requirements fill RATE FELL when these
            # sub-fields started being detected at all.
            buckets["requirements"].extend(items)
            buckets["required_skills_text"].extend(skills)
            continue

        if heading.kind == SectionKind.RESPONSIBILITIES:
            buckets["responsibilities"].extend(items)
            # Skills are collected here too, deliberately.
            #
            # Iranian boards routinely file "آشنایی با MVC" / "تسلط به React"
            # (familiarity with / proficiency in) under the DUTIES heading, not
            # under requirements. One real jobvision posting put all eleven of
            # its skill requirements under "شرح وظایف" and left required_skills
            # NULL. The phrases themselves are requirement-flavored -- a tool
            # merely used in the work reads "از Kubernetes استفاده می‌کنید",
            # which matches nothing here -- so scanning every section recovers
            # them without importing prose into the column.
            buckets["required_skills_text"].extend(skills)
            continue

        # BENEFITS / OTHER: no destination column. The section still terminates
        # here, which is the point -- it stops a requirements section running on
        # into the benefits list.
        if heading.kind not in (SectionKind.LANGUAGE,):
            buckets["required_skills_text"].extend(skills)


def extract_description_sections(
    description: str,
    *,
    max_chars: int = 20_000,
) -> ExtractionResult:
    """Split one description into the five derived columns.

    Args:
        description: The flattened description text.
        max_chars: Only the first N characters are parsed. Sections are almost
            always in the first few thousand; skipping the tail keeps a stray
            "Requirements:" in an unrelated footer from overriding the real one.

    Returns:
        ExtractionResult with only the columns that could be filled.
    """
    if not description:
        return ExtractionResult()

    text = description[:max_chars]
    headings = find_headings(text)

    # Bucket items by the column their section feeds.
    buckets: dict[str, list[str]] = {
        "responsibilities": [],
        "requirements": [],
        "preferred_skills_text": [],
        "required_skills_text": [],
        "language_requirements_text": [],
    }

    _route_sections(text, headings, buckets)

    # Fallback for the majority of rows with no heading at all, which is most of
    # jobvision: an explicit skill phrase is a requirement statement wherever it
    # appears. "مسلط به Excel" / "proficiency in Kubernetes" does not become less
    # of a requirement because the board forgot to put it under a heading.
    #
    # Guarded on requirements being empty on purpose. When a real requirements
    # section WAS found, skills come from it, and scanning the whole description
    # as well would sweep in tools merely mentioned in the responsibilities
    # ("you will use Kubernetes to deploy...") and mislabel them as required.
    if not buckets["requirements"]:
        buckets["required_skills_text"].extend(_collect_skills(text))

    # Deduplicate while preserving order, after the fallback has been merged in.
    for column, items in buckets.items():
        seen: set[str] = set()
        buckets[column] = [
            item for item in items if not (item.lower() in seen or seen.add(item.lower()))
        ]

    return ExtractionResult(
        requirements=_render(buckets["requirements"]),
        responsibilities=_render(buckets["responsibilities"]),
        required_skills_text=_render(buckets["required_skills_text"]),
        preferred_skills_text=_render(buckets["preferred_skills_text"]),
        language_requirements_text=_render(buckets["language_requirements_text"]),
        section_count=len(headings),
        headings=[h.text for h in headings],
    )


def _collect_skills(text: str) -> list[str]:
    """Extract "proficient in X"-style skill phrases from a block of text.

    Search resumes at the start of the captured skill rather than the end of the
    match, so overlapping phrases are both found. Plain ``finditer`` missed the
    second one in "مسلط به Excel و آشنایی با SQL": the capture ran to the end of
    the clause (which may legitimately contain " و " as in "C++ و Python"), so
    "آشنایی با SQL" had already been consumed as part of the first match and
    "SQL" was never extracted.
    """
    if not text:
        return []
    skills: list[str] = []
    for pattern in _SKILL_PATTERNS:
        position = 0
        while position < len(text):
            match = pattern.search(text, position)
            if match is None:
                break
            skill = _clean_skill(match.group("skill"))
            if 2 <= len(skill) <= 60 and skill.lower() not in _SKILL_STOPWORDS:
                skills.append(skill)
            position = match.start("skill")
    return skills
