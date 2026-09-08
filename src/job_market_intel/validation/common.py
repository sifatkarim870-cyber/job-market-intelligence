"""Source-agnostic batch-validation logic shared by every scraper's validator.

Where this fits: each source gets its own ``<Source>BatchValidator``
(``validation/<source>_validator.py``) that knows that source's own
plausible volume, which optional fields matter for it, and — via its own
``<Source>ValidationSettings`` — what thresholds are reasonable for it.
What every one of those validators actually *checks*, once you strip away
source-specific thresholds and field names, is the same short list of
batch-level health signals: did we get a plausible number of records, did
an unusual fraction fail per-record validation, are there duplicate
IDs within one batch, and what fraction of parsed records are missing
each field worth watching. ``validate_batch`` is that shared logic;
``BatchValidationReport`` is its shared result shape.

This mirrors ``cleaning/common.py``'s reasoning: the *shape* of "is this
batch healthy" is fully known today (it's dictated by what a scraper run
fundamentally is — a batch of records with IDs, arriving with variable
completeness — not by any particular source's feed), even though only one
source (RemoteOK) exists yet to configure it. A source's validator is
finished once it can supply its own thresholds and missing-field checks to
this function; it should not need to reimplement the arithmetic.

This module intentionally has ZERO knowledge of any specific source — no
``Raw<Source>Job`` import, no source-specific field names. That is not
just tidiness: a prior version of the RemoteOK-only validator imported
``RawRemoteOKJob`` directly for a type hint, which created a real circular
import (``scrapers.remoteok`` -> ``validation`` -> ``scrapers.remoteok``)
the moment anything imported ``job_market_intel.validation`` before
``job_market_intel.scrapers.remoteok`` — see ``remoteok_validator.py``'s
module docstring for the fix on that side. Keeping this module
structurally incapable of depending on any scraper package is what
prevents every future source's validator from reintroducing the same
cycle.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from loguru import logger
from pydantic import BaseModel


@runtime_checkable
class HasSourceJobId(Protocol):
    """Structural type for "any parsed record with a ``source_job_id``."

    A ``Protocol``, not a base class every ``Raw<Source>Job`` must
    inherit from — every source's raw-record model already independently
    defines ``source_job_id: str`` (see e.g. ``scrapers/remoteok/models.py``),
    and Python's structural typing means this module can describe "the one
    attribute I actually need" without importing any of those models,
    which is what keeps this module free of scraper-package dependencies
    (see the module docstring).
    """

    source_job_id: str


class BatchValidationReport(BaseModel):
    """Summary of one source's fetch+parse cycle health.

    Attributes:
        total_raw_records: Number of records received from the source's
            client, before per-record validation.
        total_parsed: Number of records that passed per-record validation.
        total_skipped: ``total_raw_records - total_parsed``.
        skip_rate: ``total_skipped / total_raw_records``, or ``0.0`` if
            there were no raw records at all (avoids division by zero).
        duplicate_source_job_ids: Any ``source_job_id`` values that
            appeared more than once among the *parsed* records.
        missing_field_rates: For each field checked, the fraction of
            parsed records missing that field. Purely informational —
            see ``validate_batch`` for why these aren't pass/fail criteria
            by default.
        issues: Human-readable descriptions of every problem found. Empty
            if the batch is healthy.
        passed: ``True`` if and only if ``issues`` is empty.
    """

    total_raw_records: int
    total_parsed: int
    total_skipped: int
    skip_rate: float
    duplicate_source_job_ids: list[str]
    missing_field_rates: dict[str, float]
    issues: list[str]
    passed: bool


def validate_batch(
    *,
    raw_records: Sequence[Any],
    parsed_records: Sequence[HasSourceJobId],
    missing_field_checks: Mapping[str, Callable[[Any], bool]],
    min_expected_records: int,
    max_skip_rate: float,
    source_label: str = "the source",
) -> BatchValidationReport:
    """Evaluate one source's fetch+parse cycle and produce a validation report.

    This is the source-agnostic engine behind every ``<Source>BatchValidator``.
    It checks four things, none of which are visible from any single
    record in isolation:
        - Volume sanity: is ``len(parsed_records)`` at least
          ``min_expected_records``?
        - Skip-rate sanity: did an unusually large fraction of
          ``raw_records`` fail per-record validation (i.e. never make it
          into ``parsed_records``)?
        - Within-batch duplicates: does any ``source_job_id`` appear more
          than once in ``parsed_records``? A source should never return
          the same posting twice in one response.
        - Missing-field rates: for each entry in ``missing_field_checks``,
          what fraction of ``parsed_records`` are missing that field?
          Reported as informational statistics, NOT pass/fail criteria —
          callers with an established baseline for a specific field can
          turn one into a threshold themselves; this function doesn't
          guess at what "normal" looks like for a field it knows nothing
          about.

    Args:
        raw_records: The raw records as returned by the source's client,
            before per-record validation/parsing.
        parsed_records: The records that passed per-record validation.
            Must support ``len()`` and each element must expose a
            ``source_job_id`` attribute (see ``HasSourceJobId``).
        missing_field_checks: Maps a field name to a predicate: given a
            parsed record, does it count as missing this field? Keys
            become the ``missing_field_rates`` keys in the report.
        min_expected_records: Below this many successfully parsed
            records, the batch is flagged as suspiciously small.
        max_skip_rate: Above this fraction of raw records failing
            per-record validation, the batch is flagged.
        source_label: Human-readable name of the source, used only to
            make issue/log messages specific (e.g. ``"RemoteOK"``). Purely
            cosmetic — never compared against or branched on.

    Returns:
        A ``BatchValidationReport`` describing the batch's health. Never
        raises — a validation *failure* is represented in the report's
        ``passed``/``issues`` fields, not as an exception, since a caller
        may reasonably want to log-and-continue, log-and-alert, or halt,
        and that decision belongs to the caller, not to this function.
    """
    total_raw_records = len(raw_records)
    total_parsed = len(parsed_records)
    total_skipped = total_raw_records - total_parsed
    skip_rate = (total_skipped / total_raw_records) if total_raw_records else 0.0

    id_counts = Counter(record.source_job_id for record in parsed_records)
    duplicate_source_job_ids = sorted(
        [source_job_id for source_job_id, count in id_counts.items() if count > 1]
    )

    missing_field_rates = {
        field_name: (
            sum(1 for record in parsed_records if check(record)) / total_parsed
            if total_parsed
            else 0.0
        )
        for field_name, check in missing_field_checks.items()
    }

    issues: list[str] = []

    if total_raw_records == 0:
        issues.append(
            f"Zero raw records received from {source_label}. The feed may be down, "
            "rate-limiting this client, or returning an unexpected empty response."
        )

    if total_parsed < min_expected_records:
        issues.append(
            f"Only {total_parsed} job(s) parsed successfully, below the configured "
            f"minimum of {min_expected_records}. This may indicate the feed "
            "is degraded, rate-limited, or its shape has changed."
        )

    if skip_rate > max_skip_rate:
        issues.append(
            f"Skip rate {skip_rate:.1%} exceeds the configured maximum of "
            f"{max_skip_rate:.1%}. {source_label}'s field names or "
            "required-field behavior may have changed — check the parser's "
            "WARNING-level logs for the specific validation errors."
        )

    if duplicate_source_job_ids:
        shown = duplicate_source_job_ids[:10]
        suffix = "..." if len(duplicate_source_job_ids) > 10 else ""
        issues.append(
            f"{len(duplicate_source_job_ids)} duplicate source_job_id(s) found within "
            f"a single batch: {shown}{suffix}. {source_label} should not return the same "
            "job twice in one feed response."
        )

    report = BatchValidationReport(
        total_raw_records=total_raw_records,
        total_parsed=total_parsed,
        total_skipped=total_skipped,
        skip_rate=skip_rate,
        duplicate_source_job_ids=duplicate_source_job_ids,
        missing_field_rates=missing_field_rates,
        issues=issues,
        passed=(len(issues) == 0),
    )

    if report.passed:
        logger.info(
            "{} batch validation PASSED: {} parsed, {} skipped ({:.1%} skip rate).",
            source_label,
            total_parsed,
            total_skipped,
            skip_rate,
        )
    else:
        logger.warning(
            "{} batch validation FAILED with {} issue(s): {}",
            source_label,
            len(issues),
            issues,
        )

    return report
