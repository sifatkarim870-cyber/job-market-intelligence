def _response(body: bytes, content_type: str, encoding: str):
    import requests

    resp = requests.Response()
    resp._content = body
    resp.headers["Content-Type"] = content_type
    resp.encoding = encoding
    return resp


def test_undeclared_utf8_page_is_decoded_as_utf8() -> None:
    from job_market_intel.scrapers.html_scraper.client import _response_text

    text = "ගබඩා සහයක"
    resp = _response(text.encode("utf-8"), "text/html", "ISO-8859-1")

    assert _response_text(resp) == text


def test_declared_charset_wins_over_the_utf8_default() -> None:
    from job_market_intel.scrapers.html_scraper.client import _response_text

    resp = _response("café".encode("latin-1"), "text/html; charset=iso-8859-1", "ISO-8859-1")

    assert _response_text(resp) == "café"


def test_non_utf8_bytes_keep_the_server_encoding() -> None:
    from job_market_intel.scrapers.html_scraper.client import _response_text

    resp = _response(b"caf\xe9", "text/html", "ISO-8859-1")

    assert _response_text(resp) == "café"
