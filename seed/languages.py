"""Seeds ref.languages (ISO 639-1). Initial set: ~35 most commonly required
languages on global job postings — extend as needed, it's pure data."""
from __future__ import annotations

from sqlalchemy import Connection

from .base import SeedResult, upsert_many

LANGUAGES = [
    ("en", "English"), ("es", "Spanish"), ("fr", "French"), ("de", "German"),
    ("it", "Italian"), ("pt", "Portuguese"), ("nl", "Dutch"), ("ru", "Russian"),
    ("zh", "Chinese"), ("ja", "Japanese"), ("ko", "Korean"), ("ar", "Arabic"),
    ("hi", "Hindi"), ("bn", "Bengali"), ("ur", "Urdu"), ("tr", "Turkish"),
    ("vi", "Vietnamese"), ("th", "Thai"), ("id", "Indonesian"), ("ms", "Malay"),
    ("tl", "Filipino/Tagalog"), ("pl", "Polish"), ("uk", "Ukrainian"),
    ("ro", "Romanian"), ("el", "Greek"), ("cs", "Czech"), ("hu", "Hungarian"),
    ("sv", "Swedish"), ("no", "Norwegian"), ("da", "Danish"), ("fi", "Finnish"),
    ("he", "Hebrew"), ("sw", "Swahili"), ("fa", "Persian/Farsi"), ("pa", "Punjabi"),
]


def seed_languages(conn: Connection) -> SeedResult:
    rows = [{"iso_code": code, "language_name": name} for code, name in LANGUAGES]
    return upsert_many(
        conn, schema="ref", table_name="languages",
        rows=rows, conflict_cols=("iso_code",),
    )