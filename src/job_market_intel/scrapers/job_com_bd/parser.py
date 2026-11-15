"""Parser and normalizer for Job.com.bd postings."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from job_market_intel.cleaning.common import CleanedJob
from .models import RawJobComBdJob


def _parse_deadline(deadline_str: str | None) -> datetime | None:
    """Parse dates like '17 November, 2026' or '17 Nov 2026'."""
    if not deadline_str:
        return None
    clean = deadline_str.replace(",", "").strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%B %d %Y"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            pass
    return None


def _parse_relative_posted(posted_str: str | None) -> datetime | None:
    """Parse strings like 'Posted 1 day ago', 'Posted 2 hours ago'."""
    if not posted_str:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    m_day = re.search(r"([0-9]+)\s+day", posted_str)
    if m_day:
        return now - timedelta(days=int(m_day.group(1)))
    m_hr = re.search(r"([0-9]+)\s+hour", posted_str)
    if m_hr:
        return now - timedelta(hours=int(m_hr.group(1)))
    m_min = re.search(r"([0-9]+)\s+min", posted_str)
    if m_min:
        return now - timedelta(minutes=int(m_min.group(1)))
    return now


class JobComBdParser:
    """Transforms RawJobComBdJob instances into CleanedJob records."""

    def parse_job(self, raw: RawJobComBdJob) -> CleanedJob | None:
        """Parse a single RawJobComBdJob into a validated CleanedJob."""
        soup = BeautifulSoup(raw.html_content, "html.parser")

        # Title
        title_el = soup.find("h1", class_="jd-title") or soup.find("h1")
        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            logger.debug("Dropping record without title: {}", raw.url)
            return None

        # Company
        comp_el = soup.find("div", class_="jd-company")
        company = comp_el.get_text(strip=True) if comp_el else None
        if not company:
            # Check page title fallback: "Job Title - Company Name"
            if soup.title and " - " in soup.title.string:
                company = soup.title.string.split(" - ", 1)[1].strip()
        company = company or "Undisclosed Organization"

        # Facts (overview)
        facts: dict[str, str] = {}
        for fact_el in soup.find_all("div", class_="jd-fact"):
            lbl_el = fact_el.find("div", class_="jd-fact-label")
            val_el = fact_el.find("div", class_="jd-fact-value")
            if lbl_el and val_el:
                lbl = lbl_el.get_text(strip=True)
                val = val_el.get_text(strip=True)
                facts[lbl] = val

        # Location
        raw_loc = facts.get("Job Location")
        if raw_loc:
            location = f"{raw_loc}, Bangladesh" if "bangladesh" not in raw_loc.lower() else raw_loc
        else:
            location = "Bangladesh"

        # Employment type
        emp_raw = (facts.get("Employment Type") or "").lower()
        if "part time" in emp_raw or "part-time" in emp_raw:
            emp_type_code = "part_time"
        elif "contract" in emp_raw or "temporary" in emp_raw:
            emp_type_code = "contract"
        elif "intern" in emp_raw:
            emp_type_code = "internship"
        else:
            emp_type_code = "full_time"

        # Dates
        deadline_str = facts.get("Application Deadline")
        closing_date = _parse_deadline(deadline_str)

        posted_el = soup.find("div", class_="jd-posted")
        posted_str = posted_el.get_text(" ", strip=True) if posted_el else None
        posting_date = _parse_relative_posted(posted_str)

        # Skills
        skills: list[str] = []
        skills_el = soup.find("div", class_="jd-skills")
        if skills_el:
            skills = [s.get_text(strip=True) for s in skills_el.find_all(["span", "a"]) if s.get_text(strip=True)]

        # Salary parsing
        sal_raw = facts.get("Salary", "")
        sal_min = None
        sal_max = None
        sal_disclosed = False
        pay_period = "monthly"

        # Look for numbers like 25,000 - 35,000 or 50000
        sal_m = re.search(r"([0-9]{2,3}(?:,[0-9]{3})+)\s*(?:-|to)\s*([0-9]{2,3}(?:,[0-9]{3})+)", sal_raw)
        if sal_m:
            try:
                min_f = float(sal_m.group(1).replace(",", ""))
                max_f = float(sal_m.group(2).replace(",", ""))
                if min_f > 1000 and max_f > 1000:
                    sal_min = min_f
                    sal_max = max_f
                    sal_disclosed = True
            except (ValueError, TypeError):
                pass
        else:
            single_m = re.search(r"([0-9]{2,3}(?:,[0-9]{3})+)", sal_raw)
            if single_m:
                try:
                    val = float(single_m.group(1).replace(",", ""))
                    if val > 1000:
                        sal_min = val
                        sal_max = val
                        sal_disclosed = True
                except (ValueError, TypeError):
                    pass

        # Full description text
        main_el = soup.find("div", class_="jd-main") or soup.find("div", class_="jd-layout")
        if main_el:
            # remove scripts, styles, buttons
            for bad in main_el.find_all(["script", "style", "button", "nav", "form"]):
                bad.decompose()
            desc_text = main_el.get_text("\n", strip=True)
        else:
            desc_text = soup.get_text("\n", strip=True)

        desc_text = re.sub(r"\n{3,}", "\n\n", desc_text).strip()
        words = len(desc_text.split())

        payload = {
            "url": raw.url,
            "job_id": raw.job_id,
            "title": title,
            "company": company,
            "location": location,
            "facts": facts,
            "skills": skills,
            "posted_str": posted_str,
            "deadline_str": deadline_str,
        }

        return CleanedJob(
            source_job_id=raw.job_id,
            job_title=title,
            company_name=company,
            company_logo_url=None,
            skills=skills,
            location_cleaned=location,
            salary_min=sal_min,
            salary_max=sal_max,
            salary_disclosed=sal_disclosed,
            description_clean=desc_text,
            word_count=words,
            apply_url=raw.url,
            original_url=raw.url,
            posting_date=posting_date,
            closing_date=closing_date,
            data_quality_score=0.95 if words > 50 else 0.7,
            raw_payload=payload,
            currency_iso_code="BDT",
            pay_period=pay_period,
            employment_type_code=emp_type_code,
        )

    def parse_jobs(self, raw_jobs: list[RawJobComBdJob]) -> list[CleanedJob]:
        """Parse all raw jobs into CleanedJob records."""
        cleaned: list[CleanedJob] = []
        for r in raw_jobs:
            item = self.parse_job(r)
            if item is not None:
                cleaned.append(item)
        return cleaned
