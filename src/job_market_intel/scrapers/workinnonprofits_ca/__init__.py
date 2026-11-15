"""WorkInNonProfits (Canada) scraper package."""

from .client import WorkInNonProfitsClient
from .config import WorkInNonProfitsSettings
from .exceptions import (
    WorkInNonProfitsAPIError,
    WorkInNonProfitsError,
    WorkInNonProfitsParseError,
)
from .models import DiscoveredJobItem, RawWorkInNonProfitsJob
from .parser import WorkInNonProfitsParser
from .pipeline import (
    WorkInNonProfitsPipeline,
    WorkInNonProfitsPipelineRunResult,
)

__all__ = [
    "WorkInNonProfitsClient",
    "WorkInNonProfitsSettings",
    "WorkInNonProfitsError",
    "WorkInNonProfitsAPIError",
    "WorkInNonProfitsParseError",
    "DiscoveredJobItem",
    "RawWorkInNonProfitsJob",
    "WorkInNonProfitsParser",
    "WorkInNonProfitsPipeline",
    "WorkInNonProfitsPipelineRunResult",
]
