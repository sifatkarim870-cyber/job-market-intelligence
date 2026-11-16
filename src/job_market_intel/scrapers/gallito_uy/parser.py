"""Parser for Gallito (Uruguay) vacancy detail pages."""

from __future__ import annotations

import json
import re
from typing import Any
from bs4 import BeautifulSoup

from loguru import logger
from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.scrapers.gallito_uy.exceptions import GallitoParseError
from job_market_intel.scrapers.gallito_uy.models import RawGallitoJob


class GallitoParser:
    """Extracts structured CleanedJob records from Gallito raw HTML pages."""

    @staticmethod
    def _clean_text(text: str | None) -> str:
        if not text:
            return ""
        return " ".join(text.split()).strip()

    def _extract_json_ld(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Find and parse Schema.org JobPosting JSON-LD block."""
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if data.get("@type") == "JobPosting":
                        return data
                    graph = data.get("@graph")
                    if isinstance(graph, list):
                        for item in graph:
                            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                                return item
            except Exception:
                continue
        return {}

    def parse_job(self, raw: RawGallitoJob) -> CleanedJob:
        """Parse raw Gallito HTML into a CleanedJob instance."""
        soup = BeautifulSoup(raw.html_content, "html.parser")
        json_ld = self._extract_json_ld(soup)

        # 1. Job Title
        title = self._clean_text(json_ld.get("title"))
        if not title:
            h_elem = soup.find("h2") or soup.find("h1")
            title = self._clean_text(h_elem.get_text() if h_elem else None)
        if not title and soup.title:
            page_title = soup.title.string or ""
            title = page_title.split("-")[0].strip()
        if not title:
            title = f"Puesto en Uruguay {raw.job_id}"

        # 2. Company Name
        company: str | None = None
        org_obj = json_ld.get("hiringOrganization")
        if isinstance(org_obj, dict):
            company = self._clean_text(org_obj.get("name"))
        elif isinstance(org_obj, str):
            company = self._clean_text(org_obj)

        if not company or company.lower() in ("empresa", "importante empresa", "confidencial"):
            company = "Empresa confidencial"

        # 3. Location
        location = "Uruguay"
        loc_obj = json_ld.get("jobLocation")
        if isinstance(loc_obj, dict):
            addr_obj = loc_obj.get("address")
            if isinstance(addr_obj, dict):
                loc_name = self._clean_text(addr_obj.get("addressLocality"))
                if loc_name:
                    location = f"{loc_name}, Uruguay"
                else:
                    reg = self._clean_text(addr_obj.get("addressRegion"))
                    if reg:
                        location = f"{reg}, Uruguay"

        if location == "Uruguay":
            loc_match = soup.find(class_=re.compile(r"ubicacion|localidad|departamento", re.I))
            if loc_match:
                parsed_loc = self._clean_text(loc_match.get_text())
                if parsed_loc:
                    location = f"{parsed_loc}, Uruguay"

        # 4. Dates
        posting_date = json_ld.get("datePosted")
        if isinstance(posting_date, str) and len(posting_date) >= 10:
            posting_date = posting_date[:10]
        else:
            posting_date = None

        closing_date = json_ld.get("validThrough")
        if isinstance(closing_date, str) and len(closing_date) >= 10:
            closing_date = closing_date[:10]
        else:
            closing_date = None

        # 5. Employment Type
        emp_type_code = "full_time"
        emp_val = json_ld.get("employmentType")
        if isinstance(emp_val, list) and emp_val:
            emp_val = emp_val[0]
        emp_str = str(emp_val or "").upper()
        if "FULL_TIME" in emp_str or "COMPLETO" in emp_str:
            emp_type_code = "full_time"
        elif "PART_TIME" in emp_str or "PARCIAL" in emp_str:
            emp_type_code = "part_time"
        elif "CONTRACTOR" in emp_str or "CONTRATO" in emp_str:
            emp_type_code = "contract"
        elif "INTERN" in emp_str or "PASANTIA" in emp_str:
            emp_type_code = "internship"

        # 6. Salary
        salary_disclosed = False
        salary_min: float | None = None
        salary_max: float | None = None
        currency_iso_code: str = "UYU"
        pay_period: str = "monthly"

        base_salary = json_ld.get("baseSalary")
        if isinstance(base_salary, dict):
            curr = base_salary.get("currency")
            if curr:
                currency_iso_code = curr.strip().upper()
            val_obj = base_salary.get("value")
            if isinstance(val_obj, dict):
                unit_text = str(val_obj.get("unitText") or "").upper()
                if "YEAR" in unit_text or "AÑO" in unit_text:
                    pay_period = "yearly"
                elif "HOUR" in unit_text or "HORA" in unit_text:
                    pay_period = "hourly"
                elif "MONTH" in unit_text or "MES" in unit_text:
                    pay_period = "monthly"

                min_v = val_obj.get("minValue")
                max_v = val_obj.get("maxValue") or min_v
                if min_v is not None:
                    try:
                        salary_min = float(min_v)
                        salary_disclosed = True
                    except (ValueError, TypeError):
                        pass
                if max_v is not None:
                    try:
                        salary_max = float(max_v)
                        salary_disclosed = True
                    except (ValueError, TypeError):
                        pass

        # 7. Description & Structured Sections
        sections: dict[str, Any] = {}
        summary_desc = self._clean_text(json_ld.get("description"))
        if summary_desc:
            sections["summary"] = summary_desc

        body_blocks: list[str] = []
        if summary_desc:
            body_blocks.append(summary_desc)

        # Extract cuadros de aviso (Responsabilidades, Funciones, Requisitos, etc.)
        for cuadro in soup.find_all(class_=re.compile(r"cuadro-aviso", re.I)):
            t_elem = cuadro.find(class_=re.compile(r"cuadro-aviso-title", re.I))
            txt_elem = cuadro.find(class_=re.compile(r"cuadro-aviso-text", re.I))
            sec_title = self._clean_text(t_elem.get_text() if t_elem else "")
            sec_text = self._clean_text(txt_elem.get_text() if txt_elem else "")
            if sec_title and sec_text:
                slug_key = re.sub(r"[^a-zA-Z0-9]+", "_", sec_title.lower()).strip("_")
                sections[slug_key] = sec_text
                body_blocks.append(f"{sec_title}:\n{sec_text}")

        desc_text = "\n\n".join(body_blocks).strip()
        if not desc_text:
            content_elem = soup.find(class_=re.compile(r"cont-general-aviso|contenedor-ficha-aviso", re.I))
            if content_elem:
                desc_text = self._clean_text(content_elem.get_text(" ", strip=True))
        if not desc_text:
            desc_text = title

        words = len(desc_text.split())

        # 8. Skills
        skills: list[str] = []
        for word in re.findall(r"[A-Za-z#+]{2,}", desc_text):
            if word.lower() in ("python", "java", "sql", "excel", "sales", "react", "accounting", "ingles"):
                norm = word.capitalize()
                if norm not in skills:
                    skills.append(norm)

        raw_payload = {
            "url": raw.url,
            "job_id": raw.job_id,
            "title": title,
            "company": company,
            "location": location,
            "json_ld": json_ld,
            "sections": sections,
        }

        return CleanedJob(
            source_job_id=raw.job_id,
            job_title=title,
            company_name=company,
            company_logo_url=None,
            skills=skills,
            location_cleaned=location,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_disclosed=salary_disclosed,
            description_clean=desc_text,
            word_count=words,
            apply_url=raw.url,
            original_url=raw.url,
            posting_date=posting_date,
            closing_date=closing_date,
            data_quality_score=0.95 if words > 50 else 0.7,
            raw_payload=raw_payload,
            currency_iso_code=currency_iso_code,
            pay_period=pay_period,
            employment_type_code=emp_type_code,
        )

    def parse_jobs(self, raw_jobs: list[RawGallitoJob]) -> list[CleanedJob]:
        """Batch-parse raw Gallito job pages into CleanedJob instances."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                job = self.parse_job(raw)
                cleaned.append(job)
            except Exception as exc:
                logger.warning("Error parsing Gallito vacancy {}: {}", raw.job_id, exc)
        return cleaned
