"""Seed ops.reed_search_queue with (keywords, location_name) combinations.

Usage:
    python scripts/seed_reed_queries.py                       # seed all titles x all UK cities
    python scripts/seed_reed_queries.py --query "data scientist" --location London
    python scripts/seed_reed_queries.py --list                # show current queue contents

Idempotent: re-running never creates duplicates (ON CONFLICT DO NOTHING on
(keywords, location_name)), so it is safe to run again after editing the
lists below to add new combinations.

Where the lists come from
-------------------------
TITLES is a copy (values only, not an import) of the broad job-title list
used by the separate Indeed seeding script, per the project owner's
2026-09-27 request to reuse it here. It is plain search-term text with
nothing source-specific in it. Copied rather than imported so this script
has no dependency on the paused Indeed effort's files.

UK_CITIES is every settlement with official UK city status: 76 in total
(55 England, 8 Scotland, 7 Wales, 6 Northern Ireland), cross-checked
against several published lists. Choices worth knowing about:
  - There are two Bangors with city status (Wales and Northern Ireland),
    so they are disambiguated as "Bangor, Gwynedd" and "Bangor, County
    Down" -- otherwise they'd collide on this table's unique key.
  - "Derry" is used as the search string because it is the name in
    everyday recruitment listings and the local council's own name. This
    is a practical choice of one search term, not a position on the
    Derry/Londonderry naming question.
  - "London" and "Westminster" are both official cities and are both
    included, as asked for ("all cities"). Their Reed results will overlap
    heavily; ReedPipeline deduplicates by jobId within a run.

Reed also lists a small number of international jobs (about 4% of volume).
These are not covered by this UK city list -- see the scoping conversation.

Volume: 105 titles x 76 cities = 7980 combinations.
At the default ReedSettings.queries_claimed_per_run (5), that is a long
crawl. Raise the setting once real runs show it's safe.
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.logger import configure_logging
from job_market_intel.db.reed_query_queue_repository import ReedQueryQueueRepository
from job_market_intel.db.session import get_session
from job_market_intel.scrapers.reed.search_queries import ReedSearchQuery

TITLES: list[str] = [
    "software engineer",
    "backend developer",
    "frontend developer",
    "full stack developer",
    "mobile app developer",
    "devops engineer",
    "site reliability engineer",
    "cloud engineer",
    "cybersecurity analyst",
    "network engineer",
    "systems administrator",
    "database administrator",
    "software architect",
    "qa engineer",
    "embedded systems engineer",
    "data engineer",
    "data scientist",
    "data analyst",
    "machine learning engineer",
    "ai engineer",
    "business intelligence analyst",
    "research scientist",
    "product manager",
    "project manager",
    "program manager",
    "scrum master",
    "business analyst",
    "product designer",
    "ux designer",
    "ui designer",
    "graphic designer",
    "interior designer",
    "marketing manager",
    "digital marketing specialist",
    "content marketing manager",
    "seo specialist",
    "social media manager",
    "brand manager",
    "sales representative",
    "account executive",
    "business development manager",
    "customer success manager",
    "customer support specialist",
    "technical support engineer",
    "hr manager",
    "recruiter",
    "talent acquisition specialist",
    "compensation analyst",
    "financial analyst",
    "accountant",
    "bookkeeper",
    "controller",
    "auditor",
    "investment banker",
    "actuary",
    "bank teller",
    "loan officer",
    "operations manager",
    "supply chain manager",
    "logistics coordinator",
    "procurement specialist",
    "warehouse associate",
    "registered nurse",
    "physician",
    "pharmacist",
    "medical assistant",
    "dental hygienist",
    "physical therapist",
    "veterinarian",
    "dentist",
    "teacher",
    "professor",
    "instructional designer",
    "tutor",
    "lawyer",
    "paralegal",
    "compliance officer",
    "legal assistant",
    "mechanical engineer",
    "electrical engineer",
    "civil engineer",
    "chemical engineer",
    "industrial engineer",
    "manufacturing engineer",
    "quality assurance inspector",
    "management consultant",
    "executive assistant",
    "administrative assistant",
    "office manager",
    "retail sales associate",
    "store manager",
    "restaurant manager",
    "chef",
    "construction manager",
    "electrician",
    "plumber",
    "architect",
    "copywriter",
    "editor",
    "journalist",
    "photographer",
    "video editor",
    "social worker",
    "insurance agent",
    "real estate agent",
]

UK_CITIES_ENGLAND: list[str] = [
    "Bath",
    "Birmingham",
    "Bradford",
    "Brighton and Hove",
    "Bristol",
    "Cambridge",
    "Canterbury",
    "Carlisle",
    "Chelmsford",
    "Chester",
    "Chichester",
    "Colchester",
    "Coventry",
    "Derby",
    "Doncaster",
    "Durham",
    "Ely",
    "Exeter",
    "Gloucester",
    "Hereford",
    "Kingston upon Hull",
    "Lancaster",
    "Leeds",
    "Leicester",
    "Lichfield",
    "Lincoln",
    "Liverpool",
    "London",
    "Manchester",
    "Milton Keynes",
    "Newcastle upon Tyne",
    "Norwich",
    "Nottingham",
    "Oxford",
    "Peterborough",
    "Plymouth",
    "Portsmouth",
    "Preston",
    "Ripon",
    "Salford",
    "Salisbury",
    "Sheffield",
    "Southampton",
    "Southend-on-Sea",
    "St Albans",
    "Stoke-on-Trent",
    "Sunderland",
    "Truro",
    "Wakefield",
    "Wells",
    "Westminster",
    "Winchester",
    "Wolverhampton",
    "Worcester",
    "York",
]

UK_CITIES_SCOTLAND: list[str] = [
    "Aberdeen",
    "Dundee",
    "Dunfermline",
    "Edinburgh",
    "Glasgow",
    "Inverness",
    "Perth",
    "Stirling",
]

UK_CITIES_WALES: list[str] = [
    "Bangor, Gwynedd",
    "Cardiff",
    "Newport",
    "St Asaph",
    "St Davids",
    "Swansea",
    "Wrexham",
]

UK_CITIES_NORTHERN_IRELAND: list[str] = [
    "Armagh",
    "Bangor, County Down",
    "Belfast",
    "Derry",
    "Lisburn",
    "Newry",
]

UK_CITIES: list[str] = (
    UK_CITIES_ENGLAND + UK_CITIES_SCOTLAND + UK_CITIES_WALES + UK_CITIES_NORTHERN_IRELAND
)


def _seed_defaults(repo: ReedQueryQueueRepository) -> int:
    count = 0
    with get_session() as session:
        for title in TITLES:
            for city in UK_CITIES:
                repo.seed_query(session, ReedSearchQuery(keywords=title, location_name=city))
                count += 1
    return count


def _list_queue(repo: ReedQueryQueueRepository) -> None:
    with get_session() as session:
        total = repo.count(session)
        rows = repo.get_all(session, limit=500)
    if not rows:
        print("ops.reed_search_queue is empty.")
        return
    print(f"{'query_id':<10}{'status':<14}keywords @ location  (showing {len(rows)} of {total})")
    print("-" * 70)
    for row in rows:
        print(
            f"{row['query_id']:<10}{row['status']:<14}"
            f"{row['keywords']!r} @ {row['location_name']!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed ops.reed_search_queue for Reed")
    parser.add_argument("--query", help="A single keywords string to add.")
    parser.add_argument("--location", help="Location for --query (required together).")
    parser.add_argument("--list", action="store_true", help="List current queue contents.")
    args = parser.parse_args()

    configure_logging(log_dir="logs", console_level="INFO", file_level="DEBUG")
    repo = ReedQueryQueueRepository()

    if args.list:
        _list_queue(repo)
        return 0

    if args.query and args.location:
        with get_session() as session:
            repo.seed_query(
                session, ReedSearchQuery(keywords=args.query, location_name=args.location)
            )
        logger.info("Seeded 1 query: {!r} @ {!r}", args.query, args.location)
        return 0
    if args.query or args.location:
        parser.error("--query and --location must be given together.")

    added = _seed_defaults(repo)
    logger.info(
        "Processed {} (keywords, location) combinations ({} titles x {} UK cities); "
        "already-present rows were left untouched.",
        added,
        len(TITLES),
        len(UK_CITIES),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
