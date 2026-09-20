"""Indeed scraper.

Fetches job listings from Indeed via a real Selenium (seleniumbase, UC
mode) browser session — confirmed decision, see config.py and client.py
module docstrings for why, given Indeed's active fingerprinting of plain
WebDriver sessions. Unlike remoteok/remotive/weworkremotely (each a single
flat feed pull), this scraper works through a persistent
``ops.scrape_query_queue`` of (search query, location) combinations,
paced deliberately slowly, bounded per session, and designed to be run
indefinitely over a years-long crawl rather than to completion in one run.

Deviation from the other three scrapers' shape, noted explicitly rather
than silently: parser.py exposes ``parse_search_page``/``parse_detail_page``
as module-level functions, not a single ``IndeedParser`` class with one
``parse_jobs()`` method the way ``RemoteOKParser`` does. That class shape
fits a source with one homogeneous fetch-then-parse-a-list operation;
Indeed genuinely has two different parse operations over two different
page types (a list of cards, and a single description), so forcing both
into one method would obscure rather than clarify. Everything else here —
six-file layout, own exceptions, own Raw<Source>Job model, own cleaner, own
validator, own pipeline — follows the shared pattern exactly.

Typical usage:

    from job_market_intel.scrapers.indeed import IndeedPipeline

    pipeline = IndeedPipeline()
    result = pipeline.run(store_db=False)  # dry-run first, per project convention
"""

from .client import IndeedClient
from .config import IndeedSettings
from .exceptions import IndeedBlockedError, IndeedError, IndeedFetchError, IndeedParseError
from .models import RawIndeedJob
from .parser import parse_detail_page, parse_search_page
from .pipeline import IndeedPipeline, IndeedPipelineRunResult

__all__ = [
    "IndeedClient",
    "IndeedSettings",
    "IndeedError",
    "IndeedFetchError",
    "IndeedParseError",
    "IndeedBlockedError",
    "RawIndeedJob",
    "parse_search_page",
    "parse_detail_page",
    "IndeedPipeline",
    "IndeedPipelineRunResult",
]
