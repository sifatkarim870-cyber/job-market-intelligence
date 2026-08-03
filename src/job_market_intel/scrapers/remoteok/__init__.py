"""RemoteOK scraper.

Fetches job listings from RemoteOK's public JSON feed
(``https://remoteok.com/api``) and returns validated, typed
``RawRemoteOKJob`` objects.

This package deliberately does NOT clean, normalize, or store data — that
is the responsibility of later pipeline steps (data cleaning, database
insertion). Its only job is: fetch reliably, validate what comes back, and
hand back a clean list of typed Python objects.

Typical usage:

    from src.scrapers.remoteok import RemoteOKClient, RemoteOKParser, RemoteOKSettings

    settings = RemoteOKSettings()
    client = RemoteOKClient(settings=settings)
    parser = RemoteOKParser()

    raw_jobs = client.fetch_raw_jobs()
    jobs = parser.parse_jobs(raw_jobs)
"""

from .client import RemoteOKClient
from .config import RemoteOKSettings
from .exceptions import RemoteOKError, RemoteOKFetchError, RemoteOKResponseError
from .models import RawRemoteOKJob
from .parser import RemoteOKParser

__all__ = [
    "RemoteOKClient",
    "RemoteOKSettings",
    "RemoteOKError",
    "RemoteOKFetchError",
    "RemoteOKResponseError",
    "RawRemoteOKJob",
    "RemoteOKParser",
]
