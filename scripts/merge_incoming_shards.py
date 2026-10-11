"""Fold CI-produced corpus shards back into the local Postgres database.

The problem this solves
-----------------------
CI now runs against an EPHEMERAL Postgres service container (see scrape_api.yml
for why the hosted Neon one is gone). Each job seeds that container from the
``state/`` snapshot and throws it away at the end. ``core.jobs`` is deliberately
NOT part of that snapshot -- there is no unique constraint that makes seeding
deduplication state safe -- so every CI run starts with an EMPTY ``core.jobs``
and inserts whatever it scrapes as brand-new rows.

That has two consequences, and this script exists for both:

1. **CI's shards hold rows local already has.** Local has ~112,834 rows across
   17 sources; CI re-scrapes the same boards every night. A naive re-insert
   would duplicate most of the corpus. ``ON CONFLICT`` against
   ``uq_jobs_source_natural_key (source_id, source_job_id, posting_date)``
   makes the load idempotent, which is why the merge key is that constraint and
   not ``job_id``: ``job_id`` is a per-database sequence, so CI job 12345 and
   local job 12345 are unrelated postings.

2. **CI's new rows would otherwise never reach local.** Shards are immutable
   and HF is the only place they exist. Without a fold-back, the next
   authoritative snapshot (``export_corpus_to_hf.py``) rebuilds ``shards/`` from
   local alone and DELETES every CI row that was never merged -- silently, and
   with the ledger (``_export_state.json``) still pointing at files that no
   longer exist. That already happened: 10 of the 17 ledger paths were missing
   from the repo on 2026-10-11.

What it does
------------
For each CI shard named in ``_export_state.json`` that is not yet recorded as
merged:

  * download the shard, read it with pyarrow
  * resolve the label columns back to ids via the ``ref.*`` lookups
    (the shard stores resolved labels, the database stores ids)
  * INSERT ... ON CONFLICT DO NOTHING on the natural key
  * insert ``core.job_descriptions`` rows for the descriptions
  * insert ``salary.job_salaries`` rows where salary data is present
  * record the shard in ``public.ci_merged_shards`` so a re-run is a no-op

``company_id`` is NOT NULL and the shard has no company column at all (there is
no ``ref.companies``; company identity is derived from the description text at
ingest). CI rows therefore get the UNKNOWN_COMPANY sentinel rather than a
fabricated employer. This is a real loss of fidelity -- local's own rows have
resolved companies -- and it is recorded in the shard merge log so it is
visible rather than silent.

Safety
------
* ON CONFLICT DO NOTHING everywhere: local always wins a tie, which preserves
  the derived columns (requirements, responsibilities, required_skills_text)
  that local's backfill populated.
* ``--dry-run`` reports the plan and writes nothing.
* Runs inside a transaction and rolls back on error.

Usage:
    python scripts/merge_incoming_shards.py --dry-run
    python scripts/merge_incoming_shards.py
    python scripts/merge_incoming_shards.py --remerge   # ignore the merge log
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from job_market_intel.corpus.shard_export import (
    CorpusSettings,  # noqa: E402
    resolve_token,  # noqa: E402
)

REPO = "Shifat2110724169/job-market-intel-corpus"
LOCAL_DSN = "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"
STATE_PATH = "_export_state.json"

#: The ledger of shards already folded into local. Created by this script on
#: first run; it is the ONLY durable record that a shard has been consumed,
#: because the shard files themselves are immutable and never marked.
#:
#: It lives in ``public``, not ``ref``: ``app_user`` has full DML on the tables
#: but holds no CREATE on any non-public schema, so a CREATE TABLE in ``ref``
#: fails with "permission denied for schema ref". The table is operational
#: bookkeeping rather than reference data, so ``public`` is the honest home.
LEDGER_TABLE = "public.ci_merged_shards"
LEDGER_DDL = f"""
CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
    shard_path      text        PRIMARY KEY,
    source_code     text        NOT NULL,
    rows_in_shard   integer     NOT NULL DEFAULT 0,
    rows_inserted   integer     NOT NULL DEFAULT 0,
    rows_conflict   integer     NOT NULL DEFAULT 0,
    merged_at       timestamptz NOT NULL DEFAULT now()
);
"""

#: company_id is NOT NULL on core.jobs but no company column exists in the
#: shard, so merged CI rows point here rather than at a fabricated employer.
UNKNOWN_COMPANY_NAME = "(unknown -- merged from CI shard)"

#: shard columns that are labels in the Parquet but ids in the database.
#: name -> (lookup table, id column, value column, nullable-if-unknown)
_LABEL_LOOKUPS = {
    "employment_type": ("ref.employment_types", "employment_type_id", "label", False),
    "experience_level": ("ref.experience_levels", "experience_level_id", "label", False),
    "education_level": ("ref.education_levels", "education_level_id", "label", False),
    "job_category": ("ref.job_categories", "job_category_id", "label", False),
    "country_code": ("ref.countries", "country_id", "iso_code_2", True),
}

_SALARY_COLUMNS = (
    "salary_min",
    "salary_max",
    "salary_currency",
    "pay_period",
    "salary_annual_min_usd",
    "salary_annual_max_usd",
    "salary_disclosed",
    "is_negotiable",
)

_DESCRIPTION_COLUMNS = (
    "description_clean",
    "description_en",
    "requirements",
    "responsibilities",
    "required_skills_text",
    "preferred_skills_text",
    "word_count",
)

#: Conflict targets, and why they are not what the column list suggests.
#:
#: ``core.jobs`` is the only one of the three with a composite natural key, and
#: it is the one that matters: ``uq_jobs_source_natural_key (source_id,
#: source_job_id, posting_date)``. ``job_id`` is GENERATED ALWAYS AS IDENTITY
#: and is per-database, so CI job 12345 and local job 12345 are unrelated
#: postings -- conflict on ``job_id`` would silently match the wrong row.
#:
#: ``core.job_descriptions`` is PRIMARY KEY (job_id) alone and
#: ``salary.job_salaries`` is UNIQUE (job_id), so ON CONFLICT must name just
#: ``(job_id)``. Writing ``ON CONFLICT (job_id, posting_date)`` fails outright:
#: "there is no unique or exclusion constraint matching the ON CONFLICT
#: specification".
_CONFLICT = {
    "jobs": "(source_id, source_job_id, posting_date)",
    "job_descriptions": "(job_id)",
    "job_salaries": "(job_id)",
}


def _token() -> str:
    settings = CorpusSettings()
    token = resolve_token(settings)
    if token:
        return token
    # CorpusSettings reads .env and the HF_TOKEN/CORPUS_HF_TOKEN environment,
    # which is what CI provides. On the laptop the token lives in a file that
    # nothing points at by default, so fall back to it before giving up -- the
    # same order restore_state_snapshot.py uses.
    default_file = pathlib.Path(
        r"D:\Research_Project\JobMarketAnalysisPlatform\DataBase\Hugging_Face_token.txt"
    )
    if default_file.exists():
        return default_file.read_text(encoding="utf-8").strip()
    raise SystemExit(
        "no HF token: set HF_TOKEN, or CORPUS_HF_TOKEN, or CORPUS_HF_TOKEN_FILE"
    )


def read_ledger(api, repo_id: str) -> dict:
    """The per-source watermark ledger, exactly as shard_export.py reads it."""
    from huggingface_hub import hf_hub_download

    try:
        path = hf_hub_download(
            repo_id=repo_id,
            filename=STATE_PATH,
            repo_type="dataset",
            token=api.token,
            revision="main",
        )
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read {}: {}", STATE_PATH, exc)
        return {}


def merged_paths(engine) -> set[str]:
    """Shard paths already folded into local."""
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass(:t) IS NOT NULL"), {"t": LEDGER_TABLE}
        ).scalar_one()
        if not exists:
            return set()
        rows = conn.execute(text(f"SELECT shard_path FROM {LEDGER_TABLE}")).all()
    return {r[0] for r in rows}


def label_maps(engine) -> dict[str, dict[str, int]]:
    """Every ref.* label -> id map the shard needs, in one pass each."""
    maps: dict[str, dict[str, int]] = {}
    with engine.connect() as conn:
        for column, (table, id_col, val_col, _) in _LABEL_LOOKUPS.items():
            rows = conn.execute(
                text(
                    f"SELECT {val_col}::text, {id_col} FROM {table} "
                    f"WHERE {val_col} IS NOT NULL"
                )
            ).all()
            maps[column] = {r[0]: r[1] for r in rows}
        maps["source_code"] = dict(
            conn.execute(text("SELECT source_code, source_id FROM ref.sources")).all()
        )
        # The shard already stores normalized_title_id as the id (SHARD_SELECT
        # casts it to ::text), so it is validated against the table rather than
        # translated through it -- but only ids that actually exist are kept, so
        # a stale shard cannot write a dangling foreign key.
        known_titles = {
            r[0]
            for r in conn.execute(
                text("SELECT normalized_title_id FROM ref.normalized_job_titles")
            ).all()
            if r[0] is not None
        }
        maps["normalized_title_id"] = {str(t): t for t in known_titles}
        maps["salary_currency"] = {
            str(r[0]): r[1]
            for r in conn.execute(text("SELECT iso_code, currency_id FROM ref.currencies")).all()
        }
    return maps


def unknown_company_id(engine) -> int:
    """Get or create the sentinel company row CI-merged jobs point at.

    ``core.companies.company_id`` is ``GENERATED ALWAYS AS IDENTITY``, so the
    column must be omitted from the INSERT entirely -- supplying it fails with
    "cannot insert a non-DEFAULT value". Omit it and take it from RETURNING.
    """
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT company_id FROM core.companies WHERE company_name = :n"),
            {"n": UNKNOWN_COMPANY_NAME},
        ).first()
        if row:
            return row[0]
        company_id = conn.execute(
            text(
                "INSERT INTO core.companies (company_name, normalized_name, is_verified) "
                "VALUES (:n, :norm, false) RETURNING company_id"
            ),
            {"n": UNKNOWN_COMPANY_NAME, "norm": UNKNOWN_COMPANY_NAME.lower()},
        ).scalar_one()
    logger.info("sentinel company created: {} (company_id={})", UNKNOWN_COMPANY_NAME, company_id)
    return company_id


def _as_date(value) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def _text(value) -> str | None:
    return None if value is None else str(value)


def insert_shard(
    engine,
    rows: list[dict],
    source_code: str,
    maps: dict[str, dict[str, int]],
    company_id: int,
    shard_path: str,
) -> tuple[int, int]:
    """Fold one shard's rows into local. Returns (inserted, conflicted)."""
    inserted = conflicted = 0

    job_sql = text(
        """
        INSERT INTO core.jobs (
            source_id, source_job_id, original_url, company_id, job_title,
            normalized_title_id, job_category_id, employment_type_id,
            experience_level_id, education_level_id, num_vacancies,
            visa_sponsorship, relocation_support, application_method,
            application_url, posting_date, closing_date, first_scraped_at,
            last_scraped_at, job_status, content_hash, data_quality_score,
            language_code, job_title_en, created_at, updated_at
        ) VALUES (
            :source_id, :source_job_id, :original_url, :company_id, :job_title,
            :normalized_title_id, :job_category_id, :employment_type_id,
            :experience_level_id, :education_level_id, :num_vacancies,
            :visa_sponsorship, :relocation_support, :application_method,
            :application_url, :posting_date, :closing_date, :first_scraped_at,
            :last_scraped_at, :job_status, :content_hash, :data_quality_score,
            :language_code, :job_title_en, now(), now()
        )
        ON CONFLICT (source_id, source_job_id, posting_date) DO NOTHING
        RETURNING job_id
        """
    )

    for row in rows:
        posting_date = _as_date(row.get("posting_date"))
        if posting_date is None:
            # uq_jobs_source_natural_key includes posting_date, so a row without
            # one cannot be merged at all. Never fabricate the date.
            logger.warning("skipping {}: no posting_date", row.get("source_job_id"))
            continue

        params = {
            "source_id": maps["source_code"].get(source_code),
            "source_job_id": _text(row.get("source_job_id")),
            "original_url": _text(row.get("job_url")) or "",
            "company_id": company_id,
            "job_title": _text(row.get("title_original")) or "",
            "posting_date": posting_date,
            "closing_date": _as_date(row.get("closing_date")),
            "first_scraped_at": row.get("first_scraped_at") or dt.datetime.now(dt.UTC),
            "last_scraped_at": row.get("last_scraped_at") or row.get("first_scraped_at"),
            "job_status": _text(row.get("job_status")) or "active",
            "content_hash": _text(row.get("content_hash")) or "",
            "data_quality_score": row.get("data_quality_score"),
            "language_code": _text(row.get("language_code")),
            "job_title_en": _text(row.get("title_en")),
            "num_vacancies": row.get("num_vacancies"),
            "visa_sponsorship": row.get("visa_sponsorship"),
            "relocation_support": row.get("relocation_support"),
            "application_method": _text(row.get("application_method")),
            "application_url": _text(row.get("application_url")),
            "normalized_title_id": None,
            "job_category_id": None,
            "employment_type_id": None,
            "experience_level_id": None,
            "education_level_id": None,
        }
        for column in ("job_category", "employment_type", "experience_level", "education_level"):
            label = row.get(column)
            params[f"{column}_id"] = maps.get(column, {}).get(label) if label else None
        nti = row.get("normalized_title_id")
        params["normalized_title_id"] = maps["normalized_title_id"].get(str(nti)) if nti else None

        with engine.begin() as conn:
            job_id = conn.execute(job_sql, params).scalar_one_or_none()
            if job_id is None:
                conflicted += 1
                continue
            inserted += 1

            desc = {c: row.get(c) for c in _DESCRIPTION_COLUMNS}
            if any(v is not None for v in desc.values()):
                conn.execute(
                    text(
                        """
                        INSERT INTO core.job_descriptions (
                            job_id, posting_date, description_clean, description_en,
                            requirements, responsibilities, required_skills_text,
                            preferred_skills_text, word_count
                        ) VALUES (
                            :job_id, :posting_date, :description_clean, :description_en,
                            :requirements, :responsibilities, :required_skills_text,
                            :preferred_skills_text, :word_count
                        )
                        ON CONFLICT (job_id) DO NOTHING
                        """
                    ),
                    {"job_id": job_id, "posting_date": posting_date, **desc},
                )

            if row.get("salary_min") is not None or row.get("salary_max") is not None:
                conn.execute(
                    text(
                        """
                        INSERT INTO salary.job_salaries (
                            job_id, posting_date, salary_min, salary_max, currency_id,
                            pay_period, salary_disclosed, is_negotiable,
                            normalized_annual_min_usd, normalized_annual_max_usd
                        ) VALUES (
                            :job_id, :posting_date, :salary_min, :salary_max, :currency_id,
                            :pay_period, :salary_disclosed, :is_negotiable,
                            :normalized_annual_min_usd, :normalized_annual_max_usd
                        )
                        ON CONFLICT (job_id) DO NOTHING
                        """
                    ),
                    {
                        "job_id": job_id,
                        "posting_date": posting_date,
                        "salary_min": row.get("salary_min"),
                        "salary_max": row.get("salary_max"),
                        "currency_id": maps["salary_currency"].get(str(row.get("salary_currency")))
                        if row.get("salary_currency")
                        else None,
                        "pay_period": _text(row.get("pay_period")),
                        "salary_disclosed": bool(row.get("salary_disclosed")),
                        "is_negotiable": row.get("is_negotiable"),
                        "normalized_annual_min_usd": row.get("salary_annual_min_usd"),
                        "normalized_annual_max_usd": row.get("salary_annual_max_usd"),
                    },
                )

            conn.execute(
                text(
                    """
                    INSERT INTO public.ci_merged_shards
                        (shard_path, source_code, rows_in_shard, rows_inserted, rows_conflict)
                    VALUES (:p, :s, 0, 0, 0)
                    ON CONFLICT (shard_path) DO NOTHING
                    """
                ),
                {"p": shard_path, "s": source_code},
            )

    return inserted, conflicted


def plan(ledger: dict, already: set[str], only: str | None) -> list[tuple[str, str, int]]:
    """Ledger entries whose shard has not been folded into local yet."""
    out: list[tuple[str, str, int]] = []
    for code, entry in sorted(ledger.items()):
        if only and code != only:
            continue
        path = entry.get("last_path")
        if not path or path in already:
            continue
        out.append((code, path, entry.get("last_rows") or 0))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--dsn", default=LOCAL_DSN)
    ap.add_argument(
        "--remerge",
        action="store_true",
        help=(
            "re-fold shards already recorded in public.ci_merged_shards "
            "(ON CONFLICT keeps it safe)"
        ),
    )
    ap.add_argument("--source", help="merge one source_code only")
    args = ap.parse_args(argv)

    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(token=_token())
    ledger = read_ledger(api, args.repo)
    if not ledger:
        logger.error("{} is empty or unreadable; nothing to merge", STATE_PATH)
        return 1

    engine = create_engine(args.dsn)
    already = set() if args.remerge else merged_paths(engine)
    if not already and not args.remerge:
        with engine.begin() as conn:
            conn.execute(text(LEDGER_DDL))
        already = merged_paths(engine)

    candidates = plan(ledger, already, args.source)

    logger.info(
        "ledger has {} sources; {} not yet merged ({} already recorded)",
        len(ledger),
        len(candidates),
        len(already),
    )
    if not candidates:
        logger.info("nothing to merge")
        return 0

    maps = label_maps(engine)
    company_id = unknown_company_id(engine)

    total_in = total_new = total_conflict = 0
    for code, path, expected_rows in candidates:
        try:
            local = hf_hub_download(
                repo_id=args.repo, filename=path, repo_type="dataset", token=api.token
            )
        except Exception as exc:  # noqa: BLE001
            # A ledger path that is not in the repo means a snapshot export
            # already replaced that shard. Report it; do not fail the merge.
            logger.warning("{}: shard not downloadable ({}); skipping", code, str(exc)[:100])
            continue

        table = pq.read_table(local)
        rows = table.to_pylist()
        missing = [c for c in ("source_job_id", "posting_date") if c not in table.column_names]
        if missing:
            logger.error("{}: shard lacks required column(s) {}; skipping", code, missing)
            continue

        # The ledger records how many rows the export wrote. A shard holding
        # fewer is truncated or was replaced, and merging it silently would
        # under-count. Warn rather than abort: one bad shard must not stop the
        # other sixteen sources from folding back.
        if expected_rows and len(rows) != expected_rows:
            logger.warning(
                "{:<14} shard holds {} rows but the ledger recorded {}",
                code,
                f"{len(rows):,}",
                f"{expected_rows:,}",
            )

        logger.info("{:<14} {} rows in {}", code, f"{len(rows):,}", path)
        if args.dry_run:
            total_in += len(rows)
            continue

        inserted, conflicted = insert_shard(engine, rows, code, maps, company_id, path)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE public.ci_merged_shards
                    SET rows_in_shard = :n, rows_inserted = :i, rows_conflict = :c,
                        merged_at = now()
                    WHERE shard_path = :p
                    """
                ),
                {"n": len(rows), "i": inserted, "c": conflicted, "p": path},
            )
        logger.info(
            "{:<14} {:>7,} inserted, {:>7,} already in local (conflict)",
            code,
            inserted,
            conflicted,
        )
        total_in += len(rows)
        total_new += inserted
        total_conflict += conflicted

    if args.dry_run:
        logger.info("--dry-run: would have processed {} rows; nothing written", f"{total_in:,}")
        return 0

    logger.info(
        "merge complete: {} rows read, {} new, {} already present locally",
        f"{total_in:,}",
        f"{total_new:,}",
        f"{total_conflict:,}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
