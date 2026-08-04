"""Generic text-cleaning primitives.

Why this module is source-agnostic (unlike ``scrapers/``, which stays
strictly per-source until a second source exists — see that package's
docstrings for the reasoning): the problems solved here — garbled
character encodings, undecoded HTML entities, raw HTML tags, inconsistent
whitespace — are not RemoteOK-specific. Every future source scraped from
the open web (We Work Remotely, Remotive, Indeed, company career pages)
will produce the same categories of mess, for the same underlying reasons
(text passed through multiple systems, some of which guess encodings
wrong, or delivered as HTML fragments meant for a browser to render).
Building this once, generically, now, is not premature — it is fixing a
problem whose *shape* is already fully known, unlike a `BaseScraper`
abstraction, whose shape would have to be guessed from a single example.

Two categories of cleaning are provided:
    - ``clean_plain_text``: for fields that are NOT HTML (titles, company
      names, location strings, tags) but may still contain undecoded HTML
      entities (e.g. "Chubb Fire &amp; Security") and/or mojibake.
    - ``clean_html_text``: for fields that ARE HTML fragments (RemoteOK's
      job descriptions), which additionally need tags stripped.

Both are deliberately lossy in a controlled way: they produce clean,
readable text for storage in ``core.job_descriptions.description_clean``
and similar columns. The *original*, unmodified text is never discarded —
callers are expected to retain ``raw_payload`` alongside the cleaned
output, per the project's "never discard original source data" principle.
"""

from __future__ import annotations

import html
import re

import ftfy
from bs4 import BeautifulSoup

#: Matches any run of whitespace (spaces, tabs, newlines) of length >= 1.
_WHITESPACE_RUN = re.compile(r"\s+")


def _collapse_whitespace(text: str) -> str:
    """Collapse any run of whitespace (including newlines) into a single space, then trim ends."""
    return _WHITESPACE_RUN.sub(" ", text).strip()


def clean_plain_text(text: str | None) -> str | None:
    """Clean a non-HTML text field: fix mojibake, decode HTML entities, normalize whitespace.

    Use this for fields that are plain text but may still contain
    undecoded HTML entities (RemoteOK sends ``"Chubb Fire &amp; Security"``
    as a literal string, not inside an HTML tag) and/or character-encoding
    corruption (mojibake), such as job titles, company names, tags, and
    raw location strings.

    Args:
        text: The raw text to clean. ``None`` and the empty string are
            passed through unchanged (there is nothing to clean).

    Returns:
        The cleaned text, or ``None``/``""`` if that's what was given.

    Processing order (each step depends on the previous one having run):
        1. ``html.unescape`` — decode HTML entities (``&amp;`` -> ``&``,
           ``&#39;`` -> ``'``, etc.) using Python's standard library.
        2. ``ftfy.fix_text`` — repair mojibake (e.g. ``"Ã©"`` -> ``"é"``),
           with its own entity-unescaping disabled since step 1 already
           handled that.
        3. Collapse whitespace and trim.
    """
    if text is None or text == "":
        return text

    decoded = html.unescape(text)
    fixed = ftfy.fix_text(decoded, unescape_html=False)
    return _collapse_whitespace(fixed)


def clean_html_text(html_text: str | None) -> str | None:
    """Clean an HTML fragment into plain, readable text.

    Use this for fields that are HTML markup (RemoteOK's job descriptions
    are HTML, e.g. ``"<p>We are hiring...</p>"``), not plain text.

    Args:
        html_text: The raw HTML fragment to clean. ``None`` and the empty
            string are passed through unchanged.

    Returns:
        Plain text with all HTML tags removed, entities decoded, mojibake
        repaired, and whitespace normalized. ``None``/``""`` pass through
        unchanged.

    Processing order:
        1. Parse as HTML and extract text content (``BeautifulSoup`` with
           Python's built-in ``html.parser`` — no extra parser dependency
           needed). This also decodes HTML entities as a side effect of
           parsing, so no separate ``html.unescape`` step is needed here.
        2. ``ftfy.fix_text`` — repair any mojibake in the extracted text.
        3. Collapse whitespace and trim. Block-level tags (``<p>``,
           ``<br>``, ``<li>``, ...) are joined with a single space rather
           than concatenated with no separator, so ``"<p>A</p><p>B</p>"``
           becomes ``"A B"`` rather than ``"AB"``.
    """
    if html_text is None or html_text == "":
        return html_text

    plain = BeautifulSoup(html_text, "html.parser").get_text(separator=" ")
    fixed = ftfy.fix_text(plain, unescape_html=False)
    return _collapse_whitespace(fixed)
