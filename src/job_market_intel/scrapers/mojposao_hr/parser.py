"""Parser and normalizer for MojPosao (Croatia)."""

from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import datetime
from typing import Any

from job_market_intel.cleaning.common import CleanedJob
from .exceptions import MojPosaoHrParseError
from .models import RawMojPosaoHrJob

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text_or_html: str | None) -> str:
    """Remove HTML tags, decode HTML entities, and normalize whitespace."""
    if not text_or_html:
        return ""
    decoded = html_lib.unescape(text_or_html)
    clean = _TAG_RE.sub(" ", decoded)
    clean = re.sub(r"[ \t]+", " ", clean).strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean


def _parse_iso_date(dt_str: str | None) -> datetime | None:
    """Parse ISO date strings like '2026-11-13T14:18:09.000Z'."""
    if not dt_str:
        return None
    clean = dt_str.strip().replace("Z", "+00:00")
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(clean)
    except Exception:
        return None


class MojPosaoHrParser:
    """Parses RawMojPosaoHrJob models into CleanedJob records."""

    def parse_job(self, job: RawMojPosaoHrJob) -> CleanedJob | None:
        """Transform a single RawMojPosaoHrJob into CleanedJob."""
        data = job.data

        # Title
        title = ""
        if data and "title" in data:
            title = str(data["title"]).strip()
        if not title and job.raw_html:
            # Fallback to <title> or <h1>
            h1_m = re.search(r'<h1[^>]*>(.*?)</h1>', job.raw_html, re.DOTALL)
            if h1_m:
                title = _strip_html(h1_m.group(1))

        if not title:
            # Clean slug as title
            title = job.slug.replace("-", " ").title()

        # Company Name & Logo
        company_name = "MojPosao Poslodavac"
        logo_url = None
        if data:
            org = data.get("organization") or data.get("employer") or {}
            if isinstance(org, dict):
                company_name = (org.get("name") or "").strip() or company_name
                logo_url = org.get("logoUrl")

        # Location
        location_cleaned = "Croatia"
        if data:
            loc = data.get("location") or {}
            if isinstance(loc, dict):
                summary = loc.get("summary")
                if summary:
                    location_cleaned = f"{summary.strip()}, Croatia"

        # Description
        desc_parts: list[str] = [title, f"Poslodavac: {company_name}", f"Lokacija: {location_cleaned}"]
        if data:
            desc_text = _strip_html(data.get("description"))
            req_text = _strip_html(data.get("requirements"))
            ben_text = _strip_html(data.get("benefits"))
            if desc_text:
                desc_parts.append(f"Opis posla:\n{desc_text}")
            if req_text:
                desc_parts.append(f"Uvjeti:\n{req_text}")
            if ben_text:
                desc_parts.append(f"Što nudimo:\n{ben_text}")

            if not desc_text and not req_text and data.get("html"):
                html_body = _strip_html(data.get("html"))
                if html_body:
                    desc_parts.append(html_body)

        full_desc = "\n\n".join(desc_parts)
        words = len(full_desc.split())

        # Dates
        post_dt = None
        ends_dt = None
        if data:
            post_dt = _parse_iso_date(data.get("publishedAt") or data.get("startsAt"))
            ends_dt = _parse_iso_date(data.get("endsAt"))

        # Employment type
        emp_type = "full_time"
        if data:
            types_str = str(data.get("employmentTypes") or "").lower()
            if "honorarni" in types_str or "part" in types_str:
                emp_type = "part_time"
            elif "određeno" in types_str or "sezonski" in types_str or "studentski" in types_str:
                emp_type = "contract"

        return CleanedJob(
            source_job_id=job.uuid,
            job_title=title,
            company_name=company_name,
            company_logo_url=str(logo_url) if logo_url else None,
            skills=[],
            location_cleaned=location_cleaned,
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean=full_desc,
            word_count=words,
            apply_url=job.url,
            original_url=job.url,
            posting_date=post_dt,
            closing_date=ends_dt,
            data_quality_score=0.9 if words > 50 else 0.7,
            raw_payload=data or {"slug": job.slug, "uuid": job.uuid},
            currency_iso_code="EUR",
            pay_period="monthly",
            employment_type_code=emp_type,
            work_schedule=None,
        )

    def parse_jobs(self, raw_jobs: list[RawMojPosaoHrJob]) -> list[CleanedJob]:
        """Parse multiple RawMojPosaoHrJob models into CleanedJob list."""
        cleaned: list[CleanedJob] = []
        for raw in raw_jobs:
            try:
                job = self.parse_job(raw)
                if job:
                    cleaned.append(job)
            except Exception as exc:
                logger.warning("Failed to parse MojPosao job %s: %s", raw.uuid, exc)
        return cleaned
