"""Unit tests for job_market_intel.cleaning.text_utils.

What these tests verify, and why each matters:
    - None and empty-string inputs pass through unchanged (no crash).
    - HTML entities are decoded (the literal "&amp;" seen in live RemoteOK
      titles like "Chubb Fire &amp; Security").
    - Mojibake is repaired (the literal "LÃ‘N"-style corruption seen in
      live RemoteOK titles).
    - Whitespace (including newlines/tabs, and multiple consecutive
      spaces) is collapsed to single spaces and trimmed.
    - clean_html_text strips tags, joins block-level content with spaces
      (not silently concatenated), and still fixes entities/mojibake.
"""

from __future__ import annotations

from job_market_intel.cleaning.text_utils import clean_html_text, clean_plain_text


class TestCleanPlainTextEdgeCases:
    def test_none_passes_through(self) -> None:
        assert clean_plain_text(None) is None

    def test_empty_string_passes_through(self) -> None:
        assert clean_plain_text("") == ""


class TestCleanPlainTextEntities:
    def test_ampersand_entity_is_decoded(self) -> None:
        assert clean_plain_text("Chubb Fire &amp; Security") == "Chubb Fire & Security"

    def test_apostrophe_entity_is_decoded(self) -> None:
        assert clean_plain_text("It&#39;s a job") == "It's a job"


class TestCleanPlainTextMojibake:
    def test_utf8_as_latin1_mojibake_is_repaired(self) -> None:
        # "é" encoded as UTF-8 (bytes 0xC3 0xA9), then misread as Latin-1,
        # produces the two-character garble "Ã©". This is the same class
        # of corruption observed live in RemoteOK titles (e.g. "LÃ‘N").
        mojibake = "Ã©"
        assert clean_plain_text(mojibake) == "é"


class TestCleanPlainTextWhitespace:
    def test_multiple_spaces_collapse_to_one(self) -> None:
        assert clean_plain_text("Senior   Backend    Engineer") == "Senior Backend Engineer"

    def test_newlines_and_tabs_collapse_to_space(self) -> None:
        assert clean_plain_text("Line one\n\nLine\ttwo") == "Line one Line two"

    def test_leading_and_trailing_whitespace_is_trimmed(self) -> None:
        assert clean_plain_text("   Padded Title   ") == "Padded Title"


class TestCleanHtmlTextEdgeCases:
    def test_none_passes_through(self) -> None:
        assert clean_html_text(None) is None

    def test_empty_string_passes_through(self) -> None:
        assert clean_html_text("") == ""


class TestCleanHtmlTextStripsTags:
    def test_simple_tags_are_removed(self) -> None:
        assert clean_html_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_block_level_tags_are_joined_with_space_not_concatenated(self) -> None:
        # Without a separator, BeautifulSoup would produce "AB" here —
        # that's wrong for job descriptions, where each <p> is a distinct
        # paragraph and should not visually merge into the next one.
        result = clean_html_text("<p>A</p><p>B</p>")
        assert result == "A B"

    def test_entities_inside_html_are_decoded(self) -> None:
        assert clean_html_text("<p>R&amp;D team</p>") == "R&D team"

    def test_nested_tags_are_all_removed(self) -> None:
        html_text = "<div><p>We need a <strong>Senior</strong> engineer.</p></div>"
        assert clean_html_text(html_text) == "We need a Senior engineer."
