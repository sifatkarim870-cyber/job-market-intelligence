"""Every third-party import must be declared in pyproject.toml.

Why this file exists
--------------------
``duckdb`` was imported by ``scripts/sync_corpus_from_hf.py``,
``scripts/merge_incoming_shards.py`` and ``scripts/apply_translations.py``
and appeared in **no** dependency list. It worked only because somebody had
run ``uv pip install duckdb`` by hand.

On 2026-10-19 a plain ``uv sync`` pruned it, and ``run_corpus_sync.cmd``
started failing its pull half with::

    ModuleNotFoundError: No module named 'duckdb'

That sync is the thing that keeps local and Hugging Face identical. So the
failure mode is not "a script broke" -- it is "the project's core invariant
stops being maintained and nothing says so", which is the same shape as the
lxml incident this project already learned the hard way.

The audit
---------
Walks ``scripts/`` and ``src/``, collects every top-level import with
:mod:`ast`, drops the standard library and this package, and requires the rest
to appear in ``pyproject.toml`` -- as a base dependency or under an extra.

A second, non-import dependency is declared by hand and checked separately:
``pytz``, which DuckDB needs at *runtime* to read the corpus's ``TIMESTAMP WITH
TIME ZONE`` columns. No ``import pytz`` exists anywhere, so the audit above
cannot see it -- but removing it makes DuckDB raise
``UnicodeDecodeError`` on a perfectly valid shard, which reads like data
corruption rather than a missing module. The test named at the end of this
file guards both explicitly, so deleting them is a deliberate act.

Import name vs distribution name
--------------------------------
Several packages are imported under a different name than they are
distributed as. Those are listed in :data:`ALIASES` with a note, rather than
being exempted wholesale, so a genuinely new gap still fails the test.

Run with:  uv run pytest tests/unit/test_declared_dependencies.py -q
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
import tomllib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "pyproject.toml"

#: Imported name -> distribution name, when they differ.
#:
#: ``seleniumbase`` pulls in ``selenium`` as a transitive dependency and the
#: pyproject comment on the ``selenium`` extra says so explicitly, so the
#: Indeed scraper's ``import selenium`` is covered by that extra.
ALIASES: dict[str, str] = {
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "selenium": "seleniumbase",
    # sentence-transformers requires both; the translation kernel imports
    # them directly rather than through sentence_transformers.
    "torch": "sentence-transformers",
    "transformers": "sentence-transformers",
}

#: First-party modules inside scripts/ that other scripts import by name
#: rather than by path (e.g. register_source.py importing export_state_snapshot).
#: Stored normalised, the same way imports are, so the comparison is not a
#: test of underscore-vs-hyphen luck.
FIRST_PARTY_SCRIPTS: frozenset[str] = frozenset(
    p.stem.lower().replace("_", "-")
    for p in (REPO / "scripts").glob("*.py")
    if not p.stem.startswith("_")
)


def _normalise(name: str) -> str:
    return name.lower().replace("_", "-")


def _distribution_name(requirement: str) -> str:
    """``beautifulsoup4>=4.15.0`` -> ``beautifulsoup4``; ``passlib[bcrypt]`` -> ``passlib``."""
    return _normalise(re.split(r"[<>=!~\[; ]", requirement.strip(), maxsplit=1)[0])


@pytest.fixture(scope="module")
def declared() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    names: set[str] = set()
    for group in (
        data["project"].get("dependencies", []),
        *data["project"].get("optional-dependencies", {}).values(),
    ):
        names |= {_distribution_name(r) for r in group}
    return names


def _iter_source_files() -> list[pathlib.Path]:
    return [
        *sorted((REPO / "scripts").rglob("*.py")),
        *sorted((REPO / "src/job_market_intel").rglob("*.py")),
    ]


@pytest.fixture(scope="module")
def imports_by_package() -> dict[str, set[str]]:
    """Third-party top-level import name -> the files that import it."""
    stdlib = {_normalise(m) for m in sys.stdlib_module_names}
    stdlib |= {"job-market-intel", "future"}
    found: dict[str, set[str]] = {}
    for path in _iter_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                top = _normalise(name.split(".")[0])
                if top in stdlib or top.startswith("-"):
                    continue
                if top in FIRST_PARTY_SCRIPTS:
                    continue
                if (REPO / "src/job_market_intel" / name.split(".")[0]).is_dir():
                    continue
                found.setdefault(top, set()).add(rel)
    return found


class TestDeclaredDependencies:
    def test_the_audit_found_something(self, imports_by_package: dict[str, set[str]]) -> None:
        """A vacuous pass. If the walker breaks, this fails loudly."""
        assert len(imports_by_package) >= 15, (
            f"only {len(imports_by_package)} third-party packages found across "
            "scripts/ and src/ -- the AST walk is probably broken, and every "
            "other test in this file would pass for the wrong reason"
        )

    def test_every_third_party_import_is_declared(
        self, declared: set[str], imports_by_package: dict[str, set[str]]
    ) -> None:
        undeclared = {
            name: sorted(where)
            for name, where in imports_by_package.items()
            if name not in declared and ALIASES.get(name) not in declared
        }
        assert not undeclared, (
            "these packages are imported but not declared in pyproject.toml. An "
            "ad-hoc `uv pip install` is not a dependency: the next plain "
            "`uv sync` prunes it and the script fails at run time, usually "
            "somewhere far from the install.\n"
            + "\n".join(
                f"  {name} (as {ALIASES.get(name, name)}): {len(where)} file(s), e.g. {where[0]}"
                for name, where in sorted(undeclared.items())
            )
        )

    def test_aliases_all_point_at_declared_packages(self, declared: set[str]) -> None:
        """An alias to a package that is itself undeclared is just a hole."""
        missing = {imported: dist for imported, dist in ALIASES.items() if dist not in declared}
        assert not missing, f"alias targets not declared in pyproject.toml: {missing}"

    def test_the_specific_regression_that_caused_this_file(self, declared: set[str]) -> None:
        """duckdb and pytz were the two that bit. Named so removing them is deliberate."""
        for package, consumers in {
            "duckdb": [
                "scripts/sync_corpus_from_hf.py",
                "scripts/merge_incoming_shards.py",
                "scripts/apply_translations.py",
            ],
            "pytz": ["scripts/sync_corpus_from_hf.py (via DuckDB TIMESTAMPTZ)"],
        }.items():
            assert package in declared, (
                f"{package} was removed from pyproject.toml. It is needed by "
                f"{'; '.join(consumers)}. Without it the corpus sync that keeps local "
                "and Hugging Face identical fails -- and with pytz missing, DuckDB "
                "reports it as a UnicodeDecodeError on a valid file rather than "
                "saying what is actually wrong."
            )
