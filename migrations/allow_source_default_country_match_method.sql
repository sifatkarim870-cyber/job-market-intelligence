-- Allow match_method = 'source_default_country'
--
-- normalization/geographic_resolution.py emits six values; this constraint
-- permitted only five. The missing one is 'source_default_country', which the
-- resolver produces whenever a raw location cannot be matched and it falls back
-- to the board's home country (SOURCE_HOME_COUNTRY in that module -- jobvision,
-- jobinja, irantalent, reed, 51job, myjob, jobam).
--
-- The effect in CI was a CheckViolation on every such row, so those jobs were
-- silently dropped: 2 rows in one reed run, 1 in a job51 run. The constraint was
-- never exercised locally because these sources are scraped on the laptop into
-- a database that already had the row.
--
-- DROP + ADD rather than a bare ALTER: Postgres cannot add a value to an
-- existing CHECK constraint, it must be replaced. IF EXISTS/IF NOT EXISTS keep
-- this re-runnable on databases that never had the constraint.

ALTER TABLE core.location_aliases
    DROP CONSTRAINT IF EXISTS ck_location_aliases_match_method;

ALTER TABLE core.location_aliases
    ADD CONSTRAINT ck_location_aliases_match_method CHECK (match_method IN
        ('city_exact', 'region_exact', 'country_exact', 'global_assertion',
         'fallback_unmatched', 'source_default_country'));

COMMENT ON CONSTRAINT ck_location_aliases_match_method ON core.location_aliases IS
    'Audit trail of how a raw location string was resolved. source_default_country means the raw text did not match and the resolver fell back to the board''s home country -- a much weaker claim than the *_exact values, and kept distinct from fallback_unmatched (no location at all) on purpose.';