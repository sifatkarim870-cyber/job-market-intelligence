"""Data validation.

Currently contains batch-level validation for RemoteOK scrape runs
(Step 7) — see ``remoteok_validator.py`` for what "batch-level" means and
why it's distinct from the per-record validation already performed by
``scrapers/remoteok/parser.py``.

As additional sources are added (We Work Remotely, Remotive, ...), watch
for genuinely shared validation logic (volume sanity, skip-rate sanity,
duplicate-ID detection) that could be extracted into a source-agnostic
base here — but per the project's established YAGNI approach (see
``scrapers/`` for precedent), that extraction should wait until a second
source's validator actually exists to compare against, not be guessed at
now.
"""

from .remoteok_validator import (
    BatchValidationReport,
    RemoteOKBatchValidator,
    RemoteOKValidationSettings,
)

__all__ = [
    "BatchValidationReport",
    "RemoteOKBatchValidator",
    "RemoteOKValidationSettings",
]
