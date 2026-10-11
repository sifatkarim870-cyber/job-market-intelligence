"""tests/unit/scrapers/test_jobam_client_exceptions.py

The jobam client's retry wrapper caught ``curl_exceptions.RequestsError``, a
name that does not exist in curl_cffi. The except clause therefore raised

    AttributeError: module 'curl_cffi.requests.exceptions' has no attribute
    'RequestsError'

whenever a transport error occurred, replacing the intended
``TransientHTTPError`` with an unhandled AttributeError -- so the retry never
happened and one slow response ended the run. Observed 2026-10-11 when jobam.us
timed out after 20s (curl error 28).

This pins the exception base class to the one the installed library actually
exports, so an upgrade that renames it fails here instead of on a live scrape.
"""

from __future__ import annotations

import importlib

import pytest

curl_exceptions = importlib.import_module("curl_cffi.requests.exceptions")

client_module = importlib.import_module("job_market_intel.scrapers.jobam.client")


def test_the_exceptions_the_client_catches_exist():
    """The caught names must resolve on the installed curl_cffi.

    RequestException is curl_cffi's request-error base class and CurlError is
    its libcurl-error base class. Neither subsumes the other -- Timeout's MRO
    is Timeout -> RequestException -> CurlError -> OSError, so Timeout matches
    either clause, but a bare CurlError does not match RequestException. The
    client catches both for that reason. RequestsError was never exported.
    """
    assert hasattr(curl_exceptions, "RequestException"), (
        "curl_cffi no longer exports RequestException; the client needs updating"
    )
    assert hasattr(curl_exceptions, "CurlError"), (
        "curl_cffi no longer exports CurlError; the client needs updating"
    )
    assert not hasattr(curl_exceptions, "RequestsError"), (
        "RequestsError now exists -- if this is a rename in curl_cffi, the "
        "client and this test should both move to it deliberately"
    )


@pytest.mark.parametrize(
    "name",
    ["Timeout", "ConnectTimeout", "ReadTimeout", "ConnectionError", "CurlError"],
)
def test_typical_transport_errors_are_caught(name):
    """Everything the wrapper exists to retry must match one of the clauses."""
    exc_cls = getattr(curl_exceptions, name, None)
    if exc_cls is None:  # pragma: no cover - depends on installed version
        pytest.skip(f"curl_cffi does not export {name}")
    caught = issubclass(
        exc_cls,
        (curl_exceptions.RequestException, curl_exceptions.CurlError),
    )
    assert caught, f"{name} would escape the client's except clause unretried"


def test_client_source_does_not_catch_requests_error():
    """A direct source check, because the failure is an AttributeError.

    Nothing imports the client's except clause in a way that exercises this,
    and the attribute error only fires when a request actually fails -- which
    on a healthy network is never, which is why it survived in the codebase.

    Only the executable code is checked; the module's own comment explains the
    mistake by name, and matching on prose would flag the explanation as the
    bug.
    """
    import ast

    tree = ast.parse(open(client_module.__file__, encoding="utf-8").read())

    def names_of(expr) -> set[str]:
        """Names an except clause refers to, attribute form or bare."""
        if expr is None:
            return set()
        if isinstance(expr, ast.Tuple):
            return {n for element in expr.elts for n in names_of(element)}
        if isinstance(expr, ast.Attribute):
            return {expr.attr}
        if isinstance(expr, ast.Name):
            return {expr.id}
        return set()

    caught_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            caught_names |= names_of(node.type)

    assert "RequestsError" not in caught_names, (
        f"client.py catches {sorted(caught_names)}; RequestsError does not exist "
        "in curl_cffi"
    )
    assert "RequestException" in caught_names
    assert "CurlError" in caught_names
