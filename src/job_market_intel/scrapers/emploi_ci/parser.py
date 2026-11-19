"""Parser for Emploi.ci (Côte d'Ivoire) vacancy detail pages."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any
from bs4 import BeautifulSoup

from loguru import logger
from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.scrapers.emploi_ci.exceptions import EmploiCiParseError
from job_market_intel.scrapers.emploi_ci.models import RawEmploiCiJob


class EmploiCiParser:
    """Extracts structured CleanedJob records from Emploi.ci raw HTML pages."""

    @staticmethod
    def _clean_text(text: str | None) -> str:
        if not text:
            return ""
        unescaped = html.unescape(text)
        return " ".join(unescaped.split()).strip()

    def _extract_json_ld(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Find and parse Schema.org JobPosting JSON-LD block with repair for unescaped description HTML."""
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string and not script.text:
                continue
            content = (script.string or script.text).strip()
            if "JobPosting" not in content and "jobposting" not in content:
                continue

            # Attempt 1: Direct JSON parse with strict=False
            try:
                data = json.loads(content, strict=False)
                if isinstance(data, dict):
                    if data.get("@type") in ("JobPosting", "jobposting"):
                        return data
                    graph = data.get("@graph")
                    if isinstance(graph, list):
                        for item in graph:
                            if isinstance(item, dict) and item.get("@type") in ("JobPosting", "jobposting"):
                                return item
            except Exception:
                pass

            # Attempt 2: Description in JSON-LD often contains unescaped HTML quotes.
            # Strip the description field from raw JSON and parse the remaining metadata.
            try:
                repaired = re.sub(
                    r'"description"\s*:\s*".*?"\s*,\s*"identifier"',
                    '"identifier"',
                    content,
                    flags=re.DOTALL,
                )
                data = json.loads(repaired, strict=False)
                if isinstance(data, dict) and data.get("@type") in ("JobPosting", "jobposting"):
                    return data
            except Exception:
                pass

        return {}

    @staticmethod
    def _parse_date(date_str: str | None) -> str | None:
        """Parse various date formats into YYYY-MM-DD string."""
        if not date_str or not isinstance(date_str, str):
            return None
        date_str = date_str.strip()
        # ISO format: 2026-11-19T01:00:02+00:00
        iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})", date_str)
        if iso_match:
            return iso_match.group(1)

        # French format: 19.11.2026 or 19/11/2026
        fr_match = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", date_str)
        if fr_match:
            return f"{fr_match.group(3)}-{int(fr_match.group(2)):02d}-{int(fr_match.group(1)):02d}"

        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d.%m.%Y",
        ):
            try:
                dt_obj = datetime.strptime(date_str, fmt)
                return dt_obj.strftime("%Y-%m-%d")
            except ValueError:
                pass
        return None

    def parse_job(self, raw: RawEmploiCiJob) -> CleanedJob:
        """Parse raw Emploi.ci HTML into a CleanedJob instance."""
        soup = BeautifulSoup(raw.html_content, "html.parser")
        json_ld = self._extract_json_ld(soup)

        # 1. Job Title
        title = self._clean_text(json_ld.get("title") or json_ld.get("Title"))
        if not title:
            h_elem = soup.find("h1") or soup.find("h2")
            title = self._clean_text(h_elem.get_text() if h_elem else None)
        if not title and soup.title:
            page_title = soup.title.string or ""
            title = page_title.split("|")[0].split("-")[0].strip()
        if not title:
            title = f"Poste en Côte d'Ivoire {raw.job_id}"

        # 2. Company Name
        company: str | None = None
        org_obj = json_ld.get("hiringOrganization")
        if isinstance(org_obj, dict):
            company = self._clean_text(org_obj.get("name"))
        elif isinstance(org_obj, str):
            company = self._clean_text(org_obj)

        if not company:
            comp_elem = soup.find(class_=re.compile(r"company-name|card-block-company|job-company", re.I))
            if comp_elem:
                company = self._clean_text(comp_elem.get_text())

        if not company or company.lower() in ("confidentiel", "confidential", "anonyme"):
            company = "Confidential Employer"

        # 3. Location
        location = "Côte d'Ivoire"
        loc_obj = json_ld.get("jobLocation")
        if isinstance(loc_obj, dict):
            addr_obj = loc_obj.get("address")
            if isinstance(addr_obj, dict):
                loc_name = self._clean_text(addr_obj.get("addressLocality"))
                reg_name = self._clean_text(addr_obj.get("addressRegion"))
                country_name = self._clean_text(addr_obj.get("addressCountry")) or "Côte d'Ivoire"
                if loc_name and reg_name and loc_name != reg_name:
                    location = f"{loc_name}, {reg_name}, {country_name}"
                elif loc_name:
                    location = f"{loc_name}, {country_name}"
                elif reg_name:
                    location = f"{reg_name}, {country_name}"
                else:
                    location = country_name

        # 4. Dates
        posting_date = self._parse_date(json_ld.get("datePosted"))
        closing_date = self._parse_date(json_ld.get("validThrough"))

        if not posting_date:
            date_match = re.search(r"Publi[ée]e?\s+le\s+(\d{1,2}[./]\d{1,2}[./]\d{4})", raw.html_content)
            if date_match:
                posting_date = self._parse_date(date_match.group(1))

        # 5. Employment Type
        emp_type_code = "full_time"
        emp_val = json_ld.get("employmentType")
        if isinstance(emp_val, list) and emp_val:
            emp_val = emp_val[0]
        emp_str = str(emp_val or "").upper()
        if "CDI" in emp_str or "FULL" in emp_str or "PERMANENT" in emp_str:
            emp_type_code = "full_time"
        elif "CDD" in emp_str or "TEMPORARY" in emp_str or "CONTRACT" in emp_str:
            emp_type_code = "contract"
        elif "STAGE" in emp_str or "INTERN" in emp_str:
            emp_type_code = "internship"
        elif "PART" in emp_str or "TEMPS PARTIEL" in emp_str:
            emp_type_code = "part_time"

        # 6. Salary
        salary_disclosed = False
        salary_min: float | None = None
        salary_max: float | None = None
        currency_iso_code: str = "XOF"
        pay_period: str = "monthly"

        base_salary = json_ld.get("baseSalary")
        if isinstance(base_salary, dict):
            curr = base_salary.get("currency")
            if curr:
                currency_iso_code = curr.strip().upper()
            val_obj = base_salary.get("value")
            if isinstance(val_obj, dict):
                unit_text = str(val_obj.get("unitText") or "").upper()
                if "YEAR" in unit_text or "AN" in unit_text:
                    pay_period = "yearly"
                elif "HOUR" in unit_text or "HEURE" in unit_text:
                    pay_period = "hourly"
                elif "MONTH" in unit_text or "MOIS" in unit_text:
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
        desc_text = ""

        # Check HTML description container first for cleanest rendering
        desc_elem = soup.find("div", class_="job-description")
        if desc_elem:
            desc_text = desc_elem.get_text("\n", strip=True)
        elif json_ld.get("description"):
            desc_soup = BeautifulSoup(json_ld.get("description"), "html.parser")
            desc_text = desc_soup.get_text("\n", strip=True)
        else:
            fallback_elem = soup.find(class_=re.compile(r"job-detail|description|job-content", re.I))
            if fallback_elem:
                desc_text = fallback_elem.get_text("\n", strip=True)
            else:
                desc_text = title

        desc_text = re.sub(r"\n{3,}", "\n\n", desc_text).strip()
        if not desc_text:
            desc_text = title

        sections["description"] = desc_text
        words = len(desc_text.split())

        # 8. Skills
        skills: list[str] = []
        for word in re.findall(r"[A-Za-z#+]{2,}", desc_text):
            w_lower = word.lower()
            if w_lower in (
                "python",
                "java",
                "sql",
                "excel",
                "comptabilité",
                "gestion",
                "marketing",
                "javascript",
                "anglais",
                "management",
                "vente",
                "logistique",
                "finance",
            ):
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

    def parse_jobs(self, raw_jobs: list[RawEmploiCiJob]) -> list[CleanedJob]:
        """Batch-parse raw Emploi.ci job pages into CleanedJob instances."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                job = self.parse_job(raw)
                cleaned.append(job)
            except Exception as exc:
                logger.warning("Error parsing Emploi.ci vacancy {}: {}", raw.job_id, exc)
        return cleaned
