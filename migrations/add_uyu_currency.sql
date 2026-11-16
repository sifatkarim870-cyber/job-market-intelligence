-- Migration: Add UYU (Uruguayan Peso) to ref.currencies for gallito_uy scraper
-- Applied manually on 2026-11-16 prior to scraper deployment.

INSERT INTO ref.currencies (iso_code, currency_name, symbol)
VALUES ('UYU', 'Uruguayan Peso', '$')
ON CONFLICT (iso_code) DO NOTHING;

UPDATE ref.countries
SET default_currency_id = (SELECT currency_id FROM ref.currencies WHERE iso_code = 'UYU')
WHERE iso_code_2 = 'UY' AND default_currency_id IS NULL;
