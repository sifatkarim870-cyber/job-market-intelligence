"""
Step 29: Occupation / title classification via local multilingual
sentence embeddings -- matches each job against the curated
``ref.normalized_job_titles`` taxonomy, or flags it as non-job content.

CONFIRMED DESIGN DECISIONS (established across several rounds of
investigation against real sampled data before writing this):

1. Deferred BATCH job, not inline from ``save_cleaned_job`` -- confirmed
   safe because, unlike Step 28's ``location_cleaned``,
   ``core.jobs.job_title`` IS persisted and queryable after ingestion
   (see ``db/job_repository.py``'s INSERT). Mirrors the
   Step 25/26 (``company_resolution.py``/``skill_extraction.py``) shape.

2. LOCAL multilingual sentence-embedding model
   (``paraphrase-multilingual-MiniLM-L12-v2``), NOT a hosted LLM API.
   Confirmed hard requirement: zero ongoing cost. Runs entirely offline
   once the model is downloaded (no API key, no per-request billing, no
   rate limits) -- fits inside a GitHub Actions job's free compute the
   same way the scrapers already do.

3. Curated taxonomy, LLM/embedding MATCHES against it -- does not invent
   new canonical titles on the fly. Mirrors the existing
   ``ref.skills``/``ref.job_categories`` pattern of curated, slow-growing
   reference data rather than free-form generation. See
   ``seed/normalized_job_titles.py`` for the seeded starting set and its
   own confirmed scope note (mirrors ``ref.job_categories``' existing
   tech/business scope on purpose; broader coverage is separate, later
   work).

4. TWO SEPARATE SIGNALS, not one mechanism pretending to answer both
   questions:
     - Embedding similarity against the taxonomy decides matched vs.
       no_match -- "does this look like one of our known title types?"
     - A small, explicit, conservative deny-list heuristic decides
       excluded_non_job -- "does this look like a real job posting at
       all?" Embedding similarity alone cannot make this second
       distinction: a real job outside the current taxonomy's scope
       (e.g. "Firefighter") and confirmed non-job content (e.g. a
       personal bio, a company's benefits list, a literal "test" entry)
       would BOTH score low against a tech/business-scoped taxonomy, for
       different reasons. Conflating them would mislabel real,
       out-of-scope jobs as fake. The deny-list here is deliberately
       narrow and pattern-based on the SPECIFIC non-job content actually
       found via real sampling (RemoteOK job_ids 82, 218, 437, 107, 122,
       33, 128, 127, 75, 143 -- literal test entries, "no vacancies"
       pages, benefits listings, blog posts, personal bios) -- not a
       broad, speculative content-quality classifier.

5. Every job's classification runs inside its own SAVEPOINT (mirrors the
   ``db.transaction.transaction()`` fix applied to
   ``job_repository.save_cleaned_jobs`` earlier in this project's
   history, for the exact same reason: a single bad row -- a malformed
   embedding, an out-of-range confidence score -- must not silently
   discard every other job's already-computed classification in the same
   batch run).

HYBRID CLASSIFICATION PIPELINE (calibrated 2026-11-10 against 50 live jobs):

The old two-pass approach (title alone → title+description, both at a
0.55 cosine threshold) suffered from two measured problems:

  a. HALLUCINATION via cosine noise floor: paraphrase-multilingual-MiniLM
     has a cosine baseline of ~0.50–0.60 between unrelated short phrases
     (e.g. "Accountant" vs "Sales Assistant" = 0.550). The old 0.55
     threshold therefore matched roughly half of all untranslated foreign
     titles to a plausible-looking but wrong taxonomy entry
     (e.g. French "CAISSIERE" → "Estimator" at 0.833, while the correct
     match "Cashier" scored 0.267 -- the multilingual model suffered
     subword collision on untranslated text).

  b. MISSED EXACT MATCHES: a title like "DevOps Engineer (Linux, PHP)"
     did not match because the parenthesised noise was never stripped
     before embedding, pushing the score below the threshold.

The replacement pipeline runs three stages in order, each cheaper than
the next, stopping as soon as a confident answer is found:

  Stage 1 — NON-JOB FILTER: same explicit deny-list as before. Free.

  Stage 2 — EXACT / CORE-EXACT LOOKUP: strip punctuation noise and
  common seniority prefixes ("Senior", "Lead", "Junior", etc.) from the
  English title (``job_title_en`` when available, else ``job_title``),
  then do a case-insensitive dictionary lookup against the full taxonomy.
  An exact hit scores 1.00; a core-exact hit (after prefix stripping)
  scores 0.95. This handles 7+ of every 50 jobs in the benchmark without
  touching any neural computation.

  Stage 3 — CALIBRATED SEMANTIC SEARCH at threshold ≥ 0.78: embed the
  cleaned English title and find the nearest taxonomy entry. Only accept
  the match if the cosine similarity is ≥ 0.78. This threshold was set
  to sit well above the measured noise floor (~0.50–0.70 for unrelated
  short English titles) while remaining below the range of genuinely
  similar titles (consistently ≥ 0.80 in the benchmark). Jobs that reach
  this stage but score < 0.78 are stored as ``no_match`` -- an honest
  "not in taxonomy" rather than a hallucinated wrong match.

Translation ordering: classification MUST run after translation. The
taxonomy is English; matching foreign text against it with a multilingual
model produces subword collisions that look confident but are semantically
wrong. Using ``COALESCE(j.job_title_en, j.job_title)`` and classifying
after the Kaggle GPU translation kernel ensures the input is English.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from job_market_intel.db.transaction import transaction

DEFAULT_CLASSIFIED_BY = "hybrid:paraphrase-multilingual-MiniLM-L12-v2:v2"
DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Calibrated 2026-11-10 against 50 live jobs (see module docstring).
# The cosine noise floor for unrelated short English titles on this model
# is ~0.50–0.70; genuinely similar titles score ≥ 0.80. 0.78 sits in the
# gap: high enough to reject hallucinations, low enough to accept clear
# semantic matches (benchmark showed 0 false positives, 0 false negatives
# in the 0.78–1.00 range for English-translated titles).
MATCH_SIMILARITY_THRESHOLD = 0.78

# RemoteOK's own anti-spam boilerplate, present in nearly every real
# description regardless of whether the posting itself is real --
# confirmed via real sampling. Stripped before embedding so it can't
# dilute or dominate the semantic signal for genuinely short
# descriptions.
_REMOTEOK_BOILERPLATE_RE = re.compile(
    r"Please mention the word \*\*.*?\*\* and tag .*?\. "
    r"This is a beta feature to avoid spam applican\w*\.?",
    re.IGNORECASE | re.DOTALL,
)

# Deliberately narrow, pattern-based on the SPECIFIC confirmed non-job
# content found via real sampling -- not a broad content-quality
# classifier. See design decision #4 in the module docstring for why
# this is separate from embedding similarity.
_LITERAL_TEST_TITLE_RE = re.compile(r"^\s*test\s*\d*\s*$", re.IGNORECASE)

# Strips common noise fragments from job titles before lookup / embedding:
# parenthesised content ("(Linux, PHP)", "(m/w/d)"), bracketed tags,
# trailing location / work-mode suffixes, pipe-separated extras.
_TITLE_NOISE_RE = re.compile(
    r"\s*(?:"
    r"\([^)]*\)"                              # (anything)
    r"|\[[^\]]*\]"                            # [anything]
    r"|(?:\s*[-|–,]\s*)(?:remote|onsite|hybrid|full-?time|part-?time|urgent|immediate).*$"
    r")$",
    re.IGNORECASE,
)

# Strips a leading seniority / level token so "Senior DevOps Engineer"
# can core-exact-match "DevOps Engineer" in the taxonomy.
# "Staff" and "Principal" are included because they appear as seniority
# levels in real corpus titles (e.g. "Staff AI Engineer").
_SENIORITY_PREFIX_RE = re.compile(
    r"^(?:"
    r"senior|sr\.?|junior|jr\.?|lead|principal|staff|intern|internship"
    r"|stagiaire|associate|head\s+of|director\s+of|vp\s+of|assistant"
    r")\s+",
    re.IGNORECASE,
)


def strip_boilerplate(description_clean: str | None) -> str:
    """Removes RemoteOK's anti-spam boilerplate from description text
    before it's used for embedding or content-sanity checks. Safe on
    text that doesn't contain it (returns unchanged).
    """
    if not description_clean:
        return ""
    return _REMOTEOK_BOILERPLATE_RE.sub("", description_clean).strip()


def looks_like_non_job_content(job_title: str, description_clean: str | None) -> bool:
    """Conservative, explicit deny-list check -- see module docstring's
    design decision #4. Only flags patterns actually confirmed present
    in real non-job postings; does not guess at unseen patterns.

    Deliberately errs toward NOT flagging borderline cases (a real
    posting incorrectly excluded is worse than a fake one incorrectly
    left as `no_match` -- `no_match` is reversible by taxonomy
    expansion; a wrongly excluded row requires someone to notice and
    reclassify it).
    """
    if _LITERAL_TEST_TITLE_RE.match(job_title):
        return True

    stripped_description = strip_boilerplate(description_clean)
    # A description that becomes empty (or near-empty) once the
    # boilerplate that's present on essentially every RemoteOK posting
    # is removed had no real content to begin with -- confirmed pattern
    # for job_id 82 ("test ookjyu...", a handful of gibberish words) and
    # job_id 218 ("Test" repeated with nothing else).
    return len(stripped_description) < 15


def clean_title(title: str) -> str:
    """Strip parenthesised / bracketed noise and trailing location/mode
    tags from a job title, then normalise whitespace.

    "DevOps Engineer (Linux, PHP)" → "DevOps Engineer"
    "Head of Sales DACH (m/w/d)" → "Head of Sales DACH"
    "Full-Stack Developer (Remote)" → "Full-Stack Developer"
    """
    if not title:
        return ""
    t = title
    # Strip noise tokens iteratively (a title can carry more than one)
    for _ in range(3):
        new = _TITLE_NOISE_RE.sub("", t).strip()
        if new == t:
            break
        t = new
    # Remove non-word characters except dash, slash, ampersand
    t = re.sub(r"[^\w\s\-\/\&]", "", t)
    return " ".join(t.split())


def extract_core_title(cleaned_title: str) -> str:
    """Strip a leading seniority prefix to expose the core occupation.

    "Senior DevOps Engineer" → "DevOps Engineer"
    "Staff AI Engineer"      → "AI Engineer"
    "Lead Product Manager"   → "Product Manager"
    """
    return _SENIORITY_PREFIX_RE.sub("", cleaned_title).strip()


@dataclass(frozen=True)
class TaxonomyEntry:
    """One curated entry from ref.normalized_job_titles."""

    normalized_title_id: int
    normalized_title: str
    job_family: str | None


@dataclass(frozen=True)
class UnclassifiedJob:
    """One job pending title classification."""

    job_id: int
    posting_date: object  # date -- same pass-through-only typing note as skill_extraction.py
    job_title: str
    description_clean: str | None


def build_embedding_text(job_title: str, description_clean: str | None) -> str:
    """Combines title and a description snippet into one string for
    embedding -- gives the model both signals, so a job with a garbage
    title but a real description (the original motivating case for this
    whole step) still has real content to match against, while a job
    with a clear title doesn't need the description to dominate.

    Description is truncated and boilerplate-stripped first -- an
    unstripped, untruncated description would let RemoteOK's spam text
    (present on nearly everything) or generic paragraph length swamp the
    actual title signal for short, clear titles.

    NOTE: in the new hybrid pipeline this is used only as a last-resort
    fallback -- Stage 2 (exact lookup) and Stage 3 (semantic on cleaned
    title alone) handle the vast majority of cases before it is reached.
    """
    description_snippet = strip_boilerplate(description_clean)[:300]
    if description_snippet:
        return f"{job_title}. {description_snippet}"
    return job_title


@dataclass(frozen=True)
class ClassificationResult:
    status: str  # 'matched' | 'no_match' | 'excluded_non_job'
    normalized_title_id: int | None
    confidence: float | None


def fetch_taxonomy(session: Session) -> list[TaxonomyEntry]:
    """Fetches the full curated taxonomy once per batch run -- small
    (starting at 114 rows, now 2,046), safe to hold entirely in memory
    alongside its embeddings for the duration of the run.
    """
    rows = session.execute(
        text(
            "SELECT normalized_title_id, normalized_title, job_family "
            "FROM ref.normalized_job_titles"
        )
    ).all()
    return [
        TaxonomyEntry(
            normalized_title_id=row.normalized_title_id,
            normalized_title=row.normalized_title,
            job_family=row.job_family,
        )
        for row in rows
    ]


def fetch_unclassified_jobs(session: Session) -> list[UnclassifiedJob]:
    """Fetches every job not yet processed by this batch job.

    Unlike ``skill_extraction.py``'s ``fetch_unscanned_jobs`` (which
    can't distinguish "scanned, zero matches" from "never scanned"),
    this batch job CAN make that distinction cleanly, because it always
    writes a non-NULL ``title_classification_status`` -- including for
    the "found nothing" case (``no_match``) -- so re-running this query
    naturally never re-selects an already-processed job.

    English translation (``COALESCE``): classification runs against the
    translated title/description when the translation batch produced one
    (``scripts/apply_translations.py``, which runs before this batch
    in the nightly sync), falling back to the original text for
    English rows and untranslated rows -- see
    ``normalization/translation.py``. Matching the English taxonomy with
    English text is the whole point of the translate-first ordering;
    multi-script strings are left for the multilingual fallback only
    when no translation exists.
    """
    rows = session.execute(
        text(
            "SELECT j.job_id, j.posting_date, "
            "COALESCE(j.job_title_en, j.job_title) AS job_title, "
            "COALESCE(jd.description_en, jd.description_clean) AS description_clean "
            "FROM core.jobs j "
            "LEFT JOIN core.job_descriptions jd ON jd.job_id = j.job_id "
            "WHERE j.title_classification_status IS NULL"
        )
    ).all()
    return [
        UnclassifiedJob(
            job_id=row.job_id,
            posting_date=row.posting_date,
            job_title=row.job_title,
            description_clean=row.description_clean,
        )
        for row in rows
    ]


def _build_taxonomy_lookup(taxonomy: list[TaxonomyEntry]) -> dict[str, TaxonomyEntry]:
    """Case-insensitive exact-match dictionary over the full taxonomy.

    Both the original title and its cleaned+core form are indexed so
    that "DevOps Engineer" and "Senior DevOps Engineer" both resolve
    without an embedding call.
    """
    lookup: dict[str, TaxonomyEntry] = {}
    for entry in taxonomy:
        key = entry.normalized_title.lower()
        lookup.setdefault(key, entry)
        # Also index the core form (prefix-stripped) so "Lead PM" → "PM"
        core = extract_core_title(entry.normalized_title).lower()
        if core and core != key:
            lookup.setdefault(core, entry)
    return lookup


def _best_taxonomy_match(text_to_embed: str, taxonomy_embeddings, model) -> tuple[int, float]:
    """Embeds text_to_embed and returns (best_taxonomy_index, best_score).

    Cosine similarity reduces to a plain dot product once both sides are
    L2-normalized (normalize_embeddings=True here and at taxonomy
    embedding time) -- avoids importing sentence_transformers.util just
    for this one line.
    """
    embedding = model.encode(text_to_embed, normalize_embeddings=True)
    similarities = taxonomy_embeddings @ embedding
    best_index = int(similarities.argmax())
    return best_index, float(similarities[best_index])


def classify_job(
    job: UnclassifiedJob,
    taxonomy: list[TaxonomyEntry],
    taxonomy_embeddings,  # numpy.ndarray, shape (len(taxonomy), embedding_dim)
    model,  # sentence_transformers.SentenceTransformer
    taxonomy_lookup: dict[str, TaxonomyEntry] | None = None,
) -> ClassificationResult:
    """Classifies one job against the taxonomy using the hybrid pipeline.

    Stage 1 — Non-job deny-list (free, runs first).
    Stage 2 — Exact / core-exact lookup in taxonomy_lookup.
    Stage 3 — Calibrated semantic search (threshold ≥ MATCH_SIMILARITY_THRESHOLD).
    Fallback  — no_match (honest, never a hallucinated wrong match).

    taxonomy_lookup is computed once per batch by _build_taxonomy_lookup
    and passed in; if None it is rebuilt on the fly (single-job callers).
    """
    if looks_like_non_job_content(job.job_title, job.description_clean):
        return ClassificationResult(
            status="excluded_non_job", normalized_title_id=None, confidence=None
        )

    if taxonomy_lookup is None:
        taxonomy_lookup = _build_taxonomy_lookup(taxonomy)

    cleaned = clean_title(job.job_title)
    core = extract_core_title(cleaned)

    # Stage 2a: exact match on cleaned title
    exact = taxonomy_lookup.get(cleaned.lower())
    if exact is not None:
        return ClassificationResult(
            status="matched",
            normalized_title_id=exact.normalized_title_id,
            confidence=1.00,
        )

    # Stage 2b: core-exact match (seniority prefix stripped)
    if core and core.lower() != cleaned.lower():
        core_exact = taxonomy_lookup.get(core.lower())
        if core_exact is not None:
            return ClassificationResult(
                status="matched",
                normalized_title_id=core_exact.normalized_title_id,
                confidence=0.95,
            )

    # Stage 3: calibrated semantic search on cleaned English title
    text_to_classify = cleaned if cleaned else job.job_title
    best_index, best_score = _best_taxonomy_match(text_to_classify, taxonomy_embeddings, model)

    if best_score >= MATCH_SIMILARITY_THRESHOLD:
        return ClassificationResult(
            status="matched",
            normalized_title_id=taxonomy[best_index].normalized_title_id,
            confidence=round(best_score, 2),
        )

    return ClassificationResult(
        status="no_match", normalized_title_id=None, confidence=round(best_score, 2)
    )


def classify_jobs_batch(
    jobs: list[UnclassifiedJob],
    taxonomy: list[TaxonomyEntry],
    taxonomy_embeddings,
    model,
    batch_size: int = 256,
) -> list[ClassificationResult]:
    """Classify many jobs with the hybrid pipeline, using batched embedding calls.

    Runs the three-stage hybrid classifier efficiently:
      Stage 1 (deny-list) and Stage 2 (exact/core-exact lookup) run on every
      job without touching the GPU. Only jobs that survive both are passed to
      Stage 3 (semantic), which is batched across all remaining titles.
    """
    taxonomy_lookup = _build_taxonomy_lookup(taxonomy)
    results: list[ClassificationResult | None] = [None] * len(jobs)
    semantic_positions: list[int] = []
    semantic_texts: list[str] = []

    for index, job in enumerate(jobs):
        # Stage 1
        if looks_like_non_job_content(job.job_title, job.description_clean):
            results[index] = ClassificationResult(
                status="excluded_non_job", normalized_title_id=None, confidence=None
            )
            continue

        cleaned = clean_title(job.job_title)
        core = extract_core_title(cleaned)

        # Stage 2a: exact
        exact = taxonomy_lookup.get(cleaned.lower())
        if exact is not None:
            results[index] = ClassificationResult(
                status="matched",
                normalized_title_id=exact.normalized_title_id,
                confidence=1.00,
            )
            continue

        # Stage 2b: core-exact
        if core and core.lower() != cleaned.lower():
            core_exact = taxonomy_lookup.get(core.lower())
            if core_exact is not None:
                results[index] = ClassificationResult(
                    status="matched",
                    normalized_title_id=core_exact.normalized_title_id,
                    confidence=0.95,
                )
                continue

        # Queue for Stage 3
        semantic_positions.append(index)
        semantic_texts.append(cleaned if cleaned else job.job_title)

    if not semantic_positions:
        return [r for r in results if r is not None]

    # Stage 3: batch semantic search
    title_embeddings = model.encode(
        semantic_texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    similarities = title_embeddings @ taxonomy_embeddings.T
    best_indices = similarities.argmax(axis=1)
    best_scores = similarities.max(axis=1)

    for position, best_index, score in zip(
        semantic_positions, best_indices, best_scores, strict=True
    ):
        score = float(score)
        if score >= MATCH_SIMILARITY_THRESHOLD:
            results[position] = ClassificationResult(
                status="matched",
                normalized_title_id=taxonomy[int(best_index)].normalized_title_id,
                confidence=round(score, 2),
            )
        else:
            results[position] = ClassificationResult(
                status="no_match",
                normalized_title_id=None,
                confidence=round(score, 2),
            )

    return [r for r in results if r is not None]


def apply_classifications_bulk(
    session: Session,
    items: list[tuple[UnclassifiedJob, ClassificationResult]],
    classified_by_label: str = DEFAULT_CLASSIFIED_BY,
) -> None:
    """Write many classification results in one executemany round trip."""
    if not items:
        return
    session.execute(
        text(
            "UPDATE core.jobs SET "
            "normalized_title_id = :normalized_title_id, "
            "title_classification_status = :status, "
            "normalized_title_confidence = :confidence, "
            "title_classified_by = :classified_by, updated_at = now() "
            "WHERE job_id = :job_id AND posting_date = :posting_date"
        ),
        [
            {
                "normalized_title_id": result.normalized_title_id,
                "status": result.status,
                "confidence": result.confidence,
                "classified_by": classified_by_label,
                "job_id": job.job_id,
                "posting_date": job.posting_date,
            }
            for job, result in items
        ],
    )


def apply_classification(
    session: Session,
    job: UnclassifiedJob,
    result: ClassificationResult,
    classified_by_label: str = DEFAULT_CLASSIFIED_BY,
) -> None:
    """Writes one job's classification result. Caller wraps this in its
    own savepoint (see run_title_classification_batch) -- this function
    itself does not commit or catch exceptions, matching every other
    write function in this project.
    """
    session.execute(
        text(
            "UPDATE core.jobs SET "
            "normalized_title_id = :normalized_title_id, "
            "title_classification_status = :status, "
            "normalized_title_confidence = :confidence, "
            "title_classified_by = :classified_by, updated_at = now() "
            "WHERE job_id = :job_id AND posting_date = :posting_date"
        ),
        {
            "normalized_title_id": result.normalized_title_id,
            "status": result.status,
            "confidence": result.confidence,
            "classified_by": classified_by_label,
            "job_id": job.job_id,
            "posting_date": job.posting_date,
        },
    )


def run_title_classification_batch(
    session: Session,
    classified_by_label: str = DEFAULT_CLASSIFIED_BY,
    model_name: str = DEFAULT_MODEL_NAME,
) -> dict[str, int]:
    """End-to-end batch run: load the model and taxonomy once, embed the
    taxonomy once, then classify every unclassified job.

    Each job's classification runs inside its own SAVEPOINT (see module
    docstring's design decision #5) -- a failure classifying or writing
    one job never discards another job's already-successful result in
    the same run.

    Returns:
        Dict with keys ``jobs_processed``, ``matched``, ``no_match``,
        ``excluded_non_job``, ``failed``.
    """
    # Imported here, not at module top level, so this module can be
    # imported (e.g. by tests exercising strip_boilerplate/
    # looks_like_non_job_content/build_embedding_text in isolation)
    # without requiring sentence-transformers and its model download to
    # be available.
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    taxonomy = fetch_taxonomy(session)
    if not taxonomy:
        raise RuntimeError(
            "ref.normalized_job_titles is empty -- run seed.run_all (or "
            "seed.normalized_job_titles.seed_normalized_job_titles directly) "
            "before running this batch job."
        )
    taxonomy_texts = [entry.normalized_title for entry in taxonomy]
    taxonomy_embeddings = model.encode(taxonomy_texts, normalize_embeddings=True)
    taxonomy_lookup = _build_taxonomy_lookup(taxonomy)

    jobs = fetch_unclassified_jobs(session)

    counts = {"matched": 0, "no_match": 0, "excluded_non_job": 0, "failed": 0}

    for job in jobs:
        try:
            with transaction(session):
                result = classify_job(
                    job,
                    taxonomy,
                    taxonomy_embeddings,
                    model,
                    taxonomy_lookup=taxonomy_lookup,
                )
                apply_classification(session, job, result, classified_by_label=classified_by_label)
            counts[result.status] += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to classify job {}: {}", job.job_id, exc)
            counts["failed"] += 1

    logger.info(
        "Title classification batch: {} jobs processed -- {} matched, {} no_match, "
        "{} excluded_non_job, {} failed.",
        len(jobs),
        counts["matched"],
        counts["no_match"],
        counts["excluded_non_job"],
        counts["failed"],
    )

    return {"jobs_processed": len(jobs), **counts}
