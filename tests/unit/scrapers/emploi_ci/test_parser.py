"""Unit tests for Emploi.ci (Côte d'Ivoire) vacancy parser."""

from __future__ import annotations

import pytest

from job_market_intel.scrapers.emploi_ci.models import RawEmploiCiJob
from job_market_intel.scrapers.emploi_ci.parser import EmploiCiParser

SAMPLE_JSON_LD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Chef de Projet Informatique Junior - Abidjan | Emploi.ci</title>
    <script type="application/ld+json">
    {
        "@context": "http://schema.org/",
        "@type": "JobPosting",
        "datePosted": "2026-11-19T01:00:02+00:00",
        "title": "Chef de Projet Informatique Junior - Abidjan",
        "description": "<p>Nous recrutons un Chef de Projet IT Junior pour notre client, une Fintech.</p>",
        "identifier": {
            "@type": "PropertyValue",
            "name": "AFRICAWORK",
            "value": "2123897"
        },
        "validThrough": "2026-12-29T00:00:00+00:00",
        "employmentType": "CDI",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "AFRICAWORK"
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Abidjan",
                "addressRegion": "Abidjan",
                "addressCountry": "Côte d´ivoire"
            }
        }
    }
    </script>
</head>
<body>
    <h1>Chef de Projet Informatique Junior - Abidjan</h1>
    <div class="job-description">
        <p>Nous recrutons un Chef de Projet IT Junior pour notre client, une Fintech.</p>
        <p>Compétences requises: Python, SQL, Gestion de projet, Excel.</p>
    </div>
</body>
</html>
"""

SAMPLE_REPAIRED_JSON_LD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Infirmier Formateur Clinique H/F | Emploi.ci</title>
    <script type="application/ld+json">
    {
        "@context": "http://schema.org/",
        "@type": "JobPosting",
        "datePosted": "2026-11-19T01:00:02+00:00",
        "title": "Infirmier Formateur Clinique H/F - Expatriation - Djibouti",
        "description": "<p>Un hôpital privé à Djibouti recherche un(e) <strong data-end="193" data-start="149">Infirmier(ère)</strong> Formateur.</p>",
        "identifier": {
            "@type": "PropertyValue",
            "name": "AFRICAWORK",
            "value": "2117132"
        },
        "validThrough": "2026-12-29T00:00:00+00:00",
        "employmentType": "CDI",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "AFRICAWORK"
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Abidjan",
                "addressRegion": "Abidjan",
                "addressCountry": "Côte d´ivoire"
            }
        }
    }
    </script>
</head>
<body>
    <h1>Infirmier Formateur Clinique H/F - Expatriation - Djibouti</h1>
    <div class="job-description">
        <p>Un hôpital privé à Djibouti recherche un(e) Infirmier(ère) Formateur.</p>
    </div>
</body>
</html>
"""

SAMPLE_FALLBACK_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Stagiaire Assistant RH | Emploi.ci</title>
</head>
<body>
    <h1>Stagiaire Assistant RH - Abidjan</h1>
    <div class="company-name">IVOIRE RH CONSEIL</div>
    <div class="job-description">
        <p>Nous cherchons un stagiaire motivé pour assister l'équipe RH.</p>
        <p>Missions: recrutement, gestion des dossiers, administration.</p>
    </div>
    <div class="date-posted">Publiée le 19.11.2026</div>
</body>
</html>
"""


def test_emploi_ci_parser_clean_json_ld():
    parser = EmploiCiParser()
    raw = RawEmploiCiJob(
        url="https://www.emploi.ci/offre-emploi-cote-ivoire/chef-projet-2123897",
        job_id="2123897",
        html_content=SAMPLE_JSON_LD_HTML,
    )
    cleaned = parser.parse_job(raw)

    assert cleaned.source_job_id == "2123897"
    assert cleaned.job_title == "Chef de Projet Informatique Junior - Abidjan"
    assert cleaned.company_name == "AFRICAWORK"
    assert "Abidjan" in cleaned.location_cleaned
    assert str(cleaned.posting_date).startswith("2026-11-19")
    assert cleaned.employment_type_code == "full_time"
    assert "Python" in cleaned.skills or "Sql" in cleaned.skills
    assert cleaned.currency_iso_code == "XOF"


def test_emploi_ci_parser_repaired_json_ld():
    parser = EmploiCiParser()
    raw = RawEmploiCiJob(
        url="https://www.emploi.ci/offre-emploi-cote-ivoire/infirmier-2117132",
        job_id="2117132",
        html_content=SAMPLE_REPAIRED_JSON_LD_HTML,
    )
    cleaned = parser.parse_job(raw)

    assert cleaned.source_job_id == "2117132"
    assert "Infirmier Formateur" in cleaned.job_title
    assert cleaned.company_name == "AFRICAWORK"
    assert str(cleaned.posting_date).startswith("2026-11-19")
    assert cleaned.employment_type_code == "full_time"


def test_emploi_ci_parser_fallback_html():
    parser = EmploiCiParser()
    raw = RawEmploiCiJob(
        url="https://www.emploi.ci/offre-emploi-cote-ivoire/stagiaire-rh-99999",
        job_id="99999",
        html_content=SAMPLE_FALLBACK_HTML,
    )
    cleaned = parser.parse_job(raw)

    assert cleaned.source_job_id == "99999"
    assert cleaned.job_title == "Stagiaire Assistant RH - Abidjan"
    assert cleaned.company_name == "IVOIRE RH CONSEIL"
    assert str(cleaned.posting_date).startswith("2026-11-19")
