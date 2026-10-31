"""schema.org ``JobPosting`` extraction shared by the scraper clients.

Boards such as Qatar Living render the visible page as unlabelled layout divs
but publish the same record in a ``<script type="application/ld+json">`` block;
Slovakia's HelloWorld prints the ad body as normal markup *and* a summary
``JobPosting`` whose ``datePosted``/``hiringOrganization`` fill fields the
markup does not name. The browser client maps the block wholesale through
``detail_json_map``; the HTTP parser only fills the gaps the CSS selectors left
(see ``SiteConfig.detail_json_ld_fill``), so both live here.
"""

from __future__ import annotations

import json

from bs4 import BeautifulSoup


def json_ld_job_posting(html: str) -> dict | None:
    """Return the schema.org ``JobPosting`` block embedded in a detail page.

    The block can be a dict, a list of dicts, or a ``@graph`` container, so all
    three shapes are accepted.
    """
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Some boards (Chile's BNE) emit raw line breaks inside the
            # description string, which strict JSON rejects. Keep the record
            # instead of discarding the only structured copy of the ad.
            try:
                payload = json.loads(raw, strict=False)
            except json.JSONDecodeError:
                continue

        candidates: list = []
        if isinstance(payload, dict):
            candidates = payload.get("@graph") or [payload]
        elif isinstance(payload, list):
            candidates = payload
        for item in candidates:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None
