"""Merge the Neon-only rows into the local database.

Why
---
The corpus lives in three places (Neon, the laptop, Hugging Face) and the user
wants the laptop to hold every posting too, so local and HF agree row for row.
Neon holds 54,652 identities and the laptop 71,531, but they overlap on only
37,277 -- 34,375 rows exist only in Neon.

The awkward part: ``job_id`` is NOT portable. Each database has its own
sequence, so Neon job 12345 and local job 12345 are different postings. Copying
ids across would silently overwrite local rows with the wrong jobs, because the
composite primary key is (job_id, posting_date). So every copied row gets a
**fresh local id** and its child rows are re-keyed to it.

Identity for "do we already have this posting?" is the natural key
``(source_id, source_job_id, posting_date)`` -- the same key the unique
constraint enforces -- so the merge is idempotent: re-running copies nothing.

Taxonomy is remapped by its own natural codes (source_code, iso_code_2, the
ref label columns), creating local rows where a value is missing. Anything that
cannot be mapped is left NULL rather than guessed: a wrong country or salary
currency is worse than a missing one.

Cost: streaming inserts in batches, one transaction per batch, server-side
cursors on the source. No table is read into memory whole.

Usage:
    python scripts/merge_neon_into_local.py --dry-run
    python scripts/merge_neon_into_local.py --source jobinja
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from loguru import logger
from sqlalchemy import text

BATCH = 500


def neon_dsn() -> str:
    root = pathlib.Path(__file__).resolve().parents[1]
    return next(
        line.split("=", 1)[1].strip()
        for line in (root / ".env").read_text(encoding="utf-8").splitlines()
        if line.startswith("NEON_DATABASE_URL=")
    )


# ---------------------------------------------------------------- taxonomy ---
# (table, natural-key column(s), columns to copy). Missing values are created.
#
# parent_category_id is deliberately NOT copied. It is a Neon-local id, and
# inserting it verbatim violates the self-referencing foreign key -- "Key
# (parent_category_id)=(357) is not present in table". Same class of bug as
# copying job_id. The hierarchy is re-linked afterwards by CODE in
# link_category_parents().
TAXONOMY = [
    (
        "ref.sources",
        ["source_code"],
        [
            "source_name",
            "source_type",
            "base_url",
            "requires_auth",
            "terms_of_service_url",
            "trust_score",
        ],
    ),
    ("ref.countries", ["iso_code_2"], ["iso_code_3", "country_name", "continent"]),
    ("ref.employment_types", ["code"], ["label", "description", "sort_order"]),
    (
        "ref.experience_levels",
        ["code"],
        ["label", "description", "sort_order", "min_years", "max_years"],
    ),
    ("ref.education_levels", ["code"], ["label", "description", "ordinal_rank"]),
    ("ref.job_categories", ["code"], ["label", "description", "sort_order"]),
    ("ref.currencies", ["iso_code"], ["currency_name", "symbol"]),
]

JOB_COLUMNS = [
    "source_job_id",
    "posting_date",
    "closing_date",
    "job_title",
    "job_title_en",
    "language_code",
    "job_status",
    "num_vacancies",
    "visa_sponsorship",
    "relocation_support",
    "application_method",
    "application_url",
    "original_url",
    "content_hash",
    "data_quality_score",
    "source_code",
    "normalized_title_id",
    "employment_type_code",
    "experience_code",
    "education_code",
    "category_code",
    "location_raw",
]

DESC_COLUMNS = [
    "description_clean",
    "description_en",
    "requirements",
    "responsibilities",
    "required_skills_text",
    "preferred_skills_text",
    "language_requirements_text",
    "word_count",
]

SELECT_ROWS = """
SELECT j.source_job_id::text,
       j.posting_date,
       j.closing_date,
       j.job_title,
       j.job_title_en,
       j.language_code,
       j.job_status,
       j.num_vacancies,
       j.visa_sponsorship,
       j.relocation_support,
       j.application_method,
       j.application_url,
       j.original_url,
       j.content_hash,
       j.data_quality_score,
       s.source_code,
       j.normalized_title_id::text,
       et.code        AS employment_type_code,
       el.code        AS experience_code,
       ed.code        AS education_code,
       jc.code        AS category_code,
       l.raw_location_text AS location_raw,
       d.description_clean, d.description_en, d.requirements, d.responsibilities,
       d.required_skills_text, d.preferred_skills_text,
       d.language_requirements_text, d.word_count,
       sal.salary_min::float8, sal.salary_max::float8, cur.iso_code AS salary_currency,
       sal.pay_period, sal.normalized_annual_min_usd::float8,
       sal.normalized_annual_max_usd::float8, sal.salary_disclosed, sal.is_negotiable,
       co.normalized_name AS company_normalized, co.company_name AS company_name,
       co.website AS company_website, co.domain AS company_domain
FROM core.jobs j
JOIN ref.sources s ON s.source_id = j.source_id
JOIN core.companies co ON co.company_id = j.company_id
LEFT JOIN core.job_descriptions d ON d.job_id = j.job_id
LEFT JOIN ref.locations l      ON l.location_id = j.location_id
LEFT JOIN ref.employment_types et ON et.employment_type_id = j.employment_type_id
LEFT JOIN ref.experience_levels el ON el.experience_level_id = j.experience_level_id
LEFT JOIN ref.education_levels ed  ON ed.education_level_id = j.education_level_id
LEFT JOIN ref.job_categories jc    ON jc.job_category_id = j.job_category_id
LEFT JOIN LATERAL (
    SELECT * FROM salary.job_salaries s2 WHERE s2.job_id = j.job_id
    ORDER BY s2.posting_date DESC NULLS LAST, s2.job_salary_id DESC LIMIT 1
) sal ON TRUE
LEFT JOIN ref.currencies cur ON cur.currency_id = sal.currency_id
ORDER BY s.source_code, j.source_job_id
"""


#: The id column is named after the TABLE, not the key: ref.sources has
#: source_id, not sources_id (and ref.job_categories -> job_category_id).
ID_COLUMN = {
    "ref.sources": "source_id",
    "ref.countries": "country_id",
    "ref.employment_types": "employment_type_id",
    "ref.experience_levels": "experience_level_id",
    "ref.education_levels": "education_level_id",
    "ref.job_categories": "job_category_id",
    "ref.currencies": "currency_id",
}


def load_taxonomy(conn) -> dict:
    """key column value -> local id, for every taxonomy table, plus a loader."""
    mapping: dict[str, dict] = {}
    for table, keys, _cols in TAXONOMY:
        idcol = ID_COLUMN[table]
        rows = conn.execute(text(f"SELECT {', '.join(keys)}, {idcol} FROM {table}")).all()
        mapping[table] = {tuple(r[: len(keys)]): r[len(keys)] for r in rows}
        mapping[f"{table}__idcol"] = idcol
    return mapping


def ensure_taxonomy(src_conn, dst_conn, mapping: dict) -> None:
    """Create any taxonomy value present in Neon but missing locally."""
    created = 0
    for table, keys, cols in TAXONOMY:
        idcol = mapping[f"{table}__idcol"]
        for row in src_conn.execute(
            text(f"SELECT {', '.join(keys)}, {', '.join(cols)} FROM {table}")
        ).all():
            key = tuple(row[: len(keys)])
            if key in mapping[table]:
                continue
            placeholders = ", ".join(f":{c}" for c in [*keys, *cols])
            params = dict(zip([*keys, *cols], row, strict=True))
            dst_conn.execute(
                text(
                    f"INSERT INTO {table} ({', '.join([*keys, *cols])}) "
                    f"VALUES ({placeholders}) "
                    f"ON CONFLICT ({', '.join(keys)}) DO NOTHING RETURNING {idcol}"
                ),
                params,
            )
            got = dst_conn.execute(
                text(
                    f"SELECT {idcol} FROM {table} WHERE {', '.join(keys)} = "
                    f"{', '.join(f':{c}' for c in keys)}"
                ),
                dict(zip(keys, key, strict=True)),
            ).first()
            if got:
                mapping[table][key] = got[0]
                created += 1
    if created:
        dst_conn.commit()
        logger.info("taxonomy: created {} missing values", created)


def ensure_locations(src_conn, dst_conn, mapping: dict) -> None:
    """Locations have no single natural key here; match on raw text, else copy.

    ref.locations.remote_work_type_id is NOT NULL, and the local column is a
    local id, so it is resolved by CODE (rwt.code) like every other reference
    rather than copied. 'on_site' is the safe default: an unrecognised remote
    type should not be invented as 'remote'.
    """
    rwt = mapping.get("ref.remote_work_types", {})
    if not rwt:
        rows = dst_conn.execute(
            text("SELECT code, remote_work_type_id FROM ref.remote_work_types")
        ).all()
        rwt = {r[0]: r[1] for r in rows}
        mapping["ref.remote_work_types"] = rwt
    default_rwt = rwt.get("on_site") or next(iter(rwt.values()))

    existing = {
        r[0]: r[1]
        for r in dst_conn.execute(
            text("SELECT raw_location_text, location_id FROM ref.locations")
        ).all()
        if r[0]
    }
    mapping["__locations"] = existing
    added = 0
    for raw, country_iso, remote_code in src_conn.execute(
        text("""SELECT l.raw_location_text, c.iso_code_2, rwt.code
                 FROM ref.locations l
                 LEFT JOIN ref.countries c ON c.country_id = l.country_id
                 LEFT JOIN ref.remote_work_types rwt
                        ON rwt.remote_work_type_id = l.remote_work_type_id
                WHERE l.raw_location_text IS NOT NULL""")
    ).all():
        if raw in existing:
            continue
        cid = mapping["ref.countries"].get((country_iso,)) if country_iso else None
        rid = rwt.get(remote_code, default_rwt) if remote_code else default_rwt
        got = dst_conn.execute(
            text("""INSERT INTO ref.locations (raw_location_text, country_id,
                                                 remote_work_type_id, is_global_remote)
                    VALUES (:raw, :cid, :rid, false) RETURNING location_id"""),
            {"raw": raw, "cid": cid, "rid": rid},
        ).first()
        if got:
            existing[raw] = got[0]
            added += 1
    if added:
        dst_conn.commit()
        logger.info("locations: created {} missing values", added)


def link_category_parents(src_conn, dst_conn) -> int:
    """Re-attach the job-category hierarchy by CODE, after the bulk insert.

    Taxonomy rows are created with parent_category_id NULL because the Neon id
    is meaningless locally. This resolves child.code -> parent.code against the
    local table, so the hierarchy survives the merge without ever trusting a
    foreign id from the other database.
    """
    pairs = src_conn.execute(
        text("""SELECT c.code AS child_code, p.code AS parent_code
                 FROM ref.job_categories c
                 JOIN ref.job_categories p ON p.job_category_id = c.parent_category_id
                WHERE c.parent_category_id IS NOT NULL""")
    ).all()
    linked = 0
    for child_code, parent_code in pairs:
        got = dst_conn.execute(
            text("""UPDATE ref.job_categories c
                      SET parent_category_id = p.job_category_id
                     FROM ref.job_categories p
                    WHERE c.code = :child AND p.code = :parent"""),
            {"child": child_code, "parent": parent_code},
        )
        linked += got.rowcount or 0
    if linked:
        dst_conn.commit()
        logger.info("job categories: re-linked {} parent references by code", linked)
    return linked


def ensure_companies(src_conn, dst_conn, mapping: dict) -> None:
    """Map core.companies by normalized_name, creating what local lacks.

    core.jobs.company_id is NOT NULL, so every copied row needs a local company.
    company_id is another cross-database id and cannot be copied; the natural key
    is normalized_name (falling back to the lowercased name when that is NULL).
    """
    existing = {
        (r[0] or "").lower(): r[1]
        for r in dst_conn.execute(
            text("SELECT normalized_name, company_id FROM core.companies")
        ).all()
    }
    mapping["__companies"] = existing
    added = 0
    for norm, name, website, domain, iso in src_conn.execute(
        text("""SELECT co.normalized_name, co.company_name, co.website, co.domain, c.iso_code_2
                 FROM core.companies co
                 LEFT JOIN ref.countries c ON c.country_id = co.country_id""")
    ).all():
        key = (norm or name or "").lower()
        if not key or key in existing:
            continue
        cid = mapping["ref.countries"].get((iso,)) if iso else None
        got = dst_conn.execute(
            text("""INSERT INTO core.companies (company_name, normalized_name,
                                                 website, domain, country_id, is_verified)
                    VALUES (:name, :norm, :web, :dom, :cid, false)
                    ON CONFLICT DO NOTHING RETURNING company_id"""),
            {"name": name, "norm": norm or key, "web": website, "dom": domain, "cid": cid},
        ).first()
        if got:
            existing[key] = got[0]
            added += 1
    if added:
        dst_conn.commit()
        logger.info("companies: created {} missing values", added)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="limit to one source_code")
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if anything failed (default: fail open)",
    )
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine

    src = create_engine(neon_dsn())
    dst = create_engine(
        "postgresql+psycopg://app_user:changeme@localhost:5432/job_market_intelligence"
    )

    with dst.connect() as dc:
        have = {
            tuple(r)
            for r in dc.execute(
                text(
                    "SELECT s.source_code, j.source_job_id::text FROM core.jobs j "
                    "JOIN ref.sources s ON s.source_id = j.source_id"
                )
            ).all()
        }
    logger.info("local identities: {:,}", len(have))

    copied = 0
    failed = 0
    with src.connect() as sc, dst.connect() as dc:
        mapping = load_taxonomy(dc)
        if not args.dry_run:
            ensure_taxonomy(sc, dc, mapping)
            ensure_locations(sc, dc, mapping)
            ensure_companies(sc, dc, mapping)
            link_category_parents(sc, dc)

        cursor = 0
        while True:
            rows = sc.execute(
                text(SELECT_ROWS + " LIMIT :n OFFSET :o"),
                {"n": args.batch, "o": cursor},
            ).all()
            if not rows:
                break
            cursor += len(rows)
            payload = [
                r
                for r in rows
                if (r[15], r[0]) not in have  # (source_code, source_job_id)
                and (args.source is None or r[15] == args.source)
            ]
            if not payload:
                continue
            if args.dry_run:
                copied += len(payload)
                continue

            try:
                for r in payload:
                    _insert_job(dc, r, mapping)
                    have.add((r[15], r[0]))
                dc.commit()
                copied += len(payload)
            except Exception as exc:  # noqa: BLE001 - one bad row must not stop the merge
                dc.rollback()
                failed += len(payload)
                logger.warning("batch at offset {} failed ({}); continuing", cursor, exc)

    logger.info("copied {:,} rows ({} failed batches)", copied, failed)
    if failed and args.strict:
        return 1
    return 0


def _insert_job(dc, r, mapping: dict) -> None:
    """Insert one job plus its description and salary, with fresh local ids."""
    (
        source_job_id,
        posting_date,
        closing_date,
        job_title,
        job_title_en,
        language_code,
        job_status,
        num_vacancies,
        visa,
        relocation,
        app_method,
        app_url,
        original_url,
        content_hash,
        dq,
        source_code,
        norm_title,
        emp_code,
        exp_code,
        edu_code,
        cat_code,
        loc_raw,
        desc_clean,
        desc_en,
        requirements,
        responsibilities,
        req_skills,
        pref_skills,
        lang_reqs,
        word_count,
        sal_min,
        sal_max,
        sal_cur,
        pay_period,
        sal_min_usd,
        sal_max_usd,
        sal_disclosed,
        sal_negotiable,
        company_norm,
        company_name_raw,
        company_web,
        company_domain,
    ) = r

    src_id = mapping["ref.sources"][(source_code,)]
    loc_id = mapping["__locations"].get(loc_raw) if loc_raw else None
    emp_id = mapping["ref.employment_types"].get((emp_code,)) if emp_code else None
    exp_id = mapping["ref.experience_levels"].get((exp_code,)) if exp_code else None
    edu_id = mapping["ref.education_levels"].get((edu_code,)) if edu_code else None
    cat_id = mapping["ref.job_categories"].get((cat_code,)) if cat_code else None
    cur_id = mapping["ref.currencies"].get((sal_cur,)) if sal_cur else None

    # company_id is NOT NULL and is a cross-database id, so it cannot be copied.
    # Resolve by natural key, creating the company on demand so that no row can
    # fail on a missing reference.
    ckey = (company_norm or company_name_raw or "").strip().lower()
    company_id = mapping["__companies"].get(ckey)
    if company_id is None:
        if not ckey:
            raise ValueError(f"job {source_job_id} of {source_code}: no usable company identity")
        got_c = dc.execute(
            text("""INSERT INTO core.companies (company_name, normalized_name,
                                                 website, domain, is_verified)
                    VALUES (:name, :norm, :web, :dom, false)
                    ON CONFLICT DO NOTHING RETURNING company_id"""),
            {
                "name": company_name_raw or ckey,
                "norm": company_norm or ckey,
                "web": company_web,
                "dom": company_domain,
            },
        ).first()
        if got_c:
            company_id = got_c[0]
        else:
            company_id = dc.execute(
                text("SELECT company_id FROM core.companies WHERE normalized_name = :n"),
                {"n": company_norm or ckey},
            ).first()[0]
        mapping["__companies"][ckey] = company_id

    # ON CONFLICT DO NOTHING: the natural key is what makes this idempotent.
    got = dc.execute(
        text("""
            INSERT INTO core.jobs (
                source_id, source_job_id, posting_date, closing_date, job_title,
                job_title_en, language_code, job_status, num_vacancies,
                visa_sponsorship, relocation_support, application_method,
                application_url, original_url, content_hash, data_quality_score,
                location_id, employment_type_id, experience_level_id,
                education_level_id, job_category_id, company_id)
            VALUES (:sid, :sjid, :pdate, :cdate, :title, :title_en, :lang, :status,
                    :vac, :visa, :reloc, :am, :au, :url, :chash, :dq,
                    :loc, :emp, :exp, :edu, :cat, :comp)
            ON CONFLICT (source_id, source_job_id, posting_date) DO NOTHING
            RETURNING job_id"""),
        {
            "sid": src_id,
            "sjid": source_job_id,
            "pdate": posting_date,
            "cdate": closing_date,
            "title": job_title,
            "title_en": job_title_en,
            "lang": language_code,
            "status": job_status,
            "vac": num_vacancies,
            "visa": visa,
            "reloc": relocation,
            "am": app_method,
            "au": app_url,
            "url": original_url,
            "chash": content_hash,
            "dq": dq,
            "loc": loc_id,
            "emp": emp_id,
            "exp": exp_id,
            "edu": edu_id,
            "cat": cat_id,
            "comp": company_id,
        },
    ).first()
    if not got:
        return  # already present by natural key
    job_id = got[0]

    if desc_clean or desc_en:
        dc.execute(
            text("""
                INSERT INTO core.job_descriptions (
                    job_id, posting_date, description_clean, description_en,
                    requirements, responsibilities, required_skills_text,
                    preferred_skills_text, language_requirements_text, word_count)
                VALUES (:jid, :pdate, :dc, :de, :rq, :rs, :rs2, :ps2, :lr, :wc)
                ON CONFLICT DO NOTHING"""),
            {
                "jid": job_id,
                "pdate": posting_date,
                "dc": desc_clean,
                "de": desc_en,
                "rq": requirements,
                "rs": responsibilities,
                "rs2": req_skills,
                "ps2": pref_skills,
                "lr": lang_reqs,
                "wc": word_count,
            },
        )

    if sal_min is not None or sal_max is not None:
        dc.execute(
            text("""
                INSERT INTO salary.job_salaries (
                    job_id, posting_date, salary_min, salary_max, currency_id,
                    pay_period, normalized_annual_min_usd, normalized_annual_max_usd,
                    salary_disclosed, is_negotiable)
                VALUES (:jid, :pdate, :smin, :smax, :cur, :pp, :sminu, :smaxu, :disc, :neg)
                ON CONFLICT DO NOTHING"""),
            {
                "jid": job_id,
                "pdate": posting_date,
                "smin": sal_min,
                "smax": sal_max,
                "cur": cur_id,
                "pp": pay_period,
                "sminu": sal_min_usd,
                "smaxu": sal_max_usd,
                "disc": sal_disclosed,
                "neg": sal_negotiable,
            },
        )


if __name__ == "__main__":
    sys.exit(main())
