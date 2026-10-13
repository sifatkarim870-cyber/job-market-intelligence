"""tests/unit/test_workflows_are_valid.py

Workflow files are validated by yaml.safe_load before every deploy, and that
is not enough. PyYAML silently keeps the LAST of two duplicate mapping keys
instead of raising, so a step written with two ``env:`` blocks parses cleanly,
looks correct in review, and is rejected by GitHub only when someone tries to
dispatch it:

    HTTP 422: Invalid Argument - failed to parse workflow:
    (Line: 108, Col: 9): 'env' is already defined

That happened to all five seeded workflows at once when the DSN indirection was
introduced. The duplicate was introduced and locally "verified" in the same
edit.

These tests use a loader that rejects duplicate keys, so the failure surfaces
in the suite rather than on a dispatch.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

WORKFLOW_DIR = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows"

#: No workflow should reference the dead provider's secret.
DEAD_SECRET = "secrets.DATABASE_URL"


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that raises on a duplicate mapping key."""


def _construct_mapping(self, node, deep=False):
    seen = set()
    for key_node, _value_node in node.value:
        key = self.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(self, node, deep=deep)


StrictLoader.construct_mapping = _construct_mapping


def workflow_files() -> list[pathlib.Path]:
    return sorted(WORKFLOW_DIR.glob("*.yml"))


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_workflow_has_no_duplicate_keys(path: pathlib.Path):
    """GitHub rejects a duplicate mapping key that PyYAML happily accepts."""
    yaml.load(path.read_text(encoding="utf-8"), Loader=StrictLoader)


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_workflow_does_not_use_the_dead_neon_secret(path: pathlib.Path):
    """The Neon quota is exhausted; every reference to it is a dead branch.

    The one allowed occurrence is inside a comment explaining the history, so
    the test asserts on active uses rather than raw text.
    """
    text = path.read_text(encoding="utf-8")
    active = [
        line
        for line in text.splitlines()
        if DEAD_SECRET in line and not line.lstrip().startswith("#")
    ]
    assert not active, f"{path.name} still uses {DEAD_SECRET}: {active}"


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_steps_that_dump_a_database_name_one(path: pathlib.Path):
    """A step that actually dumps must say which database it dumps.

    A step with no DATABASE_URL/CI_DATABASE_URL silently inherits whatever the
    job set, or falls through to the local default and dumps that. That is how
    the pg_dump step kept targeting Neon after the rest of its workflow had
    moved: it carried its own hardcoded reference and nothing tied it to the
    seeded database.

    The check is on the pg_dump INVOCATION, not the mention: one step installs
    pg_dump from the PGDG repository and mentions it in a comment without ever
    connecting to anything.
    """
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job_name, job in (doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            name = step.get("name", "<unnamed>")
            run = str(step.get("run", ""))
            if '"$PG_BIN/pg_dump" -h' not in run:
                continue
            env = step.get("env") or {}
            assert "CI_DATABASE_URL" in env or "DATABASE_URL" in env, (
                f"{path.name}::{job_name}::{name} dumps without naming a DSN"
            )


@pytest.mark.parametrize("path", workflow_files(), ids=lambda p: p.name)
def test_seed_steps_name_a_dsn(path: pathlib.Path):
    """The state-snapshot restore must be told which database to restore into."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job_name, job in (doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            if "restore_state_snapshot" not in str(step.get("run", "")):
                continue
            run = str(step["run"])
            assert "--dsn" in run, (
                f"{path.name}::{job_name}::{step.get('name')} restores without --dsn, "
                "so it defaults to the laptop's DSN and fails on every runner"
            )
            assert "CI_DATABASE_URL" in (step.get("env") or {}), (
                f"{path.name}::{job_name}::{step.get('name')} restores without "
                "passing the hosted DSN in its environment"
            )
