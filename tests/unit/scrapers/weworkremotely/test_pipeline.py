"""Unit tests for WWRPipeline.

Exact structural mirror of ``scrapers/remoteok/test_pipeline.py`` — same
mocked-collaborator approach, same two scenarios (dry-run and mocked-DB
persistence). Only the concrete data shapes differ (WWR's raw dict shape,
no salary fields).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from job_market_intel.cleaning.common import CleanedJob
from job_market_intel.scrapers.weworkremotely.models import RawWWRJob
from job_market_intel.scrapers.weworkremotely.pipeline import WWRPipeline


class TestWWRPipelineUnit:
    def test_pipeline_dry_run_executes_steps(self) -> None:
        mock_client = MagicMock()
        mock_parser = MagicMock()
        mock_validator = MagicMock()
        mock_cleaner = MagicMock()

        raw_job = {
            "title": "Acme: Dev",
            "guid": "https://weworkremotely.com/remote-jobs/acme-dev",
            "link": "https://weworkremotely.com/remote-jobs/acme-dev",
        }
        mock_client.fetch_raw_jobs.return_value = [raw_job]

        parsed_job = RawWWRJob(
            source_job_id="acme-dev",
            job_title="Dev",
            company_name="Acme",
            original_url="https://weworkremotely.com/remote-jobs/acme-dev",
        )
        mock_parser.parse_jobs.return_value = [parsed_job]

        mock_report = MagicMock()
        mock_report.passed = True
        mock_report.issues = []
        mock_validator.validate.return_value = mock_report

        cleaned_job = CleanedJob(
            source_job_id="acme-dev",
            job_title="Dev",
            company_name="Acme",
            company_logo_url=None,
            skills=["python"],
            location_cleaned="Anywhere in the World",
            salary_min=None,
            salary_max=None,
            salary_disclosed=False,
            description_clean="Clean desc",
            word_count=2,
            apply_url="https://weworkremotely.com/remote-jobs/acme-dev",
            original_url="https://weworkremotely.com/remote-jobs/acme-dev",
            posting_date=None,
            closing_date=None,
            data_quality_score=0.5,
            raw_payload=raw_job,
        )
        mock_cleaner.clean_jobs.return_value = [cleaned_job]

        pipeline = WWRPipeline(
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

        mock_repo.get_source_id_by_code.return_value = 2
        mock_repo.create_scraping_session.return_value = 99
        mock_repo.save_cleaned_jobs.return_value = {
            "inserted": 3,
            "updated": 0,
            "unchanged": 4,
            "failed": 0,
        }

        pipeline = WWRPipeline(
            client=mock_client,
            parser=mock_parser,
            validator=mock_validator,
            cleaner=mock_cleaner,
            repository=mock_repo,
        )

        res = pipeline.run(store_db=True, session_override=mock_session)

        assert res.session_id == 99
        assert res.inserted_count == 3
        assert res.updated_count == 0
        assert res.unchanged_count == 4
        assert res.failed_count == 0

        mock_repo.get_source_id_by_code.assert_called_once_with(mock_session, "weworkremotely")
        mock_repo.create_scraping_session.assert_called_once()
        mock_repo.finish_scraping_session.assert_called_once()
