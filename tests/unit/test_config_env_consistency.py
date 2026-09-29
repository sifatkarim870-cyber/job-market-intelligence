"""tests/unit/test_config_env_consistency.py

Step 15 guard test: every environment variable actually read by the
application's settings classes must be documented (commented or live) in
.env.example.

Why this exists
----------------
While building Step 15 we found that ``db.config.get_database_config()``
read ``DB_MAX_OVERFLOW`` while ``.env.example`` documented (correctly)
``DB_POOL_MAX_OVERFLOW`` — a silent mismatch meaning setting the
documented variable had no effect. Nothing caught it because nothing
checked the two against each other. This test is that check, in the same
spirit as ``test_import_order.py``'s regression test for the Step 14
circular-import bug: guard a specific, previously-real bug class going
forward, rather than trust that fixing it once is enough.

What this does NOT check
--------------------------
The reverse direction — every variable in ``.env.example`` has a real
implementation — is deliberately not asserted. ``.env.example``
intentionally documents reserved-but-not-yet-built variables for future
steps (API, dashboard, partition maintenance). Only "code reads X" =>
"X is documented somewhere in .env.example" is checked.
"""

from __future__ import annotations

import re
from pathlib import Path

import job_market_intel.db.config as db_config_module
from job_market_intel.common.config import Settings
from job_market_intel.db.config import KNOWN_ENV_VARS as DB_KNOWN_ENV_VARS
from job_market_intel.scheduler.config import SchedulerSettings
from job_market_intel.scrapers.indeed.config import IndeedSettings
from job_market_intel.scrapers.reed.config import ReedSettings
from job_market_intel.scrapers.remoteok.config import RemoteOKSettings
from job_market_intel.validation.indeed_validator import IndeedValidationSettings
from job_market_intel.validation.reed_validator import ReedValidationSettings
from job_market_intel.validation.remoteok_validator import RemoteOKValidationSettings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"

# Matches "VAR=" or "# VAR=" at the start of a line (commented-but-documented
# entries count as documented — they're still visible to a collaborator
# reading the file).
_ENV_LINE_RE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)

# Matches the literal env-var-name argument of every _env_int(...),
# _env_bool(...), or os.getenv(...) call in db.config's source — i.e. what
# the module *actually* reads at runtime, independent of whatever
# KNOWN_ENV_VARS happens to (correctly or incorrectly) claim.
_DB_CONFIG_CALL_RE = re.compile(r'(?:_env_int|_env_bool|os\.getenv)\(\s*"([A-Z][A-Z0-9_]*)"')


def _documented_vars() -> set[str]:
    """Every variable name mentioned in .env.example, commented or not."""
    content = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    return set(_ENV_LINE_RE.findall(content))


def _pydantic_settings_env_vars(settings_cls: type) -> set[str]:
    """Derives the env var name for every field on a pydantic-settings
    class from its env_prefix + field name — the convention every
    ``*Settings`` class in this codebase follows (no per-field aliases
    used anywhere currently, so this simple derivation is accurate; if
    that ever changes, this helper needs to grow accordingly).
    """
    prefix = settings_cls.model_config.get("env_prefix", "") or ""
    return {f"{prefix}{field_name}".upper() for field_name in settings_cls.model_fields}


def _db_config_source_derived_vars() -> set[str]:
    """Parses db/config.py's own source and returns every env var name it
    actually reads, by inspecting the real ``_env_int``/``_env_bool``/
    ``os.getenv`` call sites — not the hand-maintained ``KNOWN_ENV_VARS``
    list. This is deliberately independent of ``KNOWN_ENV_VARS`` so that
    if the two ever drift (someone changes a call site but forgets to
    update the list, exactly the shape of the original DB_MAX_OVERFLOW
    bug one level removed), a test here fails instead of both silently
    agreeing with each other while being wrong.
    """
    source = Path(db_config_module.__file__).read_text(encoding="utf-8")
    return set(_DB_CONFIG_CALL_RE.findall(source))


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE_PATH.is_file(), ".env.example is missing from the project root."


def test_every_common_config_var_is_documented() -> None:
    missing = _pydantic_settings_env_vars(Settings) - _documented_vars()
    assert not missing, (
        f"common.config.Settings reads {sorted(missing)}, but .env.example "
        "does not mention them. Add a documented (or commented) entry."
    )


def test_db_config_known_env_vars_list_matches_the_real_source() -> None:
    """KNOWN_ENV_VARS is a hand-maintained convenience list for humans
    reading db/config.py. Keep it honest: it must exactly match what the
    module's own _env_int/_env_bool/os.getenv calls actually reference.
    """
    declared = set(DB_KNOWN_ENV_VARS)
    actual = _db_config_source_derived_vars()
    assert declared == actual, (
        f"db.config.KNOWN_ENV_VARS ({sorted(declared)}) has drifted from "
        f"the env vars its code actually reads ({sorted(actual)}). "
        f"Only in declared: {sorted(declared - actual)}. "
        f"Only in actual code: {sorted(actual - declared)}."
    )


def test_every_db_config_var_is_documented() -> None:
    """Checks the *source-derived* set (what the code really reads), not
    the hand-maintained KNOWN_ENV_VARS list, so this test still catches a
    doc/code mismatch even if KNOWN_ENV_VARS itself were wrong or stale.
    """
    missing = _db_config_source_derived_vars() - _documented_vars()
    assert not missing, (
        f"db.config actually reads {sorted(missing)}, but .env.example "
        "does not mention them. Add a documented (or commented) entry. "
        "This is exactly the class of bug DB_MAX_OVERFLOW vs. "
        "DB_POOL_MAX_OVERFLOW was — see db.config's module docstring."
    )


def test_every_remoteok_settings_var_is_documented() -> None:
    missing = _pydantic_settings_env_vars(RemoteOKSettings) - _documented_vars()
    assert not missing, f"RemoteOKSettings reads {sorted(missing)}, undocumented in .env.example."


def test_every_remoteok_validation_settings_var_is_documented() -> None:
    missing = _pydantic_settings_env_vars(RemoteOKValidationSettings) - _documented_vars()
    assert not missing, (
        f"RemoteOKValidationSettings reads {sorted(missing)}, undocumented in .env.example."
    )


def test_every_indeed_settings_var_is_documented() -> None:
    missing = _pydantic_settings_env_vars(IndeedSettings) - _documented_vars()
    assert not missing, f"IndeedSettings reads {sorted(missing)}, undocumented in .env.example."


def test_every_indeed_validation_settings_var_is_documented() -> None:
    missing = _pydantic_settings_env_vars(IndeedValidationSettings) - _documented_vars()
    assert not missing, (
        f"IndeedValidationSettings reads {sorted(missing)}, undocumented in .env.example."
    )


def test_every_reed_settings_var_is_documented() -> None:
    missing = _pydantic_settings_env_vars(ReedSettings) - _documented_vars()
    assert not missing, f"ReedSettings reads {sorted(missing)}, undocumented in .env.example."


def test_every_reed_validation_settings_var_is_documented() -> None:
    missing = _pydantic_settings_env_vars(ReedValidationSettings) - _documented_vars()
    assert not missing, (
        f"ReedValidationSettings reads {sorted(missing)}, undocumented in .env.example."
    )


def test_every_scheduler_settings_var_is_documented() -> None:
    missing = _pydantic_settings_env_vars(SchedulerSettings) - _documented_vars()
    assert not missing, f"SchedulerSettings reads {sorted(missing)}, undocumented in .env.example."


def test_db_config_no_longer_reads_the_old_buggy_var_name() -> None:
    """Regression guard for the specific historical bug: the misnamed
    DB_MAX_OVERFLOW (missing the POOL segment) must not silently
    reappear in the real code, and the correct name must still be in
    place.
    """
    actual = _db_config_source_derived_vars()
    assert "DB_MAX_OVERFLOW" not in actual
    assert "DB_POOL_MAX_OVERFLOW" in actual
