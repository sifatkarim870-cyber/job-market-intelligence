"""A thousands-grouped salary must not lose three orders of magnitude.

BNE (bne.gob.cl) prints Chilean wages as ``$610.001 - $760.000`` with dot as
the thousands separator. ``float("610.001")`` is 610.001, so the cleaner would
have stored a 610,001 CLP monthly wage as 610.001 CLP. ``_salary_from_text``
now collapses a token that is exactly ``\\d{1,3}(.\\d{3})+`` before converting,
while leaving genuine decimals (``850.50``) alone. US boards group with a
comma (``$78,000.00``), which ``float`` also rejects, so comma grouping is
collapsed while keeping a real decimal tail.

Run with:  uv run pytest tests/unit/test_html_scraper_salary_thousands.py -q
"""

from __future__ import annotations

from job_market_intel.scrapers.html_scraper.parser import _salary_from_text

CLP_PATTERN = r"\$\s*(?P<min>[\d.]+)\s*-\s*\$?\s*(?P<max>[\d.]+)"


def test_dot_thousands_separator_is_collapsed() -> None:
    facts = _salary_from_text(CLP_PATTERN, "$610.001 - $760.000")

    assert facts["salary_min"] == 610001
    assert facts["salary_max"] == 760000


def test_leading_space_and_single_dollar_are_tolerated() -> None:
    facts = _salary_from_text(CLP_PATTERN, " $1.210.001 - $1.360.000")

    assert facts["salary_min"] == 1210001
    assert facts["salary_max"] == 1360000


def test_plain_integers_still_parse() -> None:
    facts = _salary_from_text(r"(?P<min>\d+)\s*-\s*(?P<max>\d+)", "900 - 1200")

    assert facts["salary_min"] == 900
    assert facts["salary_max"] == 1200


def test_a_real_decimal_is_not_treated_as_thousands() -> None:
    facts = _salary_from_text(r"(?P<min>[\d.]+)", "850.50")

    assert facts["salary_min"] == 850.5


COMMA_PATTERN = r"\$\s*(?P<min>[\d,.]+)(?:\s*-\s*\$?\s*(?P<max>[\d,.]+))?"


def test_comma_thousands_separator_is_collapsed() -> None:
    facts = _salary_from_text(COMMA_PATTERN, "$78,000.00")

    assert facts["salary_min"] == 78000
    assert facts["salary_max"] == 78000


def test_comma_thousands_keeps_the_decimal_tail() -> None:
    facts = _salary_from_text(COMMA_PATTERN, "$78,000.50 - $90,000.00")

    assert facts["salary_min"] == 78000.5
    assert facts["salary_max"] == 90000


def test_a_small_decimal_comma_is_not_treated_as_thousands() -> None:
    # "1,5" is a decimal comma in many locales, not a grouped integer.
    assert _salary_from_text(r"(?P<min>[\d,]+)", "1,5") == {}
