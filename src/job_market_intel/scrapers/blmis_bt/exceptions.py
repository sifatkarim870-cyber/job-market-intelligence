"""BLMIS-specific exceptions.

Same role as the other sources' ``exceptions.py``: the shared
``common/http_client.py`` errors describe why an HTTP call failed in
general terms, while these describe failures in terms a caller of the
BLMIS scraper cares about ("BLMIS could not be reached" vs "BLMIS
responded but the payload wasn't a usable vacancy list"). ``client.py``
catches the generic ones and re-raises these.
"""

from __future__ import annotations


class BlmisError(Exception):
    """Base class for all BLMIS scraper errors."""


class BlmisFetchError(BlmisError):
    """The single listing GET failed after all retries.

    There is nothing else to fetch for a BLMIS run -- the whole inventory
    arrives in that one response -- so a failed GET ends the run rather
    than degrading to a partial result.
    """


class BlmisResponseError(BlmisError):
    """BLMIS responded, but the payload wasn't a usable vacancy list.

    Raised for a page with no Livewire ``wire:initial-data`` attribute, a
    non-JSON blob, a JSON envelope without the expected data, or a first
    read that yielded zero unique vacancies -- a fully broken site (or a
    format change) fails loudly, never as a silent zero-jobs no-op.
    """
