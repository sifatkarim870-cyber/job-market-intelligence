"""Unit tests for the description section extractor.

Each test pins a specific bug that occurred while building this, against text
taken verbatim from the corpus. If a regression reintroduces any of them, the
test names why it matters.

Run with:  uv run python -m pytest tests/unit/normalization/test_section_extraction.py
"""

from __future__ import annotations

from job_market_intel.normalization.section_extraction import (
    SectionKind,
    extract_description_sections,
    find_headings,
)


def _kinds(text: str) -> list[str]:
    return [h.kind for h in find_headings(text)]


def _headings(text: str) -> list[str]:
    return [h.text.strip() for h in find_headings(text)]


class TestHeadingLocation:
    def test_persian_heading_detected(self):
        text = "شرح وظایف: • مراجعه حضوری • معرفی محصولات"
        assert _headings(text) == ["شرح وظایف"]

    def test_zwnj_and_space_spellings_match_the_same(self):
        """Boards write Persian inter-word ZWNJ as a space, a ZWNJ, or nothing.
        All three must resolve to the same heading."""
        with_zwnj = "مسئولیت\u200cها: • انجام امور"
        with_space = "مسئولیت ها: • انجام امور"
        with_none = "مسئولیتها: • انجام امور"
        for text in (with_zwnj, with_space, with_none):
            assert SectionKind.RESPONSIBILITIES in _kinds(text), text

    def test_vietnamese_diacritics_fold(self):
        """Written as 'Mô tả công việc', 'MÔ TẢ CÔNG VIỆC' and 'Mo ta cong viec'
        in the wild; all three are the same heading."""
        for text in (
            "Mô tả công việc: Quản lý chiến lược",
            "MÔ TẢ CÔNG VIỆC: Quản lý chiến lược",
            "Mo ta cong viec: Quản lý chiến lược",
        ):
            assert SectionKind.RESPONSIBILITIES in _kinds(text), text

    def test_longest_heading_wins(self):
        """'شرایط احراز' must not be shadowed by the 'شرایط' prefix."""
        text = "شرایط احراز: • حداقل 3 سال سابقه"
        assert _headings(text) == ["شرایط احراز"]

    def test_persian_heading_after_a_latin_word_is_found(self):
        """Regression: a Latin word-boundary guard rejected this heading, because
        the character before it was the 's' of 'DataTables'. jobvision lost a
        heading and its sections ran together."""
        text = "آشنایی با ابزارهایی مانند DataTables وظایف اصلی: • تحلیل طراحی"
        assert "وظایف اصلی" in _headings(text)

    def test_heading_after_flattened_newline_is_found(self):
        """Regression: the cleaner turns '<h3>Responsibilities</h3>End-to-end
        control' into '...environment. Responsibilities End-to-end control', so
        there is no separator. The sentence-ending period is the only signal."""
        text = (
            "in a fast-paced environment. Responsibilities End-to-end "
            "controllership for assigned legal entities. Requirements 6+ years "
            "of B2B SAAS closing experience."
        )
        kinds = _kinds(text)
        assert SectionKind.RESPONSIBILITIES in kinds
        assert SectionKind.REQUIREMENTS in kinds

    def test_heading_fused_to_the_next_word_is_found(self):
        """Regression: remoteok renders '</b>Distributor' with no whitespace, so
        the heading and the first item touch."""
        text = (
            "premium spirits brand in a competitive market. Key Responsibilities"
            "Distributor Management Work closely with partners."
        )
        assert SectionKind.RESPONSIBILITIES in _kinds(text)

    def test_mid_sentence_word_is_not_a_heading(self):
        """'experience' inside '3+ years of PM experience in developer tools'
        must not become a heading: not at a block start, followed by lowercase."""
        text = "Requirements 6+ years of PM experience in developer tools."
        assert _headings(text) == ["Requirements"]

    def test_persian_sentence_is_not_a_heading(self):
        """'مزیت' inside the sentence 'مزیت محسوب می‌شود' is not a 'Nice to have'
        heading. Persian has no letter case, so the uppercase test cannot fire."""
        text = "سابقه بازاریابی و فروش حضوری مزیت محسوب می‌شود. مزایا - حقوق ثابت"
        assert "مزیت" not in _headings(text)

    def test_empty_text_yields_nothing(self):
        assert find_headings("") == []


class TestRouting:
    def test_persian_jobvision_sections_split_correctly(self):
        """Verbatim corpus text. Regression: 'وظایف اصلی' went undetected, so its
        heading text leaked into a responsibilities item as
        '...DataTables وظایف اصلی:'."""
        text = (
            "شاخص\u200cهای کلیدی: • داشتن نمونه\u200cکار عملی • تجربه کار با "
            "پروژه\u200cهای دارای Web API و دیتابیس SQL Server شرح وظایف: • آشنایی با "
            "معماری\u200cهای MVC • آشنایی با اصول SOLID"
        )
        result = extract_description_sections(text)
        assert result.requirements is not None
        assert "نمونه" in result.requirements
        assert "SQL Server" in result.requirements
        assert result.responsibilities is not None
        assert "MVC" in result.responsibilities
        # The second heading must not survive as content.
        assert "وظایف" not in result.responsibilities

    def test_dash_separated_list_is_split(self):
        """jobinja-style postings use ' - ' as the only list delimiter."""
        text = (
            "مجموعه‌ای با سابقه در صنعت هستیم. شرح وظایف - مراجعه حضوری به فروشگاه "
            "- معرفی محصولات - پیگیری سفارش‌ها شرایط احراز - ساکن تهران - ترجیحاً خانم"
        )
        result = extract_description_sections(text)
        assert result.responsibilities is not None
        assert "مراجعه حضوری به فروشگاه" in result.responsibilities
        assert "معرفی محصولات" in result.responsibilities
        assert result.requirements is not None
        assert "ساکن تهران" in result.requirements

    def test_qualification_subfields_stay_in_requirements(self):
        """Regression: age/gender/degree were routed to EDUCATION and dropped,
        which left 'شرایط احراز' with an empty body and DISCARDED everything
        after it -- the requirements fill rate fell when these were detected."""
        text = "شرایط احراز: سن: 20 تا 35 سال تحصیلات: حداقل دیپلم سابقه کار: 2 سال"
        result = extract_description_sections(text)
        assert result.requirements is not None
        assert "20 تا 35 سال" in result.requirements
        assert "حداقل دیپلم" in result.requirements
        assert "2 سال" in result.requirements

    def test_bullets_become_separate_lines(self):
        text = "Requirements: Python • Kubernetes • Postgres • Terraform"
        result = extract_description_sections(text)
        assert result.requirements is not None
        lines = result.requirements.splitlines()
        assert lines == ["- Python", "- Kubernetes", "- Postgres", "- Terraform"]

    def test_nice_to_have_is_preferred_not_required(self):
        text = "Requirements: Python. Nice to have: Kubernetes and Ray."
        result = extract_description_sections(text)
        assert result.preferred_skills_text is not None
        assert "Kubernetes" in result.preferred_skills_text
        assert result.requirements is not None
        assert "Kubernetes" not in result.requirements

    def test_items_are_deduplicated(self):
        text = "Requirements: Python • Python • Python • Docker"
        result = extract_description_sections(text)
        assert result.requirements is not None
        assert result.requirements.count("Python") == 1


class TestSkillExtraction:
    def test_persian_skill_phrase_without_a_heading(self):
        """Most jobvision rows have no heading at all. An explicit 'proficient in
        X' statement is a requirement wherever it appears."""
        text = "ما به دنبال یک برنامه‌نویس مسلط به Excel و آشنایی با SQL هستیم."
        result = extract_description_sections(text)
        assert result.required_skills_text is not None
        assert "Excel" in result.required_skills_text
        assert "SQL" in result.required_skills_text

    def test_english_skill_phrase(self):
        text = "We are looking for someone with proficiency in Kubernetes."
        result = extract_description_sections(text)
        assert result.required_skills_text is not None
        assert "Kubernetes" in result.required_skills_text

    def test_no_whole_description_scan_when_a_requirements_section_exists(self):
        """Tools mentioned in responsibilities must not become required skills.
        The requirements section names Docker via a skill phrase, so the column
        is populated -- and Terraform, which appears only under the
        responsibilities section, must not appear in it."""
        text = (
            "Responsibilities: You will use Terraform to provision "
            "infrastructure. Requirements: experience with Docker and Python."
        )
        result = extract_description_sections(text)
        assert result.required_skills_text is not None
        assert "Docker" in result.required_skills_text
        assert "Terraform" not in result.required_skills_text

    def test_skill_capture_is_trimmed(self):
        text = "آشنایی با اصول SOLID و Design Pattern، آشنایی با React"
        result = extract_description_sections(text)
        assert result.required_skills_text is not None
        assert "SOLID" in result.required_skills_text
        assert "React" in result.required_skills_text


class TestLanguageRequirements:
    def test_language_section_is_captured(self):
        text = "Languages: English (fluent) and Persian."
        result = extract_description_sections(text)
        assert result.language_requirements_text is not None
        assert "English" in result.language_requirements_text
        assert "Persian" in result.language_requirements_text

    def test_a_mention_without_a_language_cue_is_not_a_requirement(self):
        """'English teacher' is a job title, not a language requirement."""
        text = "Requirements: We are hiring an English teacher for our academy."
        result = extract_description_sections(text)
        assert result.language_requirements_text is None


class TestBoilerplateBoundaries:
    def test_about_company_ends_the_requirements_section(self):
        """Regression: with no terminator, a requirements section ran on into
        the company blurb, and one greenhouse row stored 'BS (or higher) in
        Computer Science ... About Databricks Databricks is the Data and AI
        company. More than 20,000 organizations worldwide ... rely on the
        Databricks Data + AI Platform' as a single requirement item."""
        text = (
            "Requirements BS (or higher) in Computer Science, or a related field "
            "7+ years of production level experience. About Databricks Databricks "
            "is the Data and AI company. More than 20,000 organizations rely on it."
        )
        result = extract_description_sections(text)
        assert result.requirements is not None
        assert "Computer Science" in result.requirements
        assert "Databricks" not in result.requirements
        assert "20,000 organizations" not in result.requirements

    def test_equal_opportunity_and_privacy_are_not_content(self):
        text = (
            "Requirements Python and Docker. Equal Opportunity at Datadog "
            "Datadog is an equal opportunity employer. Privacy Policy we collect "
            "categories of personal information."
        )
        result = extract_description_sections(text)
        assert result.requirements is not None
        assert "personal information" not in result.requirements


class TestSkillQuality:
    def test_quantifier_is_not_a_skill(self):
        """Regression: 'experience in one of: Python, Java, Scala' matched the
        skill pattern and stored 'one of' as a skill."""
        text = (
            "Requirements 7+ years of production level experience in one of: "
            "Python, Java, Scala, C++ or similar language."
        )
        result = extract_description_sections(text)
        assert result.required_skills_text is None or "one of" not in result.required_skills_text

    def test_skills_under_a_duties_heading_are_still_requirements(self):
        """Iranian boards file 'آشنایی با MVC' under the DUTIES heading. One real
        jobvision posting put all eleven of its skill requirements there and
        left required_skills NULL."""
        text = (
            "شرح وظایف: • آشنایی با معماری‌های MVC و React • تسلط به Bootstrap "
            "شرایط احراز: • حداقل ۳ سال سابقه"
        )
        result = extract_description_sections(text)
        assert result.required_skills_text is not None
        assert "Bootstrap" in result.required_skills_text

    def test_prose_tools_are_not_skills(self):
        """A tool merely used in the work is not a stated requirement."""
        text = "Responsibilities: • از Kubernetes استفاده می‌کنید برای استقرار"
        result = extract_description_sections(text)
        assert result.required_skills_text is None


class TestSafety:
    def test_empty_description_returns_empty_result(self):
        result = extract_description_sections("")
        assert not result.has_any
        assert result.section_count == 0

    def test_description_with_no_headings_returns_empty_result(self):
        result = extract_description_sections("Just a wall of prose with no sections.")
        assert not result.has_any

    def test_extracted_text_keeps_original_diacritics(self):
        """Folding is only used to LOCATE headings. Content must come back with
        its original characters intact."""
        text = "Yêu cầu: Kinh nghiệm tối thiểu 2 năm trong lĩnh vực marketing."
        result = extract_description_sections(text)
        assert result.requirements is not None
        assert "kinh nghiệm" in result.requirements.lower()
        assert "nghiệm" in result.requirements

    def test_long_prose_is_not_duplicated_into_a_column(self):
        """A heading with no bullets followed by a wall of text must not copy the
        whole description into a column."""
        text = "Requirements: " + ("A detailed sentence about the role. " * 200)
        result = extract_description_sections(text)
        if result.requirements:
            assert len(result.requirements) < 20_000
