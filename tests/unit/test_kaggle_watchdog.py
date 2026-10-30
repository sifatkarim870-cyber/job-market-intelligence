"""Unit tests for scripts/kaggle_watchdog.py.

The watchdog runs unattended in CI, so its two decision points are tested
here where a mistake is cheap rather than at 15:23 local time where a mistake
silently leaves the day's translations untranslated:

* ``decide`` maps every status Kaggle's ``kernels status`` endpoint has been
  observed to return (plus the ones documented but unseen) to exactly one of
  the two actions. The dangerous direction is treating a dead run as healthy;
  the expensive direction is re-pushing a run that is in flight.
* ``verify_pulled`` refuses to push a pull whose metadata lost the GPU
  configuration, the creds dataset, or whose notebook still references Neon --
  the watchdog's one remediation attempt must never spend itself re-creating
  the CPU failure it exists to fix.

No network, no kaggle package: both functions are pure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from kaggle_watchdog import decide, verify_pulled  # noqa: E402


class TestDecide:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            # Observed in production on this kernel.
            ("error", "repush"),
            ("complete", "noop"),
            ("running", "noop"),
            # Documented by the API, not yet observed here.
            ("queued", "noop"),
            ("cancelacknowledged", "repush"),
            # Case-insensitivity: the API has returned both cases historically.
            ("ERROR", "repush"),
            ("Error", "repush"),
            (" Running ", "noop"),
        ],
    )
    def test_status_maps_to_exactly_one_action(self, status: str, expected: str) -> None:
        assert decide(status) == expected

    def test_unknown_status_is_never_a_repush(self) -> None:
        """A status the API grew tomorrow must not blind-fire a push."""
        assert decide("something-new-from-the-api") == "noop"

    def test_dead_statuses_are_exactly_error_and_cancel(self) -> None:
        assert decide("error") == "repush" and decide("cancelacknowledged") == "repush"


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
