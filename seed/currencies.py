"""
Seeds ref.currencies (ISO 4217).

Initial set: the ~40 currencies most relevant to global remote-work job
markets (covers every currency likely to appear across RemoteOK, Indeed,
LinkedIn, Glassdoor postings in year one). Extend this list — it's just
data — as new markets are onboarded; no code change required.
"""
from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, upsert_many

CURRENCIES: list[dict] = [
    {"iso_code": "USD", "currency_name": "United States Dollar", "symbol": "$"},
    {"iso_code": "EUR", "currency_name": "Euro", "symbol": "€"},
    {"iso_code": "GBP", "currency_name": "British Pound Sterling", "symbol": "£"},
    {"iso_code": "CAD", "currency_name": "Canadian Dollar", "symbol": "$"},
    {"iso_code": "AUD", "currency_name": "Australian Dollar", "symbol": "$"},
    {"iso_code": "NZD", "currency_name": "New Zealand Dollar", "symbol": "$"},
    {"iso_code": "CHF", "currency_name": "Swiss Franc", "symbol": "Fr"},
    {"iso_code": "JPY", "currency_name": "Japanese Yen", "symbol": "¥"},
    {"iso_code": "CNY", "currency_name": "Chinese Yuan Renminbi", "symbol": "¥"},
    {"iso_code": "INR", "currency_name": "Indian Rupee", "symbol": "₹"},
    {"iso_code": "SGD", "currency_name": "Singapore Dollar", "symbol": "$"},
    {"iso_code": "HKD", "currency_name": "Hong Kong Dollar", "symbol": "$"},
    {"iso_code": "AED", "currency_name": "UAE Dirham", "symbol": "د.إ"},
    {"iso_code": "SAR", "currency_name": "Saudi Riyal", "symbol": "﷼"},
    {"iso_code": "ILS", "currency_name": "Israeli New Shekel", "symbol": "₪"},
    {"iso_code": "SEK", "currency_name": "Swedish Krona", "symbol": "kr"},
    {"iso_code": "NOK", "currency_name": "Norwegian Krone", "symbol": "kr"},
    {"iso_code": "DKK", "currency_name": "Danish Krone", "symbol": "kr"},
    {"iso_code": "PLN", "currency_name": "Polish Zloty", "symbol": "zł"},
    {"iso_code": "CZK", "currency_name": "Czech Koruna", "symbol": "Kč"},
    {"iso_code": "HUF", "currency_name": "Hungarian Forint", "symbol": "Ft"},
    {"iso_code": "RON", "currency_name": "Romanian Leu", "symbol": "lei"},
    {"iso_code": "TRY", "currency_name": "Turkish Lira", "symbol": "₺"},
    {"iso_code": "ZAR", "currency_name": "South African Rand", "symbol": "R"},
    {"iso_code": "NGN", "currency_name": "Nigerian Naira", "symbol": "₦"},
    {"iso_code": "KES", "currency_name": "Kenyan Shilling", "symbol": "KSh"},
    {"iso_code": "EGP", "currency_name": "Egyptian Pound", "symbol": "£"},
    {"iso_code": "BRL", "currency_name": "Brazilian Real", "symbol": "R$"},
    {"iso_code": "MXN", "currency_name": "Mexican Peso", "symbol": "$"},
    {"iso_code": "ARS", "currency_name": "Argentine Peso", "symbol": "$"},
    {"iso_code": "CLP", "currency_name": "Chilean Peso", "symbol": "$"},
    {"iso_code": "COP", "currency_name": "Colombian Peso", "symbol": "$"},
    {"iso_code": "PHP", "currency_name": "Philippine Peso", "symbol": "₱"},
    {"iso_code": "IDR", "currency_name": "Indonesian Rupiah", "symbol": "Rp"},
    {"iso_code": "MYR", "currency_name": "Malaysian Ringgit", "symbol": "RM"},
    {"iso_code": "THB", "currency_name": "Thai Baht", "symbol": "฿"},
    {"iso_code": "VND", "currency_name": "Vietnamese Dong", "symbol": "₫"},
    {"iso_code": "KRW", "currency_name": "South Korean Won", "symbol": "₩"},
    {"iso_code": "PKR", "currency_name": "Pakistani Rupee", "symbol": "₨"},
    {"iso_code": "BDT", "currency_name": "Bangladeshi Taka", "symbol": "৳"},
    {"iso_code": "UAH", "currency_name": "Ukrainian Hryvnia", "symbol": "₴"},
    # Added for Emploitic (Algeria): listings carry no salary field, but
    # the cleaner asserts DZD as the home-market currency for CleanedJob's
    # required currency field, so the ref row must exist.
    {"iso_code": "DZD", "currency_name": "Algerian Dinar", "symbol": "دج"},
]


def seed_currencies(conn: Connection) -> SeedResult:
    return upsert_many(
        conn,
        schema="ref",
        table_name="currencies",
        rows=CURRENCIES,
        conflict_cols=("iso_code",),
    )
