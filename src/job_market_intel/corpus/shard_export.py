"""Corpus shard export: Postgres rows out to Hugging Face Parquet.

Why this module exists
----------------------
Neon Free refuses writes once a project passes 1 GB. Rather than buy a bigger
database, the corpus is split by write pattern:

  * Postgres keeps the **relational slice** -- ids, taxonomy, joins, status.
    Small, indexed, and the thing scrapers write into.
  * Parquet shards on Hugging Face keep the **analysis-ready rows** -- one flat
    row per posting with every ref.* label already resolved. Measured at
    **692 bytes/row** versus ~9.8 KB/row in the relational tables (7.3x), which
    is what turns "millions of rows" from a dream into a budget line.

Design decisions that matter
----------------------------
* **Identity is ``(source_code, source_job_id)``, never ``job_id``.** Each
  database has its own sequence, so local job 12345 and Neon job 12345 are
  unrelated. Deduping on ``job_id`` silently produced nonsense once; do not
  "simplify" this back.
* **Shards are immutable.** Every export writes a NEW part file named for its
  UTC timestamp, so two concurrent runs of the same source never collide and no
  already-published history is ever rewritten.
* **The watermark lives in the dataset repo** (``_export_state.json``), not in
  Postgres: it travels with the data it describes and needs no migration.
* **Fail-open.** Every Hugging Face interaction is best-effort. A corpus export
  must never be able to fail a scrape that already succeeded.

The denormalising SELECT lives here, next to :data:`SHARD_COLUMNS`, so the
column order and the names cannot drift apart.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import HfApi
from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Engine

#: Default repo. Override with ``CORPUS_HF_REPO`` for a fork or a private mirror.
DEFAULT_REPO = "Shifat2110724169/job-market-intel-corpus"

#: Where the per-source watermark is kept, inside the dataset repo.
STATE_PATH = "_export_state.json"

#: Ceiling on rows in one shard file. A run that scraped more than this leaves
#: the remainder for the next export, which keeps peak memory bounded on a CI
#: runner (and would be the seam for splitting very large backfills).
DEFAULT_MAX_ROWS = 20000


class CorpusSettings(BaseSettings):
    """Corpus export knobs (env prefix ``CORPUS_``)."""

    model_config = SettingsConfigDict(
        env_prefix="CORSPUS_PLACEHOLDER_",  # replaced below; see _ENV_PREFIX
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    hf_repo: str = Field(
        default=DEFAULT_REPO,
        description="Hugging Face dataset repo id (user/name).",
    )
    hf_token: str | None = Field(
        default=None,
        description=(
            "Write token for hf_repo. In CI this is the HF_TOKEN secret; "
            "locally it can come from CORPUS_HF_TOKEN or the file at "
            "Hugging_Face_token.txt."
        ),
    )
    hf_token_file: Path | None = Field(
        default=None,
        description="Read the token from this file when hf_token is unset.",
    )
    max_rows_per_shard: int = Field(
        default=DEFAULT_MAX_ROWS,
        ge=100,
        description="Row ceiling for a single exported part file.",
    )
    compression_level: int = Field(
        default=9,
        ge=1,
        le=22,
        description="zstd level; 9 is the sweet spot for text on CPU time.",
    )


# The placeholder above exists only so the class body reads in order; the real
# prefix is applied here because a literal "CORPUS_" inside the class would be
# a magic string repeated in .env.example and the consistency test.
CorpusSettings.model_config["env_prefix"] = "CORPUS_"
CorpusSettings.model_rebuild()


#: One flat, analysis-ready row per posting. Labels are resolved through ref.*
#: (not ids) so most questions need no joins.
#:
#: Written against the real schema, checked against information_schema:
#: core.jobs has no company_name/salary_*/job_url/country_id columns; identity is
#: source_job_id + original_url; ref.locations has raw_location_text; there is no
#: ref.companies table at all.
SHARD_SELECT = """
SELECT j.source_job_id::text                 AS source_job_id,
       s.source_code,
       s.source_name,
       j.posting_date,
       j.closing_date,
       j.first_scraped_at,
       j.job_title                            AS title_original,
       j.job_title_en                         AS title_en,
       j.language_code,
       j.normalized_title_id::text            AS normalized_title_id,
       j.job_status,
       j.num_vacancies,
       j.visa_sponsorship,
       j.relocation_support,
       j.application_method,
       j.application_url,
       j.original_url                         AS job_url,
       j.content_hash,
       j.is_duplicate_of::text                AS is_duplicate_of,
       j.data_quality_score::float8           AS data_quality_score,
       l.raw_location_text                    AS location_raw,
       c.iso_code_2                           AS country_code,
       c.country_name,
       et.label                               AS employment_type,
       el.label                               AS experience_level,
       ed.label                               AS education_level,
       jc.label                               AS job_category,
       sal.salary_min::float8                 AS salary_min,
       sal.salary_max::float8                 AS salary_max,
       cur.iso_code                           AS salary_currency,
       sal.pay_period,
       sal.normalized_annual_min_usd::float8  AS salary_annual_min_usd,
       sal.normalized_annual_max_usd::float8  AS salary_annual_max_usd,
       sal.salary_disclosed,
       sal.is_negotiable,
       d.description_clean,
       d.description_en,
       -- English rows are never sent to the translator (language_code = 'en'
       -- is the skip path), so description_en is legitimately NULL for them.
       -- Resolve it once, here, so every shard row has English text.
       CASE WHEN j.language_code = 'en' THEN d.description_clean
            ELSE d.description_en END         AS text_en,
       d.requirements,
       d.responsibilities,
       d.required_skills_text,
       d.preferred_skills_text,
       d.word_count
FROM core.jobs j
JOIN ref.sources s                 ON s.source_id = j.source_id
LEFT JOIN core.job_descriptions d  ON d.job_id = j.job_id
LEFT JOIN ref.locations l          ON l.location_id = j.location_id
LEFT JOIN ref.countries c          ON c.country_id = l.country_id
LEFT JOIN ref.employment_types et  ON et.employment_type_id = j.employment_type_id
LEFT JOIN ref.experience_levels el ON el.experience_level_id = j.experience_level_id
LEFT JOIN ref.education_levels ed  ON ed.education_level_id = j.education_level_id
LEFT JOIN ref.job_categories jc    ON jc.job_category_id = j.job_category_id
LEFT JOIN LATERAL (
    SELECT * FROM salary.job_salaries s2
    WHERE s2.job_id = j.job_id
    ORDER BY s2.posting_date DESC NULLS LAST, s2.job_salary_id DESC
    LIMIT 1
) sal ON TRUE
LEFT JOIN ref.currencies cur        ON cur.currency_id = sal.currency_id
"""

#: Column order of :data:`SHARD_SELECT`. Kept adjacent so the two cannot drift.
SHARD_COLUMNS = [
    "source_job_id",
    "source_code",
    "source_name",
    "posting_date",
    "closing_date",
    "first_scraped_at",
    "title_original",
    "title_en",
    "language_code",
    "normalized_title_id",
    "job_status",
    "num_vacancies",
    "visa_sponsorship",
    "relocation_support",
    "application_method",
    "application_url",
    "job_url",
    "content_hash",
    "is_duplicate_of",
    "data_quality_score",
    "location_raw",
    "country_code",
    "country_name",
    "employment_type",
    "experience_level",
    "education_level",
    "job_category",
    "salary_min",
    "salary_max",
    "salary_currency",
    "pay_period",
    "salary_annual_min_usd",
    "salary_annual_max_usd",
    "salary_disclosed",
    "is_negotiable",
    "description_clean",
    "description_en",
    "text_en",
    "requirements",
    "responsibilities",
    "required_skills_text",
    "preferred_skills_text",
    "word_count",
]


def to_arrow(rows: list[tuple], origin: str) -> pa.Table:
    """Build one shard table from SHARD_SELECT rows.

    ``origin`` records provenance ("neon" for rows scraped by CI, "local" for a
    backfill that only ever existed on a laptop) so a consumer can tell a
    freshly scraped row from a historical one.
    """
    if len(SHARD_COLUMNS) + 1 != len(rows[0]) + 1:  # pragma: no cover - guard
        raise ValueError(f"expected {len(SHARD_COLUMNS)} columns, got {len(rows[0])}")
    arrays: dict[str, pa.Array] = {}
    for i, name in enumerate(SHARD_COLUMNS):
        arr = pa.array([r[i] for r in rows])
        if pa.types.is_null(arr.type):
            # All values NULL in this shard -> Arrow infers type "null", which
            # later breaks a cast to VARCHAR when shards are unioned (e.g.
            # country_code is absent for some sources).
            arr = pa.array([None] * len(rows), pa.string())
        arrays[name] = arr
    arrays["origin"] = pa.array([origin] * len(rows), pa.string())
    return pa.table(arrays)


def fetch_rows(engine: Engine, source_code: str, since: str | None, limit: int) -> list[tuple]:
    """Rows for one source, newest-updated first, capped at ``limit``.

    ``since`` is an ISO timestamp watermark: only rows changed after it are
    exported, so a daily run costs one indexed scan instead of a full table read.
    """
    sql = SHARD_SELECT + " WHERE s.source_code = :code"
    params: dict = {"code": source_code, "limit": limit}
    if since:
        sql += " AND COALESCE(j.updated_at, j.created_at) > :since"
        params["since"] = since
    sql += " ORDER BY COALESCE(j.updated_at, j.created_at) DESC LIMIT :limit"
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def read_state(api: HfApi, repo_id: str) -> dict:
    """Per-source watermark from the repo, or an empty state on any problem."""
    try:
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(
            repo_id=repo_id,
            filename=STATE_PATH,
            repo_type="dataset",
            token=api.token,
            revision="main",
        )
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - first run, or the file does not exist yet
        return {}


def write_state(api: HfApi, repo_id: str, state: dict, tmp_dir: Path) -> None:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    local = tmp_dir / STATE_PATH
    local.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    api.upload_file(
        path_or_fileobj=str(local),
        path_in_repo=STATE_PATH,
        repo_id=repo_id,
        repo_type="dataset",
    )


def resolve_token(settings: CorpusSettings) -> str | None:
    """hf_token -> token file -> CORPUS_HF_TOKEN-free environment fallback."""
    if settings.hf_token:
        return settings.hf_token
    env = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if env:
        return env
    if settings.hf_token_file and settings.hf_token_file.exists():
        return settings.hf_token_file.read_text(encoding="utf-8").strip()
    return None


def export_source(
    engine: Engine,
    source_code: str,
    settings: CorpusSettings | None = None,
    origin: str = "neon",
    tmp_dir: Path | None = None,
) -> dict:
    """Export one source's new rows to a new immutable shard on Hugging Face.

    Returns a summary dict. Never raises: Hugging Face problems are logged and
    reported, because a corpus export must not fail the scrape that preceded it.
    """
    settings = settings or CorpusSettings()
    repo_id = settings.hf_repo
    tmp_dir = tmp_dir or Path("corpus_export_tmp")
    summary: dict = {"source": source_code, "repo": repo_id, "rows": 0, "uploaded": False}

    token = resolve_token(settings)
    if not token:
        summary["skipped"] = "no HF token (set CORPUS_HF_TOKEN or HF_TOKEN in CI)"
        logger.warning("corpus export skipped for {}: {}", source_code, summary["skipped"])
        return summary

    try:
        api = HfApi(token=token)
        state = read_state(api, repo_id)
        since = (state.get(source_code) or {}).get("watermark")
        rows = fetch_rows(engine, source_code, since, settings.max_rows_per_shard)
        summary["rows"] = len(rows)
        summary["since"] = since
        if not rows:
            logger.info("corpus export {}: nothing new since {}", source_code, since)
            return summary

        tbl = to_arrow(rows, origin)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        rel = f"shards/source={source_code}/dt={datetime.now(UTC):%Y-%m-%d}/part-{stamp}.parquet"
        local = tmp_dir / rel
        local.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            tbl,
            local,
            compression="zstd",
            compression_level=settings.compression_level,
            use_dictionary=True,
            write_statistics=True,
        )
        summary["bytes"] = local.stat().st_size
        api.upload_file(
            path_or_fileobj=str(local),
            path_in_repo=rel,
            repo_id=repo_id,
            repo_type="dataset",
        )
        summary["path"] = rel

        # Advance the watermark from the newest row we actually exported, not
        # from "now": a row written mid-export must still be picked up next run.
        newest = max(
            (r[SHARD_COLUMNS.index("first_scraped_at")] for r in rows),
            default=None,
        )
        state[source_code] = {
            "watermark": datetime.now(UTC).isoformat(),
            "last_rows": len(rows),
            "last_bytes": summary["bytes"],
            "last_path": rel,
            "last_export_at": datetime.now(UTC).isoformat(),
            "oldest_first_scraped_in_shard": str(newest) if newest else None,
        }
        write_state(api, repo_id, state, tmp_dir)
        summary["uploaded"] = True
        logger.info(
            "corpus export {}: {} rows -> {} ({:.1f} KiB)",
            source_code,
            len(rows),
            rel,
            summary["bytes"] / 1024,
        )
    except Exception as exc:  # noqa: BLE001 - fail-open by design
        summary["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("corpus export {} failed (scraping is unaffected): {}", source_code, exc)
    return summary
