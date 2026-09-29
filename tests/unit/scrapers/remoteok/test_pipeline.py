"""Unit tests for RemoteOKPipeline (Step 11)."""

from __future__ import annotations

from unittest.mock import MagicMock

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.scrapers.remoteok.models import RawRemoteOKJob
from job_market_intel.scrapers.remoteok.pipeline import RemoteOKPipeline


class TestRemoteOKPipelineUnit:
    def test_pipeline_dry_run_executes_steps(self) -> None:
        mock_client = MagicMock()
        mock_parser = MagicMock()
        mock_validator = MagicMock()
        mock_cleaner = MagicMock()

        raw_job = {"id": "1", "position": "Dev", "company": "Acme", "url": "https://x.test/1"}
        mock_client.fetch_raw_jobs.return_value = [raw_job]

        parsed_job = RawRemoteOKJob(
            source_job_id="1", job_title="Dev", company_name="Acme", original_url="https://x.test/1"
        )
        mock_parser.parse_jobs.return_value = [parsed_job]

        mock_report = MagicMock()
        mock_report.passed = True
        mock_report.issues = []
        mock_validator.validate.return_value = mock_report

        cleaned_job = CleanedJob(
            source_job_id="1",
            job_title="Dev",
            company_name="Acme",
            company_logo_url=None,
            skills=["python"],
            location_cleaned="Remote",
            salary_min=100000,
            salary_max=150000,
            salary_disclosed=True,
            description_clean="Clean desc",
            word_count=2,
            apply_url=None,
            original_url="https://x.test/1",
            posting_date=None,
            data_quality_score=1.0,
            raw_payload=raw_job,
            currency_iso_code="USD",
            pay_period="yearly",
        )
        mock_cleaner.clean_jobs.return_value = [cleaned_job]

        pipeline = RemoteOKPipeline(
            client=mock_client,
            parser=mock_parser,
            validator=mock_validator,
            cleaner=mock_cleaner,
        )

        res = pipeline.run(store_db=False)

        assert res.raw_count == 1
        assert res.parsed_count == 1
        assert res.cleaned_count == 1
        assert res.validation_passed is True
        assert res.inserted_count == 0

        mock_client.fetch_raw_jobs.assert_called_once()
        mock_parser.parse_jobs.assert_called_once_with([raw_job])
        mock_validator.validate.assert_called_once()
        mock_cleaner.clean_jobs.assert_called_once_with([parsed_job])

    def test_pipeline_with_mocked_db_persistence(self) -> None:
        mock_client = MagicMock()
        mock_parser = MagicMock()
        mock_validator = MagicMock()
        mock_cleaner = MagicMock()
        mock_repo = MagicMock()
        mock_session = MagicMock()

        mock_client.fetch_raw_jobs.return_value = []
        mock_parser.parse_jobs.return_value = []
        mock_validator.validate.return_value = MagicMock(passed=True, issues=[])
        mock_cleaner.clean_jobs.return_value = []

        mock_repo.get_source_id_by_code.return_value = 1
        mock_repo.create_scraping_session.return_value = 42
        mock_repo.save_cleaned_jobs.return_value = {
            "inserted": 2,
            "updated": 1,
            "unchanged": 5,
            "failed": 0,
        }

        pipeline = RemoteOKPipeline(
            client=mock_client,
            parser=mock_parser,
            validator=mock_validator,
            cleaner=mock_cleaner,
            repository=mock_repo,
        )

        res = pipeline.run(store_db=True, session_override=mock_session)

        assert res.session_id == 42
        assert res.inserted_count == 2
        assert res.updated_count == 1
        assert res.unchanged_count == 5
        assert res.failed_count == 0

        mock_repo.get_source_id_by_code.assert_called_once_with(mock_session, "remoteok")
        mock_repo.create_scraping_session.assert_called_once()
        mock_repo.finish_scraping_session.assert_called_once()
