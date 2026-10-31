"""Unit tests for scripts/kaggle_watchdog.py.

The watchdog runs unattended in CI, so its two decision points are tested
here where a mistake is cheap rather than at 15:23 local time where a mistake
silently leaves the day's translations untranslated:

* ``overlay_is_fresh`` / ``decide`` map the Hugging Face overlay's
  last-modified time to exactly one of two actions. The dangerous direction is
  treating a stale overlay as healthy (missed day of translations); the
  expensive direction is re-pushing a fresh overlay (double-run, wasted GPU
  quota).
* ``verify_pulled`` refuses to push a pull whose metadata lost the GPU
  configuration, the creds dataset, or whose notebook still references Neon --
  the watchdog's one remediation attempt must never spend itself re-creating
  the CPU failure it exists to fix.

No network, no kaggle package: all functions under test are pure.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kaggle_watchdog import decide, overlay_is_fresh, verify_pulled  # noqa: E402

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
        [
            (True, "noop"),
            (False, "repush"),
        ],
    )
    def test_decide_maps_freshness_to_action(self, fresh: bool, expected: str) -> None:
        assert decide(fresh) == expected


def _meta(**overrides: object) -> dict:
    meta: dict = {
        "id": "mskarim870/jmi-translate-hf",
        "enable_gpu": True,
        "machine_shape": "NvidiaTeslaT4",
        "docker_image": "gcr.io/kaggle-private-byod/python@sha256:2757e0c7d1e0a9cb4",
        "dataset_sources": ["mskarim870/jmi-translate-creds"],
    }
    meta.update(overrides)
    return meta


def _source() -> str:
    return "def find_token():\n    ..."


class TestVerifyPulled:
    def test_a_healthy_pull_passes(self) -> None:
        verify_pulled(_meta(), _source())  # must not raise

    @pytest.mark.parametrize(
        ("overrides", "fragment"),
        [
            # The CPU failure, re-created: the guard exists to make this loud.
            ({"enable_gpu": False}, "enable_gpu=False"),
            ({"enable_gpu": None}, "enable_gpu=None"),
            ({"machine_shape": "NvidiaTeslaP100"}, "machine_shape='NvidiaTeslaP100'"),
            ({"machine_shape": None}, "machine_shape=None"),
            # A CPU-only base image is the same trap in another costume.
            (
                {"docker_image": "gcr.io/kaggle-images/python@sha256:81b1e7c4"},
                "not the CUDA BYOD image",
            ),
            # No creds dataset -> find_token() dies ~10s into the run.
            ({"dataset_sources": []}, "lost the creds dataset"),
        ],
    )
    def test_degraded_metadata_is_refused(self, overrides: dict, fragment: str) -> None:
        with pytest.raises(SystemExit) as excinfo:
            verify_pulled(_meta(**overrides), _source())
        assert fragment in str(excinfo.value)

    def test_a_neon_reference_is_refused(self) -> None:
        """The port scripts guard this exact regression; so does the watchdog."""
        with pytest.raises(SystemExit) as excinfo:
            verify_pulled(_meta(), "conn = psycopg2.connect(NEON_DATABASE_URL)")
        assert "Neon" in str(excinfo.value)
