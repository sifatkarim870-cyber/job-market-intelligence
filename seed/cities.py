"""
Seeds ref.cities — an initial ~90-city dataset spanning every seeded
country's major tech/business hubs (sufficient for the first scraper's
location-resolution needs). `region_id` is resolved by (country_iso, region_name)
where applicable; left NULL for city-only countries like Singapore.
"""
from __future__ import annotations

from sqlalchemy import Connection, text

from .base import SeedResult, get_id_map, upsert_many

# (city_name, country_iso2, region_name_or_None, lat, lon, timezone)
_CITIES: list[tuple[str, str, str | None, float, float, str]] = [
    ("New York", "US", "New York", 40.7128, -74.0060, "America/New_York"),
    ("San Francisco", "US", "California", 37.7749, -122.4194, "America/Los_Angeles"),
    ("Los Angeles", "US", "California", 34.0522, -118.2437, "America/Los_Angeles"),
    ("Seattle", "US", "Washington", 47.6062, -122.3321, "America/Los_Angeles"),
    ("Austin", "US", "Texas", 30.2672, -97.7431, "America/Chicago"),
    ("Chicago", "US", "Illinois", 41.8781, -87.6298, "America/Chicago"),
    ("Boston", "US", "Massachusetts", 42.3601, -71.0589, "America/New_York"),
    ("Denver", "US", "Colorado", 39.7392, -104.9903, "America/Denver"),
    ("Miami", "US", "Florida", 25.7617, -80.1918, "America/New_York"),
    ("Washington", "US", "District of Columbia", 38.9072, -77.0369, "America/New_York"),
    ("Toronto", "CA", "Ontario", 43.6532, -79.3832, "America/Toronto"),
    ("Vancouver", "CA", "British Columbia", 49.2827, -123.1207, "America/Vancouver"),
    ("Montreal", "CA", "Quebec", 45.5019, -73.5674, "America/Toronto"),
    ("Mexico City", "MX", None, 19.4326, -99.1332, "America/Mexico_City"),
    ("London", "GB", "England", 51.5074, -0.1278, "Europe/London"),
    ("Manchester", "GB", "England", 53.4808, -2.2426, "Europe/London"),
    ("Edinburgh", "GB", "Scotland", 55.9533, -3.1883, "Europe/London"),
    ("Dublin", "IE", None, 53.3498, -6.2603, "Europe/Dublin"),
    ("Berlin", "DE", None, 52.5200, 13.4050, "Europe/Berlin"),
    ("Munich", "DE", None, 48.1351, 11.5820, "Europe/Berlin"),
    ("Paris", "FR", None, 48.8566, 2.3522, "Europe/Paris"),
    ("Madrid", "ES", None, 40.4168, -3.7038, "Europe/Madrid"),
    ("Barcelona", "ES", None, 41.3851, 2.1734, "Europe/Madrid"),
    ("Lisbon", "PT", None, 38.7223, -9.1393, "Europe/Lisbon"),
    ("Rome", "IT", None, 41.9028, 12.4964, "Europe/Rome"),
    ("Milan", "IT", None, 45.4642, 9.1900, "Europe/Rome"),
    ("Amsterdam", "NL", None, 52.3676, 4.9041, "Europe/Amsterdam"),
    ("Brussels", "BE", None, 50.8503, 4.3517, "Europe/Brussels"),
    ("Zurich", "CH", None, 47.3769, 8.5417, "Europe/Zurich"),
    ("Vienna", "AT", None, 48.2082, 16.3738, "Europe/Vienna"),
    ("Stockholm", "SE", None, 59.3293, 18.0686, "Europe/Stockholm"),
    ("Oslo", "NO", None, 59.9139, 10.7522, "Europe/Oslo"),
    ("Copenhagen", "DK", None, 55.6761, 12.5683, "Europe/Copenhagen"),
    ("Helsinki", "FI", None, 60.1699, 24.9384, "Europe/Helsinki"),
    ("Warsaw", "PL", None, 52.2297, 21.0122, "Europe/Warsaw"),
    ("Prague", "CZ", None, 50.0755, 14.4378, "Europe/Prague"),
    ("Budapest", "HU", None, 47.4979, 19.0402, "Europe/Budapest"),
    ("Bucharest", "RO", None, 44.4268, 26.1025, "Europe/Bucharest"),
    ("Athens", "GR", None, 37.9838, 23.7275, "Europe/Athens"),
    ("Kyiv", "UA", None, 50.4501, 30.5234, "Europe/Kyiv"),
    ("Istanbul", "TR", None, 41.0082, 28.9784, "Europe/Istanbul"),
    ("Mumbai", "IN", "Maharashtra", 19.0760, 72.8777, "Asia/Kolkata"),
    ("Bangalore", "IN", "Karnataka", 12.9716, 77.5946, "Asia/Kolkata"),
    ("Delhi", "IN", "Delhi", 28.7041, 77.1025, "Asia/Kolkata"),
    ("Hyderabad", "IN", "Telangana", 17.3850, 78.4867, "Asia/Kolkata"),
    ("Pune", "IN", "Maharashtra", 18.5204, 73.8567, "Asia/Kolkata"),
    ("Shanghai", "CN", None, 31.2304, 121.4737, "Asia/Shanghai"),
    ("Beijing", "CN", None, 39.9042, 116.4074, "Asia/Shanghai"),
    ("Shenzhen", "CN", None, 22.5431, 114.0579, "Asia/Shanghai"),
    ("Tokyo", "JP", None, 35.6762, 139.6503, "Asia/Tokyo"),
    ("Osaka", "JP", None, 34.6937, 135.5023, "Asia/Tokyo"),
    ("Seoul", "KR", None, 37.5665, 126.9780, "Asia/Seoul"),
    ("Singapore", "SG", None, 1.3521, 103.8198, "Asia/Singapore"),
    ("Hong Kong", "HK", None, 22.3193, 114.1694, "Asia/Hong_Kong"),
    ("Manila", "PH", None, 14.5995, 120.9842, "Asia/Manila"),
    ("Jakarta", "ID", None, -6.2088, 106.8456, "Asia/Jakarta"),
    ("Kuala Lumpur", "MY", None, 3.1390, 101.6869, "Asia/Kuala_Lumpur"),
    ("Bangkok", "TH", None, 13.7563, 100.5018, "Asia/Bangkok"),
    ("Ho Chi Minh City", "VN", None, 10.8231, 106.6297, "Asia/Ho_Chi_Minh"),
    ("Karachi", "PK", None, 24.8607, 67.0011, "Asia/Karachi"),
    ("Dhaka", "BD", None, 23.8103, 90.4125, "Asia/Dhaka"),
    ("Tel Aviv", "IL", None, 32.0853, 34.7818, "Asia/Jerusalem"),
    ("Dubai", "AE", None, 25.2048, 55.2708, "Asia/Dubai"),
    ("Riyadh", "SA", None, 24.7136, 46.6753, "Asia/Riyadh"),
    ("Sydney", "AU", "New South Wales", -33.8688, 151.2093, "Australia/Sydney"),
    ("Melbourne", "AU", "Victoria", -37.8136, 144.9631, "Australia/Melbourne"),
    ("Brisbane", "AU", "Queensland", -27.4698, 153.0251, "Australia/Brisbane"),
    ("Auckland", "NZ", None, -36.8485, 174.7633, "Pacific/Auckland"),
    ("Cape Town", "ZA", None, -33.9249, 18.4241, "Africa/Johannesburg"),
    ("Johannesburg", "ZA", None, -26.2041, 28.0473, "Africa/Johannesburg"),
    ("Lagos", "NG", None, 6.5244, 3.3792, "Africa/Lagos"),
    ("Nairobi", "KE", None, -1.2921, 36.8219, "Africa/Nairobi"),
    ("Cairo", "EG", None, 30.0444, 31.2357, "Africa/Cairo"),
    ("Accra", "GH", None, 5.6037, -0.1870, "Africa/Accra"),
    ("Sao Paulo", "BR", None, -23.5505, -46.6333, "America/Sao_Paulo"),
    ("Rio de Janeiro", "BR", None, -22.9068, -43.1729, "America/Sao_Paulo"),
    ("Buenos Aires", "AR", None, -34.6037, -58.3816, "America/Argentina/Buenos_Aires"),
    ("Santiago", "CL", None, -33.4489, -70.6693, "America/Santiago"),
    ("Bogota", "CO", None, 4.7110, -74.0721, "America/Bogota"),
    ("Lima", "PE", None, -12.0464, -77.0428, "America/Lima"),
    ("Montevideo", "UY", None, -34.9011, -56.1645, "America/Montevideo"),
    ("Moscow", "RU", None, 55.7558, 37.6173, "Europe/Moscow"),
]


def seed_cities(conn: Connection) -> SeedResult:
    country_ids = get_id_map(
        conn, schema="ref", table_name="countries", key_col="iso_code_2", id_col="country_id"
    )
    region_rows = conn.execute(
        __import__("sqlalchemy").text(
            "SELECT country_id, region_name, region_id FROM ref.regions"
        )
    ).all()
    region_ids = {(r.country_id, r.region_name): r.region_id for r in region_rows}

    rows = []
    for name, iso2, region_name, lat, lon, tz in _CITIES:
        country_id = country_ids[iso2]
        region_id = region_ids.get((country_id, region_name)) if region_name else None
        rows.append(
            {
                "city_name": name,
                "country_id": country_id,
                "region_id": region_id,
                "latitude": lat,
                "longitude": lon,
                "timezone": tz,
                "population": None,
            }
        )

    result = SeedResult(table="ref.cities")
    stmt = text("""
        INSERT INTO ref.cities
            (city_name, country_id, region_id, latitude, longitude, timezone, population)
        VALUES
            (:city_name, :country_id, :region_id, :latitude, :longitude, :timezone, :population)
        ON CONFLICT (country_id, COALESCE(region_id, 0), city_name)
        DO UPDATE SET
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            timezone = EXCLUDED.timezone,
            population = EXCLUDED.population
        RETURNING (xmax = 0) AS inserted
    """)
    for row in rows:
        r = conn.execute(stmt, row).first()
        if r.inserted:
            result.inserted += 1
        else:
            result.updated += 1
    return result