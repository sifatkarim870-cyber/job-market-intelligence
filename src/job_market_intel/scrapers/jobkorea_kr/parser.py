"""HTML and JSON-LD parser for Jobkorea postings."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.cleaning.common import CleanedJob

from .models import RawJobkoreaJob

_CLEAN_WS_RE = re.compile(r"\s+")


class JobkoreaParser:
    """Parser that extracts structured job attributes and multi-section text from Jobkorea pages."""

    @staticmethod
    def _clean_text(val: str | None) -> str:
        if not val:
            return ""
        return _CLEAN_WS_RE.sub(" ", val).strip()

    def parse_job(self, raw: RawJobkoreaJob) -> CleanedJob | None:
        """Parse a RawJobkoreaJob into CleanedJob, extracting JSON-LD and HTML text."""
        soup = BeautifulSoup(raw.html_content, "html.parser")

        # 1. Extract Schema.org JobPosting JSON-LD
        json_ld: dict[str, Any] = {}
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get("@type") == "JobPosting":
                    json_ld = data
                    break
            except Exception:
                continue

        # 2. Title & Company
        title = self._clean_text(json_ld.get("title"))
        if not title:
            # Fallback to page title or heading
            h1 = soup.find("h1") or soup.find("h2") or soup.find("title")
            if h1:
                title = self._clean_text(h1.get_text())

        if not title:
            logger.warning("Jobkorea posting %s has no title; skipping", raw.job_id)
            return None

        company = ""
        hiring_org = json_ld.get("hiringOrganization")
        if isinstance(hiring_org, dict):
            company = self._clean_text(hiring_org.get("name"))
        if not company:
            comp_elem = soup.find("a", class_=re.compile(r"comp|company", re.I))
            if comp_elem:
                company = self._clean_text(comp_elem.get_text())

        if not company:
            company = "JobKorea Employer"

        # 3. Location
        location = ""
        job_loc = json_ld.get("jobLocation")
        if isinstance(job_loc, dict):
            addr = job_loc.get("address")
            if isinstance(addr, dict):
                location = self._clean_text(addr.get("streetAddress"))
        if not location:
            # Look for location text in body
            loc_match = re.search(r"위치\s+([^<\n\r]+)", raw.html_content)
            if loc_match:
                location = self._clean_text(loc_match.group(1))

        if location and "South Korea" not in location and "대한민국" not in location:
            location = f"{location}, South Korea"
        elif not location:
            location = "South Korea"

        # 4. Dates
        posting_date: str | None = None
        raw_posted = json_ld.get("datePosted")
        if raw_posted:
            try:
                dt = datetime.fromisoformat(str(raw_posted).replace("Z", "+00:00"))
                posting_date = dt.strftime("%Y-%m-%d")
            except Exception:
                posting_date = str(raw_posted)[:10]

        closing_date: str | None = None
        raw_valid = json_ld.get("validThrough")
        if raw_valid:
            try:
                dt = datetime.fromisoformat(str(raw_valid).replace("Z", "+00:00"))
                closing_date = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                closing_date = str(raw_valid)[:19]

        # 5. Employment Type
        emp_type_code: str | None = None
        emp_val = json_ld.get("employmentType")
        if isinstance(emp_val, list) and emp_val:
            emp_val = emp_val[0]
        emp_str = str(emp_val or "").upper()
        if "FULL_TIME" in emp_str or "정규직" in raw.html_content:
            emp_type_code = "full_time"
        elif "PART_TIME" in emp_str or "아르바이트" in raw.html_content:
            emp_type_code = "part_time"
        elif "CONTRACTOR" in emp_str or "계약직" in raw.html_content:
            emp_type_code = "contract"
        elif "INTERN" in emp_str or "인턴" in raw.html_content:
            emp_type_code = "internship"

        # 6. Salary
        salary_disclosed = False
        salary_min: float | None = None
        salary_max: float | None = None
        currency_iso_code: str | None = None
        pay_period: str = "yearly"

        base_salary = json_ld.get("baseSalary")
        if isinstance(base_salary, dict):
            currency_iso_code = base_salary.get("currency") or "KRW"
            val_obj = base_salary.get("value")
            if isinstance(val_obj, dict):
                unit_text = str(val_obj.get("unitText") or "").upper()
                if "YEAR" in unit_text:
                    pay_period = "yearly"
                elif "MONTH" in unit_text:
                    pay_period = "monthly"
                elif "HOUR" in unit_text:
                    pay_period = "hourly"

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

        body_text_blocks: list[str] = []
        if summary_desc:
            body_text_blocks.append(summary_desc)

        content_elem = (
            soup.find("div", class_=re.compile(r"\[grid-area:content\]|artDetail", re.I))
            or soup.find("div", id="artDetail")
            or soup.body
        )
        if content_elem:
            text = self._clean_text(content_elem.get_text(" ", strip=True))
            if text and len(text) > len(summary_desc):
                sections["details"] = text
                body_text_blocks.append(text)

        desc_text = "\n\n".join(body_text_blocks).strip()
        if not desc_text:
            desc_text = title

        words = len(desc_text.split())

        # 8. Skills
        skills: list[str] = []
        skills_box = soup.find(class_=re.compile(r"skill|tag", re.I))
        if skills_box:
            for s_item in skills_box.find_all(["span", "a", "li"]):
                sk_txt = self._clean_text(s_item.get_text())
                if sk_txt and len(sk_txt) < 30 and sk_txt not in skills:
                    skills.append(sk_txt)

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
            currency_iso_code=currency_iso_code or "KRW",
            pay_period=pay_period,
            employment_type_code=emp_type_code,
        )

    def parse_jobs(self, raw_jobs: list[RawJobkoreaJob]) -> list[CleanedJob]:
        """Parse all raw jobs into CleanedJob records."""
        cleaned: list[CleanedJob] = []
        for r in raw_jobs:
            item = self.parse_job(r)
            if item is not None:
                cleaned.append(item)
        return cleaned
