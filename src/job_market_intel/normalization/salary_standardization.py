"""Salary/currency normalization (Step 27).

Where this fits: the design doc's own words on ``salary.job_salaries`` --
"``normalized_annual_min_usd``/``normalized_annual_max_usd``: computed --
converted + annualized, for cross-job comparison." Confirmed against the
real codebase before writing a line of this (same discipline Step 25/26
started with): unlike company resolution and skill extraction,
``db.job_repository.save_cleaned_job`` was *already* writing
``salary_min``/``salary_max``/``salary_disclosed``/``currency_id`` (hard-
coded to USD)/``pay_period`` (hard-coded to the literal ``'yearly'``) into
``salary.job_salaries`` on both insert and update. What was actually
missing, confirmed by reading that function directly rather than assuming
either way:

    - ``normalized_annual_min_usd``/``max_usd`` were never computed --
      always left NULL.
    - ``salary.salary_history`` was never written to at all, on insert or
      update -- a re-scrape that changed a job's salary silently
      overwrote the only record of the previous value, with no audit
      trail. This cuts against the design doc's own stated principle
      ("immutable history everywhere it matters ... is what makes any
      time-series or causal claim ... reproducible") for exactly this
      table.

What this module deliberately is NOT:

    - NOT a batch job. Unlike ``dedup.py``/``company_resolution.py``/
      ``skill_extraction.py``, every input this module needs
      (``salary_min``, ``salary_max``, currency, pay period) is already
      fully available on a ``CleanedJob`` at ingestion time -- there is
      nothing to look up in already-persisted rows the way fuzzy company
      matching or skill-vocabulary scanning needs a second pass. This
      module is a pure function, called inline from
      ``db.job_repository.save_cleaned_job``, the same way
      ``get_or_create_company`` is.
    - NOT currency conversion in the general sense. The three original
      feed sources (RemoteOK, We Work Remotely, Remotive) are USD-only by
      construction of their own raw models -- RemoteOK's feed has no
      currency field at all (implicitly USD), Remotive's free-text salary
      parser (``RawRemotiveJob._parse_salary_range``) only matches a
      ``"$..."``-prefixed pattern, and WWR has no salary field of any
      kind. The conversion table was USD-only while that was true, and
      grew only when real non-USD sources arrived to use it: GBP (Reed,
      2026-10), DZD (Emploitic, 2026-10), MUR (MyJob.mu, 2026-10) --
      dated mid-market reference rates in ``_USD_CONVERSION_RATES``.
      Any currency still without an entry returns ``(None, None)`` with
      a logged warning -- correct and honest: it will not silently
      mis-convert, it visibly does nothing until a rate exists.

Pay-period annualization
-------------------------
None of the three original feed sources captures pay period explicitly
(when this module was written: no ``pay_period`` field existed on
``CleanedJob`` or on any raw model), so ``job_repository`` defaulted those
sources' ``salary.job_salaries.pay_period`` to ``'yearly'`` on the
assumption that all three report full-time-equivalent annual figures.
That assumption is reasonable for these three sources specifically
(RemoteOK's own docs describe its salary fields as annual; Remotive's
free-text parser only matches whole-dollar range strings typical of
annual tech-salary postings; WWR has no salary at all) but it is an
assumption, not a fact this module can verify.

Sources that know their own cadence populate ``CleanedJob.pay_period``
for real (MyJob.mu: monthly MUR ranges; Reed: ``salaryType``), and
``job_repository`` passes that value straight through -- the earlier
``_ASSUMED_PAY_PERIOD`` literal no longer exists (see job_repository.py's
module docstring).

This module's annualization table covers every ``pay_period`` value the
schema's own CHECK constraint allows (``hourly``, ``daily``, ``weekly``,
``monthly``, ``yearly``) using standard full-time-equivalent multipliers,
so the day a source that reports a different pay period arrives, only
that source's cleaner needs to start populating a real pay-period value --
this function already handles it correctly.
"""

from __future__ import annotations

from loguru import logger

#: Full-time-equivalent multipliers to annualize a salary figure, keyed by
#: every ``pay_period`` value the schema's CHECK constraint
#: (``ck_job_salaries_pay_period`` / ``ck_salary_history_pay_period``)
#: allows. Standard FTE assumptions: 2,080 hours/year (40hr week x 52),
#: 260 working days/year (5-day week x 52), 52 weeks/year, 12 months/year.
_ANNUALIZATION_MULTIPLIERS: dict[str, float] = {
    "hourly": 2080.0,
    "daily": 260.0,
    "weekly": 52.0,
    "monthly": 12.0,
    "yearly": 1.0,
}

#: Currency conversion rates to USD, as of 2026-10-02 mid-market close
#: (exchangerates.org.uk / tradingeconomics daily reference rates).
#: USD was the only entry until the audit-driven non-USD sources arrived
#: (GBP for Reed, DZD for Emploitic, MUR for MyJob.mu, CNY for 51job) —
#: each addition is a rate this codebase now actually uses, not a
#: speculative table.
#: These are static reference rates for cross-job comparability, not
#: live FX: re-check and update when a materially different rate regime
#: matters to an analysis. Currencies with no entry here still return
#: (None, None) with a logged warning rather than a guessed conversion.
_USD_CONVERSION_RATES: dict[str, float] = {
    "USD": 1.0,
    "GBP": 1.3240,  # 1 GBP = 1.3240 USD (02 Oct 2026)
    "DZD": 0.007462,  # 1 USD = 134.02 DZD (02 Oct 2026)
    "MUR": 0.02077,  # 1 MUR = 0.02077 USD (02 Oct 2026; 1 USD = 48.15 MUR)
    "CNY": 0.1492,  # 1 CNY = 0.1492 USD (02 Oct 2026; 1 USD = 6.7046 CNY)
}


def normalize_annual_salary(
    salary_min: int | float | None,
    salary_max: int | float | None,
    *,
    currency_iso_code: str,
    pay_period: str,
) -> tuple[float | None, float | None]:
    """Convert a raw (min, max) salary pair into annualized USD figures.

    Maps onto ``salary.job_salaries.normalized_annual_min_usd``/
    ``normalized_annual_max_usd`` in the schema.

    Args:
        salary_min: Raw minimum salary bound, in ``currency_iso_code``, at
            ``pay_period`` cadence. ``None`` if undisclosed.
        salary_max: Raw maximum salary bound. Same units/cadence as
            ``salary_min``. ``None`` if undisclosed.
        currency_iso_code: ISO 4217 code (e.g. ``"USD"``) the raw figures
            are denominated in.
        pay_period: One of ``"hourly"``, ``"daily"``, ``"weekly"``,
            ``"monthly"``, ``"yearly"`` -- must match the schema's
            ``pay_period`` CHECK constraint values.

    Returns:
        ``(normalized_annual_min_usd, normalized_annual_max_usd)``. Either
        or both may be ``None`` if the corresponding input was ``None``,
        if ``currency_iso_code`` has no known conversion rate (logged as a
        warning, not an error -- an unconvertible salary is an honest gap,
        not a failure), or if ``pay_period`` is not a recognized value
        (logged as an error -- this indicates a caller bug, since every
        caller in this codebase controls its own ``pay_period`` value).
    """
    multiplier = _ANNUALIZATION_MULTIPLIERS.get(pay_period)
    if multiplier is None:
        logger.error(
            "normalize_annual_salary: unrecognized pay_period {!r}; "
            "expected one of {}. Returning (None, None).",
            pay_period,
            sorted(_ANNUALIZATION_MULTIPLIERS),
        )
        return None, None

    # Nothing to annualize: with no salary bounds the conversion rate is
    # irrelevant, so return before the rate lookup. Otherwise every
    # no-salary job whose currency has no rate yet logs a misleading
    # "no USD conversion rate" warning per row — observed on Job.am's
    # first real run (2026-10-05): 94 warnings, one per job, for a
    # source whose payloads carry no salary at all. A *real* salary in
    # an unrated currency still falls through to the warning below.
    if salary_min is None and salary_max is None:
        return None, None

    rate_to_usd = _USD_CONVERSION_RATES.get(currency_iso_code.upper())
    if rate_to_usd is None:
        logger.warning(
            "normalize_annual_salary: no USD conversion rate available for "
            "currency {!r} (not yet in _USD_CONVERSION_RATES -- see module "
            "docstring). Returning (None, None) rather than guessing.",
            currency_iso_code,
        )
        return None, None

    def _normalize(value: int | float | None) -> float | None:
        if value is None:
            return None
        return round(float(value) * multiplier * rate_to_usd, 2)

    return _normalize(salary_min), _normalize(salary_max)
