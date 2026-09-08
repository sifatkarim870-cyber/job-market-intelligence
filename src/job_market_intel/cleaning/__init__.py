"""Data cleaning pipeline.

``common.py`` holds ``CleanedJob``: the single, source-agnostic
storage-ready record shape every source's cleaner must produce (Step 14 —
see that module's docstring for why this is extracted now, generically,
rather than guessed at later).

Beyond that shared contract, this package holds each source's own
cleaning logic: fixing character encoding, decoding HTML entities,
stripping HTML tags, normalizing whitespace, and repairing obvious
mechanical data-entry mistakes specific to that source. See
``remoteok_cleaner.py``, ``weworkremotely_cleaner.py``, and
``remotive_cleaner.py`` for each source's specific logic and
``text_utils.py`` for the generic, reusable text-cleaning primitives every
source's cleaner builds on. Per the project's established YAGNI approach
(see ``scrapers/`` for precedent), further cleaning-logic extraction
beyond the output model and the text primitives already shared waits
until enough sources' cleaners exist to compare against and find genuine,
repeated duplication worth extracting.
"""

from .common import CleanedJob
from .remoteok_cleaner import RemoteOKCleaner
from .remotive_cleaner import RemotiveCleaner
from .text_utils import clean_html_text, clean_plain_text
from .weworkremotely_cleaner import WWRCleaner

__all__ = [
    "CleanedJob",
    "RemoteOKCleaner",
    "RemotiveCleaner",
    "WWRCleaner",
    "clean_html_text",
    "clean_plain_text",
]
