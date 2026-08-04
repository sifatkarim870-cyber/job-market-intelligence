"""Unit tests for JobRepository and content hashing functions."""

from __future__ import annotations

from job_market_intel.db.job_repository import compute_job_content_hash


class TestJobContentHashing:
    def test_hash_is_deterministic(self) -> None:
        h1 = compute_job_content_hash(
            job_title="Software Engineer",
            company_name="Acme Corp",
            description_clean="Python developer needed",
            location_cleaned="Remote",
            salary_min=100000,
            salary_max=150000,
        )
        h2 = compute_job_content_hash(
            job_title="Software Engineer",
            company_name="Acme Corp",
            description_clean="Python developer needed",
            location_cleaned="Remote",
            salary_min=100000,
            salary_max=150000,
        )
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest length

    def test_hash_case_and_whitespace_insensitivity_for_company(self) -> None:
        h1 = compute_job_content_hash("Engineer", "ACME CORP ", "desc", "remote", 100, 200)
        h2 = compute_job_content_hash("Engineer", "acme corp", "desc", "remote", 100, 200)
        assert h1 == h2

    def test_hash_differs_when_salary_changes(self) -> None:
        h1 = compute_job_content_hash("Engineer", "Acme", "desc", "remote", 100000, 150000)
        h2 = compute_job_content_hash("Engineer", "Acme", "desc", "remote", 120000, 150000)
        assert h1 != h2

    def test_hash_differs_when_title_changes(self) -> None:
        h1 = compute_job_content_hash("Senior Engineer", "Acme", "desc", "remote", 100000, 150000)
        h2 = compute_job_content_hash("Junior Engineer", "Acme", "desc", "remote", 100000, 150000)
        assert h1 != h2
