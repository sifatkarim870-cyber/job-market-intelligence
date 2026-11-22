"""Parses a National Employment Agency (Cambodia) vacancy detail page.

The board publishes no schema.org block, so this is label-keyed HTML
extraction against the board's own Khmer labels. Measured on 2026-11-22::

    <span id="vacancyTitle">អ្នកដេរ</span>
    <div class="tit_box"><span class="tit">ហ្សេតអិម ហ្វ៊ូតវែរ (ខេមបូឌា) ឯ.ក</span></div>
    <div class="cont"><strong class="tit">ប្រាក់បៀវត្ស</strong>
                     <span class="con">ខែ $210~$250</span></div>
    <div class="form_wrap">
      <div class="form_title"><h3>ព័ត៌មានជ្រើសរើសកម្លាំងពលកម្ម</h3></div>
      <div class="view_form">
        <strong class="title">រយៈពេលជ្រើសរើស</strong>
        <p class="cont_box">20/11/2026 ~ 13/02/2027</p>
      </div>
    </div>

The traps:

* Zero-width spaces (``U+200B``) are embedded inside Khmer words. Labels are
  normalised before matching and values have them removed.
* ``អាសយដ្ឋាន`` (address) appears twice: the employer address in the summary
  block, then the *job centre* address near the bottom. First non-empty wins,
  which is the employer address that belongs to the vacancy.
* The workplace is ``<vacancies> / <province>`` in
  ``ចំនួនកម្លាំងពលកម្មត្រូវជ្រើសរើស / ទីកន្លែងធ្វើការ``. The province after the
  slash is the location; the full address is the fallback when it is blank.
* Salary text is USD per month (``ខែ $210~$250``). The dollar sign is the
  local quoting convention, not a currency conversion.
* The description section is frequently the literal placeholder
  ``Job Descriptions Responsibilities Duties``. When the rendered text is
  too short to be a description, a factual one is composed from the
  structured fields rather than shipping the placeholder.
"""

from __future__ import annotations

import re
from datetime import date
from html import escape

from bs4 import BeautifulSoup
from loguru import logger

from .exceptions import NeaGovKhParseError
from .models import RawNeaGovKhJob

#: Invisible characters the CMS sprinkles through Khmer words.
_INVISIBLE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_WHITESPACE = re.compile(r"\s+")

#: Khmer digits -> ASCII digits.
_KH_DIGITS = str.maketrans("០១២៣៤៥៦៧៨៩", "0123456789")

#: The board's own labels, normalised (zero-width spaces removed).
_L_OCCUPATION = "មុខរបរ"
_L_WORKPLACE = "ចំនួនកម្លាំងពលកម្មត្រូវជ្រើសរើស / ទីកន្លែងធ្វើការ"
_L_ADDRESS = "អាសយដ្ឋាន"
_L_EDUCATION = "ការអប់រំ"
_L_EXPERIENCE = "បទពិសោធន៍ការងារ"
_L_EXPERIENCE_SHORT = "បទពិសោធន៍"
_L_JOB_TYPE = "ប្រភេទការងារនៃមុខតំណែងត្រូវការជ្រើសរើស"
_L_PERIOD = "រយៈពេលជ្រើសរើស"
_L_BASE_SALARY = "ប្រាក់ឈ្នួលគោល"
_L_SALARY = "ប្រាក់បៀវត្ស"
_L_INDUSTRY = "វិស័យ"
_L_CONTRACT = "កិច្ចសន្យាការងារនៃមុខតំណែងត្រូវការជ្រើសរើស"
_L_VACANCIES = "ចំនួនកម្លាំងពលកម្មត្រូវជ្រើសរើស"
_L_POSITION_NAME = "ឈ្មោះមុខតំណែងត្រូវការជ្រើសរើស"
_L_DESCRIPTION = "ការពណ៌នាអំពីតួនាទី"

#: A "description" that is only the CMS placeholder.
_PLACEHOLDERS = {
    "job descriptions responsibilities duties",
    "job description responsibilities duties",
}

#: The shortest real description accepted before a factual one is composed.
_MIN_REAL_DESCRIPTION_CHARS = 40


def _norm_label(text: str | None) -> str:
    if not text:
        return ""
    return _WHITESPACE.sub(" ", _INVISIBLE.sub("", text)).strip()


def _clean_value(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = _WHITESPACE.sub(" ", _INVISIBLE.sub("", text)).strip()
    return cleaned or None


def _khmer_digits(text: str | None) -> str:
    return (text or "").translate(_KH_DIGITS)


def _as_numbers(text: str | None) -> list[float]:
    if not text:
        return []
    normalised = _khmer_digits(text).replace(",", "")
    values: list[float] = []
    for token in re.findall(r"\d+(?:\.\d+)?", normalised):
        try:
            number = float(token)
        except ValueError:
            continue
        if number > 0:
            values.append(number)
    return values


def _salary(text: str | None) -> tuple[float | None, float | None]:
    values = _as_numbers(text)
    if not values:
        return None, None
    return round(min(values), 2), round(max(values), 2)


def _date_range(text: str | None) -> tuple[date | None, date | None]:
    if not text:
        return None, None
    normalised = _khmer_digits(text)
    dates: list[date] = []
    for day, month, year in re.findall(r"(\d{1,2})/(\d{1,2})/(\d{4})", normalised):
        try:
            dates.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    if not dates:
        return None, None
    if len(dates) == 1:
        return dates[0], None
    return dates[0], dates[1]


def _vacancies(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"\d+", _khmer_digits(text))
    return int(match.group()) if match else None


def _collect_summary(soup: BeautifulSoup) -> dict[str, str]:
    """First non-empty value for each label in the ``.cont`` summary block."""
    summary: dict[str, str] = {}
    for cont in soup.select(".cont"):
        strong = cont.find("strong", class_="tit")
        if strong is None:
            continue
        con = cont.find("span", class_="con")
        label = _norm_label(strong.get_text(" ", strip=True))
        value = _clean_value(con.get_text(" ", strip=True) if con else None)
        if label and value:
            summary.setdefault(label, value)
    return summary


def _collect_sections(soup: BeautifulSoup) -> tuple[dict[str, str], list[str]]:
    """First non-empty value for each label across the ``.form_wrap`` sections."""
    section_fields: dict[str, str] = {}
    section_titles: list[str] = []
    for form_wrap in soup.select(".form_wrap"):
        heading = form_wrap.select_one(".form_title h3")
        heading_text = _clean_value(heading.get_text(" ", strip=True)) if heading else None
        if heading_text:
            section_titles.append(heading_text)
        for view_form in form_wrap.select(".view_form"):
            strong = view_form.find("strong", class_="title")
            if strong is None:
                continue
            node = view_form.find("p", class_="cont_box") or view_form.find(
                "div", class_="cont_box"
            )
            label = _norm_label(strong.get_text(" ", strip=True))
            value = _clean_value(node.get_text(" ", strip=True) if node else None)
            if label and value:
                section_fields.setdefault(label, value)
    return section_fields, section_titles


def _collect_fields(
    soup: BeautifulSoup,
) -> tuple[dict[str, str], dict[str, str], list[str], dict[str, str]]:
    """Return ``(summary, section_fields, section_titles, merged)``."""
    summary = _collect_summary(soup)
    section_fields, section_titles = _collect_sections(soup)

    merged: dict[str, str] = {}
    for source in (summary, section_fields):
        for label, value in source.items():
            merged.setdefault(label, value)
    return summary, section_fields, section_titles, merged


def _description_html(soup: BeautifulSoup) -> str | None:
    """The rendered description section, if it is more than a placeholder."""
    for form_wrap in soup.select(".form_wrap"):
        heading = form_wrap.select_one(".form_title h3")
        if heading is None:
            continue
        if not _norm_label(heading.get_text(" ", strip=True)).startswith(_L_DESCRIPTION):
            continue
        node = form_wrap.select_one("div.cont_box") or form_wrap.select_one("p.cont_box")
        if node is None:
            return None
        for tag in node.find_all(["script", "style"]):
            tag.decompose()
        text = _WHITESPACE.sub(" ", node.get_text(" ", strip=True)).strip()
        if text and len(text) >= _MIN_REAL_DESCRIPTION_CHARS and text.lower() not in _PLACEHOLDERS:
            return node.decode_contents().strip()
        return None
    return None


def _compose_description(
    *,
    title: str,
    occupation: str | None,
    location: str | None,
    job_type: str | None,
    education: str | None,
    experience: str | None,
    salary_text: str | None,
    vacancies: int | None,
) -> str:
    """A factual description built from the structured fields."""
    rows: list[tuple[str, str | None]] = [
        ("Position", title),
        ("Occupation", occupation),
        ("Location", location),
        ("Employment type", job_type),
        ("Education", education),
        ("Experience", experience),
        ("Salary", salary_text),
        ("Vacancies", str(vacancies) if vacancies else None),
    ]
    parts = [f"<p><strong>{label}:</strong> {escape(value)}</p>" for label, value in rows if value]
    return "".join(parts)


def parse_detail(
    job_id: str,
    html: str,
    url: str | None = None,
    listing_category: str | None = None,
) -> RawNeaGovKhJob:
    """Parse one NEA Cambodia vacancy detail page."""
    soup = BeautifulSoup(html or "", "html.parser")

    summary, section_fields, section_titles, fields = _collect_fields(soup)

    title_node = soup.find(id="vacancyTitle")
    title = _clean_value(title_node.get_text(" ", strip=True) if title_node else None)
    if not title:
        title = fields.get(_L_POSITION_NAME)
    if not title:
        heading = soup.select_one("div#contents h3.h0.title") or soup.find("h1")
        title = _clean_value(heading.get_text(" ", strip=True) if heading else None)
    if not title:
        raise NeaGovKhParseError(
            f"NEA Cambodia vacancy {job_id} has no #vacancyTitle, position name or <h1>. "
            "The vacancy is withdrawn or the page markup changed."
        )

    company_node = soup.select_one(".tit_box span.tit")
    company = _clean_value(company_node.get_text(" ", strip=True) if company_node else None)

    occupation = fields.get(_L_OCCUPATION)
    workplace = fields.get(_L_WORKPLACE)
    address = fields.get(_L_ADDRESS)

    location = None
    if workplace and "/" in workplace:
        candidate = workplace.rsplit("/", 1)[-1].strip()
        location = candidate or None
    location = location or address

    education = fields.get(_L_EDUCATION)
    experience = fields.get(_L_EXPERIENCE) or fields.get(_L_EXPERIENCE_SHORT)
    job_type = fields.get(_L_JOB_TYPE)
    contract_type = fields.get(_L_CONTRACT)

    period_text = fields.get(_L_PERIOD)
    posted_date, closing_date = _date_range(period_text)

    salary_text = fields.get(_L_BASE_SALARY) or fields.get(_L_SALARY)
    salary_min, salary_max = _salary(salary_text)

    vacancies = _vacancies(fields.get(_L_VACANCIES))

    description_html = _description_html(soup)
    if not description_html:
        description_html = _compose_description(
            title=title,
            occupation=occupation,
            location=location,
            job_type=job_type,
            education=education,
            experience=experience,
            salary_text=salary_text,
            vacancies=vacancies,
        )

    return RawNeaGovKhJob(
        source_job_id=str(job_id),
        title=title,
        company_name=company or "Unknown employer",
        company_logo_url=None,
        location_text=location,
        region=None,
        country="Cambodia",
        address=address,
        description_html=description_html,
        posted_date=posted_date,
        closing_date=closing_date,
        employment_types=[job_type] if job_type else [],
        contract_type_raw=contract_type,
        work_hours=None,
        education_raw=education,
        experience_raw=experience,
        occupational_category=occupation,
        industry=fields.get(_L_INDUSTRY),
        salary_currency="USD",
        salary_min=salary_min,
        salary_max=salary_max,
        salary_period="monthly",
        salary_text_raw=salary_text,
        vacancies_count=vacancies,
        job_url=url,
        listing_category=listing_category,
        raw={
            "summary_fields": summary,
            "section_fields": section_fields,
            "section_titles": section_titles,
            "recruitment_period": period_text,
            "salary_text": salary_text,
            "page_bytes": len(html or ""),
            "title_tag": soup.title.get_text(" ", strip=True) if soup.title else None,
        },
    )


class NeaGovKhParser:
    """Turns an NEA Cambodia vacancy page into a model."""

    def parse(
        self,
        job_id: str,
        html: str | None = None,
        url: str | None = None,
        listing_category: str | None = None,
    ) -> RawNeaGovKhJob:
        return parse_detail(job_id, html or "", url=url, listing_category=listing_category)

    def parse_many(self, records: list[dict]) -> tuple[list[RawNeaGovKhJob], list[str]]:
        parsed: list[RawNeaGovKhJob] = []
        issues: list[str] = []
        for record in records:
            try:
                parsed.append(
                    self.parse(
                        str(record.get("job_id") or ""),
                        record.get("html"),
                        url=record.get("url"),
                        listing_category=record.get("listing_category"),
                    )
                )
            except NeaGovKhParseError as exc:
                issues.append(str(exc))
        if issues:
            logger.warning(
                "dropped {} of {} NEA Cambodia records that failed to parse",
                len(issues),
                len(records),
            )
        return parsed, issues
