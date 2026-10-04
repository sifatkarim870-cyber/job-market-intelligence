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
    # Round 2: currencies needed for the audit-driven non-tech/global
    # sources (Africa, MENA, South/SE Asia) added to ref.sources over time.
    {"iso_code": "MUR", "currency_name": "Mauritian Rupee", "symbol": "₨"},
    {"iso_code": "MAD", "currency_name": "Moroccan Dirham", "symbol": "د.م."},
    {"iso_code": "TND", "currency_name": "Tunisian Dinar", "symbol": "د.ت"},
    {"iso_code": "GHS", "currency_name": "Ghanaian Cedi", "symbol": "₵"},
    {"iso_code": "UGX", "currency_name": "Ugandan Shilling", "symbol": "USh"},
    {"iso_code": "TZS", "currency_name": "Tanzanian Shilling", "symbol": "TSh"},
    {"iso_code": "ETB", "currency_name": "Ethiopian Birr", "symbol": "Br"},
    {"iso_code": "RWF", "currency_name": "Rwandan Franc", "symbol": "RF"},
    {"iso_code": "XOF", "currency_name": "West African CFA Franc", "symbol": "CFA"},
    {"iso_code": "XAF", "currency_name": "Central African CFA Franc", "symbol": "FCFA"},
    {"iso_code": "AOA", "currency_name": "Angolan Kwanza", "symbol": "Kz"},
    {"iso_code": "ZMW", "currency_name": "Zambian Kwacha", "symbol": "ZK"},
    {"iso_code": "MZN", "currency_name": "Mozambican Metical", "symbol": "MT"},
    {"iso_code": "BWP", "currency_name": "Botswana Pula", "symbol": "P"},
    {"iso_code": "MGA", "currency_name": "Malagasy Ariary", "symbol": "Ar"},
    {"iso_code": "TWD", "currency_name": "New Taiwan Dollar", "symbol": "NT$"},
    {"iso_code": "JOD", "currency_name": "Jordanian Dinar", "symbol": "د.ا"},
    {"iso_code": "KWD", "currency_name": "Kuwaiti Dinar", "symbol": "د.ك"},
    {"iso_code": "BHD", "currency_name": "Bahraini Dinar", "symbol": ".د.ب"},
    {"iso_code": "QAR", "currency_name": "Qatari Riyal", "symbol": "ر.ق"},
    {"iso_code": "OMR", "currency_name": "Omani Rial", "symbol": "ر.ع."},
    {"iso_code": "LBP", "currency_name": "Lebanese Pound", "symbol": "£"},
]


def seed_currencies(conn: Connection) -> SeedResult:
    return upsert_many(
        conn,
        schema="ref",
        table_name="currencies",
        rows=CURRENCIES,
        conflict_cols=("iso_code",),
    )
