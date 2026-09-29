"""Reed scraper.

Fetches job listings from Reed's official Jobseeker API
(``https://www.reed.co.uk/api/1.0``, requires a free API key — see
``config.py``'s module docstring) and returns validated, typed
``RawReedJob`` objects.

Genuinely different from every other source in this codebase — see each
module's own docstring for the full detail, this is only a map:
    - ``config.py``: requires ``REED_API_KEY``, no default (every other
      source needs no auth at all).
    - ``search_queries.py``: Reed has no "give me everything" feed; what
      to search for is real, configurable, and — as of this delivery —
      still not a confirmed production decision.
    - ``client.py``: two endpoints (Search, paginated; Details, one job
      at a time), Basic Auth on every request, no documented rate limit.
    - ``models.py``: ``RawReedJob`` is built from BOTH endpoints merged,
      not one flat payload.
    - ``pipeline.py``: reads the database before cleaning (to prioritize
      which jobs get a Details call when a run exceeds its per-run cap),
      not just at persist time like every other source's pipeline.

This package deliberately does NOT clean, normalize, or store data
beyond what ``pipeline.py``'s orchestration requires — cleaning is
``cleaning/reed_cleaner.py``'s job, matching every other source.
"""

from .client import ReedClient
from .config import ReedSettings
from .exceptions import ReedAuthenticationError, ReedError, ReedFetchError, ReedResponseError
from .models import RawReedJob
from .parser import ReedParser
from .pipeline import ReedPipeline, ReedPipelineRunResult
from .search_queries import DEFAULT_SEARCH_QUERIES, ReedSearchQuery

__all__ = [
    "ReedClient",
    "ReedSettings",
    "ReedError",
    "ReedAuthenticationError",
    "ReedFetchError",
    "ReedResponseError",
    "RawReedJob",
    "ReedParser",
    "ReedPipeline",
    "ReedPipelineRunResult",
    "ReedSearchQuery",
    "DEFAULT_SEARCH_QUERIES",
]
