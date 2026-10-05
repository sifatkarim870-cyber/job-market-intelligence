"""Copy locally-scraped rows for one source into the Neon (cloud) database.

Why this exists
---------------
The desktop is wired as a two-button workflow (both are .lnk shortcuts):

  * "Run Indeed Scrape" -> ``scripts/run_indeed_scrape.ps1``: scrapes Indeed
    and writes into the LOCAL Postgres (the launcher pins ``DATABASE_URL`` to
    ``LOCAL_DATABASE_URL`` for that process only).
  * "Indeed to Neon"    -> ``scripts/run_indeed_to_neon.ps1`` which calls this
    module: no browser, no scraping -- it takes what the local scrape already
    stored and upserts it into Neon in one click.

Only Indeed uses this local-then-push split; every other source still writes
straight into Neon (locally by hand, or on the GitHub 12-hour schedule), so
this script takes ``--source-code`` but defaults to ``indeed``.

What gets pushed
----------------
For the source: core.companies (create-only, matched on normalized_name),
ref.locations (matched on raw_location_text + is_global_remote, otherwise
created together with any missing city/region rows), core.jobs (upserted on
source_id + source_job_id + posting_date), core.job_descriptions (upserted on
job_id; its description_tsv is a schema-generated column and maintains
itself), salary.job_salaries (upserted on the
job_id unique key), and salary.salary_history / bridge.job_skills /
bridge.job_categories_map (replaced per job).

IDs are never copied between the databases: each assigns its own identities,
so every foreign key is re-resolved through a natural key (normalized_name,
iso_code, ref ``code``s, normalized_title, category code, skill_name) via
``_RefIndex``. A value that exists locally but not in Neon is a hard error,
never a silent NULL.

On update, "enrichment" columns -- title classification, job categories,
employment/experience/education/remote types, industry, is_duplicate_of --
are COALESced: the local value only overwrites Neon when it is actually set.
Local Indeed rows carry none of these (classification runs against Neon), so
a push can never wipe classification Neon already computed. Freshness moves
one way only: ``last_scraped_at`` = GREATEST(local, existing),
``first_scraped_at`` = LEAST(local, existing).

``ops.scrape_query_queue`` and ``ops.scraping_sessions`` are deliberately not
pushed: queue state and session ids are per-database bookkeeping, and a pushed
job's ``last_scraping_session_id`` is left as-is (NULL on insert).

Usage:
    python scripts/push_indeed_to_neon.py [--source-code indeed] [--dry-run]

DSNs come from LOCAL_DATABASE_URL / NEON_DATABASE_URL (process env first,
then .env). --dry-run performs every step inside one transaction and rolls it
back, so the report reflects exactly what a real click would do.
Exit codes: 0 pushed (or nothing to push), 1 a known, reported failure.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

REPO_ROOT = Path(__file__).resolve().parents[1]


class PushError(RuntimeError):
    """A known, reportable failure (missing DSN, missing reference value...)."""


# Reference kinds: local id -> natural value -> Neon id.
# (table, id column, natural-key column)
_REF_KINDS: dict[str, tuple[str, str, str]] = {
    "normalized_title": ("ref.normalized_job_titles", "normalized_title_id", "normalized_title"),
    "job_category": ("ref.job_categories", "job_category_id", "code"),
    "employment_type": ("ref.employment_types", "employment_type_id", "code"),
    "experience_level": ("ref.experience_levels", "experience_level_id", "code"),
    "education_level": ("ref.education_levels", "education_level_id", "code"),
    "remote_work_type": ("ref.remote_work_types", "remote_work_type_id", "code"),
    "industry": ("ref.industries", "industry_id", "industry_name"),
    "currency": ("ref.currencies", "currency_id", "iso_code"),
    "skill": ("ref.skills", "skill_id", "skill_name"),
}

# core.jobs columns whose local value is the scraped truth (written as-is).
_RAW_JOB_COLS = [
    "source_job_id",
    "original_url",
    "job_title",
    "posting_date",
    "closing_date",
    "first_scraped_at",
    "last_scraped_at",
    "job_status",
    "content_hash",
    "raw_html_ref",
    "data_quality_score",
    "num_vacancies",
    "visa_sponsorship",
    "relocation_support",
    "application_method",
    "application_url",
]

# Raw columns with special update rules (matched key / merged timestamps).
_RAW_UPDATE_EXCLUDED = ("posting_date", "first_scraped_at", "last_scraped_at")

# core.jobs columns owned by enrichment pipelines (classification, dedup...).
# Local only ever overwrites these when it actually has a value (COALESCE).
_ENRICH_JOB_COLS = [
    "normalized_title_id",
    "industry_id",
    "job_category_id",
    "employment_type_id",
    "experience_level_id",
    "education_level_id",
    "remote_work_type_id",
    "title_classification_status",
    "normalized_title_confidence",
    "title_classified_by",
]

_ENRICH_SQL_TYPE = {
    "normalized_title_id": "bigint",
    "industry_id": "integer",
    "job_category_id": "integer",
    "employment_type_id": "integer",
    "experience_level_id": "integer",
    "education_level_id": "integer",
    "remote_work_type_id": "integer",
    "title_classification_status": "text",
    "normalized_title_confidence": "numeric",
    "title_classified_by": "text",
}

# Which enrichment columns are ids that need local -> Neon remapping.
_ID_ENRICH_COLS = {
    "normalized_title_id": "normalized_title",
    "industry_id": "industry",
    "job_category_id": "job_category",
    "employment_type_id": "employment_type",
    "experience_level_id": "experience_level",
    "education_level_id": "education_level",
    "remote_work_type_id": "remote_work_type",
}


def _dsn(name: str) -> str:
    """Resolve a DSN: process env first, then the repo's .env."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    raise PushError(f"{name} not found (process env or {env_file})")


def _columns(conn: Connection, table: str) -> set[str]:
    schema, name = table.split(".")
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :name"
        ),
        {"schema": schema, "name": name},
    ).scalars()
    return set(rows)


def _insert_sql(table: str, cols: list[str], exprs: dict[str, str] | None = None,
                returning: str | None = None) -> str:
    exprs = exprs or {}
    values = ", ".join(exprs.get(c, f":{c}") for c in cols)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({values})"
    return sql + (f" RETURNING {returning}" if returning else "")


def _upsert_sql(table: str, cols: list[str], conflict_cols: list[str],
                coalesce_cols: set[str] | None = None,
                exprs: dict[str, str] | None = None) -> str:
    """INSERT .. ON CONFLICT (conflict_cols) DO UPDATE.

    ``coalesce_cols`` keep the existing Neon value when the incoming one is
    NULL (used for salary normalization, which Neon computes after the push).
    """
    coalesce_cols = coalesce_cols or set()
    exprs = exprs or {}
    values = ", ".join(exprs.get(c, f":{c}") for c in cols)
    setters = []
    for c in cols:
        if c in conflict_cols:
            continue
        if c in coalesce_cols:
            setters.append(f"{c} = COALESCE(EXCLUDED.{c}, {table}.{c})")
        else:
            setters.append(f"{c} = EXCLUDED.{c}")
    return (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({values}) "
        f"ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {', '.join(setters)}"
    )


class _RefIndex:
    """Natural-key translation between the local and Neon reference tables,
    plus create-on-demand for companies and locations.

    Local and Neon assign different ids to the same concepts (Neon's
    taxonomy is years newer: 2046 titles vs 138 locally), so ids are never
    reused across the wire -- every id goes through its natural value.
    """

    def __init__(self, local: Connection, neon: Connection, stats: dict[str, Any]):
        self._neon = neon
        self._stats = stats
        self._local_values: dict[str, dict[int, Any]] = {}
        self._neon_ids: dict[str, dict[Any, int]] = {}
        for kind, (table, id_col, key_col) in _REF_KINDS.items():
            self._local_values[kind] = {
                r[id_col]: r[key_col]
                for r in local.execute(text(f"SELECT {id_col}, {key_col} FROM {table}")).mappings()
            }
            ids: dict[Any, int] = {}
            for r in neon.execute(text(f"SELECT {id_col}, {key_col} FROM {table}")).mappings():
                ids.setdefault(r[key_col], r[id_col])  # first row wins on dup keys
            self._neon_ids[kind] = ids
        self._company_cache: dict[str, int] = {}
        self._location_cache: dict[int, int] = {}

    # -- plain reference translation ------------------------------------
    def translate(self, kind: str, local_id: int | None) -> int | None:
        if local_id is None:
            return None
        table, id_col, key_col = _REF_KINDS[kind]
        value = self._local_values[kind].get(local_id)
        if value is None:
            raise PushError(f"local {table} row {local_id} (id column {id_col}) not found")
        neon_id = self._neon_ids[kind].get(value)
        if neon_id is None:
            raise PushError(
                f"{table}.{key_col}={value!r} is used by a local row but does not exist "
                "in Neon; seed Neon's reference data before pushing"
            )
        return neon_id

    # -- companies -------------------------------------------------------
    def company_id(self, row: dict[str, Any]) -> int:
        key = row["normalized_name"]
        if key in self._company_cache:
            return self._company_cache[key]
        hit = self._neon.execute(
            text("SELECT company_id FROM core.companies WHERE normalized_name = :name LIMIT 1"),
            {"name": key},
        ).scalar()
        if hit is None:
            hit = self._neon.execute(
                text(
                    "INSERT INTO core.companies (company_name, normalized_name, logo_url) "
                    "VALUES (:company_name, :normalized_name, :logo_url) RETURNING company_id"
                ),
                {"company_name": row["company_name"], "normalized_name": key,
                 "logo_url": row.get("logo_url")},
            ).scalar()
            self._stats["companies_created"] += 1
        self._company_cache[key] = int(hit)
        return int(hit)

    # -- locations (and their city/region/country components) ------------
    def location_id(self, row: dict[str, Any]) -> int:
        cached = self._location_cache.get(row["location_id"])
        if cached is not None:
            return cached
        raw = row.get("raw_location_text")
        is_remote = bool(row.get("is_global_remote"))

        # 1. same place, same wording -> reuse.
        hit = self._neon.execute(
            text(
                "SELECT location_id FROM ref.locations "
                "WHERE raw_location_text IS NOT DISTINCT FROM :raw "
                "AND is_global_remote = :is_remote LIMIT 1"
            ),
            {"raw": raw, "is_remote": is_remote},
        ).scalar()
        if hit is None:
            country_id = self._country_id(row.get("country_name"))
            region_id = self._region_id(row.get("region_name"), row.get("region_code"), country_id)
            city_id = self._city_id(row, region_id, country_id)
            remote_type_id = self.translate("remote_work_type", row.get("remote_work_type_id"))

            # 2. The unique key on ref.locations is the component tuple, not
            #    the raw text -- if a remote-typed row already has these exact
            #    components it must be reused or the insert would violate it.
            if remote_type_id is not None:
                hit = self._neon.execute(
                    text(
                        "SELECT location_id FROM ref.locations "
                        "WHERE city_id IS NOT DISTINCT FROM :city "
                        "AND region_id IS NOT DISTINCT FROM :region "
                        "AND country_id IS NOT DISTINCT FROM :country "
                        "AND remote_work_type_id IS NOT DISTINCT FROM :rw LIMIT 1"
                    ),
                    {"city": city_id, "region": region_id, "country": country_id,
                     "rw": remote_type_id},
                ).scalar()
            if hit is None:
                hit = self._neon.execute(
                    text(
                        "INSERT INTO ref.locations "
                        "(city_id, region_id, country_id, remote_work_type_id, "
                        " raw_location_text, is_global_remote) "
                        "VALUES (:city, :region, :country, :rw, :raw, :is_remote) "
                        "RETURNING location_id"
                    ),
                    {"city": city_id, "region": region_id, "country": country_id,
                     "rw": remote_type_id, "raw": raw, "is_remote": is_remote},
                ).scalar()
                self._stats["locations_created"] += 1
            else:
                self._stats["locations_reused"] += 1
        self._location_cache[row["location_id"]] = int(hit)
        return int(hit)

    def _country_id(self, country_name: Any) -> int | None:
        if country_name is None:
            return None
        hit = self._neon.execute(
            text("SELECT country_id FROM ref.countries WHERE country_name = :name"),
            {"name": country_name},
        ).scalar()
        if hit is None:
            raise PushError(f"ref.countries has no row for {country_name!r} in Neon")
        return int(hit)

    def _region_id(self, region_name: Any, region_code: Any, country_id: int | None) -> int | None:
        if region_name is None:
            return None
        hit = self._neon.execute(
            text(
                "SELECT region_id FROM ref.regions WHERE region_name = :name "
                "AND country_id IS NOT DISTINCT FROM :country LIMIT 1"
            ),
            {"name": region_name, "country": country_id},
        ).scalar()
        if hit is None:
            hit = self._neon.execute(
                text(
                    "INSERT INTO ref.regions (region_name, country_id, region_code) "
                    "VALUES (:name, :country, :code) RETURNING region_id"
                ),
                {"name": region_name, "country": country_id, "code": region_code},
            ).scalar()
            logger.info("push: created ref.regions row {!r}", region_name)
        return int(hit)

    def _city_id(self, row: dict[str, Any], region_id: int | None, country_id: int | None) -> int | None:
        city_name = row.get("city_name")
        if city_name is None:
            return None
        if country_id is None:
            hit = self._neon.execute(
                text(
                    "SELECT city_id FROM ref.cities WHERE city_name = :name "
                    "ORDER BY (region_id IS NOT DISTINCT FROM :region) DESC LIMIT 1"
                ),
                {"name": city_name, "region": region_id},
            ).scalar()
        else:
            hit = self._neon.execute(
                text(
                    "SELECT city_id FROM ref.cities WHERE city_name = :name "
                    "AND country_id = :country "
                    "ORDER BY (region_id IS NOT DISTINCT FROM :region) DESC LIMIT 1"
                ),
                {"name": city_name, "country": country_id, "region": region_id},
            ).scalar()
        if hit is None:
            hit = self._neon.execute(
                text(
                    "INSERT INTO ref.cities (city_name, region_id, country_id, latitude, "
                    "longitude, timezone, population) "
                    "VALUES (:name, :region, :country, :lat, :lon, :tz, :pop) RETURNING city_id"
                ),
                {"name": city_name, "region": region_id, "country": country_id,
                 "lat": row.get("latitude"), "lon": row.get("longitude"),
                 "tz": row.get("timezone"), "pop": row.get("population")},
            ).scalar()
            logger.info("push: created ref.cities row {!r}", city_name)
        return int(hit)


def _load_local(source_code: str, local: Connection) -> dict[str, Any]:
    """Read every row of this source that the push will carry."""
    source_id = local.execute(
        text("SELECT source_id FROM ref.sources WHERE source_code = :code"),
        {"code": source_code},
    ).scalar()
    if source_id is None:
        raise PushError(f"source_code {source_code!r} is not in the LOCAL ref.sources table")

    jobs = [dict(r) for r in local.execute(
        text("SELECT * FROM core.jobs WHERE source_id = :source_id"), {"source_id": source_id}
    ).mappings()]
    if not jobs:
        return {"source_id": source_id, "jobs": []}
    job_ids = [j["job_id"] for j in jobs]

    location_ids = sorted({j["location_id"] for j in jobs if j.get("location_id") is not None})
    loc_cols = _columns(local, "ref.locations")
    city_cols = _columns(local, "ref.cities")
    region_cols = _columns(local, "ref.regions")

    select_geo = [
        "l.location_id", "l.raw_location_text", "l.is_global_remote",
        "l.remote_work_type_id" if "remote_work_type_id" in loc_cols else "NULL AS remote_work_type_id",
        "ci.city_name" if "city_name" in city_cols else "NULL AS city_name",
        "ci.latitude" if "latitude" in city_cols else "NULL AS latitude",
        "ci.longitude" if "longitude" in city_cols else "NULL AS longitude",
        "ci.timezone" if "timezone" in city_cols else "NULL AS timezone",
        "ci.population" if "population" in city_cols else "NULL AS population",
        "rg.region_name" if "region_name" in region_cols else "NULL AS region_name",
        "rg.region_code" if "region_code" in region_cols else "NULL AS region_code",
        "co.country_name",
    ]
    locations = [dict(r) for r in local.execute(text(
        "SELECT " + ", ".join(select_geo) + """
        FROM ref.locations l
        LEFT JOIN ref.cities ci ON ci.city_id = l.city_id
        LEFT JOIN ref.regions rg ON rg.region_id = l.region_id
        LEFT JOIN ref.countries co ON co.country_id = l.country_id
        WHERE l.location_id = ANY(:ids)"""
    ), {"ids": location_ids}).mappings()] if location_ids else []

    company_ids = sorted({j["company_id"] for j in jobs if j.get("company_id") is not None})
    companies = [dict(r) for r in local.execute(text(
        "SELECT company_id, company_name, normalized_name, logo_url "
        "FROM core.companies WHERE company_id = ANY(:ids)"
    ), {"ids": company_ids}).mappings()] if company_ids else []

    def _children(table: str) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = {}
        for r in local.execute(
            text(f"SELECT * FROM {table} WHERE job_id = ANY(:ids)"), {"ids": job_ids}
        ).mappings():
            grouped.setdefault(r["job_id"], []).append(dict(r))
        return grouped

    return {
        "source_id": source_id,
        "jobs": jobs,
        "locations": locations,
        "companies": companies,
        "descriptions": _children("core.job_descriptions"),
        "salaries": _children("salary.job_salaries"),
        "salary_history": _children("salary.salary_history"),
        "job_skills": _children("bridge.job_skills"),
        "job_categories": _children("bridge.job_categories_map"),
    }


def push(source_code: str, dry_run: bool) -> dict[str, Any]:
    local_dsn = _dsn("LOCAL_DATABASE_URL")
    neon_dsn = _dsn("NEON_DATABASE_URL")

    stats: dict[str, Any] = {
        "jobs_inserted": 0, "jobs_updated": 0, "jobs_duplicate_links": 0,
        "companies_created": 0, "locations_created": 0, "locations_reused": 0,
        "descriptions": 0, "salaries": 0, "salary_history_rows": 0,
        "job_skill_rows": 0, "job_category_rows": 0,
    }

    local = create_engine(local_dsn)
    neon = create_engine(neon_dsn)

    with local.connect() as lc:
        data = _load_local(source_code, lc)
        if not data["jobs"]:
            logger.info("nothing to push: source {!r} has no local rows", source_code)
            return stats

        with neon.connect() as nc:
            neon_source_id = nc.execute(
                text("SELECT source_id FROM ref.sources WHERE source_code = :code"),
                {"code": source_code},
            ).scalar()
            if neon_source_id is None:
                raise PushError(
                    f"source_code {source_code!r} is not in Neon's ref.sources; "
                    "run the repo's source seeding first"
                )

            # Existing Neon rows for this source, keyed by the natural key.
            existing = {
                (r["source_job_id"], r["posting_date"]): r["job_id"]
                for r in nc.execute(text(
                    "SELECT job_id, source_job_id, posting_date FROM core.jobs "
                    "WHERE source_id = :source_id"
                ), {"source_id": neon_source_id}).mappings()
            }

            local_job_cols = _columns(lc, "core.jobs")
            neon_job_cols = _columns(nc, "core.jobs")
            both = local_job_cols & neon_job_cols

            refs = _RefIndex(lc, nc, stats)

            insert_cols = [c for c in ["source_id", "source_job_id", "original_url",
                                       "company_id", "job_title", "location_id"]
                           if c in both] + [c for c in _RAW_JOB_COLS if c in both] \
                + [c for c in _ENRICH_JOB_COLS if c in both]
            # de-duplicate while preserving order (company_id etc. appear once)
            insert_cols = list(dict.fromkeys(insert_cols))

            raw_update_cols = [c for c in _RAW_JOB_COLS if c in both
                               and c not in _RAW_UPDATE_EXCLUDED]
            enrich_update_cols = [c for c in _ENRICH_JOB_COLS if c in both]

            def _job_params(job: dict[str, Any]) -> dict[str, Any]:
                params: dict[str, Any] = {c: job.get(c) for c in insert_cols}
                params["source_id"] = neon_source_id
                if job.get("company_id") is None:
                    raise PushError(
                        f"local core.jobs row {job['job_id']} has no company_id "
                        "(core.jobs.company_id is NOT NULL, so it cannot be pushed)"
                    )
                params["company_id"] = company_map.get(job["company_id"])
                params["location_id"] = location_map.get(job.get("location_id"))
                for col, kind in _ID_ENRICH_COLS.items():
                    if col in params:
                        params[col] = refs.translate(kind, job.get(col))
                return params

            insert_sql = _insert_sql("core.jobs", insert_cols, returning="job_id")
            update_setters = [f"{c} = :{c}" for c in raw_update_cols]
            update_setters += [
                "first_scraped_at = LEAST(CAST(:first_scraped_at AS timestamptz), first_scraped_at)",
                "last_scraped_at = GREATEST(CAST(:last_scraped_at AS timestamptz), last_scraped_at)",
            ]
            for c in enrich_update_cols:
                update_setters.append(
                    f"{c} = COALESCE(CAST(:{c} AS {_ENRICH_SQL_TYPE[c]}), {c})"
                )
            update_sql = (
                f"UPDATE core.jobs SET {', '.join(update_setters)} WHERE job_id = :job_id"
            )

            job_id_map: dict[int, int] = {}  # local job_id -> Neon job_id
            duplicates: list[tuple[int, int]] = []  # (local job, local canonical)

            # The preparatory SELECTs above already opened an implicit
            # (autobegin) transaction; close it before starting the explicit
            # one so begin() is legal. Only reads happened in it.
            nc.rollback()
            trans = nc.begin()
            try:
                # Company/location resolution writes (create-on-demand), so it
                # must run inside the same transaction as the jobs it feeds.
                company_map = {c["company_id"]: refs.company_id(c) for c in data["companies"]}
                location_map = {l["location_id"]: refs.location_id(l) for l in data["locations"]}

                for job in data["jobs"]:
                    key = (job["source_job_id"], job["posting_date"])
                    params = _job_params(job)
                    if key in existing:
                        nc.execute(text(update_sql), {**params, "job_id": existing[key]})
                        job_id_map[job["job_id"]] = existing[key]
                        stats["jobs_updated"] += 1
                    else:
                        new_id = nc.execute(text(insert_sql), params).scalar()
                        job_id_map[job["job_id"]] = int(new_id)
                        existing[key] = int(new_id)
                        stats["jobs_inserted"] += 1
                    if job.get("is_duplicate_of") is not None:
                        duplicates.append((job["job_id"], job["is_duplicate_of"]))

                # Duplicate links need every job mapped first (a job may point
                # at a canonical row inserted later in the loop).
                for local_job_id, local_canonical in duplicates:
                    canonical = job_id_map.get(local_canonical)
                    if canonical is None:
                        raise PushError(
                            f"core.jobs.is_duplicate_of points at local job {local_canonical}, "
                            "which is not part of this push (duplicate links must stay "
                            "inside one source's pushed rows)"
                        )
                    nc.execute(text(
                        "UPDATE core.jobs SET is_duplicate_of = :canonical "
                        "WHERE job_id = :job_id"
                    ), {"canonical": canonical, "job_id": job_id_map[local_job_id]})
                    stats["jobs_duplicate_links"] += 1

                # --- children ------------------------------------------------
                neon_desc_cols = [c for c in (_columns(lc, "core.job_descriptions")
                                              & _columns(nc, "core.job_descriptions"))
                                  if c not in ("created_at", "updated_at", "description_tsv")]
                # description_tsv is a GENERATED column in this schema
                # (to_tsvector('english', COALESCE(description_clean, ''))):
                # Postgres maintains it on insert/update, so it is never
                # written by hand -- passing it would be an error.
                desc_sql = _upsert_sql("core.job_descriptions", neon_desc_cols, ["job_id"])
                for local_jid, rows in data["descriptions"].items():
                    for row in rows:
                        params = {c: row.get(c) for c in neon_desc_cols}
                        params["job_id"] = job_id_map[local_jid]
                        nc.execute(text(desc_sql), params)
                        stats["descriptions"] += 1

                sal_cols = [c for c in (_columns(lc, "salary.job_salaries")
                                        & _columns(nc, "salary.job_salaries"))
                            if c not in ("job_salary_id", "created_at", "updated_at")]
                sal_sql = _upsert_sql(
                    "salary.job_salaries", sal_cols, ["job_id"],
                    coalesce_cols={"normalized_annual_min_usd", "normalized_annual_max_usd"}
                    & set(sal_cols),
                )
                for local_jid, rows in data["salaries"].items():
                    for row in rows:
                        params = {c: row.get(c) for c in sal_cols}
                        if "currency_id" in params:
                            params["currency_id"] = refs.translate("currency", row.get("currency_id"))
                        params["job_id"] = job_id_map[local_jid]
                        nc.execute(text(sal_sql), params)
                        stats["salaries"] += 1

                # History / skills / categories: replaced per job -- but only
                # for jobs that HAVE local rows, so Neon-side rows for jobs
                # this push doesn't own are never touched.
                hist_cols = [c for c in (_columns(lc, "salary.salary_history")
                                         & _columns(nc, "salary.salary_history"))
                             if c not in ("salary_history_id", "created_at", "updated_at")]
                for local_jid, rows in data["salary_history"].items():
                    neon_jid = job_id_map[local_jid]
                    nc.execute(text("DELETE FROM salary.salary_history WHERE job_id = :job_id"),
                               {"job_id": neon_jid})
                    for row in rows:
                        params = {c: row.get(c) for c in hist_cols}
                        if "currency_id" in params:
                            params["currency_id"] = refs.translate("currency", row.get("currency_id"))
                        params["job_id"] = neon_jid
                        nc.execute(text(_insert_sql("salary.salary_history", hist_cols)), params)
                        stats["salary_history_rows"] += 1

                skill_cols = [c for c in (_columns(lc, "bridge.job_skills")
                                          & _columns(nc, "bridge.job_skills"))
                              if c not in ("created_at", "updated_at")]
                for local_jid, rows in data["job_skills"].items():
                    neon_jid = job_id_map[local_jid]
                    nc.execute(text("DELETE FROM bridge.job_skills WHERE job_id = :job_id"),
                               {"job_id": neon_jid})
                    for row in rows:
                        params = {c: row.get(c) for c in skill_cols}
                        if "skill_id" in params:
                            params["skill_id"] = refs.translate("skill", row.get("skill_id"))
                        params["job_id"] = neon_jid
                        nc.execute(text(_insert_sql("bridge.job_skills", skill_cols)), params)
                        stats["job_skill_rows"] += 1

                cat_cols = [c for c in (_columns(lc, "bridge.job_categories_map")
                                        & _columns(nc, "bridge.job_categories_map"))
                            if c not in ("created_at", "updated_at")]
                for local_jid, rows in data["job_categories"].items():
                    neon_jid = job_id_map[local_jid]
                    nc.execute(text("DELETE FROM bridge.job_categories_map WHERE job_id = :job_id"),
                               {"job_id": neon_jid})
                    for row in rows:
                        params = {c: row.get(c) for c in cat_cols}
                        if "job_category_id" in params:
                            params["job_category_id"] = refs.translate(
                                "job_category", row.get("job_category_id"))
                        params["job_id"] = neon_jid
                        nc.execute(text(_insert_sql("bridge.job_categories_map", cat_cols)), params)
                        stats["job_category_rows"] += 1

                if dry_run:
                    trans.rollback()
                    logger.info("dry-run: rolled back everything")
                else:
                    trans.commit()
            except BaseException:
                trans.rollback()
                raise

    return stats


def _report(stats: dict[str, Any], source_code: str, dry_run: bool) -> None:
    mode = "DRY RUN (rolled back -- nothing was written)" if dry_run else "LIVE"
    line = "=" * 70
    print(line)
    print(f"  PUSH REPORT   source={source_code}   {mode}")
    print(line)
    print(f"  core.jobs                inserted={stats['jobs_inserted']:<5} updated={stats['jobs_updated']}")
    print(f"  core.companies           created={stats['companies_created']}")
    print(f"  ref.locations            created={stats['locations_created']}  reused={stats['locations_reused']}")
    print(f"  core.job_descriptions    written={stats['descriptions']}")
    print(f"  salary.job_salaries      written={stats['salaries']}")
    print(f"  salary.salary_history    rows={stats['salary_history_rows']}")
    print(f"  bridge.job_skills        rows={stats['job_skill_rows']}")
    print(f"  bridge.job_categories    rows={stats['job_category_rows']}")
    print(f"  duplicate links (is_duplicate_of) = {stats['jobs_duplicate_links']}")
    print(line)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Push locally-scraped rows into Neon (no scraping)."
    )
    parser.add_argument("--source-code", default="indeed",
                        help="ref.sources.source_code to push (default: indeed)")
    parser.add_argument("--dry-run", action="store_true",
                        help="run every step, then roll back (report only)")
    args = parser.parse_args()

    try:
        stats = push(args.source_code, dry_run=args.dry_run)
    except PushError as exc:
        logger.error("push failed: {}", exc)
        print(f"PUSH FAILED: {exc}")
        return 1
    except Exception:
        logger.exception("push failed with an unexpected error")
        return 1

    _report(stats, args.source_code, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
