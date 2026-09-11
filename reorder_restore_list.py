"""
Reorders a pg_restore --list output file (the "TOC" listing) so that
dependency-parent tables are always restored before the tables that
foreign-key reference them, for a --data-only restore.

WHY THIS EXISTS
---------------
pg_restore, for a --data-only restore, processes TABLE DATA entries in
whatever order they appear in the dump file's table of contents -- which
is NOT guaranteed to respect foreign-key dependency order, especially
across many schemas and partitioned tables. Confirmed against a real
restore attempt: bridge.job_skills and core.job_descriptions_* were
processed BEFORE core.jobs' own partitions, causing every one of their
rows to fail with "is not present in table jobs" -- not because the data
was missing, but purely because of processing order.

This script reads the plain-text output of:
    pg_restore --list your_dump.dump > toc.txt
reorders the TABLE DATA lines according to a fixed dependency priority
(parents first), and writes a new file that can be fed back via:
    pg_restore --use-list=reordered_toc.txt your_dump.dump ...

It leaves every other kind of line (headers, comments, non-table-data
entries) exactly where it was -- only TABLE DATA lines get reordered
relative to each other; nothing is added, removed, or renamed.

USAGE
-----
    python reorder_restore_list.py toc.txt reordered_toc.txt
"""
from __future__ import annotations

import re
import sys

# Lower number = restored earlier. Matched against the *unqualified* table
# name (schema stripped) via substring/prefix rules below. Anything not
# matched falls into DEFAULT_PRIORITY, which sits safely after every named
# group here but before nothing in particular -- i.e. genuinely unknown
# tables restore last, which is the safe default when we don't know their
# dependencies.
PRIORITY_RULES: list[tuple[str, int]] = [
    ("companies", 10),
    ("company_aliases", 11),
    ("scraping_sessions", 12),
    ("jobs_", 20),        # every jobs_YYYY_MM partition, and jobs_default
    ("jobs", 20),         # in case a build ever restores via the parent name directly
    ("job_descriptions", 30),
    ("job_salaries", 30),
    ("salary_history", 30),
    ("job_skills", 30),
    ("job_benefits", 30),
    ("job_languages", 30),
    ("job_categories_map", 30),
    ("company_industries", 30),
    ("job_status_history", 40),
    ("job_field_changes", 40),
    ("scraper_logs", 50),
    ("failed_scrapes", 50),
    ("source_statistics", 50),
    ("currency_exchange_rates", 50),
]
DEFAULT_PRIORITY = 100

# Matches a pg_restore --list TABLE DATA line. Confirmed against real
# pg_restore 18.4 output that schema/table/owner names are NOT quoted
# when they don't need to be (plain lowercase identifiers), e.g.:
#   8330; 0 24090 TABLE DATA audit change_log postgres
# but pg_restore WILL quote an identifier that needs it (mixed case,
# special characters), e.g.:
#   102; 0 12347 TABLE DATA core "Some-Table" postgres
# so both the quoted and unquoted forms are matched here.
_IDENT = r'(?:"[^"]+"|\S+)'
TABLE_DATA_RE = re.compile(
    r"^(?P<id>\d+);\s+\d+\s+\d+\s+TABLE DATA\s+"
    + _IDENT
    + r"\s+(?P<table_raw>"
    + _IDENT
    + r")\s+\S+\s*$"
)


def _unquote(raw: str) -> str:
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def priority_for(table_name: str) -> int:
    for pattern, priority in PRIORITY_RULES:
        if table_name.startswith(pattern) or table_name == pattern:
            return priority
    return DEFAULT_PRIORITY


def reorder(lines: list[str]) -> list[str]:
    header: list[str] = []
    table_data_entries: list[tuple[int, int, str]] = []  # (priority, original_index, line)

    # Header block: everything up to and including the "Selected TOC
    # Entries:" marker line (or the first real entry, whichever comes
    # first) is preserved verbatim, in place, at the top.
    seen_real_entry = False
    for idx, line in enumerate(lines):
        match = TABLE_DATA_RE.match(line)
        if match:
            seen_real_entry = True
            priority = priority_for(_unquote(match.group("table_raw")))
            table_data_entries.append((priority, idx, line))
        elif not seen_real_entry:
            header.append(line)
        else:
            # A non-TABLE-DATA entry (e.g. a sequence SET value, or a
            # non-table object) appearing after real entries have
            # started. Keep these pinned at their original relative
            # position by giving them a priority tied to the nearest
            # preceding TABLE DATA priority, falling back to DEFAULT.
            last_priority = table_data_entries[-1][0] if table_data_entries else DEFAULT_PRIORITY
            table_data_entries.append((last_priority, idx, line))

    # Stable sort: within the same priority, original order is preserved.
    table_data_entries.sort(key=lambda item: (item[0], item[1]))

    return header + [line for _, _, line in table_data_entries]


def detect_encoding(path: str) -> str:
    """Sniff the byte-order-mark, if any, to pick the right text encoding.

    Windows PowerShell's `>` redirection operator (classic 5.1, not
    PowerShell 7+) writes UTF-16LE with a BOM by default -- unlike almost
    every other tool on the system, which writes UTF-8. Confirmed as the
    real cause of a UnicodeDecodeError on a real toc.txt generated via
    `pg_restore --list ... > toc.txt` in this exact environment. Rather
    than require a special redirection flag to be remembered every time,
    detect it here and handle it transparently.
    """
    with open(path, "rb") as f:
        head = f.read(4)
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        # Generic "utf-16" (no explicit endianness) auto-detects from the
        # BOM AND strips it from the decoded text -- utf-16-le/-be would
        # decode the BOM bytes into a literal U+FEFF character left
        # sitting in the output, which could confuse pg_restore's parser
        # on the file's first line.
        return "utf-16"
    if head.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return "utf-8"


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: python reorder_restore_list.py <input_toc.txt> <output_toc.txt>",
            file=sys.stderr,
        )
        return 2

    input_path, output_path = sys.argv[1], sys.argv[2]

    encoding = detect_encoding(input_path)
    with open(input_path, encoding=encoding) as f:
        lines = [line.rstrip("\n") for line in f]

    reordered = reorder(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(reordered) + "\n")

    table_data_count = sum(1 for line in lines if TABLE_DATA_RE.match(line))
    print(
        f"Read {len(lines)} lines as {encoding} "
        f"({table_data_count} TABLE DATA entries). Wrote {output_path}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
