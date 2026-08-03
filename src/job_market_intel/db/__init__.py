"""
db
==

The single, project-wide interface to PostgreSQL.

Every other component of the Job Market Intelligence Platform (scrapers,
seed scripts, the API, the dashboard, ML pipelines) imports from this
package rather than talking to SQLAlchemy or psycopg directly. That
constraint is what keeps connection handling, pooling behavior, and
transaction discipline consistent as the number of callers grows from one
script to a dozen concurrent services.

Nothing in this package defines ORM models or table mappings — see the
module docstrings in `engine.py`, `session.py`, and `base.py` for why that
boundary is deliberate.
"""

from job_market_intel.db.base import Base
from job_market_intel.db.config import DatabaseConfig, get_database_config
from job_market_intel.db.engine import dispose_engine, get_engine
from job_market_intel.db.exceptions import (
    ConfigurationError,
    DatabaseConnectionError,
    DatabaseError,
    RepositoryError,
    TransactionError,
)
from job_market_intel.db.repository import AbstractRepository
from job_market_intel.db.session import get_session, get_session_factory
from job_market_intel.db.transaction import transaction
from job_market_intel.db.utils import dispose_all, health_check, test_connection

__all__ = [
    "Base",
    "DatabaseConfig",
    "get_database_config",
    "get_engine",
    "dispose_engine",
    "get_session",
    "get_session_factory",
    "transaction",
    "test_connection",
    "health_check",
    "dispose_all",
    "AbstractRepository",
    "DatabaseError",
    "DatabaseConnectionError",
    "TransactionError",
    "ConfigurationError",
    "RepositoryError",
]
