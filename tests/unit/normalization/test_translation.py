"""Unit tests for normalization/translation.py.

Design constraint honored here (same as test_title_classification.py):
every test exercises only the cheap, offline, deterministic pieces --
language detection (seed-pinned, no model download), the ISO 639-1 ->
FLORES mapping, chunking, and the selection predicates' building blocks.
The actual NLLB model (2.4GB weights, CPU inference) is never loaded in
unit tests; ``process_detection_row``/``process_description_row`` are
tested through an injected fake translator where behavior matters.
"""

from __future__ import annotations

from job_market_intel.normalization import translation
from job_market_intel.normalization.translation import (
    DEFAULT_TRANSLATED_BY,
    TranslationJob,
    TranslationSettings,
    choose_detection_text,
    detect_language,
    resolve_flores_code,
    split_into_chunks,
)


class FakeTranslator:
    """Stands in for NllbTranslator -- records calls, returns ASCII canned text.

    The canned output is deliberately ASCII: the non-English-output gate
    (``looks_like_non_english_output``) rejects real translations that
    come back non-Latin, so an echo-style fake would trip it."""

    provenance_label = DEFAULT_TRANSLATED_BY

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def translate(self, source_text: str, flores_source_lang: str) -> str:
        self.calls.append((source_text, flores_source_lang))
        return f"EN[{len(source_text)} chars]"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_env_prefix() -> None:
    """TRANSLATE_* is what .env.example documents and what the
    env-consistency test enforces -- pin it here so a prefix change
    breaks loudly in two places instead of silently orphaning .env vars."""
    assert TranslationSettings.model_config.get("env_prefix") == "TRANSLATE_"


def test_settings_defaults_are_the_documented_ones() -> None:
    settings = TranslationSettings()
    assert settings.model_name == "facebook/nllb-200-distilled-600M"
    assert settings.target_lang == "eng_Latn"
    assert settings.quantize_dynamic is True


# ---------------------------------------------------------------------------
# ISO 639-1 -> FLORES mapping
# ---------------------------------------------------------------------------


def test_english_resolves_to_none_the_skip_path() -> None:
    """'en' maps to None deliberately: detected-English rows are recorded
    in language_code but never translated."""
    assert resolve_flores_code("en") is None


def test_known_upcoming_sources_map_to_flores_codes() -> None:
    """Every language named in the scraper roadmap must resolve -- these
    are the sites queued behind 51job in the audit spreadsheet."""
    expected = {
        "zh": "zho_Hans",  # 51job (already ingested), 11 Traditional-Chinese sites
        "zh-cn": "zho_Hans",
        "zh-tw": "zho_Hant",
        "fa": "pes_Arab",  # Jobinja / IranTalent / Jobvision
        "he": "heb_Hebr",  # JobMaster -- was a nonexistent 'heb_Arab' until 2026-10-07
        "ko": "kor_Hang",  # JobKorea
        "uk": "ukr_Cyrl",  # Work.ua
        "es": "spa_Latn",  # Tecoloco x4
        "ru": "rus_Cyrl",  # hh KZ/KG/UZ, Rabota.by
        "ne": "nep_Deva",  # Merojob
        "is": "isl_Latn",  # Vinnumalastofnun
        "sr": "srp_Cyrl",  # Infostud
        "kk": "kaz_Cyrl",  # hh KZ
        "fr": "fra_Latn",  # Emploitic (already ingested), France Travail
        "hy": "hye_Armn",  # job.am (already ingested)
        "ar": "arb_Arab",
        "tr": "tur_Latn",
    }
    for code, flores in expected.items():
        assert resolve_flores_code(code) == flores, code


def test_lookup_is_case_insensitive() -> None:
    assert resolve_flores_code("ZH-CN") == "zho_Hans"
    assert resolve_flores_code("En") is None


def test_langdetect_quirky_codes_from_production_are_mapped() -> None:
    """Observed in the first real local run: langdetect emits 'tl' (not
    'fil') for Tagalog and 'af' for Afrikaans -- both previously fell
    through to record-only. Pin them so the map can't silently regress."""
    assert resolve_flores_code("tl") == "tgl_Latn"
    assert resolve_flores_code("fil") == "tgl_Latn"
    assert resolve_flores_code("af") == "afr_Latn"
    assert resolve_flores_code("bs") == "bos_Latn"


def test_unmapped_language_resolves_to_none_without_crashing() -> None:
    """An unmapped language is recorded (language_code set, no
    translation) -- never force-guessed through a wrong NLLB source."""
    assert resolve_flores_code("xx") is None
    assert resolve_flores_code("") is None
    assert resolve_flores_code(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Detection (seed-pinned -> deterministic across runs)
# ---------------------------------------------------------------------------


def test_detects_english_prose() -> None:
    assert detect_language("We are looking for a software engineer to join our team") == "en"


def test_detects_chinese() -> None:
    assert detect_language("招聘软件工程师，负责后端开发与系统维护工作") in {"zh", "zh-cn"}


def test_detects_french() -> None:
    assert detect_language("Developeur Python experienced pour equipe plateforme") == "fr"


def test_short_or_empty_text_is_undecidable() -> None:
    """Under the minimum length we record 'unknown' rather than let a
    detector guess from a handful of characters -- unless the script
    decides it first (see the script-first tests below)."""
    assert detect_language(None) is None
    assert detect_language("") is None
    assert detect_language("   ") is None
    assert detect_language("QA") is None


# ---------------------------------------------------------------------------
# Script-first detection (the production misroute fix)
# ---------------------------------------------------------------------------


def test_armenian_detected_by_script_even_when_langdetect_cannot() -> None:
    """langdetect has NO Armenian profile -- it reported 'et' (Estonian)
    for all 172 job.am titles in production. Script detection must win,
    including below the statistical minimum length."""
    from job_market_intel.normalization.translation import detect_by_script

    assert detect_by_script("Գրաֆիկ դիզայներ") == "hy"
    assert detect_language("Գրաֆիկ դիզայներ") == "hy"
    assert detect_language("Մենեջեր") == "hy"  # 7 chars, under the 10-char gate


def test_chinese_detected_by_script_beats_langdetect_noise() -> None:
    """Observed misroutes: Chinese titles came back ko/no/vi. Script
    detection pins them to zh regardless of length."""
    from job_market_intel.normalization.translation import detect_by_script

    assert detect_by_script("跨境电商运营") == "zh"
    assert detect_language("管道/仪表/电气工程师") == "zh"  # previously 'no'
    assert detect_language("项目工程师") == "zh"  # previously 'vi'


def test_japanese_and_korean_scripts() -> None:
    from job_market_intel.normalization.translation import detect_by_script

    assert detect_by_script("アシスタント募集") == "ja"
    assert detect_by_script("ソフトウェアエンジニア") == "ja"
    assert detect_by_script("백엔드 개발자") == "ko"


def test_kana_wins_over_kanji_in_mixed_japanese_text() -> None:
    """Priority is by RANGE, not by first character: a Japanese title
    opening with kanji must not be claimed by zh."""
    from job_market_intel.normalization.translation import detect_by_script

    assert detect_by_script("日本語の先生を募集") == "ja"  # kanji first, kana present


def test_korean_with_hanja_stays_korean() -> None:
    from job_market_intel.normalization.translation import detect_by_script

    # Hangul before Han in range order -> ko wins even with hanja present.
    assert detect_by_script("서비스 엔지니어 경력") == "ko"
    assert detect_by_script("工場 技術자") == "ko"  # hanja + Hangul


def test_georgian_detected_by_script() -> None:
    from job_market_intel.normalization.translation import detect_by_script

    assert detect_by_script("პროგრამისტი") == "ka"


def test_latin_and_cyrillic_text_is_left_to_langdetect() -> None:
    """Deliberately NOT in the script table: langdetect has working
    profiles and can distinguish what a bare range cannot."""
    from job_market_intel.normalization.translation import detect_by_script

    assert detect_by_script("Senior Backend Engineer") is None
    assert detect_by_script("Менеджер по экспорту") is None
    assert detect_language("Менеджер по экспорту") == "ru"  # langdetect's job


# ---------------------------------------------------------------------------
# Output quality gate
# ---------------------------------------------------------------------------


def test_output_gate_passes_english_and_mostly_english() -> None:
    from job_market_intel.normalization.translation import looks_like_non_english_output

    assert looks_like_non_english_output("") is False
    assert looks_like_non_english_output("12345 !!!") is False
    assert looks_like_non_english_output("Cross-border e-commerce operations") is False
    # Accented letters in English output are fine (a few non-ASCII chars).
    assert looks_like_non_english_output("Développeur backend (CAFE team)") is False


def test_output_gate_catches_echoed_non_english() -> None:
    from job_market_intel.normalization.translation import looks_like_non_english_output

    # NLLB echoing the input when the source token was wrong (observed).
    assert looks_like_non_english_output("管道/仪表/电气工程师") is True
    assert looks_like_non_english_output("肉制品加工厂残疾人专项招聘") is True
    assert looks_like_non_english_output("Աշխղեկ (прораб)") is True


def test_detection_is_deterministic_across_calls() -> None:
    """The seed pin (DetectorFactory.seed = 0 at import) is what stops a
    row from flipping language between batch runs and re-translating
    forever -- assert the invariant directly."""
    sample = "Entrez votre CV pour postuler au poste de developpeur backend senior"
    first = detect_language(sample)
    for _ in range(5):
        assert detect_language(sample) == first
    assert first == "fr"


# ---------------------------------------------------------------------------
# Detection-text choice
# ---------------------------------------------------------------------------


def test_prefers_long_description_over_title() -> None:
    long_desc = "A" * 200
    assert choose_detection_text("Short title", long_desc) == long_desc


def test_falls_back_to_title_when_description_missing_or_short() -> None:
    assert choose_detection_text("Software Engineer", None) == "Software Engineer"
    assert choose_detection_text("Software Engineer", "tiny") == "Software Engineer"
    # Below the 60-char preference threshold the title still wins.
    assert choose_detection_text("Software Engineer", "x" * 59) == "Software Engineer"


def test_falls_back_to_description_when_title_empty() -> None:
    assert choose_detection_text("", "A perfectly adequate description here") == (
        "A perfectly adequate description here"
    )


# ---------------------------------------------------------------------------
# Chunking (keeps every chunk inside NLLB's context window)
# ---------------------------------------------------------------------------


def test_empty_input_yields_no_chunks() -> None:
    assert split_into_chunks("", 100) == []


def test_short_text_is_one_chunk() -> None:
    assert split_into_chunks("One short sentence.", 500) == ["One short sentence."]


def test_splits_at_sentence_boundaries_and_packs_greedily() -> None:
    text = "First sentence is here. Second sentence follows! Third one ends here?"
    chunks = split_into_chunks(text, 30)
    assert len(chunks) >= 2
    # No chunk exceeds the budget, and every original character survives
    # in order (join with a space approximates the re-join the caller does).
    assert all(len(c) <= 30 for c in chunks)
    assert "First sentence is here." in chunks[0]
    joined = " ".join(chunks).replace(" ", "")
    assert joined == text.replace(" ", "")


def test_cjk_punctuation_is_a_boundary() -> None:
    text = "我们招聘软件工程师。负责后端开发。请投递简历。还有更多职位等你来。"
    chunks = split_into_chunks(text, 25)
    assert len(chunks) >= 2
    assert all(len(c) <= 25 for c in chunks)


def test_oversized_single_sentence_is_hard_split() -> None:
    """A pathological sentence longer than the budget must still be split
    -- otherwise one row could blow past NLLB's ~1,024-token window."""
    text = "word " * 200  # 1000 chars, no sentence punctuation at all
    chunks = split_into_chunks(text.strip(), 100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_hard_split_prefers_word_boundaries() -> None:
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi"
    chunks = split_into_chunks(text, 30)
    # Split points land on spaces, not mid-word.
    for chunk in chunks:
        assert not chunk.startswith(" ")
        assert not chunk.endswith(" ")
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_blank_lines_are_piece_boundaries_packed_into_chunks() -> None:
    """Blank lines split the text into pieces; pieces then pack greedily,
    so only a budget too small for both paragraphs forces 2 chunks."""
    text = "Paragraph one line one.\n\nParagraph two line one."
    assert len(split_into_chunks(text, 500)) == 1  # both fit -> one chunk

    chunks = split_into_chunks(text, 40)
    assert len(chunks) == 2
    assert "Paragraph one line one." in chunks[0]
    assert "Paragraph two line one." in chunks[1]


# ---------------------------------------------------------------------------
# Row processing (injected fake translator -- no model)
# ---------------------------------------------------------------------------


def _job(**overrides: object) -> TranslationJob:
    defaults: dict = {
        "job_id": 1,
        "job_title": "招聘软件工程师，负责后端开发与系统维护工作",
        "description_clean": None,
        "language_code": None,
    }
    defaults.update(overrides)
    return TranslationJob(**defaults)  # type: ignore[arg-type]


def test_process_detection_row_english_writes_skip_markers_only() -> None:
    translator = FakeTranslator()
    job = _job(job_title="We are looking for a software engineer to join our team")
    payload = translation.process_detection_row(job, translator)  # type: ignore[arg-type]

    assert payload == {
        "language_code": "en",
        "job_title_en": None,
        "translated_by": None,
    }
    assert translator.calls == []  # English is never sent to the model


def test_title_only_detection_noise_is_the_documented_limitation() -> None:
    """Pin the KNOWN langdetect short-text artifact honestly: a bare
    content-word English title like "Senior Backend Engineer" (no
    function words, no description) can come back as another Latin
    language. This is the documented limitation, not a regression --
    production rows use the description for detection when one exists
    (choose_detection_text), and mis-translating an English original is
    survivable (the original column is never touched, and NLLB fed an
    English string mostly passes it through). If this assertion flips,
    langdetect's behavior changed under us -- re-check the batch's real
    output before celebrating."""
    from langdetect import detect

    probe = "Senior Backend Engineer"
    detected = detect(probe).lower()
    # What we EXPECT today: not 'en' (the noise), i.e. this title would
    # be routed to translation rather than skipped.
    assert detected != "en"
    # And the batch still records it without crashing.
    translator = FakeTranslator()
    payload = translation.process_detection_row(_job(job_title=probe), translator)  # type: ignore[arg-type]
    assert payload["language_code"] == detected
    assert payload["job_title_en"] is not None


def test_process_detection_row_chinese_translates_title_with_provenance() -> None:
    translator = FakeTranslator()
    job = _job()
    payload = translation.process_detection_row(job, translator)  # type: ignore[arg-type]

    assert payload["language_code"] in {"zh", "zh-cn"}
    assert payload["job_title_en"] == f"EN[{len(job.job_title)} chars]"
    assert payload["translated_by"] == DEFAULT_TRANSLATED_BY
    # The model was handed the right NLLB source code for Chinese.
    assert translator.calls[0][1] == "zho_Hans"


def test_process_detection_row_records_unmapped_language_without_translating() -> None:
    """A language missing from the map gets language_code recorded and
    nothing else -- never a guess through a wrong source code."""
    translator = FakeTranslator()
    # 'xx' is not in the map; detection may or may not return it from this
    # text, so force the state via a pre-set language_code on a text that
    # detection cannot confidently classify... instead, monkeypatch the
    # detector to make the branch deterministic.
    original = translation.detect_language
    translation.detect_language = lambda _t: "xx"  # type: ignore[assignment]
    try:
        job = _job(job_title="Some title text")
        payload = translation.process_detection_row(job, translator)  # type: ignore[arg-type]
    finally:
        translation.detect_language = original  # type: ignore[assignment]

    assert payload == {
        "language_code": "xx",
        "job_title_en": None,
        "translated_by": None,
    }
    assert translator.calls == []


def test_process_detection_row_undecidable_becomes_unknown() -> None:
    translator = FakeTranslator()
    original = translation.detect_language
    translation.detect_language = lambda _t: None  # type: ignore[assignment]
    try:
        payload = translation.process_detection_row(_job(), translator)  # type: ignore[arg-type]
    finally:
        translation.detect_language = original  # type: ignore[assignment]

    assert payload["language_code"] == "unknown"
    assert payload["job_title_en"] is None
    assert translator.calls == []


def test_process_detection_row_rejects_echoed_non_english_output() -> None:
    """NLLB's echo failure mode must not write the original text into
    job_title_en -- record detection only, keep the column NULL."""

    class EchoingTranslator:
        provenance_label = DEFAULT_TRANSLATED_BY

        def translate(self, source_text: str, flores_source_lang: str) -> str:
            return source_text  # the failure mode: input returned unchanged

    payload = translation.process_detection_row(_job(), EchoingTranslator())  # type: ignore[arg-type]
    assert payload["language_code"] in {"zh", "zh-cn"}
    assert payload["job_title_en"] is None
    assert payload["translated_by"] is None


def test_process_description_row_uses_recorded_language() -> None:
    translator = FakeTranslator()
    job = _job(language_code="fr", description_clean="Nous recherchons un developpeur.")
    result = translation.process_description_row(job, translator)  # type: ignore[arg-type]

    assert result == "EN[32 chars]"  # FakeTranslator: ASCII canned output
    assert translator.calls == [("Nous recherchons un developpeur.", "fra_Latn")]


def test_process_description_row_skips_unmapped_and_english() -> None:
    translator = FakeTranslator()
    english = _job(language_code="en", description_clean="A description.")
    unmapped = _job(language_code="xx", description_clean="A description.")

    assert translation.process_description_row(english, translator) is None  # type: ignore[arg-type]
    assert translation.process_description_row(unmapped, translator) is None  # type: ignore[arg-type]
    assert translator.calls == []


def test_process_description_row_dry_run_returns_none_but_translates_sample() -> None:
    translator = FakeTranslator()
    job = _job(language_code="fr", description_clean="Nous recherchons un developpeur.")
    result = translation.process_description_row(job, translator, dry_run=True)  # type: ignore[arg-type]

    assert result is None  # nothing to write
    assert len(translator.calls) == 1  # the sample preview still ran


# ---------------------------------------------------------------------------
# Provenance label
# ---------------------------------------------------------------------------


def test_provenance_label_shape() -> None:
    """Mirrors title_classified_by's method:model:version convention."""
    label = translation.NllbTranslator(TranslationSettings()).provenance_label
    assert label == "translation:nllb-200-distilled-600M:v1"


# ---------------------------------------------------------------------------
# Database predicates (string-level -- no database needed)
# ---------------------------------------------------------------------------


def test_fetch_predicates_filter_on_the_right_columns() -> None:
    """Pin the two idempotency predicates: they are what make re-runs
    safe without any extra bookkeeping column."""
    import inspect

    title_src = inspect.getsource(translation.fetch_detection_pending)
    assert "j.language_code IS NULL" in title_src
    assert "j.job_title_en IS NULL" in title_src

    desc_src = inspect.getsource(translation.fetch_description_pending)
    assert "NOT IN ('en', 'unknown')" in desc_src
    assert "jd.description_en IS NULL" in desc_src
    assert "j.job_title_en IS NOT NULL" in desc_src
