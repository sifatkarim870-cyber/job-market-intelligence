"""
Seeds ref.cities — an initial ~90-city dataset spanning every seeded
country's major tech/business hubs (sufficient for the first scraper's
location-resolution needs). `region_id` is resolved by (country_iso, region_name)
where applicable; left NULL for city-only countries like Singapore.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from .base import SeedResult, get_id_map

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
    # Region stays None here deliberately. The conflict key is
    # (country_id, COALESCE(region_id, 0), city_name), so adding a region to an
    # existing row makes it a *different* key and leaves the old row behind as an
    # orphan -- which test_seed.py's idempotency check catches. Kuala Lumpur is a
    # federal territory and matches on its city name alone ("city_exact"), so the
    # region link buys nothing and costs a duplicate.
    ("Kuala Lumpur", "MY", None, 3.1390, 101.6869, "Asia/Kuala_Lumpur"),
    # Malaysia's main job markets, added with the hiredly source: 29 of its
    # first 30 postings read "Petaling Jaya, Selangor", and ref.cities held
    # exactly one Malaysian city, so all of them resolved to country-only.
    ("Petaling Jaya", "MY", "Selangor", 3.1053, 101.6069, "Asia/Kuala_Lumpur"),
    ("Shah Alam", "MY", "Selangor", 3.0733, 101.5183, "Asia/Kuala_Lumpur"),
    ("Subang Jaya", "MY", "Selangor", 3.0449, 101.5854, "Asia/Kuala_Lumpur"),
    ("Klang", "MY", "Selangor", 3.0688, 101.5183, "Asia/Kuala_Lumpur"),
    ("Cyberjaya", "MY", "Selangor", 2.9213, 101.6558, "Asia/Kuala_Lumpur"),
    ("Putrajaya", "MY", "Putrajaya", 3.0216, 101.6564, "Asia/Kuala_Lumpur"),
    ("Johor Bahru", "MY", "Johor", 1.4927, 103.7414, "Asia/Kuala_Lumpur"),
    ("Skudai", "MY", "Johor", 1.5347, 103.5569, "Asia/Kuala_Lumpur"),
    ("Batu Pahat", "MY", "Johor", 1.8548, 103.4704, "Asia/Kuala_Lumpur"),
    ("George Town", "MY", "Pulau Pinang", 5.4141, 100.3288, "Asia/Kuala_Lumpur"),
    ("Penang", "MY", "Pulau Pinang", 5.4164, 100.3327, "Asia/Kuala_Lumpur"),
    ("Butterworth", "MY", "Pulau Pinang", 5.3992, 100.3098, "Asia/Kuala_Lumpur"),
    ("Bukit Mertajam", "MY", "Pulau Pinang", 5.0125, 101.2848, "Asia/Kuala_Lumpur"),
    ("Ipoh", "MY", "Perak", 4.5975, 101.0901, "Asia/Kuala_Lumpur"),
    ("Kota Kinabalu", "MY", "Sabah", 5.9804, 116.0735, "Asia/Kuching"),
    ("Sandakan", "MY", "Sabah", 5.8388, 118.1159, "Asia/Kuching"),
    ("Tawau", "MY", "Sabah", 4.2448, 117.8912, "Asia/Kuching"),
    ("Kuching", "MY", "Sarawak", 1.5535, 110.3593, "Asia/Kuching"),
    ("Miri", "MY", "Sarawak", 4.3995, 113.9914, "Asia/Kuching"),
    ("Sibu", "MY", "Sarawak", 2.2960, 111.4975, "Asia/Kuching"),
    ("Melaka", "MY", "Melaka", 2.1896, 102.2501, "Asia/Kuala_Lumpur"),
    ("Alor Setar", "MY", "Kedah", 6.1248, 100.3678, "Asia/Kuala_Lumpur"),
    ("Sungai Petani", "MY", "Kedah", 5.6415, 100.3565, "Asia/Kuala_Lumpur"),
    ("Kuantan", "MY", "Pahang", 3.8077, 103.3260, "Asia/Kuala_Lumpur"),
    ("Kota Bharu", "MY", "Kelantan", 6.1248, 102.2381, "Asia/Kuala_Lumpur"),
    ("Kuala Terengganu", "MY", "Terengganu", 5.3117, 103.1324, "Asia/Kuala_Lumpur"),
    ("Seremban", "MY", "Negeri Sembilan", 2.7297, 101.9381, "Asia/Kuala_Lumpur"),
    ("Labuan", "MY", "Labuan", 5.2831, 115.2308, "Asia/Kuala_Lumpur"),
    ("Kangar", "MY", "Perlis", 6.4981, 100.1776, "Asia/Kuala_Lumpur"),
    ("Bangkok", "TH", None, 13.7563, 100.5018, "Asia/Bangkok"),
    ("Ho Chi Minh City", "VN", None, 10.8231, 106.6297, "Asia/Ho_Chi_Minh"),
    ("Karachi", "PK", None, 24.8607, 67.0011, "Asia/Karachi"),
    ("Dhaka", "BD", None, 23.8103, 90.4125, "Asia/Dhaka"),
    ("Tel Aviv", "IL", None, 32.0853, 34.7818, "Asia/Jerusalem"),
    ("Dubai", "AE", None, 25.2048, 55.2708, "Asia/Dubai"),
    ("Riyadh", "SA", None, 24.7136, 46.6753, "Asia/Riyadh"),
    # Armenia: added for Job.am (2026-10-05), whose board is ~85%
    # Yerevan with the rest spread over Gyumri/Abovyan/… — without
    # these rows every job.am location resolved to the shared
    # unmatched fallback (is_global_remote=true) instead of a city.
    ("Yerevan", "AM", None, 40.1792, 44.4991, "Asia/Yerevan"),
    ("Gyumri", "AM", None, 40.7894, 43.8475, "Asia/Yerevan"),
    ("Vanadzor", "AM", None, 40.8128, 44.4883, "Asia/Yerevan"),
    ("Abovyan", "AM", None, 40.2694, 44.6347, "Asia/Yerevan"),
    ("Ashtarak", "AM", None, 40.2991, 44.3620, "Asia/Yerevan"),
    ("Armavir", "AM", None, 40.1072, 44.0336, "Asia/Yerevan"),
    ("Kapan", "AM", None, 39.2075, 46.4058, "Asia/Yerevan"),
    ("Hrazdan", "AM", None, 40.4937, 44.7690, "Asia/Yerevan"),
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
    # ---------------------------------------------------------------------
    # Cities for the boards added later. Each entry below exists because a
    # measured posting named that city and the resolver had no row to match it
    # against -- which is how 150 Rwandan, 112 Afghan and 65 Ghanaian postings
    # ended up country-only.
    # ---------------------------------------------------------------------
    # Brazil. vagas.com.br posted in Belo Horizonte, Mariana, Parauapebas,
    # Governador Celso Ramos and Governador Valadares.
    ("Brasilia", "BR", "Distrito Federal", -15.7975, -47.8919, "America/Sao_Paulo"),
    ("Belo Horizonte", "BR", "Minas Gerais", -19.9167, -43.9345, "America/Sao_Paulo"),
    ("Governador Valadares", "BR", "Minas Gerais", -18.8511, -41.9455, "America/Sao_Paulo"),
    ("Mariana", "BR", "Minas Gerais", -19.6636, -43.0376, "America/Sao_Paulo"),
    ("Salvador", "BR", "Bahia", -12.9777, -38.5016, "America/Bahia"),
    ("Fortaleza", "BR", "Ceara", -3.7319, -38.5267, "America/Fortaleza"),
    ("Recife", "BR", "Pernambuco", -8.0476, -34.8770, "America/Recife"),
    ("Curitiba", "BR", "Parana", -25.4284, -49.2733, "America/Sao_Paulo"),
    ("Porto Alegre", "BR", "Rio Grande do Sul", -30.0346, -51.2177, "America/Sao_Paulo"),
    ("Manaus", "BR", "Amazonas", -3.1190, -60.0217, "America/Manaus"),
    ("Campinas", "BR", "Sao Paulo", -22.9058, -47.0608, "America/Sao_Paulo"),
    ("Campo Grande", "BR", "Mato Grosso do Sul", -20.4697, -54.6201, "America/Campo_Grande"),
    ("Parauapebas", "BR", "Para", -6.0672, -49.9017, "America/Belem"),
    ("Governador Celso Ramos", "BR", "Santa Catarina", -27.3153, -49.6556, "America/Sao_Paulo"),
    # Afghanistan. acbar.org posts in Baghlan, Kabul, Nangarhar, Balkh,
    # Kunar, Herat, Kandahar, Helmand and Oruzgan.
    ("Kabul", "AF", "Kabul", 34.5553, 69.2075, "Asia/Kabul"),
    ("Kandahar", "AF", "Kandahar", 31.6289, 65.7372, "Asia/Kabul"),
    ("Herat", "AF", "Herat", 34.3529, 62.2040, "Asia/Kabul"),
    ("Mazar-e Sharif", "AF", "Balkh", 36.7090, 67.1109, "Asia/Kabul"),
    ("Jalalabad", "AF", "Nangarhar", 34.4265, 70.4515, "Asia/Kabul"),
    ("Kunduz", "AF", "Kunar", 36.7286, 68.8681, "Asia/Kabul"),
    ("Ghazni", "AF", "Ghazni", 33.5533, 68.4228, "Asia/Kabul"),
    ("Kunun", "AF", "Kunar", 34.9333, 64.9500, "Asia/Kabul"),
    ("Taloqan", "AF", "Takhar", 36.7139, 69.7964, "Asia/Kabul"),
    ("Lashkar Gah", "AF", "Helmand", 32.6264, 64.8372, "Asia/Kabul"),
    ("Chaharmalq", "AF", "Uruzgan", 33.1000, 66.2500, "Asia/Kabul"),
    ("Pull-e-Khumri", "AF", "Baghlan", 36.3000, 67.6200, "Asia/Kabul"),
    # Angola. angolaemprego.com posts in Luanda, Cazenga and the Huambo area.
    ("Luanda", "AO", "Luanda", -8.8390, 13.2894, "Africa/Luanda"),
    ("Huambo", "AO", "Huambo", -12.7761, 15.7392, "Africa/Luanda"),
    ("Lubango", "AO", "Huila", -14.9167, 13.4925, "Africa/Luanda"),
    ("Benguela", "AO", "Benguela", -12.5783, 13.4156, "Africa/Luanda"),
    ("Cabinda", "AO", "Cabinda", -5.5500, 12.2000, "Africa/Luanda"),
    ("Cazenga", "AO", "Luanda", -8.8833, 13.4667, "Africa/Luanda"),
    ("Malanje", "AO", "Malanje", -9.5333, 16.3333, "Africa/Luanda"),
    # Rwanda. jobinrwanda.com names Kigali repeatedly and mentions HUYE.
    ("Kigali", "RW", "Kigali", -1.9441, 30.0619, "Africa/Kigali"),
    ("Huye", "RW", "Butare", -2.6036, 29.7361, "Africa/Kigali"),
    # Ghana. jobwebghana.com posts in Accra, Kumasi, Takoradi and Tema.
    ("Kumasi", "GH", "Ashanti", 6.6885, -1.6244, "Africa/Accra"),
    ("Takoradi", "GH", "Western", 4.8975, -1.7605, "Africa/Accra"),
    ("Tema", "GH", "Greater Accra", 5.6698, -0.0166, "Africa/Accra"),
    ("Tamale", "GH", "Northern", 9.4008, -0.8393, "Africa/Accra"),
    # Iceland. alfred.is is all Reykjavik.
    ("Reykjavik", "IS", None, 64.1466, -21.9426, "Atlantic/Reykjavik"),
    # Pakistan. mustakbil.pk posts in Taxila, Rawalpindi and Islamabad.
    ("Taxila", "PK", None, 33.7459, 72.3592, "Asia/Karachi"),
    ("Rawalpindi", "PK", None, 33.5651, 73.0169, "Asia/Karachi"),
    ("Islamabad", "PK", None, 33.6844, 73.0479, "Asia/Karachi"),
    ("Lahore", "PK", None, 31.5204, 74.3587, "Asia/Karachi"),
    # South Africa. careers24 and careerjunction post across all nine provinces.
    ("Durban", "ZA", "KwaZulu-Natal", -29.8587, 31.0218, "Africa/Johannesburg"),
    ("Pretoria", "ZA", "Gauteng", -25.7479, 28.2293, "Africa/Johannesburg"),
    ("Centurion", "ZA", "Gauteng", -25.8603, 28.1894, "Africa/Johannesburg"),
    ("Port Elizabeth", "ZA", "Eastern Cape", -33.9608, 25.6022, "Africa/Johannesburg"),
    ("East London", "ZA", "Eastern Cape", -33.0192, 27.9075, "Africa/Johannesburg"),
    ("Polokwane", "ZA", "Limpopo", -23.8965, 29.4657, "Africa/Johannesburg"),
    ("Nelspruit", "ZA", "Mpumalanga", -25.4658, 30.9853, "Africa/Johannesburg"),
    ("Kimberley", "ZA", "Northern Cape", -28.7382, 24.7719, "Africa/Johannesburg"),
    ("Bloemfontein", "ZA", "Free State", -29.1042, 26.2007, "Africa/Johannesburg"),
    ("Rustenburg", "ZA", "North West", -25.6672, 27.2422, "Africa/Johannesburg"),
    ("George", "ZA", "Western Cape", -33.9630, 22.4612, "Africa/Johannesburg"),
]


def seed_cities(conn: Connection) -> SeedResult:
    country_ids = get_id_map(
        conn, schema="ref", table_name="countries", key_col="iso_code_2", id_col="country_id"
    )
    region_rows = conn.execute(
        __import__("sqlalchemy").text("SELECT country_id, region_name, region_id FROM ref.regions")
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
