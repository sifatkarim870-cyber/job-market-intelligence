"""Data cleaning pipeline.

Currently contains RemoteOK-specific cleaning (Step 8): fixing character
encoding, decoding HTML entities, stripping HTML tags, normalizing
whitespace, and repairing a couple of obvious mechanical data-entry
mistakes (swapped salary bounds). See ``remoteok_cleaner.py`` for the
RemoteOK-specific logic and ``text_utils.py`` for the generic, reusable
text-cleaning primitives every future source's cleaner is expected to
build on.
"""

from .remoteok_cleaner import CleanedRemoteOKJob, RemoteOKCleaner
from .text_utils import clean_html_text, clean_plain_text

__all__ = [
    "CleanedRemoteOKJob",
    "RemoteOKCleaner",
    "clean_html_text",
    "clean_plain_text",
]
