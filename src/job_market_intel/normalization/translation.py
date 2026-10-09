"""English translation of non-English jobs (language detection + NLLB).

Why this exists (the confirmed driver)
--------------------------------------
Three pieces of this project's enrichment stack are English-only, and the
scraper queue ahead (Persian, Korean, Ukrainian, Spanish, Russian, Nepali,
Icelandic, Serbian, Kazakh, Chinese Traditional ... sites from the audit's
FREE-API list) would otherwise hit the same wall 51job just demonstrated:

* the ``ref.normalized_job_titles`` taxonomy (2,046 entries, zero of them
  non-Latin) that ``title_classification.py`` embeds against -- on 51job's
  Chinese titles the multilingual model mostly coped (299/305 matched) but
  with confidently *wrong* matches visible in production data (a Chinese
  "fastener quality engineer" title matched "MLOps Engineer" at 0.77);
* the ``ref.skills`` vocabulary (461 English terms) that
  ``skill_extraction.py`` scans descriptions for -- 20% yield on Chinese
  descriptions versus ~85% project-wide on English ones;
* PostgreSQL full-text search and every downstream English-language
  analysis query.

The fix that serves all three at once: translate each non-English job to
English **once, at rest, in a batch** -- never inline in a scraper
pipeline (a model download or inference failure must not block ingestion,
and scrapers stay source-shaped). Raw text is never modified; English
lives in additive columns (``language_code``/``job_title_en``/
``translated_by`` on ``core.jobs``, ``description_en`` on
``core.job_descriptions`` -- see ``migrations/add_translation_columns
.sql``). Consumers read ``COALESCE(translated, original)``.

Engine choice: local NLLB, no API key, no per-character billing
----------------------------------------------------------------
``facebook/nllb-200-distilled-600M`` via the already-installed
``transformers``/``torch`` stack (sentence-transformers brought both) --
keeping this project's confirmed hard requirement of zero API-key, zero
per-request cost (the same requirement documented at the top of
``.github/workflows/classify_titles.yml``). One model covers 100+ source
languages, so the ever-growing scraper queue needs no per-pair models and
no new dependency besides ``sentencepiece`` (the tokenizer backend) and
``langdetect`` (detection). Weights are downloaded once and cached
(``~/.cache/huggingface`` locally; an ``actions/cache`` step in CI).

Batch flow (scripts/run_translation_batch.py orchestrates)
----------------------------------------------------------
Two idempotent passes, both keyed off plain column state so no extra
bookkeeping is needed:

1. **Detection + title pass** -- selects rows where ``language_code IS
   NULL`` (never processed) plus rows whose non-English ``job_title_en``
   is still NULL (a previously interrupted row; all fields for a row are
   written in one UPDATE, so this only triggers after a crash mid-row).
   Detection runs on the *longest* available text (description when >= 60
   chars, else title) because language detectors are far more reliable on
   longer text. English rows get ``language_code='en'`` and nothing else
   (terminal state: detected, not translated). Non-English rows get their
   title translated in the same UPDATE that records detection.

2. **Description pass** -- selects non-English rows with a title already
   translated and a description that still lacks ``description_en``.
   English rows are excluded by the predicate itself (no description_en
   is ever needed for them), so no "processed" flag has to live on
   ``job_descriptions``.

Long text is split on sentence boundaries and translated in chunks
(NLLB's context window is ~1,024 tokens; unchunked 3,000-char job
descriptions would silently truncate). Chunk translations are joined with
a space -- translated descriptions are normalized single-spaced English
prose, not formatting-preserving copies.

Determinism
-----------
``langdetect`` is probabilistic; its seed is pinned at import time
(``DetectorFactory.seed = 0``) so re-running the batch over unchanged
input yields the same language decision -- without this, a row could
flip languages between runs and re-translate forever.

Script first, statistics second
-------------------------------
Detection has two authorities, tried in order (``detect_language``):

1. **Script ranges** (``detect_by_script``) for scripts langdetect
   cannot handle: no Armenian/Georgian/Ethiopic/Myanmar/Khmer/Lao/
   Sinhala profiles exist at all, and short Han/Hangul/Kana text was
   observed routing to ko/no/vi (Chinese) and Armenian to et (Estonian)
   in the first production run. A script match is unambiguous and works
   even on 3-character titles -- before the minimum-length gate.
2. **langdetect** for everything else, where its profiles work (Latin,
   Cyrillic, Arabic, Devanagari, Thai ...).

A translated *output* is additionally sanity-checked
(``looks_like_non_english_output``): if NLLB echoed the input or
produced mostly non-ASCII letters, the row records detection only
rather than pretend English content landed in ``job_title_en``.

Known limitations (deliberate, documented rather than papered over)
-------------------------------------------------------------------
* Detection misfires on very short title-only rows are possible
  (langdetect noise -- observed: "Senior Backend Engineer" detects as
  German because content-word-only titles lack the function words it
  keys on); the practical cost is translating text that was already
  English -- a paraphrase that still embeds and scans fine -- not
  corruption of the original (originals are never touched). The
  description-first detection choice exists precisely to keep real rows
  off this path; title-only exposure is limited to English-source rows
  with missing descriptions (Indeed's known gap). If this ever needs a
  harder fix, the levers are a per-source language hint (each source's
  dominant language is known) or an ASCII/stopword veto.
* Unmapped languages are recorded (``language_code`` set, no
  translation, warning logged) rather than force-guessed through a wrong
  NLLB source code, which would produce fluent-but-wrong output.
* NLLB output quality is good-but-not-perfect for technical prose; every
  translated cell keeps its ``translated_by`` provenance so quality can
  be audited, and re-translation is a column reset away if a better
  engine arrives.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from langdetect import DetectorFactory, LangDetectException, detect
from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

# langdetect is probabilistic -- pin the seed ONCE at import so repeated
# runs over unchanged rows make the same call (see module docstring).
DetectorFactory.seed = 0

#: Provenance label written to core.jobs.translated_by, mirroring
#: title_classified_by's "method:model:version" shape.
DEFAULT_TRANSLATED_BY = "translation:nllb-200-distilled-600M:v1"

#: ISO 639-1 code langdetect emits -> NLLB/FLORES-200 source language.
#: ``"en" -> None`` is the load-bearing entry: English is detected and
#: then *skipped*, which is what keeps compute off the ~90% of the
#: project that is already English. Broad on purpose: every language the
#: audit's remaining scraper queue is expected to produce (hy, fa, ko,
#: uk, ne, is, sr, kk, zh-tw ...) plus common incidental ones. An entry
#: missing here is NOT a crash -- see ``resolve_flores_code``.
_ISO639_1_TO_FLORES: dict[str, str | None] = {
    "en": None,  # detected, not translated -- the skip path
    # Chinese: langdetect emits zh-cn / zh-tw variants; base 'zh' kept in
    # the map as the conservative default (Simplified).
    "zh": "zho_Hans",
    "zh-cn": "zho_Hans",
    "zh-tw": "zho_Hant",
    # The audit's known upcoming sources
    "fa": "pes_Arab",  # Persian/Farsi (Jobinja, IranTalent, Jobvision)
    "ko": "kor_Hang",  # Korean (JobKorea)
    "uk": "ukr_Cyrl",  # Ukrainian (Work.ua, VDAB's neighbor)
    "es": "spa_Latn",  # Spanish (Tecoloco x4)
    "ru": "rus_Cyrl",  # Russian (hh KZ/KG/UZ, Rabota.by)
    "ne": "nep_Deva",  # Nepali (Merojob)
    "is": "isl_Latn",  # Icelandic (Vinnumalastofnun)
    "sr": "srp_Cyrl",  # Serbian (Infostud)
    "kk": "kaz_Cyrl",  # Kazakh (hh KZ)
    "tr": "tur_Latn",  # Turkish
    "ar": "arb_Arab",  # Arabic
    "hy": "hye_Armn",  # Armenian (job.am -- already ingested)
    "fr": "fra_Latn",  # French (Emploitic, France Travail)
    # Common incidental detections elsewhere
    "pt": "por_Latn",
    "de": "deu_Latn",
    "it": "ita_Latn",
    "nl": "nld_Latn",
    "pl": "pol_Latn",
    "cs": "ces_Latn",
    "sk": "slk_Latn",
    "hu": "hun_Latn",
    "ro": "ron_Latn",
    "bg": "bul_Cyrl",
    "el": "ell_Grek",
    "sv": "swe_Latn",
    "da": "dan_Latn",
    "no": "nob_Latn",
    "fi": "fin_Latn",
    "et": "est_Latn",
    "lv": "lav_Latn",
    "lt": "lit_Latn",
    "id": "ind_Latn",
    "ms": "msa_Latn",
    "vi": "vie_Latn",
    "th": "tha_Thai",
    "ja": "jpn_Jpan",
    "hi": "hin_Deva",
    "bn": "ben_Beng",
    "ta": "tam_Taml",
    "te": "tel_Telu",
    "ur": "urd_Arab",
    # Hebrew was 'heb_Arab' (no such FLORES code) until JobMaster (IL) made Hebrew live
    "he": "heb_Hebr",
    "ka": "kat_Geor",
    "az": "aze_Latn",
    "uz": "uzb_Latn",
    "ky": "kir_Cyrl",
    "mn": "mon_Cyrl",
    "sq": "sqi_Latn",
    "ca": "cat_Latn",
    "eu": "eus_Latn",
    "gl": "glg_Latn",
    "hr": "hrv_Latn",
    "sl": "slv_Latn",
    "fil": "tgl_Latn",
    "tl": "tgl_Latn",  # Tagalog -- langdetect emits 'tl', not 'fil' (observed in production run)
    "af": "afr_Latn",  # Afrikaans (observed in production run)
    "bs": "bos_Latn",  # Bosnian
    "so": "som_Latn",  # Somali
    "cy": "cym_Latn",  # Welsh
    "ga": "gle_Latn",  # Irish
    "mt": "mlt_Latn",  # Maltese
    "lb": "ltz_Latn",  # Luxembourgish
    "co": "cos_Latn",  # Corsican
    "fy": "fry_Latn",  # Western Frisian
    "su": "sun_Latn",  # Sundanese
    "ha": "hau_Latn",  # Hausa
    "yo": "yor_Latn",  # Yoruba
    "ig": "ibo_Latn",  # Igbo
    "sw": "swh_Latn",
    "km": "khm_Khmr",
    "lo": "lao_Laoo",
    "si": "sin_Sinh",
    "my": "mya_Mymr",
    "am": "ethi_Ethi",
    "gu": "guj_Gujr",
    "kn": "kan_Knda",
    "ml": "mal_Mlym",
    "pa": "pan_Guru",
}

#: Minimum length for detection to be attempted on the chosen text;
#: shorter than this and we record 'unknown' rather than let a detector
#: guess from a handful of characters.
_MIN_DETECTION_CHARS = 10

#: Prefer the description for detection when it is at least this long --
#: detectors are far more reliable on longer text than on a 15-char title.
_DETECTION_PREFERRED_DESC_CHARS = 60


class TranslationSettings(BaseSettings):
    """Configuration for the translation batch (env prefix ``TRANSLATE_``).

    Attributes:
        model_name: Hugging Face model id; anything NLLB-family works.
        target_lang: FLORES-200 target -- fixed to English here by design
            (this project translates *to* English, never between others).
        max_chars_per_chunk: Sentence-chunking budget for descriptions
            (characters, roughly proportional to NLLB's ~1,024-token
            window; 800 chars is comfortably inside it for CJK text where
            chars ~= tokens).
        max_new_tokens: Generation cap per chunk.
        num_beams: Beam width -- 2 balances quality/speed for short titles
            on CPU; raise for a slower, sharper translation.
        quantize_dynamic: Apply torch int8 dynamic quantization to linear
            layers on load. ~2x faster on CPU with negligible quality
            change for this task; set false to compare.
    """

    model_config = SettingsConfigDict(
        env_prefix="TRANSLATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model_name: str = "facebook/nllb-200-distilled-600M"
    target_lang: str = "eng_Latn"
    max_chars_per_chunk: int = Field(default=800, ge=100)
    max_new_tokens: int = Field(default=384, ge=16)
    num_beams: int = Field(default=2, ge=1, le=8)
    quantize_dynamic: bool = True


def resolve_flores_code(language_code: str) -> str | None:
    """Maps a langdetect ISO 639-1 code to an NLLB/FLORES-200 source code.

    Returns:
        The FLORES code, ``None`` for English (the skip path), or
        ``None`` for an unmapped language -- callers must distinguish the
        two by the input code (English => nothing needed; unknown =>
        recorded and warned, never guessed through a wrong source code).
    """
    if not language_code:
        return None
    code = language_code.lower()
    if code in _ISO639_1_TO_FLORES:
        return _ISO639_1_TO_FLORES[code]
    # zh-cn/zh-tw style variants -> try the base language tag.
    base = code.split("-", 1)[0]
    return _ISO639_1_TO_FLORES.get(base)


#: Script pre-detection -- codepoint ranges for languages whose script
#: langdetect either has NO profile (Armenian, Georgian, Ethiopic,
#: Myanmar, Khmer, Lao, Sinhala) or badly confuses on short text (the
#: first production run routed Chinese titles to ko/no/vi and Armenian
#: to et). ORDERED BY PRIORITY so mixed-script texts resolve to the
#: intended language: kana before Hangul before Han (a Japanese title
#: with kanji -> ja, a Korean title with hanja -> ko), then the
#: single-script languages (their scripts never meaningfully co-occur --
#: mixed Armenian/Cyrillic job.am titles resolve to Armenian, which is
#: the job's actual language). Latin, Cyrillic, Arabic, Devanagari and
#: Thai are deliberately ABSENT: langdetect has working profiles for
#: them and can distinguish what a bare range cannot (Russian vs
#: Ukrainian, Persian vs Arabic, Hindi vs Nepali).
#: (Lo, Hi, iso-639-1) -- inclusive codepoint bounds, see PUA note:
_SCRIPT_CODEPOINT_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x3040, 0x30FF, "ja"),  # Hiragana + Katakana
    (0x1100, 0x11FF, "ko"),  # Hangul Jamo
    (0xAC00, 0xD7AF, "ko"),  # Hangul Syllables
    (0x3400, 0x4DBF, "zh"),  # CJK Unified Ideographs Ext A
    (0x4E00, 0x9FFF, "zh"),  # CJK Unified Ideographs
    (0x0530, 0x058F, "hy"),  # Armenian
    (0xFB13, 0xFB17, "hy"),  # Armenian ligatures
    (0x10A0, 0x10FF, "ka"),  # Georgian
    (0x1C90, 0x1CBF, "ka"),  # Georgian Mtavruli
    (0x2D00, 0x2D2F, "ka"),  # Georgian Sup
    (0x1200, 0x137F, "am"),  # Ethiopic
    (0x1000, 0x109F, "my"),  # Myanmar
    (0x1780, 0x17FF, "km"),  # Khmer
    (0x0E80, 0x0EFF, "lo"),  # Lao
    (0x0D80, 0x0DFF, "si"),  # Sinhala
)


def detect_by_script(text_to_probe: str) -> str | None:
    """Returns a language code from unambiguous codepoint ranges, else ``None``.

    Runs BEFORE langdetect (see ``detect_language``): a script match is
    a stronger signal than a probabilistic profile, and it stays
    reliable even on titles too short for statistical detection --
    which is exactly where langdetect produced the observed misroutes.
    Ranges are checked in priority order, so the first *matching
    range* wins, not the first character seen (that is what makes
    kana-bearing Japanese beat its own kanji).
    """
    for lo, hi, code in _SCRIPT_CODEPOINT_RANGES:
        if any(lo <= ord(ch) <= hi for ch in text_to_probe):
            return code
    return None


def detect_language(text_to_probe: str | None) -> str | None:
    """Detects an ISO 639-1 code (lowercased), or ``None`` if undecidable.

    Two authorities, in order (the "script first" rule):

    1. ``detect_by_script`` -- unambiguous Unicode ranges for scripts
       langdetect either has no profile for (Armenian, Georgian,
       Ethiopic, Myanmar, Khmer, Lao, Sinhala) or badly confuses on
       short text (observed in production: Chinese titles routed to
       ko/no/vi, Armenian to et). Script matches are reliable even on a
       3-character title, so they run BEFORE the minimum-length gate.
    2. langdetect for everything else -- seed-pinned at import so
       results are deterministic across runs.
    """
    if not text_to_probe or not text_to_probe.strip():
        return None
    scripted = detect_by_script(text_to_probe)
    if scripted is not None:
        return scripted
    if len(text_to_probe.strip()) < _MIN_DETECTION_CHARS:
        return None
    try:
        return detect(text_to_probe).lower()
    except LangDetectException:
        return None


def choose_detection_text(title: str, description_clean: str | None) -> str | None:
    """Picks the most reliable text to run detection on: the description
    when it is usefully long, else the title (see constants for why)."""
    if description_clean and len(description_clean) >= _DETECTION_PREFERRED_DESC_CHARS:
        return description_clean
    return title or description_clean


def split_into_chunks(text_to_split: str, max_chars: int) -> list[str]:
    """Splits text into translation chunks at sentence boundaries.

    Sentence-ending punctuation (both CJK and Latin) and blank lines are
    boundaries; pieces are packed greedily up to ``max_chars``. A single
    pathological sentence longer than ``max_chars`` is hard-split so no
    input can ever exceed NLLB's context window. Never returns empty
    chunks, and never returns more text than it was given (pieces are
    re-joined by the caller in order).
    """
    if not text_to_split:
        return []
    # Split AFTER sentence punctuation (kept with the left piece) or on
    # blank lines; single newlines stay inside a piece to keep lists
    # from shattering into one-token chunks.
    pieces = [
        piece.strip()
        for piece in re.split(r"(?<=[。！？.!?；;])\s+|\n{2,}", text_to_split)
        if piece and piece.strip()
    ]
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if len(piece) > max_chars:
            # Flush what we have, then hard-split the oversized piece.
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(piece):
                end = min(start + max_chars, len(piece))
                # Prefer splitting at a space just before the limit.
                if end < len(piece):
                    space_at = piece.rfind(" ", start + max_chars // 2, end)
                    if space_at != -1:
                        end = space_at
                chunks.append(piece[start:end].strip())
                start = end
            continue
        candidate = f"{current} {piece}".strip() if current else piece
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


class NllbTranslator:
    """Translates text to English with a local NLLB model.

    The model loads lazily on first use (a batch that turns out to have
    zero non-English rows pays nothing) and stays loaded for the batch --
    loading, not inference, is the expensive part.

    One model instance serves every source language: only
    ``tokenizer.src_lang`` changes per call; the generation target stays
    ``settings.target_lang`` (English) via ``forced_bos_token_id``.
    """

    def __init__(self, settings: TranslationSettings | None = None) -> None:
        self._settings = settings or TranslationSettings()
        self._model = None
        self._tokenizer = None
        self._target_id: int | None = None

    @property
    def provenance_label(self) -> str:
        """What gets written to ``translated_by`` for rows this engine handled."""
        short_name = self._settings.model_name.rsplit("/", 1)[-1]
        return f"translation:{short_name}:v1"

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        started = time.monotonic()
        logger.info(
            "Loading translation model {} (first use in this process)...",
            self._settings.model_name,
        )
        tokenizer = AutoTokenizer.from_pretrained(self._settings.model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(self._settings.model_name)
        if self._settings.quantize_dynamic:
            model = torch.ao.quantization.quantize_dynamic(
                model, {torch.nn.Linear}, dtype=torch.qint8
            )
        model.eval()
        self._tokenizer = tokenizer
        self._model = model
        self._target_id = tokenizer.convert_tokens_to_ids(self._settings.target_lang)
        logger.info(
            "Translation model loaded in {:.1f}s (quantize_dynamic={}, target={}).",
            time.monotonic() - started,
            self._settings.quantize_dynamic,
            self._settings.target_lang,
        )

    def translate(self, source_text: str, flores_source_lang: str) -> str:
        """Translates one text to English; chunks internally.

        Args:
            source_text: Original-language text (title or description).
            flores_source_lang: NLLB source code, e.g. ``"zho_Hans"``.

        Returns:
            English text (chunk translations joined by a space).
        """
        if not source_text or not source_text.strip():
            return ""
        self._ensure_loaded()
        import torch

        assert self._model is not None and self._tokenizer is not None
        assert self._target_id is not None
        self._tokenizer.src_lang = flores_source_lang

        translations: list[str] = []
        for chunk in split_into_chunks(source_text, self._settings.max_chars_per_chunk):
            encoded = self._tokenizer(
                chunk,
                return_tensors="pt",
                truncation=True,
                max_length=512,
            )
            with torch.no_grad():
                generated = self._model.generate(
                    **encoded,
                    forced_bos_token_id=self._target_id,
                    num_beams=self._settings.num_beams,
                    max_new_tokens=self._settings.max_new_tokens,
                )
            decoded = self._tokenizer.decode(generated[0], skip_special_tokens=True).strip()
            if decoded:
                translations.append(decoded)
        return " ".join(translations)

    def translate_batch(
        self,
        texts: list[str],
        flores_source_lang: str,
        *,
        batch_size: int = 8,
    ) -> list[str]:
        """Translates a list of texts to English, batched by chunks.

        Every input text is internally split into 800-char chunks (same
        policy as :meth:`translate`); the chunk strings are then fed to
        the tokenizer/model in groups of ``batch_size`` so a single
        ``generate`` call services several chunks. That is the big
        per-row-overhead saving on CPU: a row that splits into k chunks
        becomes k chunks of throughput for one process instead of one
        process call per row.

        The per-row semantics are preserved: rows whose ``max_new_tokens``
        cap's endpoints get copied over one by one; NF strip on newlines
        is not done here, only chunk-joining at the end. Empty/blank
        rows yield `""`.
        """
        if not texts:
            return []
        self._ensure_loaded()
        import torch

        per_text_chunks: list[list[str]] = []
        flat_chunks: list[str] = []
        for text_value in texts:
            if not text_value or not text_value.strip():
                chunks: list[str] = []
            else:
                chunks = list(
                    split_into_chunks(text_value, self._settings.max_chars_per_chunk)
                )
            per_text_chunks.append(chunks)
            flat_chunks.extend(chunks)

        if not flat_chunks:
            return [""] * len(texts)

        decoded_chunks: list[str] = []
        tokenizer = self._tokenizer
        tokenizer.src_lang = flores_source_lang
        for start in range(0, len(flat_chunks), batch_size):
            group = flat_chunks[start : start + batch_size]
            encoded = tokenizer(
                group,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            )
            with torch.no_grad():
                generated = self._model.generate(
                    **encoded,
                    forced_bos_token_id=self._target_id,
                    num_beams=self._settings.num_beams,
                    max_new_tokens=self._settings.max_new_tokens,
                )
            decoded_chunks.extend(
                d.strip() for d in tokenizer.batch_decode(generated, skip_special_tokens=True)
            )

        out: list[str] = []
        cursor = 0
        for chunks in per_text_chunks:
            if not chunks:
                out.append("")
            else:
                out.append(" ".join(d for d in decoded_chunks[cursor : cursor + len(chunks)] if d))
            cursor += len(chunks)
        return out


@dataclass(frozen=True)
class TranslationJob:
    """One row the batch is considering, with everything needed to decide."""

    job_id: int
    job_title: str
    description_clean: str | None
    language_code: str | None  # pre-existing detection, if any (retry case)


def fetch_detection_pending(session: Session, limit: int | None = None) -> list[TranslationJob]:
    """Rows needing detection + title translation.

    Predicate covers two states: never processed (``language_code IS
    NULL``) and interrupted mid-row (non-English, detected, but the title
    translation never landed -- all fields for a row are written in one
    UPDATE, so this only happens after a crash between commits).
    """
    query = (
        "SELECT j.job_id, j.job_title, jd.description_clean, j.language_code "
        "FROM core.jobs j "
        "LEFT JOIN core.job_descriptions jd ON jd.job_id = j.job_id "
        "WHERE j.language_code IS NULL "
        "   OR (j.language_code NOT IN ('en', 'unknown') AND j.job_title_en IS NULL)"
    )
    if limit:
        query += f" LIMIT {int(limit)}"
    rows = session.execute(text(query)).all()
    return [
        TranslationJob(
            job_id=row.job_id,
            job_title=row.job_title,
            description_clean=row.description_clean,
            language_code=row.language_code,
        )
        for row in rows
    ]


def fetch_description_pending(session: Session, limit: int | None = None) -> list[TranslationJob]:
    """Non-English, title-translated rows whose description is untranslated.

    English rows cannot match this predicate (their ``language_code`` is
    excluded), which is why ``job_descriptions`` needs no processed flag
    of its own -- see module docstring.
    """
    query = (
        "SELECT j.job_id, j.job_title, jd.description_clean, j.language_code "
        "FROM core.jobs j "
        "JOIN core.job_descriptions jd ON jd.job_id = j.job_id "
        "WHERE j.language_code IS NOT NULL "
        "  AND j.language_code NOT IN ('en', 'unknown') "
        "  AND j.job_title_en IS NOT NULL "
        "  AND jd.description_clean IS NOT NULL "
        "  AND jd.description_en IS NULL"
    )
    if limit:
        query += f" LIMIT {int(limit)}"
    rows = session.execute(text(query)).all()
    return [
        TranslationJob(
            job_id=row.job_id,
            job_title=row.job_title,
            description_clean=row.description_clean,
            language_code=row.language_code,
        )
        for row in rows
    ]


def looks_like_non_english_output(translated: str) -> bool:
    """True when a "translation" is mostly non-ASCII letters.

    Catches NLLB's failure mode of echoing the input when the source
    language token was wrong or the model gave up (observed: a Chinese
    title routed through a Norwegian source came back identical to the
    original). Such output must NOT land in ``job_title_en`` -- it would
    pretend to be English while classification/skills treat it as such.
    English output can legitimately contain accented letters (cafe ->
    cafe with an accent, reno, Sao), hence the majority threshold, not
    "any non-ASCII".
    """
    letters = [ch for ch in translated if ch.isalpha()]
    if not letters:
        return False
    non_ascii = sum(1 for ch in letters if ord(ch) > 0x7F)
    return non_ascii / len(letters) > 0.5


def process_detection_row(
    job: TranslationJob,
    translator: NllbTranslator,
) -> dict:
    """Detection + title translation for one row; returns the UPDATE payload.

    Returns:
        A dict of column -> value to write (all columns in ONE UPDATE for
        atomicity). On a translation failure for a mapped language the
        exception propagates untouched: the row stays unmarked and is
        retried next run rather than half-written. Dry-run previews are
        orchestrated by the caller (scripts/run_translation_batch.py),
        which owns how many samples to spend model inference on.
    """
    probe = choose_detection_text(job.job_title, job.description_clean)
    detected = detect_language(probe)
    if detected is None:
        detected = "unknown"

    if detected == "en":
        return {"language_code": "en", "job_title_en": None, "translated_by": None}

    flores = resolve_flores_code(detected)
    if flores is None:
        # 'unknown' or a language missing from the map: record the
        # detection, translate nothing, warn (see module docstring).
        logger.warning(
            "job {}: no translation for detected language {!r} -- recording only.",
            job.job_id,
            detected,
        )
        return {"language_code": detected, "job_title_en": None, "translated_by": None}

    translated_title = translator.translate(job.job_title, flores)
    if looks_like_non_english_output(translated_title):
        # NLLB echoed (or garbled into non-English) the input -- record
        # the detection but leave job_title_en NULL so the row keeps its
        # original text for downstream consumers and gets retried next
        # run (cheaper than a second in-run attempt, and a later run may
        # succeed if settings change).
        logger.warning(
            "job {}: translation output for {!r} is not English ({!r}) -- "
            "recording detection only.",
            job.job_id,
            job.job_title,
            translated_title[:60],
        )
        return {"language_code": detected, "job_title_en": None, "translated_by": None}
    return {
        "language_code": detected,
        "job_title_en": translated_title,
        "translated_by": translator.provenance_label,
    }


def apply_title_translation(session: Session, job_id: int, payload: dict) -> None:
    """Writes one row's detection/translation result (single UPDATE)."""
    session.execute(
        text(
            "UPDATE core.jobs SET language_code = :language_code, "
            "job_title_en = :job_title_en, translated_by = :translated_by "
            "WHERE job_id = :job_id"
        ),
        {**payload, "job_id": job_id},
    )


def process_description_row(
    job: TranslationJob,
    translator: NllbTranslator,
    *,
    dry_run: bool = False,
) -> str | None:
    """Translates one description; returns the English text (or None in dry-run).

    Args:
        job: Must carry a non-English ``language_code`` (callers pre-filter
            via ``fetch_description_pending``).
    """
    if not job.description_clean:
        return None
    flores = resolve_flores_code(job.language_code or "")
    if flores is None:
        return None
    if dry_run:
        sample = job.description_clean[:200]
        translated = translator.translate(sample, flores)
        logger.info(
            "job {} DRY-RUN desc (first 200 chars) -> {!r}",
            job.job_id,
            translated[:200],
        )
        return None
    description_en = translator.translate(job.description_clean, flores)
    if looks_like_non_english_output(description_en):
        logger.warning(
            "job {}: translated description is not English (starts {!r}) -- skipped.",
            job.job_id,
            description_en[:60],
        )
        return None
    return description_en


def apply_description_translation(session: Session, job_id: int, description_en: str) -> None:
    """Writes one translated description."""
    session.execute(
        text(
            "UPDATE core.job_descriptions SET description_en = :description_en "
            "WHERE job_id = :job_id"
        ),
        {"description_en": description_en, "job_id": job_id},
    )
