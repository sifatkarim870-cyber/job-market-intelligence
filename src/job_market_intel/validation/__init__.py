"""Data validation.

``common.py`` holds ``validate_batch`` and ``BatchValidationReport``: the
source-agnostic batch-health engine every source's validator is built on
top of (Step 14 — see that module's docstring for why this is extracted
now, generically, and why it's kept structurally free of any dependency
on a specific scraper package).

Beyond that shared engine, this package holds each source's own
batch-level validation — see ``remoteok_validator.py`` and
``weworkremotely_validator.py`` for what "batch-level" means, why it's
distinct from the per-record validation already performed by each
source's own ``scrapers/<source>/parser.py``, and each source's own
thresholds/missing-field checks.

As additional sources are added (Indeed, LinkedIn, ...), each gets its
own ``<Source>BatchValidator`` following the same thin-wrapper pattern:
its own settings, its own missing-field checks, calling the shared
``validate_batch`` — see ``remotive_validator.py`` for the third such
example (Step 18).
"""

from .common import BatchValidationReport, validate_batch
from .emploitic_validator import EmploiticBatchValidator, EmploiticValidationSettings
from .myjob_validator import MyJobBatchValidator, MyJobValidationSettings
from .reed_validator import ReedBatchValidator, ReedValidationSettings
from .remoteok_validator import RemoteOKBatchValidator, RemoteOKValidationSettings
from .remotive_validator import RemotiveBatchValidator, RemotiveValidationSettings
from .weworkremotely_validator import WWRBatchValidator, WWRValidationSettings

__all__ = [
    "BatchValidationReport",
    "validate_batch",
    "ReedBatchValidator",
    "ReedValidationSettings",
    "EmploiticBatchValidator",
    "EmploiticValidationSettings",
    "MyJobBatchValidator",
    "MyJobValidationSettings",
    "RemoteOKBatchValidator",
    "RemoteOKValidationSettings",
    "RemotiveBatchValidator",
    "RemotiveValidationSettings",
    "WWRBatchValidator",
    "WWRValidationSettings",
]
