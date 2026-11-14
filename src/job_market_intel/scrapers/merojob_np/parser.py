"""Parser and normalizer for Merojob (Nepal) jobs."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from loguru import logger

from job_market_intel.cleaning.common import CleanedJob

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str | None) -> str | None:
    """Strip HTML tags and unescape HTML entities."""
    if not text:
        return None
    unescaped = html.unescape(text)
    clean = _TAG_RE.sub(" ", unescaped)
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip() or None


def _parse_iso_date(dt_str: str | None) -> datetime | None:
    """Parse ISO date/datetime string."""
    if not dt_str:
        return None
    clean = dt_str.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except Exception:
        return None


class MerojobParser:
    """Transforms raw Merojob API objects into validated CleanedJob instances."""

    def parse_job(
        self,
        listing: dict[str, Any],
        detail: dict[str, Any] | None = None,
    ) -> CleanedJob | None:
        """Parse combined listing and detail into a CleanedJob record."""
        combined = {**listing, **(detail or {})}
        job_id = combined.get("id")
        title = (combined.get("title") or "").strip()
        if not job_id or not title:
            logger.debug("Dropping Merojob record missing id or title: {}", combined)
            return None

        client = combined.get("client") or {}
        company = (
            client.get("client_name")
            or client.get("org_name")
            or "Confidential / Undisclosed"
        ).strip()

        # Logo URL
        logo_url = None
        client_img = client.get("client_image")
        logo_obj = combined.get("logo") or {}
        raw_logo = client_img or logo_obj.get("url")
        if raw_logo:
            if raw_logo.startswith("http"):
                logo_url = raw_logo
            else:
                logo_url = f"https://api.merojob.com{raw_logo}"

        # Location
        locations = combined.get("job_locations") or []
        loc_str = "Nepal"
        if locations:
            loc_parts = []
            loc_first = locations[0]
            if isinstance(loc_first, dict):
                addr = (loc_first.get("address") or loc_first.get("name") or "").strip()
                if addr:
                    loc_parts.append(addr)
            if loc_parts:
                loc_clean = ", ".join(loc_parts)
                if "nepal" not in loc_clean.lower():
                    loc_str = f"{loc_clean}, Nepal"
                else:
                    loc_str = loc_clean

        # Description & Specification
        desc_raw = combined.get("description") or ""
        spec_raw = combined.get("specification") or ""
        extra_raw = combined.get("extra_description") or ""

        desc_text = _strip_html(desc_raw) or ""
        spec_text = _strip_html(spec_raw) or ""
        extra_text = _strip_html(extra_raw) or ""

        body_parts = [title, f"Company: {company}"]
        if desc_text:
            body_parts.append(desc_text)
        if spec_text:
            body_parts.append(f"Requirements & Specifications:\n{spec_text}")
        if extra_text:
            body_parts.append(extra_text)

        skills = combined.get("skills") or []
        if skills:
            body_parts.append(f"Skills: {', '.join(skills)}")

        full_desc = "\n\n".join(body_parts).strip()
        words = len(full_desc.split())

        # Salary
        sal_min = None
        sal_max = None
        sal_disclosed = False
        currency_code = "NPR"
        pay_period = "monthly"

        offered = combined.get("offered_salary")
        if isinstance(offered, dict):
            min_val = offered.get("minimum")
            max_val = offered.get("maximum")
            if min_val is not None:
                try:
                    sal_min = float(min_val)
                except (ValueError, TypeError):
                    sal_min = None
            if max_val is not None:
                try:
                    sal_max = float(max_val)
                except (ValueError, TypeError):
                    sal_max = None

            if sal_min or sal_max:
                sal_disclosed = True
                unit = (offered.get("unit") or "").lower()
                if "year" in unit or "annual" in unit:
                    pay_period = "yearly"
                elif "month" in unit:
                    pay_period = "monthly"
                elif "hour" in unit:
                    pay_period = "hourly"
                elif "week" in unit:
                    pay_period = "weekly"

        # URLs
        slug = (combined.get("slug") or "").strip()
        abs_url = (combined.get("absolute_url") or "").strip()
        if abs_url.startswith("/"):
            original_url = f"https://merojob.com{abs_url}"
        elif slug:
            original_url = f"https://merojob.com/{slug}/"
        else:
            original_url = f"https://merojob.com/jobs/{job_id}/"

        # Employment type
        available = combined.get("available_for") or []
        emp_type = "full_time"
        if available:
            first_avail = str(available[0]).lower()
            if "part" in first_avail:
                emp_type = "part_time"
            elif "contract" in first_avail:
                emp_type = "contract"
            elif "intern" in first_avail:
                emp_type = "internship"

        # Dates
        posted_at = _parse_iso_date(combined.get("posted_at") or combined.get("posted_date"))
        closing_date = _parse_iso_date(combined.get("deadline"))

        return CleanedJob(
            source_job_id=str(job_id),
            job_title=title,
            company_name=company,
            company_logo_url=logo_url,
            skills=list(skills),
            location_cleaned=loc_str,
            salary_min=sal_min,
            salary_max=sal_max,
            salary_disclosed=sal_disclosed,
            description_clean=full_desc,
            word_count=words,
            apply_url=original_url,
            original_url=original_url,
            posting_date=posted_at,
            closing_date=closing_date,
            data_quality_score=0.9 if words > 50 else 0.7,
            raw_payload=combined,
            currency_iso_code=currency_code,
            pay_period=pay_period,
            employment_type_code=emp_type,
        )

    def parse_jobs(
        self,
        listings: list[dict[str, Any]],
        details_map: dict[int, dict[str, Any]] | None = None,
    ) -> list[CleanedJob]:
        """Parse all job listings, merging with detail dicts if available."""
        details_map = details_map or {}
        results: list[CleanedJob] = []
        for item in listings:
            jid = item.get("id")
            detail = details_map.get(jid) if jid is not None else None
            cleaned = self.parse_job(item, detail)
            if cleaned is not None:
                results.append(cleaned)
        return results
