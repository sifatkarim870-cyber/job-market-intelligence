"""Parser for JobNet (Myanmar) vacancy detail pages."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any
from bs4 import BeautifulSoup

from loguru import logger
from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.scrapers.jobnet_mm.exceptions import JobnetParseError
from job_market_intel.scrapers.jobnet_mm.models import RawJobnetJob


class JobnetParser:
    """Extracts structured CleanedJob records from JobNet raw HTML pages."""

    @staticmethod
    def _clean_text(text: str | None) -> str:
        if not text:
            return ""
        # Unescape HTML entities first
        unescaped = html.unescape(text)
        return " ".join(unescaped.split()).strip()

    def _extract_json_ld(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Find and parse Schema.org JobPosting JSON-LD block with strict=False."""
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            content = script.string.strip()
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
                continue
        return {}

    @staticmethod
    def _parse_date(date_str: str | None) -> str | None:
        """Parse various date formats into YYYY-MM-DD string."""
        if not date_str or not isinstance(date_str, str):
            return None
        date_str = date_str.strip()
        for fmt in (
            "%m/%d/%Y %I:%M:%S %p",
            "%m/%d/%Y %H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%d/%m/%Y",
        ):
            try:
                dt_obj = datetime.strptime(date_str, fmt)
                return dt_obj.strftime("%Y-%m-%d")
            except ValueError:
                pass
        match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", date_str)
        if match:
            return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        match_us = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", date_str)
        if match_us:
            return f"{match_us.group(3)}-{int(match_us.group(1)):02d}-{int(match_us.group(2)):02d}"
        return None

    def parse_job(self, raw: RawJobnetJob) -> CleanedJob:
        """Parse raw JobNet HTML into a CleanedJob instance."""
        soup = BeautifulSoup(raw.html_content, "html.parser")
        json_ld = self._extract_json_ld(soup)

        # 1. Job Title
        title = self._clean_text(json_ld.get("Title") or json_ld.get("title"))
        if not title:
            h_elem = soup.find("h1") or soup.find("h2")
            title = self._clean_text(h_elem.get_text() if h_elem else None)
        if not title and soup.title:
            page_title = soup.title.string or ""
            title = page_title.split("|")[0].split("-")[0].strip()
        if not title:
            title = f"Position in Myanmar {raw.job_id}"

        # 2. Company Name
        company: str | None = None
        org_obj = json_ld.get("hiringOrganization")
        if isinstance(org_obj, dict):
            company = self._clean_text(org_obj.get("name"))
        elif isinstance(org_obj, str):
            company = self._clean_text(org_obj)

        if not company:
            comp_elem = soup.find(class_=re.compile(r"company-name|employer-name|job-company", re.I))
            if comp_elem:
                company = self._clean_text(comp_elem.get_text())

        if not company or company.lower() in ("confidential", "confidential company"):
            company = "Confidential Employer"

        # 3. Location
        location = "Myanmar"
        loc_obj = json_ld.get("jobLocation")
        if isinstance(loc_obj, dict):
            addr_obj = loc_obj.get("address")
            if isinstance(addr_obj, dict):
                loc_name = self._clean_text(addr_obj.get("addressLocality"))
                reg_name = self._clean_text(addr_obj.get("addressRegion"))
                if loc_name and reg_name and loc_name != reg_name:
                    location = f"{loc_name}, {reg_name}, Myanmar"
                elif loc_name:
                    location = f"{loc_name}, Myanmar"
                elif reg_name:
                    location = f"{reg_name}, Myanmar"

        if location == "Myanmar":
            loc_match = soup.find(class_=re.compile(r"location|city|job-location", re.I))
            if loc_match:
                parsed_loc = self._clean_text(loc_match.get_text())
                if parsed_loc:
                    location = f"{parsed_loc}, Myanmar"

        # 4. Dates
        posting_date = self._parse_date(json_ld.get("datePosted"))
        closing_date = self._parse_date(json_ld.get("validThrough"))

        # 5. Employment Type
        emp_type_code = "full_time"
        emp_val = json_ld.get("employmentType")
        if isinstance(emp_val, list) and emp_val:
            emp_val = emp_val[0]
        emp_str = str(emp_val or "").upper()
        if "FULL" in emp_str:
            emp_type_code = "full_time"
        elif "PART" in emp_str:
            emp_type_code = "part_time"
        elif "CONTRACT" in emp_str:
            emp_type_code = "contract"
        elif "INTERN" in emp_str:
            emp_type_code = "internship"

        # 6. Salary
        salary_disclosed = False
        salary_min: float | None = None
        salary_max: float | None = None
        currency_iso_code: str = "MMK"
        pay_period: str = "monthly"

        base_salary = json_ld.get("baseSalary")
        if isinstance(base_salary, dict):
            curr = base_salary.get("currency")
            if curr:
                currency_iso_code = curr.strip().upper()
            val_obj = base_salary.get("value")
            if isinstance(val_obj, dict):
                unit_text = str(val_obj.get("unitText") or "").upper()
                if "YEAR" in unit_text:
                    pay_period = "yearly"
                elif "HOUR" in unit_text:
                    pay_period = "hourly"
                elif "MONTH" in unit_text:
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
        raw_desc = json_ld.get("Description") or json_ld.get("description") or ""

        if raw_desc:
            desc_soup = BeautifulSoup(raw_desc, "html.parser")
            desc_text = desc_soup.get_text("\n", strip=True)
        else:
            desc_elem = soup.find(class_=re.compile(r"job-description|job-detail|description", re.I))
            if desc_elem:
                desc_text = desc_elem.get_text("\n", strip=True)
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
            if word.lower() in (
                "python",
                "java",
                "sql",
                "excel",
                "sales",
                "accounting",
                "marketing",
                "javascript",
                "english",
                "autocad",
                "management",
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

    def parse_jobs(self, raw_jobs: list[RawJobnetJob]) -> list[CleanedJob]:
        """Batch-parse raw JobNet job pages into CleanedJob instances."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                job = self.parse_job(raw)
                cleaned.append(job)
            except Exception as exc:
                logger.warning("Error parsing JobNet vacancy {}: {}", raw.job_id, exc)
        return cleaned
