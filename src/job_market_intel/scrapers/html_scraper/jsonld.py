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
import re

from bs4 import BeautifulSoup

#: ``"description": "<raw html>"`` up to the comma that starts the next key.
#: Non-greedy on purpose: the closing quote of an unescaped HTML attribute is
#: not followed by ``, "``, so the first such boundary is the real field end.
_DESCRIPTION_FIELD = re.compile(r'("description"\s*:\s*")(.*?)("\s*,\s*")', re.DOTALL)


def _repair_unescaped_description(content: str) -> str | None:
    """Re-escape a description string that contains raw quotes or newlines.

    emploi.ma publishes ``"description": "<p>...<b data-olk-copy-source="MessageBody">...``
    -- inline HTML whose attribute quotes are not escaped for JSON, which no
    amount of ``strict=False`` can accept. The rest of the block (company,
    location, dates) is well-formed, so dropping the whole record loses real
    fields. Escaping only the description keeps them. Returns ``None`` when the
    shape does not match, so the caller can fall back to the next block.
    """
    match = _DESCRIPTION_FIELD.search(content)
    if not match:
        return None
    raw = match.group(2)
    escaped = (
        raw.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return content[: match.start(2)] + escaped + content[match.end(2) :]


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
        payload = _parse_block(raw)
        if payload is None:
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


def _parse_block(raw: str) -> object | None:
    """Parse one ``ld+json`` block, tolerating the two observed defects."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Some boards (Chile's BNE) emit raw line breaks inside the
        # description string, which strict JSON rejects. Keep the record
        # instead of discarding the only structured copy of the ad.
        try:
            return json.loads(raw, strict=False)
        except json.JSONDecodeError:
            repaired = _repair_unescaped_description(raw)
            if repaired is None:
                return None
            try:
                return json.loads(repaired, strict=False)
            except json.JSONDecodeError:
                return None
