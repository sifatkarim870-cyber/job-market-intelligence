"""Unit tests for normalization.salary_standardization.normalize_annual_salary.

See salary_standardization.py's module docstring for why this is a pure
function (no DB fixture needed) rather than a batch job -- these tests
only need to cover the annualization math and the two honest "can't
convert this" exit paths (unrecognized pay_period, unknown currency).
"""

from __future__ import annotations

from job_market_intel.normalization.salary_standardization import normalize_annual_salary


class TestPayPeriodAnnualization:
    def test_yearly_is_unchanged(self) -> None:
        lo, hi = normalize_annual_salary(
            100000, 150000, currency_iso_code="USD", pay_period="yearly"
        )
        assert lo == 100000.0
        assert hi == 150000.0

    def test_monthly_is_multiplied_by_twelve(self) -> None:
        lo, hi = normalize_annual_salary(5000, 7000, currency_iso_code="USD", pay_period="monthly")
        assert lo == 60000.0
        assert hi == 84000.0

    def test_weekly_is_multiplied_by_fifty_two(self) -> None:
        lo, hi = normalize_annual_salary(1000, 1500, currency_iso_code="USD", pay_period="weekly")
        assert lo == 52000.0
        assert hi == 78000.0

    def test_daily_is_multiplied_by_two_hundred_sixty(self) -> None:
        lo, hi = normalize_annual_salary(200, 300, currency_iso_code="USD", pay_period="daily")
        assert lo == 52000.0
        assert hi == 78000.0

    def test_hourly_is_multiplied_by_two_thousand_eighty(self) -> None:
        lo, hi = normalize_annual_salary(50, 75, currency_iso_code="USD", pay_period="hourly")
        assert lo == 104000.0
        assert hi == 156000.0

    def test_unrecognized_pay_period_returns_none_none(self) -> None:
        lo, hi = normalize_annual_salary(
            100000, 150000, currency_iso_code="USD", pay_period="fortnightly"
        )
        assert lo is None
        assert hi is None


class TestCurrencyConversion:
    def test_usd_passes_through(self) -> None:
        lo, hi = normalize_annual_salary(
            100000, 150000, currency_iso_code="USD", pay_period="yearly"
        )
        assert lo == 100000.0
        assert hi == 150000.0

    def test_usd_is_case_insensitive(self) -> None:
        lo, hi = normalize_annual_salary(
            100000, 150000, currency_iso_code="usd", pay_period="yearly"
        )
        assert lo == 100000.0
        assert hi == 150000.0

    def test_unknown_currency_returns_none_none_not_a_guess(self) -> None:
        # No entry in salary.currency_exchange_rates for EUR today -- see
        # module docstring for why this deliberately returns (None, None)
        # rather than assuming a rate.
        lo, hi = normalize_annual_salary(
            100000, 150000, currency_iso_code="EUR", pay_period="yearly"
        )
        assert lo is None
        assert hi is None


class TestNullHandling:
    def test_both_none_stays_none(self) -> None:
        lo, hi = normalize_annual_salary(None, None, currency_iso_code="USD", pay_period="yearly")
        assert lo is None
        assert hi is None

    def test_only_min_disclosed(self) -> None:
        lo, hi = normalize_annual_salary(100000, None, currency_iso_code="USD", pay_period="yearly")
        assert lo == 100000.0
        assert hi is None

    def test_only_max_disclosed(self) -> None:
        lo, hi = normalize_annual_salary(None, 150000, currency_iso_code="USD", pay_period="yearly")
        assert lo is None
        assert hi == 150000.0
