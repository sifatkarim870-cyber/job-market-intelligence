"""Registry consistency: config/sources.json must describe reality.

Why this file exists
--------------------
``careerjunction`` shipped in PR #26 with a working scraper, 40 tests, a
``ref.sources`` row and a green PR, but was **never added to
``config/sources.json``**. Because ``scrape_html.yml`` builds its matrix from
that file::

    jq -c --arg g "$GROUP" --arg only "$ONLY" \
      '{ include: [ .sources[] | select(.group == $g and .enabled)
                   | select($only == "" or .code == $only) ] }' config/sources.json

an unregistered code yields ``{"include":[]}``, the ``scrape`` job is
**skipped**, and the workflow still reports **success**. Run 38980137741 is
exactly that: ``prepare -> success``, ``scrape -> skipped``.

A green tick that scraped nothing is worse than a red one, because it is
indistinguishable from verification by reading. These tests are the difference.

Run with:  uv run pytest tests/unit/test_source_registry.py -q
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SOURCES_JSON = REPO / "config" / "sources.json"
SCRIPTS_DIR = REPO / "scripts"
GEO = REPO / "src/job_market_intel/normalization/geographic_resolution.py"

#: One workflow per group: scrape_api.yml, scrape_html.yml, scrape_browser.yml.
#: Measured from config/sources.json on 2026-10-18.
VALID_GROUPS = {"api", "html", "browser"}


@pytest.fixture(scope="module")
def sources() -> list[dict]:
    return json.loads(SOURCES_JSON.read_text(encoding="utf-8"))["sources"]


@pytest.fixture(scope="module")
def enabled(sources: list[dict]) -> list[dict]:
    return [s for s in sources if s.get("enabled")]


class TestRegistryShape:
    def test_codes_are_unique(self, sources: list[dict]) -> None:
        """A duplicate code silently doubles a matrix row or shadows one."""
        codes = [s["code"] for s in sources]
        dupes = {c for c in codes if codes.count(c) > 1}
        assert not dupes, f"duplicate source codes: {sorted(dupes)}"

    def test_every_entry_has_the_keys_the_workflow_reads(self, sources: list[dict]) -> None:
        """scrape_html.yml selects exactly these four; a missing one is a
        matrix row with a null field, not a clear error."""
        for s in sources:
            for key in ("code", "group", "script", "timeout", "enabled"):
                assert key in s, f"{s.get('code')!r} is missing {key!r}"

    def test_group_is_one_the_workflow_dispatches(self, sources: list[dict]) -> None:
        for s in sources:
            assert s["group"] in VALID_GROUPS, f"{s['code']}: {s['group']!r}"

    def test_every_script_exists(self, sources: list[dict]) -> None:
        for s in sources:
            assert (REPO / s["script"]).is_file(), f"{s['code']}: no {s['script']}"

    def test_timeout_is_sane(self, sources: list[dict]) -> None:
        for s in sources:
            assert isinstance(s["timeout"], int) and s["timeout"] > 0, s["code"]


class TestNothingShipsUnscheduled:
    """The bug this file is about."""

    def test_every_runner_script_is_registered(self, sources: list[dict]) -> None:
        """A ``scripts/run_*_scraper.py`` that is not in sources.json at all can
        never run in CI -- and, as careerjunction proved, its workflow will still
        go green while the ``scrape`` job is skipped.

        Disabled sources count as registered: ``enabled: false`` is a
        deliberate scheduling decision, absence is a bug.
        """
        registered = {s["script"] for s in sources}
        runners = {f"scripts/{p.name}" for p in SCRIPTS_DIR.glob("run_*_scraper.py")}
        missing = sorted(runners - registered)
        assert not missing, (
            f"these scrapers exist on disk but are absent from sources.json, so "
            f"CI never runs them and reports success anyway: {missing}"
        )

    def test_registry_and_runner_scripts_are_the_same_set(self, sources: list[dict]) -> None:
        """Catches the other direction too: a registry entry pointing at a
        script that was renamed or deleted fails only at run time."""
        registered = {s["script"] for s in sources}
        runners = {f"scripts/{p.name}" for p in SCRIPTS_DIR.glob("run_*_scraper.py")}
        assert registered == runners, (
            f"only in sources.json: {sorted(registered - runners)}; "
            f"only on disk: {sorted(runners - registered)}"
        )

    def test_a_disabled_source_records_why(self, sources: list[dict]) -> None:
        """Disabling is a scheduling decision, so the reason belongs in the
        file rather than in someone's memory. Both current cases do:
        ``indeed`` needs a browser on the runner, ``net_empregos`` returns 0
        links to GitHub Actions' Azure IPs."""
        for s in sources:
            if s.get("enabled"):
                continue
            assert (REPO / s["script"]).is_file(), s["code"]
            notes = s.get("notes", "")
            assert len(notes) > 40, (
                f"{s['code']} is disabled but its notes do not explain why: {notes!r}"
            )


class TestGeographicFallback:
    """``SOURCE_HOME_COUNTRY`` is a fallback for *single-country* boards, used
    when a posting carries no usable address -- before careers24, apna,
    mustakbil, alfred, net_empregos and careerjunction were added their rows
    collapsed onto the global-remote location.

    There is deliberately **no** test asserting every enabled source appears
    here. Ten of them (remoteok, remotive, weworkremotely, wellfound,
    himalayas, themuse, glints, arbeitnow, jobicy, greenhouse) are global or
    multi-country boards, and pinning them to one country would be wrong --
    the map above would then invent a nationality the postings never claimed.
    A test encoding that belief would be worse than no test.

    What *is* checked are the two invariants that cannot rot silently.
    """

    @staticmethod
    def _home_countries() -> dict[str, str]:
        text = GEO.read_text(encoding="utf-8")
        body = text.split("SOURCE_HOME_COUNTRY", 1)[1]
        return dict(re.findall(r'"([a-z0-9_]+)":\s*"([A-Z]{2})"', body))

    def test_every_home_country_belongs_to_a_registered_source(self, sources: list[dict]) -> None:
        """A typo'd key is dead code that looks like coverage."""
        codes = {s["code"] for s in sources}
        stale = sorted(set(self._home_countries()) - codes)
        assert not stale, (
            f"SOURCE_HOME_COUNTRY maps sources that are not registered, so the "
            f"mapping can never be reached: {stale}"
        )

    def test_home_country_is_an_iso2_code(self) -> None:
        for code, iso in self._home_countries().items():
            assert re.fullmatch(r"[A-Z]{2}", iso), f"{code}: {iso!r}"

    def test_the_single_country_boards_are_all_covered(self) -> None:
        """The boards this platform added *because* their country had zero
        rows. Each one needs the fallback, because their postings sometimes
        omit the address entirely."""
        for code in (
            "careers24",
            "careerjunction",
            "apna",
            "mustakbil",
            "alfred",
            "net_empregos",
            "jobbank",
            "jobam",
            "irantalent",
            "51job",
            "emploitic",
            "hrge",
            "jobinja",
            "jobmaster",
            "jobvision",
            "myjob",
            "reed",
            "usajobs",
        ):
            assert code in self._home_countries(), (
                f"{code} is a country-specific board with no SOURCE_HOME_COUNTRY "
                f"entry, so rows missing an address collapse to global-remote"
            )
