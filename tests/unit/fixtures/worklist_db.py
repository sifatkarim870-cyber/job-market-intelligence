"""A scratch database seeded with known select/skip cases for the worklist exporter.

The live corpus has nothing outstanding, so ``fetch_worklist`` returns an empty
list against it and every assertion about what gets SELECTED would pass
vacuously -- a broken query would look like a healthy "nothing to translate".
These rows make the selection logic observable.

Deliberately named ``worklist_db`` rather than ``translation_worklist``: pytest
imports the test module and this fixture under matching basenames, and the
collision produced a circular import.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

#: A Persian description long enough to clear the default min-length.
LONG_FA = "این یک توضیح کامل و طولانی درباره شغل است"

DDL = """
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ref;

DROP TABLE IF EXISTS core.job_descriptions;
DROP TABLE IF EXISTS core.jobs;
DROP TABLE IF EXISTS ref.sources;

CREATE TABLE ref.sources (
    source_id integer PRIMARY KEY,
    source_code text NOT NULL,
    source_name text NOT NULL,
    source_type text NOT NULL,
    requires_auth boolean NOT NULL,
    is_active boolean NOT NULL,
    trust_score numeric
);
CREATE TABLE core.jobs (
    job_id bigint PRIMARY KEY,
    source_id integer NOT NULL,
    source_job_id text NOT NULL,
    original_url text NOT NULL,
    company_id bigint NOT NULL,
    job_title text NOT NULL,
    posting_date date NOT NULL,
    first_scraped_at timestamptz NOT NULL DEFAULT now(),
    last_scraped_at timestamptz NOT NULL DEFAULT now(),
    job_status text NOT NULL DEFAULT 'active',
    content_hash text NOT NULL,
    language_code text
);
CREATE TABLE core.job_descriptions (
    job_id bigint,
    posting_date date,
    description_clean text,
    description_en text
);
"""

SEED = f"""
INSERT INTO ref.sources VALUES (1,'testsrc','Test','job_board',false,true,0.7);

INSERT INTO core.jobs
    (job_id, source_id, source_job_id, original_url, company_id,
     job_title, posting_date, content_hash, language_code)
VALUES
    -- MUST be selected: non-English, untranslated, description long enough.
    (1, 1, 'J-FA-1',  'http://x/1', 1, 't1', CURRENT_DATE, 'h1', 'fa'),
    -- excluded: description below the length threshold.
    (2, 1, 'J-FA-2',  'http://x/2', 1, 't2', CURRENT_DATE, 'h2', 'fa'),
    -- excluded: English source.
    (3, 1, 'J-EN-1',  'http://x/3', 1, 't3', CURRENT_DATE, 'h3', 'en'),
    -- excluded: already has an English translation.
    (4, 1, 'J-DONE',  'http://x/4', 1, 't4', CURRENT_DATE, 'h4', 'fa'),
    -- excluded: no language_code, so not identified as needing translation.
    (5, 1, 'J-NULL',  'http://x/5', 1, 't5', CURRENT_DATE, 'h5', NULL);

INSERT INTO core.job_descriptions VALUES
    (1, CURRENT_DATE, '{LONG_FA}', NULL),
    (2, CURRENT_DATE, 'tiny', NULL),
    (3, CURRENT_DATE, 'English description here', NULL),
    (4, CURRENT_DATE, 'previously translated text', 'already translated');
    -- job 5 deliberately has NO row here: nothing to translate.
"""

ADMIN_DSN = "postgresql+psycopg://postgres:changeme@localhost:5432/postgres"
DB_NAME = "jmi_wl_fixture"


@pytest.fixture(scope="module")
def fixture_engine():
    """A scratch database seeded with the known select/skip rows."""
    admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}"'))
        conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    admin.dispose()

    engine = create_engine(
        f"postgresql+psycopg://postgres:changeme@localhost:5432/{DB_NAME}"
    )
    with engine.begin() as conn:
        for statement in DDL.split(";"):
            if statement.strip():
                conn.execute(text(statement))
        for statement in SEED.split(";"):
            if statement.strip():
                conn.execute(text(statement))

    yield engine

    engine.dispose()
    admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}"'))
    admin.dispose()
