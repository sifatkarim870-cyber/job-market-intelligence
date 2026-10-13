"""Tests for the portability surface of scripts/verify_local_hf_parity.py.

Why this file exists
--------------------
The parity verifier is the one script that can catch a bad merge key or a
publish path that silently dropped rows. It was unusable outside one laptop: it
hardcoded a Windows absolute path to the HF token file and raised at import if
that file was absent, so it could not run on CI. That is a large part of why no
automated gate existed around the corpus.

These tests pin the parts that made it machine-specific, so the hardcoding
cannot quietly come back.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_local_hf_parity.py"


def _load(monkeypatch, **env):
    """Import the script fresh with a controlled environment."""
    for key, val in env.items():
        if val is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, val)
    sys.modules.pop("verify_local_hf_parity_under_test", None)
    spec = importlib.util.spec_from_file_location("verify_local_hf_parity_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module(monkeypatch):
    """A cleanly imported copy with no HF-token environment variables set."""
    return _load(
        monkeypatch,
        CORPUS_HF_TOKEN=None,
        HF_TOKEN=None,
        HUGGING_FACE_HUB_TOKEN=None,
        CORPUS_HF_TOKEN_FILE=None,
        CORPUS_HF_REPO=None,
    )


class TestNoHardcodedPaths:
    def test_source_has_no_windows_absolute_path(self):
        """The literal token path is what made this script crash on Linux."""
        text = SCRIPT.read_text(encoding="utf-8")
        assert r"D:\Research_Project" not in text
        assert 'Hugging_Face_token.txt").read_text' not in text

    def test_source_has_no_bare_default_dsn_assignment(self):
        """LOCAL_DSN must be env-first, not a constant with an env fallback."""
        text = SCRIPT.read_text(encoding="utf-8")
        line = next(ln for ln in text.splitlines() if ln.startswith("LOCAL_DSN"))
        assert "os.environ.get" in line

    def test_import_never_raises_over_a_missing_token(self, monkeypatch):
        """The regression this file exists for.

        The script used to do TOKEN = Path(r"D:\\...\\Hugging_Face_token.txt")
        .read_text() at module scope. Any environment without that exact file --
        every CI runner, every other machine -- died at import, before main()
        could print anything useful.
        """
        # No token env vars, and the only token file we can name is absent.
        module = _load(
            monkeypatch,
            CORPUS_HF_TOKEN=None,
            HF_TOKEN=None,
            HUGGING_FACE_HUB_TOKEN=None,
            CORPUS_HF_TOKEN_FILE=str(Path(__file__).with_name("does-not-exist.txt")),
        )
        # Either it found the repo-local token file, or it returned None. What
        # matters is that reaching this line was previously impossible.
        assert module.TOKEN is None or module.TOKEN.startswith("hf_")
        assert module.REPO.endswith("job-market-intel-corpus")


class TestTokenResolution:
    def test_corpus_hf_token_wins(self, monkeypatch):
        module = _load(
            monkeypatch,
            CORPUS_HF_TOKEN="hf_corpus",
            HF_TOKEN="hf_github",
            HUGGING_FACE_HUB_TOKEN="hf_alias",
        )
        assert module.TOKEN == "hf_corpus"

    def test_hf_token_is_the_ci_variable(self, monkeypatch):
        """CI supplies HF_TOKEN; it must be honoured without any file present."""
        module = _load(
            monkeypatch,
            CORPUS_HF_TOKEN=None,
            HF_TOKEN="hf_from_github_secret",
            HUGGING_FACE_HUB_TOKEN=None,
        )
        assert module.TOKEN == "hf_from_github_secret"

    def test_token_is_stripped(self, monkeypatch):
        module = _load(monkeypatch, CORPUS_HF_TOKEN="  hf_padded\n", HF_TOKEN=None)
        assert module.TOKEN == "hf_padded"

    def test_explicit_token_file_is_used(self, monkeypatch, tmp_path):
        token_file = tmp_path / "tok.txt"
        token_file.write_text("hf_from_file\n", encoding="utf-8")
        module = _load(
            monkeypatch,
            CORPUS_HF_TOKEN=None,
            HF_TOKEN=None,
            CORPUS_HF_TOKEN_FILE=str(token_file),
        )
        assert module.TOKEN == "hf_from_file"

    def test_blank_token_is_not_returned(self, monkeypatch):
        """An empty var must fall through, not win and return ''."""
        module = _load(monkeypatch, CORPUS_HF_TOKEN="   ", HF_TOKEN="hf_real")
        assert module.TOKEN == "hf_real"


class TestRepoAndDsn:
    def test_repo_overridable_for_a_fork(self, monkeypatch):
        module = _load(monkeypatch, CORPUS_HF_REPO="someone/private-corpus")
        assert module.REPO == "someone/private-corpus"

    def test_repo_default_unchanged(self, monkeypatch):
        module = _load(monkeypatch, CORPUS_HF_REPO=None)
        assert module.REPO == "Shifat2110724169/job-market-intel-corpus"

    def test_local_dsn_from_env(self, monkeypatch):
        module = _load(monkeypatch, LOCAL_DATABASE_URL="postgresql+psycopg://x/y@host/db")
        assert module.LOCAL_DSN == "postgresql+psycopg://x/y@host/db"

    def test_neon_dsn_from_environment(self, monkeypatch):
        module = _load(
            monkeypatch,
            NEON_DATABASE_URL="postgresql://u:p@neon.example/db",
            LOCAL_DATABASE_URL="postgresql+psycopg://u:changeme@localhost/db",
        )
        assert module.neon_dsn() == "postgresql+psycopg://u:p@neon.example/db"

    def test_neon_dsn_equal_to_local_is_not_configured(self, monkeypatch):
        """The local .env points DATABASE_URL at localhost; that is not Neon."""
        local = "postgresql+psycopg://u:changeme@localhost/db"
        module = _load(monkeypatch, NEON_DATABASE_URL=local, LOCAL_DATABASE_URL=local)
        assert module.neon_dsn() is None

    def test_neon_dsn_accepts_legacy_schemes(self, monkeypatch):
        for scheme in ("postgresql", "postgres"):
            module = _load(
                monkeypatch,
                NEON_DATABASE_URL=f"{scheme}://u:p@neon.example/db",
                LOCAL_DATABASE_URL="postgresql+psycopg://u:changeme@localhost/db",
            )
            assert module.neon_dsn() == "postgresql+psycopg://u:p@neon.example/db"

    def test_neon_dsn_absent_is_none(self, monkeypatch):
        module = _load(monkeypatch, NEON_DATABASE_URL=None, LOCAL_DATABASE_URL=None)
        # Falls back to reading the repo's own .env, which may or may not
        # exist; either way it must not raise.
        assert module.neon_dsn() is None or module.neon_dsn().startswith("postgresql+psycopg://")


def test_env_file_parser_handles_quotes_and_comments(module, tmp_path):
    """_env_file_values must tolerate the shapes .env files actually contain."""
    env = tmp_path / ".env"
    env.write_text(
        "A=plain\nB=\"quoted\"\nC='single'\n# a comment line\n\nBAD LINE\nD=postgres://u:p@h/db\n",
        encoding="utf-8",
    )

    parsed = module._env_file_values(env)
    assert parsed == {
        "A": "plain",
        "B": "quoted",
        "C": "single",
        "D": "postgres://u:p@h/db",
    }


def test_env_file_parser_missing_file_is_empty(module, tmp_path):
    assert module._env_file_values(tmp_path / "nope.env") == {}


def test_env_file_parser_later_key_wins(module, tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=first\nA=second\n", encoding="utf-8")
    assert module._env_file_values(env) == {"A": "second"}
