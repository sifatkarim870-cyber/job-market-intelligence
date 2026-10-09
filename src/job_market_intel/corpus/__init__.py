"""Corpus export: the analysis-ready row set that leaves Postgres for storage.

Neon Free stops accepting writes at 1 GB per project, so the corpus cannot keep
growing there. ``shard_export`` splits it by write pattern -- Postgres keeps the
relational slice (ids, taxonomy, joins), Hugging Face Parquet keeps flat
analysis-ready rows -- which measured **692 bytes/row** against ~9.8 KB/row in
the relational tables on the first export.

See :mod:`job_market_intel.corpus.shard_export` for the design notes, especially
why shard identity is ``(source_code, source_job_id)`` and never ``job_id``.
"""

from job_market_intel.corpus.shard_export import (
    DEFAULT_REPO,
    SHARD_COLUMNS,
    SHARD_SELECT,
    STATE_PATH,
    CorpusSettings,
    export_source,
    fetch_rows,
    resolve_token,
    to_arrow,
)

__all__ = [
    "DEFAULT_REPO",
    "SHARD_COLUMNS",
    "SHARD_SELECT",
    "STATE_PATH",
    "CorpusSettings",
    "export_source",
    "fetch_rows",
    "resolve_token",
    "to_arrow",
]
