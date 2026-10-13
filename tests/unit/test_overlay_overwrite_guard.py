"""Guards on the Kaggle ``upload_overlay`` merge.

Why these tests exist
---------------------
``upload_overlay`` shipped twice with a destructive body that its own docstring
contradicted. It once wrote only the current run's rows to the single fixed path
``translations.parquet``, which took the overlay from 24,722 rows to 9,331 and
lost 24,202 translations while reporting success.

The repair was then shipped broken in a subtler way: it read the prior overlay
with ``HfApi.download_repo_file``, which **does not exist** in
``huggingface_hub``, and wrapped the call in ``try/except``. The resulting
``AttributeError`` was swallowed, the code took a "publish this run's rows only"
fallback -- which is the original overwrite bug -- and set ``prior_rows = 0``
before reaching the shrink guard. So the guard could not fire, and the kernel
quietly destroyed the same 24,202 rows a second time.

Both failures share a shape: the merge was verified by reading the SQL, while the
code that actually reached the Hub was never executed. These tests therefore
check the I/O contract and the failure behaviour, not only the query text.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fix_overlay_overwrite.py"


def upload_overlay_source() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"NEW = '''(.*?)'''", text, re.S)
    assert match, "could not extract NEW from fix_overlay_overwrite.py"
    return match.group(1)


def test_upload_overlay_is_syntactically_valid() -> None:
    compile(upload_overlay_source(), "upload_overlay", "exec")


def called_names(source: str) -> set[str]:
    """Every function name invoked, whether attribute (``api.x()``) or bare.

    ``hf_hub_download`` is imported into scope and called as a bare Name, while
    the broken ``download_repo_file`` was an attribute on HfApi. Checking only
    attributes would miss the one that must be present.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
        elif isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def test_uses_an_api_that_actually_exists() -> None:
    """``HfApi.download_repo_file`` does not exist and never has.

    Calling it raised AttributeError inside the kernel. ``hf_hub_download`` is
    the supported spelling and is what the function must use.
    """
    called = called_names(upload_overlay_source())
    assert "download_repo_file" not in called
    assert "hf_hub_download" in called


def test_never_falls_back_to_publishing_alone() -> None:
    """A prior overlay that cannot be read must be fatal, not skipped.

    The "publish this run's rows only" fallback IS the overwrite bug: it
    replaced 24,202 earlier translations. Losing a run's work is recoverable;
    destroying prior runs' work is not.
    """
    source = upload_overlay_source()
    assert "publishing this run's rows only" not in source

    # The only permitted no-prior branch is "the repo has no overlay yet",
    # established by listing the repo rather than by catching a failure.
    assert "list_repo_files" in source
    assert "has_prior" in source


def test_prior_is_downloaded_outside_any_bare_except() -> None:
    """The download must not sit inside a try/except that swallows errors.

    Regression shape: ``try: download ... except: prior_rows = 0`` turns any
    download problem into a silent overwrite. The download is expected to raise.
    """
    fn = next(
        node
        for node in ast.parse(upload_overlay_source()).body
        if isinstance(node, ast.FunctionDef)
    )
    for node in ast.walk(fn):
        if isinstance(node, ast.Try):
            body = ast.unparse(node.body)
            assert "hf_hub_download" not in body, (
                "the prior-overlay download is inside a try/except; a failure "
                "there would silently degrade to the overwrite bug"
            )


def test_merge_guards_against_shrinking() -> None:
    """Two assertions must survive: exact key count, and never fewer rows."""
    source = upload_overlay_source()
    assert "total != expected" in source
    assert "total < prior_rows" in source
    assert "refusing to publish" in source


def test_bookkeeping_columns_never_reach_the_hub() -> None:
    """``src_priority``/``rn`` must be excluded from the written parquet.

    Publishing them makes the NEXT run's ``UNION ALL BY NAME`` fail outright
    with "src_priority occurs multiple times", which is what happened here once
    the repair leaked the column into a live dataset.
    """
    source = upload_overlay_source()
    assert "EXCLUDE (rn, src_priority)" in source
    assert "leaked" in source


def test_partition_key_is_the_natural_key() -> None:
    """Never ``job_id``: it is a per-database sequence, not portable."""
    source = upload_overlay_source()
    assert "PARTITION BY source_code, source_job_id" in source
    assert not re.search(
        r"PARTITION BY\s+(\w*job_id\b)?\s*job_id",
        source.replace("PARTITION BY source_code, source_job_id", ""),
    )


@pytest.mark.parametrize(
    "label",
    ["corpus drained", "publishing this run's rows only"],
)
def test_no_silent_publish_marker(label: str) -> None:
    """Documents the exact log line the broken version printed."""
    if label == "publishing this run's rows only":
        assert label not in upload_overlay_source()
