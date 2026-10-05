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

CALIBRATION NOTE: ``MATCH_SIMILARITY_THRESHOLD`` below is a documented
starting point, NOT independently calibrated against this model's real
cosine-similarity distribution on this project's data (this environment
cannot download the real model weights to test against -- no access to
huggingface.co). A first real ``--dry-run`` against this project's
actual 350 jobs found a real, structural problem before the two-pass
matching below was added: embedding title + description combined (the
original single-pass design) diluted already-clear, correct title
matches down to the same score range as genuinely wrong matches -- e.g.
a job titled identically to a taxonomy entry scored only 0.62 combined,
when an exact match should score close to 1.0. That was a matching-logic
bug, not a threshold-tuning problem -- raising the threshold to filter
out unrelated false positives would have ALSO pushed that exact match
below the cutoff. Fixed by trying the title alone first (see
``classify_job``'s docstring for the full two-pass design). Because that
fix changes the score distribution itself, the ORIGINAL dry-run's
numbers (min=0.17, max=0.80, avg=0.47) are no longer representative --
run ``--dry-run`` again after this fix and recalibrate against the NEW
distribution before trusting this threshold in production, same
"starting point, revisit once real data is observed" caveat already
established for ``DedupSettings.posting_date_window_days`` elsewhere in
this project.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from job_market_intel.db.transaction import transaction
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_CLASSIFIED_BY = "embedding:paraphrase-multilingual-MiniLM-L12-v2:v1"
DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Starting point -- see module docstring's CALIBRATION NOTE. Cosine
# similarity from this model family for a genuinely matching short
# phrase pair is typically well above this; unrelated text typically
# scores much lower. Not yet validated against this project's real data.
MATCH_SIMILARITY_THRESHOLD = 0.55

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


def fetch_taxonomy(session: Session) -> list[TaxonomyEntry]:
    """Fetches the full curated taxonomy once per batch run -- small
    (starting at 114 rows), safe to hold entirely in memory alongside
    its embeddings for the duration of the run.
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
    (``scripts/run_translation_batch.py``, which runs before this batch
    in classify_titles.yml), falling back to the original text for
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
) -> ClassificationResult:
    """Classifies one job against the taxonomy.

    Checks the non-job deny-list FIRST, before spending an embedding
    computation on content already confirmed not worth matching --
    cheap check, meaningful savings at real batch volume.

    TWO-PASS MATCHING, confirmed necessary against a real dry run on
    this project's actual data: the first version of this function
    always embedded title + description combined, which DILUTED already
    clear, correct title matches -- a job titled identically to a
    taxonomy entry (an exact string match) scored only 0.62 combined,
    when an exact match should score close to 1.0. The fix isn't a
    different threshold value -- raising the threshold to filter out
    unrelated false positives would ALSO have pushed that exact match
    below the cutoff, since dilution affects good and bad matches alike.

    Pass 1 tries the TITLE ALONE. A clear, real title should match
    confidently on its own. Pass 2 (title + description, the original
    behavior) only runs when pass 1 isn't confident -- exactly the
    original motivating case (a garbage title needs its description to
    find any real signal), now without dragging already-clear titles
    through the same dilution.

    This does NOT fix a separate, already-acknowledged gap: a real job
    genuinely outside the taxonomy's current scope (e.g. a retail "Store
    Manager") can still land on a plausible-looking but wrong match
    (e.g. "Brand Manager") purely from generic shared business
    vocabulary, in either pass. That's the taxonomy-coverage gap noted
    elsewhere in this project's history, not something matching logic
    alone can resolve -- expanding the taxonomy is the real fix for
    that, separate from this dilution fix.
    """
    if looks_like_non_job_content(job.job_title, job.description_clean):
        return ClassificationResult(
            status="excluded_non_job", normalized_title_id=None, confidence=None
        )

    title_index, title_score = _best_taxonomy_match(job.job_title, taxonomy_embeddings, model)
    if title_score >= MATCH_SIMILARITY_THRESHOLD:
        return ClassificationResult(
            status="matched",
            normalized_title_id=taxonomy[title_index].normalized_title_id,
            confidence=round(title_score, 2),
        )

    combined_text = build_embedding_text(job.job_title, job.description_clean)
    combined_index, combined_score = _best_taxonomy_match(
        combined_text, taxonomy_embeddings, model
    )

    if combined_score >= MATCH_SIMILARITY_THRESHOLD:
        return ClassificationResult(
            status="matched",
            normalized_title_id=taxonomy[combined_index].normalized_title_id,
            confidence=round(combined_score, 2),
        )

    best_score = max(title_score, combined_score)
    return ClassificationResult(
        status="no_match", normalized_title_id=None, confidence=round(best_score, 2)
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
            "title_classified_by = :classified_by "
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

    jobs = fetch_unclassified_jobs(session)

    counts = {"matched": 0, "no_match": 0, "excluded_non_job": 0, "failed": 0}

    for job in jobs:
        try:
            with transaction(session):
                result = classify_job(job, taxonomy, taxonomy_embeddings, model)
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
