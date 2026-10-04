"""One-off script to seed ops.scrape_query_queue for the Indeed scraper.

The queue starts empty — nothing in the schema or seed data pre-populates
it (see migrations/add_scrape_query_queue_table.sql's module docstring).
This script adds (query, location) combinations for source 'indeed'.
Safe to re-run: seeding is idempotent (ON CONFLICT DO NOTHING via
ScrapeQueueRepository.seed_query), so re-running with the same defaults
never creates duplicates.

Usage:
    # Seed the built-in starter list (see _DEFAULT_QUERIES below):
    python scripts/seed_indeed_queries.py

    # Add one specific combination instead:
    python scripts/seed_indeed_queries.py --query "data engineer" --location "Remote"

    # See what's currently queued and its status:
    python scripts/seed_indeed_queries.py --list

The starter list below is a deliberately small, adjustable starting point
covering common tech roles across a few major US metro areas — not a
claim about what this research platform should ultimately cover. Extend
it (or call --query/--location repeatedly, or seed_query directly) as the
project's actual coverage goals get decided.
"""

from __future__ import annotations

import argparse

from loguru import logger

from job_market_intel.common.logger import configure_logging
from job_market_intel.db.job_repository import JobRepository
from job_market_intel.db.scrape_queue_repository import ScrapeQueueRepository
from job_market_intel.db.session import get_session
from job_market_intel.scrapers.indeed.config import (
    _ALL_COUNTRIES as _COUNTRIES,
)
from job_market_intel.scrapers.indeed.config import (
    base_url_for_location,
)

# Job titles spanning every major Indeed category — tech/cloud, management,
# finance/legal, healthcare, education, marketing/sales/CS, retail/hospitality,
# trades/labour, and the professional-services adjuncts. Each is a real, common
# search term on Indeed rather than a job-family label ("engineering" wouldn't
# be typed into the search box).
_DEFAULT_QUERIES = [
    # Tech & engineering. "software developer", "data scientist", ... are all
    # separately indexed on Indeed, so they get their own rows rather than
    # being folded into one generic "tech" row.
    "software engineer", "software developer", "web developer",
    "front end developer", "back end developer", "full stack developer",
    "data analyst", "data scientist", "data engineer",
    "machine learning engineer", "devops engineer", "cybersecurity analyst",
    "it support specialist", "systems administrator", "database administrator",
    "network engineer", "cloud engineer", "security engineer", "qa engineer",
    "site reliability engineer", "embedded software engineer", "help desk technician",
    "computer support specialist", "it manager", "technical writer",
    "business intelligence analyst", "salesforce developer", "servicenow developer",
    # Management & business.
    "product manager", "project manager", "program manager",
    "business analyst", "operations manager", "supply chain manager",
    "logistics manager", "human resources manager", "office manager",
    "executive assistant", "receptionist", "recruiter", "talent acquisition specialist",
    "training manager", "marketing manager", "sales manager", "account manager",
    # Finance & legal.
    "financial analyst", "accountant", "auditor", "tax accountant",
    "paralegal", "lawyer", "bookkeeper", "controller", "actuary",
    "underwriter", "financial advisor", "loan officer", "mortgage broker",
    "insurance agent", "billing specialist", "claims adjuster",
    # Healthcare.
    "nurse", "registered nurse", "physician", "pharmacist",
    "physical therapist", "medical assistant", "dentist",
    "nurse practitioner", "physician assistant", "radiologic technologist",
    "occupational therapist", "speech therapist", "dental hygienist",
    "veterinarian", "vet technician", "paramedic", "emt",
    "surgical technologist", "phlebotomist", "hospital administrator",
    "caregiver", "home health aide", "dentist hygienist",
    # Education.
    "teacher", "elementary teacher", "professor", "school counselor",
    "librarian", "academic advisor", "tutor", "social worker",
    "childcare worker", "therapist", "counselor",
    # Marketing, sales & customer experience.
    "marketing manager", "social media manager", "sales representative",
    "account executive", "customer service representative", "call center agent",
    "digital marketing manager", "seo specialist", "content writer", "copywriter",
    "brand manager", "inside sales representative", "customer success manager",
    "client services manager", "retail sales associate",
    # Retail, hospitality & food.
    "retail sales associate", "cashier", "barista", "waiter",
    "hotel manager", "event planner", "chef", "sous chef", "pastry chef",
    "bartender", "host", "line cook", "dishwasher", "front desk agent",
    "room attendant", "travel agent", "tour guide", "retail manager",
    # Trades, construction & logistics.
    "electrician", "plumber", "carpenter", "hvac technician",
    "forklift operator", "warehouse worker", "truck driver",
    "construction worker", "landscaper", "security guard", "welder",
    "machinist", "diesel mechanic", "aircraft mechanic", "maintenance technician",
    "building manager", "janitor", "housekeeper", "painter", "roofer",
    "tiler", "drywall installer", "general laborer", "warehouse manager",
    "construction manager", "structural engineer", "civil engineer", "architect",
    # Science, design, education adjuncts, & public services.
    "research scientist", "environmental scientist", "graphic designer",
    "mechanic", "real estate agent", "laboratory technician", "statistician",
    "biotechnologist", "real estate appraiser", "quality assurance",
    "quality control inspector", "ux designer", "ui designer",
    "product designer", "school bus driver", "police officer", "firefighter",
    "postal worker", "military recruiter", "interior designer", "property manager",
    "drivers", "service technician",
]

# Locations: one row per (title, location). Non-US entries end in the country
# alias so base_url_for_location() routes them to that country's Indeed site —
# without that, the US portal silently ignores a foreign location string and
# returns US jobs instead of that country's jobs. "Remote" and US "City, ST"
# entries route to the US site.
_DEFAULT_LOCATIONS = [
    # US.
    "Remote",
    "New York, NY", "Los Angeles, CA", "San Francisco, CA", "Seattle, WA",
    "Austin, TX", "Chicago, IL", "Boston, MA", "Washington, DC",
    "Denver, CO", "Miami, FL", "Atlanta, GA", "Dallas, TX",
    # UK.
    "London, UK", "Manchester, UK", "Birmingham, UK", "Leeds, UK",
    # Germany.
    "Berlin, Germany", "Munich, Germany", "Frankfurt, Germany", "Hamburg, Germany",
    # France.
    "Paris, France", "Lyon, France",
    # Canada.
    "Toronto, Canada", "Vancouver, Canada", "Montreal, Canada",
    # India.
    "Bangalore, India", "Mumbai, India", "Delhi, India",
    "Hyderabad, India", "Chennai, India",
    # Australia.
    "Sydney, Australia", "Melbourne, Australia", "Brisbane, Australia",
    # Netherlands / Spain / Italy.
    "Amsterdam, Netherlands", "Rotterdam, Netherlands",
    "Madrid, Spain", "Barcelona, Spain",
    "Milan, Italy", "Rome, Italy",
    # Asia-Pacific.
    "Singapore", "Tokyo, Japan", "Osaka, Japan",
    "Seoul, South Korea", "Jakarta, Indonesia",
    "Ho Chi Minh City, Vietnam", "Bangkok, Thailand",
    # Latin America.
    "São Paulo, Brazil", "Rio de Janeiro, Brazil", "Mexico City, Mexico",
    "Guadalajara, Mexico", "Buenos Aires, Argentina",
    # Middle East & Africa.
    "Dubai, UAE", "Riyadh, Saudi Arabia", "Lagos, Nigeria",
    "Cape Town, South Africa", "Johannesburg, South Africa",
    # Oceania & rest of Europe.
    "Auckland, New Zealand", "Dublin, Ireland", "Zurich, Switzerland",
    "Stockholm, Sweden", "Warsaw, Poland", "Lisbon, Portugal",
    "Athens, Greece", "Prague, Czech Republic", "Vienna, Austria",
    "Brussels, Belgium", "Copenhagen, Denmark", "Oslo, Norway",
    "Helsinki, Finland", "Istanbul, Turkey",
]

# Every country in the world, as a bare location row, plus the curated
# nation/city rows above. From those, we only actually seed the locations
# that route to a real Indeed country domain: Indeed operates in ~53 markets,
# and seeding rows for the rest would just exercise them forever and always
# skip. Keeping only the scrapable rows means every queue row corresponds to
# crawling a real market's local results.
_ALL_COUNTRIES_BARE = list(_COUNTRIES)
_DEFAULT_LOCATIONS = [
    loc
    for loc in (_DEFAULT_LOCATIONS + _ALL_COUNTRIES_BARE)
    if base_url_for_location(loc) is not None
]


def _seed_defaults(repo: ScrapeQueueRepository, source_id: int) -> int:
    count = 0
    with get_session() as session:
        for query_text in _DEFAULT_QUERIES:
            for location_text in _DEFAULT_LOCATIONS:
                repo.seed_query(session, source_id, query_text, location_text)
                count += 1
    return count


def _list_queue(repo: ScrapeQueueRepository) -> None:
    with get_session() as session:
        rows = repo.get_all(session, limit=500)
    if not rows:
        print("ops.scrape_query_queue is empty.")
        return
    print(f"{'query_id':<10}{'status':<14}{'last_page':<11}query / location")
    print("-" * 70)
    for row in rows:
        print(
            f"{row['query_id']:<10}{row['status']:<14}"
            f"{'':<11}{row['query_text']!r} @ {row['location_text']!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed ops.scrape_query_queue for Indeed")
    parser.add_argument("--query", help="A single search query to add.")
    parser.add_argument("--location", help="Location for --query (required together).")
    parser.add_argument("--list", action="store_true", help="List current queue contents.")
    args = parser.parse_args()

    configure_logging(log_dir="logs", console_level="INFO", file_level="DEBUG")

    repo = ScrapeQueueRepository()
    job_repo = JobRepository()

    if args.list:
        _list_queue(repo)
        return 0

    with get_session() as session:
        source_id = job_repo.get_source_id_by_code(session, "indeed")

    if args.query and args.location:
        with get_session() as session:
            repo.seed_query(session, source_id, args.query, args.location)
        logger.info("Seeded 1 query: {!r} @ {!r}", args.query, args.location)
        return 0
    if args.query or args.location:
        parser.error("--query and --location must be given together.")

    added = _seed_defaults(repo, source_id)
    logger.info(
        "Seeded {} (query, location) combinations ({} queries x {} locations).",
        added,
        len(_DEFAULT_QUERIES),
        len(_DEFAULT_LOCATIONS),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
