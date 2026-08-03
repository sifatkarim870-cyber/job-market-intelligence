# Changelog

All notable changes to this project are documented here.

## [0.1.0] - 2026-08-02

### Added
- Database schema design and PostgreSQL implementation: 9 schemas, ~38 tables, monthly range partitioning on core.jobs, materialized analytics views (Steps 1-2).
- Python project scaffold: uv-managed environment, pyproject.toml with optional dependency groups, base configuration loader (Step 3).
- Database interface layer: SQLAlchemy engine/session management, connection pooling, transaction helpers, generic repository pattern (Step 4).
- Reference data seeding system: 16 idempotent seed modules covering all ef.* controlled-vocabulary tables (Step 4.5).
- RemoteOK scraper: JSON API client with retry/backoff, field validation and parsing, structured logging (Step 5).
- Full test suite: 123 tests passing (unit tests for the RemoteOK scraper and shared HTTP/retry/logging infrastructure; integration tests for the database and seeding layers against a live PostgreSQL instance).

### Fixed
- Consolidated project structure into a single root (DataBase/job-market-intel); resolved import-path mismatches between early scratch-folder code and the real job_market_intel package layout; added missing dependencies (sqlalchemy, psycopg, passlib) that were previously untracked in pyproject.toml.
