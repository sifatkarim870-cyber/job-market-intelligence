"""The state-snapshot restore must survive HuggingFace 429 bursts.

Every matrix job in Scrape (HTML) downloads the same state snapshot, so the
hub sees ~100 tree listings in the same minute and answers 429. That burst
took out alfred, jobsnepal, karir_com, praca_by and willhaben_at on
2026-10-30, none of which had a scraper bug. ``_with_hf_retry`` is the guard:
it retries only rate limits / 5xx, backs off exponentially, and lets a real
error (a bad token, a missing repo) fail immediately.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "restore_state_snapshot.py"


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeHTTPError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"{status_code} Client Error")
        self.response = FakeResponse(status_code)


@pytest.fixture(scope="module")
def restore():
    spec = importlib.util.spec_from_file_location("_restore_state_snapshot", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_sleep(restore, monkeypatch):
    pauses: list[float] = []
    monkeypatch.setattr(restore.time, "sleep", pauses.append)
    return pauses


def test_rate_limited_only_for_429_and_5xx(restore):
    assert restore._is_rate_limited(FakeHTTPError(429))
    assert restore._is_rate_limited(FakeHTTPError(503))
    assert not restore._is_rate_limited(FakeHTTPError(401))
    assert not restore._is_rate_limited(FakeHTTPError(404))


def test_retries_a_429_then_returns_the_result(restore, no_sleep):
    outcomes = [FakeHTTPError(429), FakeHTTPError(429), "snapshot"]

    def call():
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    assert restore._with_hf_retry(call, "list_repo_files") == "snapshot"
    assert len(no_sleep) == 2


def test_backoff_grows_between_attempts(restore, no_sleep):
    def always_limited():
        raise FakeHTTPError(429)

    with pytest.raises(FakeHTTPError):
        restore._with_hf_retry(always_limited, "list_repo_files")
    assert len(no_sleep) == restore._HF_MAX_ATTEMPTS - 1
    # Exponential growth, but jitter and the ceiling keep every pause in range.
    assert no_sleep[0] < no_sleep[-1]
    assert max(no_sleep) <= restore._HF_MAX_WAIT_SECONDS * 1.4


def test_a_real_error_is_not_retried(restore, no_sleep):
    calls = 0

    def bad_token():
        nonlocal calls
        calls += 1
        raise FakeHTTPError(401)

    with pytest.raises(FakeHTTPError):
        restore._with_hf_retry(bad_token, "hf_hub_download state/x.parquet")
    assert calls == 1
    assert no_sleep == []


def test_download_state_retries_each_call(restore, tmp_path, monkeypatch, no_sleep):
    """Both the listing and every file download go through the retry guard."""

    class FakeApi:
        def __init__(self, token: str) -> None:
            self.calls: list[str] = []

        def list_repo_files(self, repo_id: str, repo_type: str) -> list[str]:
            self.calls.append("list")
            if self.calls.count("list") == 1:
                raise FakeHTTPError(429)
            return ["state/a.parquet", "README.md"]

        def hf_hub_download(self, repo_id: str, repo_type: str, filename: str, token: str) -> str:
            self.calls.append("get")
            if self.calls.count("get") == 1:
                raise FakeHTTPError(429)
            source = tmp_path / "cached.parquet"
            source.write_bytes(b"rows")
            return str(source)

    api = FakeApi("token")
    monkeypatch.setattr(restore, "_resolve_token", lambda: "token")
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        type("FakeHub", (), {"HfApi": lambda token=None: api}),
    )

    dest = restore.download_state(tmp_path / "work")

    assert (dest / "a.parquet").read_bytes() == b"rows"
    assert api.calls.count("list") == 2
    assert api.calls.count("get") == 2
