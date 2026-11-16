"""Unit tests for the Gallito (Uruguay) parser."""

from __future__ import annotations

from job_market_intel.scrapers.gallito_uy.models import RawGallitoJob
from job_market_intel.scrapers.gallito_uy.parser import GallitoParser


def test_gallito_parser_with_salary() -> None:
    html_content = """
    <html>
      <head>
        <title>AGENTE INMOBILIARIO REMAX - Gallito.com.uy</title>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "AGENTE INMOBILIARIO REMAX",
          "description": "BUSCAMOS PERSONAS APASIONADAS EN LO QUE HACEN.",
          "datePosted": "2026-11-15",
          "validThrough": "2027-01-14",
          "employmentType": "CONTRACTOR",
          "hiringOrganization": {
            "@type": "Organization",
            "name": "REMAX Rambla"
          },
          "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "UYU",
            "value": {
              "@type": "QuantitativeValue",
              "unitText": "MONTH",
              "minValue": 45000,
              "maxValue": 60000
            }
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "@type": "PostalAddress",
              "addressLocality": "PUNTA GORDA, MONTEVIDEO",
              "addressCountry": "UY"
            }
          }
        }
        </script>
      </head>
      <body>
        <div class="cuadro-aviso">
          <div class="cuadro-aviso-title">Responsabilidades</div>
          <div class="cuadro-aviso-text">Desarrollo de cartera de clientes y captacion de propiedades inmobiliarias en Montevideo.</div>
        </div>
        <div class="cuadro-aviso">
          <div class="cuadro-aviso-title">Requisitos</div>
          <div class="cuadro-aviso-text">Experiencia previa en ventas comerciales y manejo de Excel. Disponibilidad horaria.</div>
        </div>
      </body>
    </html>
    """
    raw = RawGallitoJob(
        url="https://trabajo.gallito.com.uy/anuncio/agente-inmobiliario-remax-nhbrh",
        job_id="nhbrh",
        html_content=html_content,
    )
    parser = GallitoParser()
    cleaned = parser.parse_job(raw)

    assert cleaned is not None
    assert cleaned.source_job_id == "nhbrh"
    assert cleaned.job_title == "AGENTE INMOBILIARIO REMAX"
    assert cleaned.company_name == "REMAX Rambla"
    assert "PUNTA GORDA, MONTEVIDEO" in cleaned.location_cleaned
    assert "Uruguay" in cleaned.location_cleaned
    assert cleaned.employment_type_code == "contract"
    assert cleaned.salary_disclosed is True
    assert cleaned.salary_min == 45000.0
    assert cleaned.salary_max == 60000.0
    assert cleaned.currency_iso_code == "UYU"
    assert cleaned.pay_period == "monthly"
    assert str(cleaned.posting_date).startswith("2026-11-15")
    assert cleaned.closing_date is not None
    assert "Excel" in cleaned.skills or "Sales" in cleaned.skills
    assert cleaned.word_count > 10


def test_gallito_parser_fallback_html() -> None:
    html_content = """
    <html>
      <head>
        <title>Desarrollador Python Backend - Gallito.com.uy</title>
      </head>
      <body>
        <div class="contenedor-ficha-aviso">
          <h2>Desarrollador Python Backend</h2>
          <span class="ubicacion">Montevideo</span>
          <div class="cuadro-aviso">
            <div class="cuadro-aviso-title">Funciones</div>
            <div class="cuadro-aviso-text">Desarrollo de microservicios con Python, FastAPI y PostgreSQL para fintech uruguaya.</div>
          </div>
        </div>
      </body>
    </html>
    """
    raw = RawGallitoJob(
        url="https://trabajo.gallito.com.uy/anuncio/desarrollador-python-backend-py99x",
        job_id="py99x",
        html_content=html_content,
    )
    parser = GallitoParser()
    cleaned = parser.parse_job(raw)

    assert cleaned is not None
    assert cleaned.job_title == "Desarrollador Python Backend"
    assert "Uruguay" in cleaned.location_cleaned
    assert "Python" in cleaned.skills
    assert cleaned.salary_disclosed is False
