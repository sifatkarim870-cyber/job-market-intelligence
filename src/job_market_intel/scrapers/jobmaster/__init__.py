"""JobMaster scraper.

Anonymous/HTML-only source: discovery walks the open filter cells of
``/jobs/``, details come from ``/jobs/checknum.asp?key=…``; anonymous
pagination beyond page 1 is login-walled by the site (see
``config.py``'s docstring).
"""

from .client import JobmasterClient
from .config import JobmasterSettings
from .exceptions import JobmasterError, JobmasterFetchError, JobmasterResponseError
from .models import RawJobmasterJob
from .parser import JobmasterParser
from .pipeline import JobmasterPipeline, JobmasterPipelineRunResult

__all__ = [
    "JobmasterClient",
    "JobmasterSettings",
    "JobmasterError",
    "JobmasterFetchError",
    "JobmasterResponseError",
    "RawJobmasterJob",
    "JobmasterParser",
    "JobmasterPipeline",
    "JobmasterPipelineRunResult",
]
