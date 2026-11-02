"""Unit tests for scripts/kaggle_watchdog_local.py.

The watchdog runs unattended on the laptop, so its two decision points are
tested here where a mistake is cheap rather than at 15:20 local where a mistake
silently leaves the day's translations untranslated:

* ``overlay_is_fresh`` / ``decide`` map the Hugging Face overlay's last-modified
  time and the kernel's Kaggle status to exactly one of two actions. The
  dangerous direction is treating a stale overlay as healthy (missed day of
  translations); the expensive direction is re-pushing while a run is already
  in flight or a fresh overlay (double-run, wasted GPU quota).
* ``fix_and_verify_pulled`` restores the kernel metadata the Kaggle schedule
  keeps overwriting (docker_image -> CUDA BYOD, enable_gpu -> true,
  machine_shape -> NvidiaTeslaT4, dataset_sources -> creds dataset) and refuses
  to push degraded notebook source (missing find_token/upload_overlay, hardcoded
  token, overlay_//file typo, Neon reference).

No network, no kaggle package: all functions under test are pure.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kaggle_watchdog_local import (  # noqa: E402
    decide,
    fix_and_verify_pulled,
    overlay_age_days,
    overlay_is_fresh,
    schedule_due,
)

SCHEDULE_UTC = _dt.time(9, 3)


def _dt_utc(y: int, m: int, d: int, h: int, mi: int) -> _dt.datetime:
    return _dt.datetime(y, m, d, h, mi, tzinfo=_dt.UTC)


class TestOverlayIsFresh:
    def test_fresh_after_window_today(self) -> None:
        # Published at 09:10 UTC today, after the 09:03 window -- healthy run.
        today = _dt.datetime.now(_dt.UTC).date()
        lm = _dt.datetime.combine(today, _dt.time(9, 10), tzinfo=_dt.UTC)
        assert overlay_is_fresh(lm) is True

    def test_fresh_exactly_at_window(self) -> None:
        today = _dt.datetime.now(_dt.UTC).date()
        lm = _dt.datetime.combine(today, SCHEDULE_UTC, tzinfo=_dt.UTC)
        assert overlay_is_fresh(lm) is True

    def test_stale_before_window_today(self) -> None:
        # Published at 08:59 UTC today, before the window -- yesterday's file,
        # today's run hasn't published yet.
        today = _dt.datetime.now(_dt.UTC).date()
        lm = _dt.datetime.combine(today, _dt.time(8, 59), tzinfo=_dt.UTC)
        assert overlay_is_fresh(lm) is False

    def test_stale_yesterday(self) -> None:
        today = _dt.datetime.now(_dt.UTC).date()
        yesterday = today - _dt.timedelta(days=1)
        lm = _dt.datetime.combine(yesterday, _dt.time(12, 0), tzinfo=_dt.UTC)
        assert overlay_is_fresh(lm) is False

    def test_none_is_stale(self) -> None:
        # HF unreachable -- caller refuses to push blindly.
        assert overlay_is_fresh(None) is False


class TestDecide:
    @pytest.mark.parametrize(
        ("fresh", "expected"),
        [(True, "noop"), (False, "repush")],
    )
    def test_decide_maps_freshness_to_action(self, fresh: bool, expected: str) -> None:
        assert decide(fresh) == expected

    @pytest.mark.parametrize("status", ["QUEUED", "RUNNING"])
    def test_an_in_flight_run_is_never_re_pushed(self, status: str) -> None:
        # The daily task fires 17 minutes after the schedule, while a healthy
        # run is still translating. Re-pushing there would start a second GPU
        # session and burn quota for work already happening.
        assert decide(False, status) == "noop"

    @pytest.mark.parametrize(
        "status", ["COMPLETE", "ERROR", "CANCELED", "UNKNOWN"]
    )
    def test_a_dead_run_still_uses_overlay_freshness(self, status: str) -> None:
        assert decide(False, status) == "repush"
        assert decide(True, status) == "noop"

    def test_before_the_schedule_a_one_day_old_overlay_is_expected(self) -> None:
        # The logon trigger fires every time the laptop comes back. At 03:00
        # UTC, yesterday's overlay is the newest one by definition; re-pushing
        # there would burn a GPU slot every morning.
        assert decide(False, "COMPLETE", age_days=1, due=False) == "noop"

    def test_before_the_schedule_a_two_day_backlog_is_remediated(self) -> None:
        # Older than yesterday means the schedule is not keeping up, so do not
        # wait for today's window.
        assert decide(False, "COMPLETE", age_days=2, due=False) == "repush"

    def test_after_the_schedule_a_stale_overlay_is_remediated(self) -> None:
        assert decide(False, "ERROR", age_days=0, due=True) == "repush"

    def test_an_in_flight_run_wins_over_everything(self) -> None:
        assert decide(False, "RUNNING", age_days=5, due=True) == "noop"


class TestScheduleDue:
    def test_false_before_the_window(self) -> None:
        assert schedule_due(_dt_utc(2026, 11, 1, 8, 0)) is False

    def test_false_during_the_grace_period(self) -> None:
        # The CPU-slot abort is ~10s in; give the schedule time to fail first.
        assert schedule_due(_dt_utc(2026, 11, 1, 9, 5)) is False

    def test_true_after_the_grace_period(self) -> None:
        # 09:20 UTC is when the daily task runs.
        assert schedule_due(_dt_utc(2026, 11, 1, 9, 20)) is True


class TestOverlayAgeDays:
    def test_unreachable_is_none(self) -> None:
        assert overlay_age_days(None) is None

    def test_published_today(self) -> None:
        today = _dt.datetime.now(_dt.UTC).date()
        lm = _dt.datetime.combine(today, _dt.time(1, 0), tzinfo=_dt.UTC)
        assert overlay_age_days(lm) == 0

    def test_published_yesterday(self) -> None:
        yesterday = _dt.datetime.now(_dt.UTC).date() - _dt.timedelta(days=1)
        lm = _dt.datetime.combine(yesterday, _dt.time(23, 0), tzinfo=_dt.UTC)
        assert overlay_age_days(lm) == 1


BYOD_IMAGE = (
    "gcr.io/kaggle-private-byod/python@sha256:"
    "2757e0c7d1e0a9cb43da657b97e223c321a98f5014bdf64f44f2f6b083ad2b2f"
)
CPU_IMAGE = "gcr.io/kaggle-images/python@sha256:81b1e7c4b4f0f2a7e0a33943c95754b1b7af6b30d65221633a284b6b601cd84a"


def _meta(**overrides: object) -> dict:
    meta: dict = {
        "id": "mskarim870/jmi-translate-hf",
        "enable_gpu": True,
        "machine_shape": "NvidiaTeslaT4",
        "docker_image": BYOD_IMAGE,
        "dataset_sources": ["mskarim870/jmi-translate-creds"],
    }
    meta.update(overrides)
    return meta


def _source(extra: str = "") -> str:
    return (
        "def find_token():\n    ...\n"
        "def upload_overlay(con, rows):\n    ...\n"
        "def main():\n    ...\n"
        "CANDIDATE_LABELS = (...)\n"
        "SQL = 'UNION ALL BY NAME'\n"
        "def download_corpus(token):\n    ...\n"
        "snapshot_download(repo_id=..., allow_patterns='shards/*/*/*.parquet')\n"
        "def load_overlay_keys(con, token):\n    ...\n"
        "def build_pending(con, shards):\n    ...\n"
        "batch = fetch_pending_retry(con, offset)\n"
        "log('no new rows; leaving the published overlay untouched')\n"
        + extra
    )


def _without(fragment: str) -> str:
    """A healthy notebook source with one required fragment removed."""
    src = _source()
    assert fragment in src, f"helper bug: {fragment!r} not in base source"
    return src.replace(fragment, "", 1)


class TestFixAndVerifyPulled:
    def test_a_healthy_pull_passes(self) -> None:
        fix_and_verify_pulled(_meta(), _source())  # must not raise

    def test_a_stale_call_site_is_refused(self) -> None:
        # v60's exact defect: fetch_pending_retry's signature dropped `shards`
        # but its body still called fetch_pending(con, offset, shards). Every
        # string this guard looks for was present, and the run died on a
        # NameError 84 seconds into a GPU session.
        src = _source(
            "def fetch_pending(con, offset):\n    ...\n"
            "def fetch_pending_retry(con, offset, attempts=4):\n"
            "    return fetch_pending(con, offset, shards)\n"
        )
        with pytest.raises(SystemExit, match="disagree with its own definitions"):
            fix_and_verify_pulled(_meta(), src)

    def test_a_matching_call_site_is_accepted(self) -> None:
        src = _source(
            "def fetch_pending(con, offset):\n    ...\n"
            "def fetch_pending_retry(con, offset, attempts=4):\n"
            "    return fetch_pending(con, offset)\n"
        )
        fix_and_verify_pulled(_meta(), src)  # must not raise

    def test_varargs_and_ambiguous_names_are_not_flagged(self) -> None:
        # A *args callee accepts anything, and a name used for two different
        # signatures cannot be judged -- both must not produce false alarms.
        src = _source(
            "def run_all(*args):\n    ...\n"
            "run_all(con, offset, shards, extra)\n"
            "class Worker:\n"
            "    def work(self, con, offset):\n        ...\n"
            "def work(con):\n    ...\n"
            "work(con)\n"
        )
        fix_and_verify_pulled(_meta(), src)  # must not raise

    def test_an_unparseable_notebook_is_refused(self) -> None:
        with pytest.raises(SystemExit, match="does not parse"):
            fix_and_verify_pulled(_meta(), _source("def broken(:\n"))

    def test_a_streaming_notebook_is_accepted(self) -> None:
        # v59 reads shards over authenticated hf:// instead of downloading them.
        # It works, so the guard must not refuse it merely because v60
        # superseded it -- otherwise a rollout would leave the watchdog unable
        # to repair the kernel that is actually deployed.
        src = (
            "def find_token():\n    ...\n"
            "def upload_overlay(con, rows):\n    ...\n"
            "def main():\n    ...\n"
            "CANDIDATE_LABELS = (...)\n"
            "SQL = 'UNION ALL BY NAME'\n"
            "def corpus_shards(token):\n    ...\n"
            "con.execute('CREATE OR REPLACE SECRET hf (TYPE HUGGINGFACE, TOKEN ?)')\n"
            "batch = fetch_pending_retry(con, offset, shards)\n"
            "log('no new rows; leaving the published overlay untouched')\n"
        )
        fix_and_verify_pulled(_meta(), src)  # must not raise

    def test_dirty_metadata_is_restored(self) -> None:
        # The Kaggle schedule overwrites these; the watchdog restores them.
        meta = _meta(
            enable_gpu=False,
            machine_shape="NvidiaTeslaP100",
            docker_image=CPU_IMAGE,
            dataset_sources=[],
        )
        fix_and_verify_pulled(meta, _source())
        assert meta["enable_gpu"] is True
        assert meta["machine_shape"] == "NvidiaTeslaT4"
        assert meta["docker_image"] == BYOD_IMAGE
        assert meta["dataset_sources"] == ["mskarim870/jmi-translate-creds"]

    def test_dirty_metadata_is_restored_partial(self) -> None:
        # Only some fields are dirty; the rest are left alone.
        meta = _meta(docker_image=CPU_IMAGE)
        fix_and_verify_pulled(meta, _source())
        assert meta["enable_gpu"] is True
        assert meta["machine_shape"] == "NvidiaTeslaT4"
        assert meta["docker_image"] == BYOD_IMAGE
        assert meta["dataset_sources"] == ["mskarim870/jmi-translate-creds"]

    @pytest.mark.parametrize(
        ("bad_source", "fragment"),
        [
            # Missing find_token -- the watchdog cannot fix code by re-pushing.
            (_without("def find_token"), "missing 'def find_token'"),
            # Missing upload_overlay.
            (_without("def upload_overlay"), "missing 'def upload_overlay'"),
            # v60: corpus access by download-once + materialised backlog.
            (
                _without("def download_corpus"),
                "no known corpus-access strategy",
            ),
            (_without("snapshot_download"), "no known corpus-access strategy"),
            (_without("def build_pending"), "no known corpus-access strategy"),
            (_without("fetch_pending_retry"), "missing 'fetch_pending_retry'"),
            # Hardcoded HF token leaked into source.
            (
                _source("token = 'hf_AAAA_EXAMPLE_FAKE_TOKEN_FOR_TESTS_ONLY'"),
                "hardcoded HF token",
            ),
            # overlay_//file typo.
            (_source("open(overlay_//file)"), "overlay_//file typo"),
            # v58: the hf:// glob that needs 540 tree-API calls.
            (
                _source("SHARD_GLOBS = ['hf://datasets/x/shards/*/*/*.parquet']"),
                "HTTP 429",
            ),
            # Neon reference.
            (_source("NEON_DATABASE_URL = '...'"), "still references Neon"),
        ],
    )
    def test_degraded_notebook_source_is_refused(
        self, bad_source: str, fragment: str
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            fix_and_verify_pulled(_meta(), bad_source)
        assert fragment in str(excinfo.value)
