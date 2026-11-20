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
_CITIES: list[tuple[str, str, str | None, float | None, float | None, str | None]] = [
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
    # Irish towns, for jobsireland.ie. Ireland's 26 counties and its towns are
    # not decoration here: every address on that board is
    # "<premises>, <town>, Co. <County>, <Eircode>", so without towns and
    # counties the source resolves to country-only. Measured over 600 live
    # cards: all 26 counties appear, and Cork (20), Limerick (17), Kildare
    # (14), Mayo (11), Dublin (10), Tipperary (9) and Westmeath (9) lead.
    # The list is curated rather than mined -- token-mining the address strings
    # yields "Road", "Street", "House" and "COMM" alongside real places.
    ("Cork", "IE", "Cork", 51.8985, -8.4756, "Europe/Dublin"),
    ("Limerick", "IE", "Limerick", 52.6638, -8.6267, "Europe/Dublin"),
    ("Galway", "IE", "Galway", 53.2707, -9.0568, "Europe/Dublin"),
    ("Waterford", "IE", "Waterford", 52.2610, -7.9757, "Europe/Dublin"),
    ("Kilkenny", "IE", "Kilkenny", 52.6503, -7.2520, "Europe/Dublin"),
    ("Sligo", "IE", "Sligo", 54.2766, -8.4756, "Europe/Dublin"),
    ("Carlow", "IE", "Carlow", 52.8507, -6.9214, "Europe/Dublin"),
    ("Wexford", "IE", "Wexford", 52.3372, -6.2892, "Europe/Dublin"),
    ("Killarney", "IE", "Kerry", 52.0599, -9.5077, "Europe/Dublin"),
    ("Tralee", "IE", "Kerry", 52.2702, -9.7028, "Europe/Dublin"),
    ("Listowel", "IE", "Kerry", 52.2847, -9.3822, "Europe/Dublin"),
    ("Dungarvan", "IE", "Waterford", 52.0521, -7.2598, "Europe/Dublin"),
    ("Claremorris", "IE", "Mayo", 53.7228, -8.9906, "Europe/Dublin"),
    ("Castlebar", "IE", "Mayo", 53.9960, -9.0504, "Europe/Dublin"),
    ("Ballina", "IE", "Mayo", 54.1166, -9.1562, "Europe/Dublin"),
    ("Ballinasloe", "IE", "Galway", 53.3285, -8.1100, "Europe/Dublin"),
    ("Tuam", "IE", "Galway", 53.6972, -8.8581, "Europe/Dublin"),
    ("Ennis", "IE", "Clare", 52.8438, -8.9864, "Europe/Dublin"),
    ("Shannon", "IE", "Clare", 52.6639, -8.6267, "Europe/Dublin"),
    ("Drogheda", "IE", "Louth", 53.5231, -6.2594, "Europe/Dublin"),
    ("Dundalk", "IE", "Louth", 54.0225, -6.3903, "Europe/Dublin"),
    ("Navan", "IE", "Meath", 53.6489, -6.7080, "Europe/Dublin"),
    ("Trim", "IE", "Meath", 53.3150, -6.9485, "Europe/Dublin"),
    ("Kildare", "IE", "Kildare", 53.3313, -6.8744, "Europe/Dublin"),
    ("Naas", "IE", "Kildare", 53.2108, -6.6754, "Europe/Dublin"),
    ("Athy", "IE", "Kildare", 52.9743, -6.9894, "Europe/Dublin"),
    ("Tullamore", "IE", "Offaly", 53.2777, -7.4994, "Europe/Dublin"),
    ("Portlaoise", "IE", "Laois", 53.0475, -7.0506, "Europe/Dublin"),
    ("Athlone", "IE", "Westmeath", 53.4193, -7.9499, "Europe/Dublin"),
    ("Mullingar", "IE", "Westmeath", 53.5183, -7.3498, "Europe/Dublin"),
    ("Longford", "IE", "Longford", 53.8079, -7.7894, "Europe/Dublin"),
    ("Monaghan", "IE", "Monaghan", 54.2481, -6.9725, "Europe/Dublin"),
    ("Carrickmacross", "IE", "Monaghan", 54.0106, -6.6747, "Europe/Dublin"),
    ("Cavan", "IE", "Cavan", 54.0306, -7.0074, "Europe/Dublin"),
    ("Bray", "IE", "Wicklow", 53.3419, -6.1144, "Europe/Dublin"),
    ("Greystones", "IE", "Wicklow", 53.1506, -6.0727, "Europe/Dublin"),
    ("Wicklow", "IE", "Wicklow", 52.9808, -6.0400, "Europe/Dublin"),
    ("Aughrim", "IE", "Wicklow", 52.8530, -6.1053, "Europe/Dublin"),
    ("Thurles", "IE", "Tipperary", 52.6920, -7.9340, "Europe/Dublin"),
    ("Nenagh", "IE", "Tipperary", 52.8689, -8.9767, "Europe/Dublin"),
    ("Clonmel", "IE", "Tipperary", 52.3487, -7.9303, "Europe/Dublin"),
    ("Cashel", "IE", "Tipperary", 52.5200, -7.8904, "Europe/Dublin"),
    ("Cahir", "IE", "Tipperary", 52.3727, -7.9170, "Europe/Dublin"),
    ("Kenmare", "IE", "Kerry", 51.8558, -9.5833, "Europe/Dublin"),
    ("Donegal", "IE", "Donegal", 54.6573, -8.4725, "Europe/Dublin"),
    ("Letterkenny", "IE", "Donegal", 54.8326, -7.7333, "Europe/Dublin"),
    ("Buncrana", "IE", "Donegal", 55.1367, -7.4611, "Europe/Dublin"),
    ("Ballybofey", "IE", "Donegal", 54.7500, -8.2833, "Europe/Dublin"),
    ("Roscommon", "IE", "Roscommon", 53.7686, -8.9606, "Europe/Dublin"),
    ("Boyle", "IE", "Roscommon", 54.0500, -8.1833, "Europe/Dublin"),
    ("Carrick-on-Shannon", "IE", "Leitrim", 54.0717, -7.6494, "Europe/Dublin"),
    ("Manorhamilton", "IE", "Leitrim", 54.2519, -7.7997, "Europe/Dublin"),
    ("Newbridge", "IE", "Kildare", 53.1814, -6.8056, "Europe/Dublin"),
    ("Maynooth", "IE", "Kildare", 53.3824, -6.5936, "Europe/Dublin"),
    ("Leixlip", "IE", "Kildare", 53.3667, -6.5000, "Europe/Dublin"),
    ("Celbridge", "IE", "Kildare", 53.2705, -6.5410, "Europe/Dublin"),
    ("Swords", "IE", "Dublin", 53.4197, -6.2183, "Europe/Dublin"),
    ("Malahide", "IE", "Dublin", 53.2495, -6.0775, "Europe/Dublin"),
    ("Skerries", "IE", "Dublin", 53.2533, -6.1181, "Europe/Dublin"),
    ("Balbriggan", "IE", "Dublin", 53.2900, -6.0800, "Europe/Dublin"),
    ("Berlin", "DE", None, 52.5200, 13.4050, "Europe/Berlin"),
    ("Munich", "DE", None, 48.1351, 11.5820, "Europe/Berlin"),
    ("Paris", "FR", None, 48.8566, 2.3522, "Europe/Paris"),
    # Poitiers backs emploibenin_com: the Benin board advertises on-site roles
    # in France, and one measured ad names "Poitiers" as its locality.
    ("Poitiers", "FR", None, 46.5802, 0.3404, "Europe/Paris"),
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
    # More Malaysian job markets, added with the maukerja_my source
    # (2026-11-20). MauKerja publishes "<town>; <state>; MY", and without
    # these rows its postings in them resolved to region level rather than
    # city level. Regions here match ref.regions exactly; the resolver matches
    # them case-insensitively, and a wrong region would be invisible once
    # cached, so only well-known town/state pairs are listed.
    ("Puchong", "MY", "Selangor", 3.0030, 101.6179, "Asia/Kuala_Lumpur"),
    ("Kajang", "MY", "Selangor", 2.9930, 101.7897, "Asia/Kuala_Lumpur"),
    ("Rawang", "MY", "Selangor", 3.3210, 101.5760, "Asia/Kuala_Lumpur"),
    ("Seri Kembangan", "MY", "Selangor", 3.0220, 101.7020, "Asia/Kuala_Lumpur"),
    ("Ampang", "MY", "Selangor", 3.1510, 101.7620, "Asia/Kuala_Lumpur"),
    ("Sungai Buloh", "MY", "Selangor", 3.2100, 101.5650, "Asia/Kuala_Lumpur"),
    ("Bandar Baru Bangi", "MY", "Selangor", 2.9450, 101.7750, "Asia/Kuala_Lumpur"),
    ("Semenyih", "MY", "Selangor", 2.9490, 101.8430, "Asia/Kuala_Lumpur"),
    ("Banting", "MY", "Selangor", 2.8130, 101.5010, "Asia/Kuala_Lumpur"),
    ("Sepang", "MY", "Selangor", 2.6930, 101.7490, "Asia/Kuala_Lumpur"),
    ("Pasir Gudang", "MY", "Johor", 1.4740, 103.8800, "Asia/Kuala_Lumpur"),
    ("Kulai", "MY", "Johor", 1.6560, 103.6040, "Asia/Kuala_Lumpur"),
    ("Kluang", "MY", "Johor", 2.0300, 103.3180, "Asia/Kuala_Lumpur"),
    ("Muar", "MY", "Johor", 2.0440, 102.5690, "Asia/Kuala_Lumpur"),
    ("Nilai", "MY", "Negeri Sembilan", 2.8030, 101.7970, "Asia/Kuala_Lumpur"),
    ("Port Dickson", "MY", "Negeri Sembilan", 2.5230, 101.7960, "Asia/Kuala_Lumpur"),
    ("Taiping", "MY", "Perak", 4.8510, 100.7410, "Asia/Kuala_Lumpur"),
    ("Teluk Intan", "MY", "Perak", 4.0260, 101.0210, "Asia/Kuala_Lumpur"),
    ("Kulim", "MY", "Kedah", 5.3650, 100.5600, "Asia/Kuala_Lumpur"),
    ("Bintulu", "MY", "Sarawak", 3.1710, 113.0430, "Asia/Kuching"),
    ("Lahad Datu", "MY", "Sabah", 5.0250, 118.3350, "Asia/Kuching"),
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
    #: Egyptian localities, for forasna. Measured on live postings, and only
    #: the ones that are safe to seed.
    #:
    #: ``_match_city`` matches on ``lower(city_name)`` with NO country filter, and
    #: treats two rows with the same name as ambiguous -- no match at all. So a
    #: locality seen under two governorates must not be seeded: it would always
    #: resolve to whichever governorate was seeded first. Excluded on that
    #: ground: "مدينة العبور" (القاهرة and القليوبية) and "وسط البلد" (القاهرة
    #: and كفر الشيخ).
    #:
    #: "الرياض" is excluded for a different reason: it is a village in Kafr El
    #: Sheikh AND the Saudi capital, and 6 of the 320 sampled postings are SA.
    #: Seeding it as an Egyptian city would file a Saudi posting under Egypt.
    #:
    #: Coordinates are NULL on purpose: the board publishes none and none were
    #: measured. The country has a single timezone, so Africa/Cairo is exact.
    #: Every entry is a real posting's own locality->governorate pair.
    # الاسكندرية
    ("الابراهيمية", "EG", "الاسكندرية", None, None, "Africa/Cairo"),
    ("العامرية", "EG", "الاسكندرية", None, None, "Africa/Cairo"),
    ("العجمى", "EG", "الاسكندرية", None, None, "Africa/Cairo"),
    ("العصافرة", "EG", "الاسكندرية", None, None, "Africa/Cairo"),
    ("المنتزه", "EG", "الاسكندرية", None, None, "Africa/Cairo"),
    ("المندرة", "EG", "الاسكندرية", None, None, "Africa/Cairo"),
    ("باب شرق", "EG", "الاسكندرية", None, None, "Africa/Cairo"),
    ("برج العرب", "EG", "الاسكندرية", None, None, "Africa/Cairo"),
    ("سان ستيفانو", "EG", "الاسكندرية", None, None, "Africa/Cairo"),
    ("سموحة", "EG", "الاسكندرية", None, None, "Africa/Cairo"),
    # البحر الأحمر
    ("الغردقة", "EG", "البحر الأحمر", None, None, "Africa/Cairo"),
    # البحيرة
    ("ايتاى البارود", "EG", "البحيرة", None, None, "Africa/Cairo"),
    ("وادى النطرون", "EG", "البحيرة", None, None, "Africa/Cairo"),
    # الجيزة
    ("أبو رواش", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("ابو النمرس", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("الجيزة", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("الدقى", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("السادس من اكتوبر", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("الشيخ زايد", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("العجوزة", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("الكيت كات", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("المنيب", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("المهندسين", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("الهرم", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("اوسيم", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("حدائق الأهرام", "EG", "الجيزة", None, None, "Africa/Cairo"),
    ("طريق مصر إسكندرية الصحراوي", "EG", "الجيزة", None, None, "Africa/Cairo"),
    # الدقهلية
    ("السنبلاوين", "EG", "الدقهلية", None, None, "Africa/Cairo"),
    ("المنصورة", "EG", "الدقهلية", None, None, "Africa/Cairo"),
    # السويس
    ("العين السخنة", "EG", "السويس", None, None, "Africa/Cairo"),
    # الشرقية
    ("ابو حماد", "EG", "الشرقية", None, None, "Africa/Cairo"),
    ("الزقازيق", "EG", "الشرقية", None, None, "Africa/Cairo"),
    ("العاشر من رمضان", "EG", "الشرقية", None, None, "Africa/Cairo"),
    ("بلبيس", "EG", "الشرقية", None, None, "Africa/Cairo"),
    # الغربية
    ("المحلة الكبرى", "EG", "الغربية", None, None, "Africa/Cairo"),
    ("طنطا", "EG", "الغربية", None, None, "Africa/Cairo"),
    # الفيوم
    ("الحادقة", "EG", "الفيوم", None, None, "Africa/Cairo"),
    # القاهرة
    ("15 مايو", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("الازبكية", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("البساتين", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("التجمع الاول", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("التجمع الخامس", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("الزيتون", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("السلام", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("الشرابية", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("الشروق", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("العاصمة الجديدة", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("القاهرة الجديدة", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("القطامية", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("المرج", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("المعادى", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("المقطم", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("المنيل", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("الموسكى", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("النزهة", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("النزهة الجديدة", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("جاردن سيتى", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("جسر السويس", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("حلوان", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("شبرا", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("شيراتون", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("عباسية", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("عين شمس", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("مدينة الشروق", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("مدينة بدر", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("مدينة نصر", "EG", "القاهرة", None, None, "Africa/Cairo"),
    ("مصر الجديدة", "EG", "القاهرة", None, None, "Africa/Cairo"),
    # القليوبية
    ("الخانكة", "EG", "القليوبية", None, None, "Africa/Cairo"),
    ("القناطر الخيرية", "EG", "القليوبية", None, None, "Africa/Cairo"),
    ("بنها", "EG", "القليوبية", None, None, "Africa/Cairo"),
    ("قها", "EG", "القليوبية", None, None, "Africa/Cairo"),
    # المنوفية
    ("مدينة السادات", "EG", "المنوفية", None, None, "Africa/Cairo"),
    # المنيا
    ("ابو قرقاص", "EG", "المنيا", None, None, "Africa/Cairo"),
    ("المنيا", "EG", "المنيا", None, None, "Africa/Cairo"),
    # الوادي الجديد
    ("الداخلة", "EG", "الوادي الجديد", None, None, "Africa/Cairo"),
    # جنوب سيناء
    ("شرم الشيخ", "EG", "جنوب سيناء", None, None, "Africa/Cairo"),
    # سوهاج
    ("سوهاج", "EG", "سوهاج", None, None, "Africa/Cairo"),
    # Sri Lanka, for topjobs_lk. Every town in the seed is a real value from
    # that board's "Town" column on 2026-11-20 -- it lists areas rather than
    # provinces ("Battaramulla, Borella, Gampaha (Gampaha)"), and the resolver's
    # "City, ..." fallback reads the first comma-separated town. Regions are
    # left NULL on purpose: Sri Lanka's nine provinces are not what the board
    # publishes, and province names such as "Central"/"Western" are ambiguous
    # against other countries' seeded regions.
    ("Colombo", "LK", None, 6.9271, 79.8612, "Asia/Colombo"),
    ("Sri Jayawardenepura Kotte", "LK", None, 6.8940, 79.9026, "Asia/Colombo"),
    ("Battaramulla", "LK", None, 6.8964, 79.9173, "Asia/Colombo"),
    ("Dehiwala", "LK", None, 6.8511, 79.8636, "Asia/Colombo"),
    ("Moratuwa", "LK", None, 6.7730, 79.8816, "Asia/Colombo"),
    ("Nugegoda", "LK", None, 6.8649, 79.8997, "Asia/Colombo"),
    ("Maharagama", "LK", None, 6.8480, 79.9265, "Asia/Colombo"),
    ("Homagama", "LK", None, 6.8410, 80.0024, "Asia/Colombo"),
    ("Kelaniya", "LK", None, 6.9553, 79.9219, "Asia/Colombo"),
    ("Panadura", "LK", None, 6.7133, 79.9074, "Asia/Colombo"),
    ("Kalutara", "LK", None, 6.5854, 79.9607, "Asia/Colombo"),
    ("Gampaha", "LK", None, 7.0917, 79.9997, "Asia/Colombo"),
    ("Negombo", "LK", None, 7.2083, 79.8358, "Asia/Colombo"),
    ("Kandy", "LK", None, 7.2906, 80.6337, "Asia/Colombo"),
    ("Galle", "LK", None, 6.0535, 80.2210, "Asia/Colombo"),
    ("Matara", "LK", None, 5.9485, 80.5353, "Asia/Colombo"),
    ("Jaffna", "LK", None, 9.6615, 80.0255, "Asia/Colombo"),
    ("Kurunegala", "LK", None, 7.4863, 80.3623, "Asia/Colombo"),
    ("Anuradhapura", "LK", None, 8.3114, 80.4037, "Asia/Colombo"),
    ("Ratnapura", "LK", None, 6.6828, 80.3992, "Asia/Colombo"),
    ("Kegalle", "LK", None, 7.2513, 80.3464, "Asia/Colombo"),
    ("Badulla", "LK", None, 6.9934, 81.0550, "Asia/Colombo"),
    ("Nuwara Eliya", "LK", None, 6.9497, 80.7891, "Asia/Colombo"),
    ("Trincomalee", "LK", None, 8.5874, 81.2152, "Asia/Colombo"),
    ("Batticaloa", "LK", None, 7.7102, 81.6924, "Asia/Colombo"),
    # DR Congo, for emploi_cd. The board names one city (Kinshasa, Goma,
    # Lubumbashi) or a slash/space list of cities per ad; the resolver matches
    # a city segment exactly, so the hubs that actually appear are seeded.
    # Smaller towns in the long remote lists stay in raw_payload rather than
    # being guessed at. Regions are left NULL: the seed has no DRC region rows.
    ("Kinshasa", "CD", None, -4.4419, 15.2663, "Africa/Kinshasa"),
    ("Lubumbashi", "CD", None, -11.6876, 27.5026, "Africa/Lubumbashi"),
    ("Goma", "CD", None, -1.6771, 29.2285, "Africa/Lubumbashi"),
    ("Bukavu", "CD", None, -2.5123, 28.8638, "Africa/Lubumbashi"),
    ("Kisangani", "CD", None, 0.5153, 25.1910, "Africa/Lubumbashi"),
    ("Matadi", "CD", None, -5.8167, 13.4500, "Africa/Kinshasa"),
    ("Mbuji-Mayi", "CD", None, -6.1500, 23.6000, "Africa/Lubumbashi"),
    ("Kananga", "CD", None, -5.8958, 22.4178, "Africa/Lubumbashi"),
    ("Kolwezi", "CD", None, -10.7167, 25.4667, "Africa/Lubumbashi"),
    ("Likasi", "CD", None, -10.9814, 26.7333, "Africa/Lubumbashi"),
    ("Beni", "CD", None, 0.4917, 29.4731, "Africa/Lubumbashi"),
    ("Butembo", "CD", None, 0.1416, 29.2912, "Africa/Lubumbashi"),
    ("Bunia", "CD", None, 1.5594, 30.2522, "Africa/Lubumbashi"),
    ("Uvira", "CD", None, -3.3953, 29.1378, "Africa/Lubumbashi"),
    ("Tshikapa", "CD", None, -6.4167, 20.8000, "Africa/Lubumbashi"),
    ("Kikwit", "CD", None, -5.0400, 18.8167, "Africa/Kinshasa"),
    ("Kindu", "CD", None, -2.9500, 25.9500, "Africa/Lubumbashi"),
    ("Mbandaka", "CD", None, 0.0478, 18.2561, "Africa/Kinshasa"),
    ("Gbadolite", "CD", None, 4.2833, 21.0167, "Africa/Kinshasa"),
    ("Gemena", "CD", None, 3.2500, 19.7667, "Africa/Kinshasa"),
    ("Inongo", "CD", None, -1.9500, 18.2833, "Africa/Kinshasa"),
    ("Isiro", "CD", None, 2.7667, 27.6167, "Africa/Lubumbashi"),
    ("Kabinda", "CD", None, -6.1333, 24.4833, "Africa/Lubumbashi"),
    ("Kalemie", "CD", None, -5.9475, 29.1947, "Africa/Lubumbashi"),
    ("Kamina", "CD", None, -8.7386, 24.9906, "Africa/Lubumbashi"),
    ("Kenge", "CD", None, -4.8000, 16.9000, "Africa/Kinshasa"),
    ("Lisala", "CD", None, 2.1500, 21.5167, "Africa/Kinshasa"),
    ("Lodja", "CD", None, -3.4833, 23.4333, "Africa/Lubumbashi"),
    ("Luebo", "CD", None, -5.3500, 21.4167, "Africa/Lubumbashi"),
    ("Boende", "CD", None, -0.2833, 20.8667, "Africa/Kinshasa"),
    ("Buta", "CD", None, 2.8000, 24.7333, "Africa/Lubumbashi"),
    # Benin, for emploibenin_com. The board names one city (Cotonou,
    # Porto-Novo, Parakou) in addressLocality and puts a longer list of the
    # cities an ad is open to in addressRegion -- that list is not stored, so
    # the hubs that appear as localities are what matter. Regions are left
    # NULL: the seed has no Benin region rows. All times Africa/Porto-Novo.
    ("Cotonou", "BJ", None, 6.3654, 2.4183, "Africa/Porto-Novo"),
    ("Porto-Novo", "BJ", None, 6.4969, 2.6289, "Africa/Porto-Novo"),
    ("Parakou", "BJ", None, 9.3372, 2.6303, "Africa/Porto-Novo"),
    ("Abomey-Calavi", "BJ", None, 6.4489, 2.3556, "Africa/Porto-Novo"),
    ("Djougou", "BJ", None, 9.7085, 1.6660, "Africa/Porto-Novo"),
    ("Bohicon", "BJ", None, 7.1783, 2.0667, "Africa/Porto-Novo"),
    ("Natitingou", "BJ", None, 10.3042, 1.3796, "Africa/Porto-Novo"),
    ("Kandi", "BJ", None, 11.1342, 2.9386, "Africa/Porto-Novo"),
    ("Ouidah", "BJ", None, 6.3631, 2.0851, "Africa/Porto-Novo"),
    ("Lokossa", "BJ", None, 6.6389, 1.7167, "Africa/Porto-Novo"),
    ("Savalou", "BJ", None, 7.9281, 1.9756, "Africa/Porto-Novo"),
    ("Abomey", "BJ", None, 7.1822, 1.9911, "Africa/Porto-Novo"),
    ("Pobè", "BJ", None, 6.9800, 2.6647, "Africa/Porto-Novo"),
    ("Aplahoué", "BJ", None, 6.9333, 1.6833, "Africa/Porto-Novo"),
    ("Nikki", "BJ", None, 9.9400, 3.2100, "Africa/Porto-Novo"),
    ("Malanville", "BJ", None, 11.8685, 3.3833, "Africa/Porto-Novo"),
    ("Tchaourou", "BJ", None, 8.8869, 2.5972, "Africa/Porto-Novo"),
    ("Banikoara", "BJ", None, 11.2985, 2.4386, "Africa/Porto-Novo"),
    ("Kétou", "BJ", None, 7.3631, 2.5997, "Africa/Porto-Novo"),
    ("Savè", "BJ", None, 8.0342, 2.4858, "Africa/Porto-Novo"),
    ("Tanguiéta", "BJ", None, 10.6214, 1.2667, "Africa/Porto-Novo"),
    ("Bassila", "BJ", None, 9.0081, 1.6656, "Africa/Porto-Novo"),
    ("Allada", "BJ", None, 6.6653, 2.1511, "Africa/Porto-Novo"),
    ("Sakété", "BJ", None, 6.7361, 2.6586, "Africa/Porto-Novo"),
    ("Dogbo", "BJ", None, 6.8000, 1.7833, "Africa/Porto-Novo"),
    # Cameroon, for emploi_cm. The board names the locality on its own and puts
    # a longer list of the cities an ad is open to in addressRegion; that list
    # is not stored, so the hubs that appear as localities are what matter.
    # Regions are left NULL: the seed has no Cameroon region rows. All times
    # Africa/Douala. Douala and Yaoundé carry most ads; the rest are the cities
    # the board actually advertises in.
    ("Douala", "CM", None, 4.0511, 9.7679, "Africa/Douala"),
    ("Yaoundé", "CM", None, 3.8480, 11.5021, "Africa/Douala"),
    ("Bafoussam", "CM", None, 5.4781, 10.4172, "Africa/Douala"),
    ("Garoua", "CM", None, 9.3265, 13.3958, "Africa/Douala"),
    ("Bamenda", "CM", None, 5.9631, 10.1591, "Africa/Douala"),
    ("Maroua", "CM", None, 10.5910, 14.3159, "Africa/Douala"),
    ("Buea", "CM", None, 4.1527, 9.2410, "Africa/Douala"),
    ("Limbe", "CM", None, 4.0236, 9.1955, "Africa/Douala"),
    ("Kribi", "CM", None, 2.9373, 9.9077, "Africa/Douala"),
    ("Ngaoundéré", "CM", None, 7.3277, 13.5847, "Africa/Douala"),
    ("Bertoua", "CM", None, 4.5776, 13.6846, "Africa/Douala"),
    ("Ebolowa", "CM", None, 2.9000, 11.1500, "Africa/Douala"),
    ("Kumba", "CM", None, 4.6363, 9.4469, "Africa/Douala"),
    ("Edéa", "CM", None, 3.8000, 10.1333, "Africa/Douala"),
    ("Dschang", "CM", None, 5.4460, 10.0533, "Africa/Douala"),
    ("Foumban", "CM", None, 5.7167, 10.9000, "Africa/Douala"),
    ("Mbouda", "CM", None, 5.6266, 10.2542, "Africa/Douala"),
    ("Tiko", "CM", None, 4.0745, 9.3697, "Africa/Douala"),
    ("Sangmélima", "CM", None, 2.9333, 11.9833, "Africa/Douala"),
    ("Mbalmayo", "CM", None, 3.5167, 11.5000, "Africa/Douala"),
    ("Nkongsamba", "CM", None, 4.9547, 9.9404, "Africa/Douala"),
    ("Bafia", "CM", None, 4.7500, 11.2333, "Africa/Douala"),
    ("Guider", "CM", None, 9.9342, 13.9486, "Africa/Douala"),
    ("Mokolo", "CM", None, 10.7424, 13.8023, "Africa/Douala"),
    ("Kousséri", "CM", None, 12.0769, 15.0306, "Africa/Douala"),
    # Djibouti, for one measured emploi_cm ad (an on-site expatriation role).
    # The board writes addressCountry "Cameroun" on it, so the city is what
    # keeps the row truthful.
    ("Djibouti", "DJ", None, 11.5721, 43.1456, "Africa/Djibouti"),
    # Morocco, for emploi_ma (and the already-registered rekrute_com, whose
    # rows currently fold onto one country-level row because no MA city was
    # seeded). The board writes the city in addressLocality; regions are left
    # NULL: the seed has no Moroccan region rows. All times Africa/Casablanca.
    ("Casablanca", "MA", None, 33.5731, -7.5898, "Africa/Casablanca"),
    ("Rabat", "MA", None, 34.0209, -6.8416, "Africa/Casablanca"),
    ("Marrakech", "MA", None, 31.6295, -7.9811, "Africa/Casablanca"),
    ("Fès", "MA", None, 34.0331, -5.0003, "Africa/Casablanca"),
    ("Tanger", "MA", None, 35.7595, -5.8340, "Africa/Casablanca"),
    ("Agadir", "MA", None, 30.4278, -9.5981, "Africa/Casablanca"),
    ("Meknès", "MA", None, 33.8935, -5.5473, "Africa/Casablanca"),
    ("Oujda", "MA", None, 34.6814, -1.9086, "Africa/Casablanca"),
    ("Kénitra", "MA", None, 34.2610, -6.5802, "Africa/Casablanca"),
    ("Tétouan", "MA", None, 35.5785, -5.3684, "Africa/Casablanca"),
    ("Salé", "MA", None, 34.0531, -6.7985, "Africa/Casablanca"),
    ("Mohammedia", "MA", None, 33.6866, -7.3830, "Africa/Casablanca"),
    ("El Jadida", "MA", None, 33.2316, -8.5007, "Africa/Casablanca"),
    ("Safi", "MA", None, 32.2994, -9.2372, "Africa/Casablanca"),
    ("Béni Mellal", "MA", None, 32.3373, -6.3498, "Africa/Casablanca"),
    ("Nador", "MA", None, 35.1681, -2.9335, "Africa/Casablanca"),
    ("Khouribga", "MA", None, 32.8811, -6.9063, "Africa/Casablanca"),
    ("Settat", "MA", None, 33.0010, -7.6166, "Africa/Casablanca"),
    ("Berrechid", "MA", None, 33.2655, -7.5875, "Africa/Casablanca"),
    ("Taza", "MA", None, 34.2100, -4.0100, "Africa/Casablanca"),
    ("Essaouira", "MA", None, 31.5085, -9.7595, "Africa/Casablanca"),
    ("Laâyoune", "MA", None, 27.1536, -13.2033, "Africa/Casablanca"),
    ("Dakhla", "MA", None, 23.6848, -15.9580, "Africa/Casablanca"),
    ("Errachidia", "MA", None, 31.9314, -4.4245, "Africa/Casablanca"),
    ("Ouarzazate", "MA", None, 30.9335, -6.9370, "Africa/Casablanca"),
    ("Al Hoceima", "MA", None, 35.2517, -3.9372, "Africa/Casablanca"),
    ("Larache", "MA", None, 35.1932, -6.1557, "Africa/Casablanca"),
    ("Khémisset", "MA", None, 33.8240, -6.0658, "Africa/Casablanca"),
    ("Guelmim", "MA", None, 28.9870, -10.0574, "Africa/Casablanca"),
    ("Tinghir", "MA", None, 31.5147, -5.5326, "Africa/Casablanca"),
    # Chile, for chiletrabajos.cl. The board's city tab lists exactly these 58
    # comunas across the 16 regions (measured 2026-11-18), and its JobPosting
    # addressRegion is the ISO 3166-2:CL code mapped in seed/regions.py. The 58
    # cities keep the high-volume ads at city level; unseeded comunas still
    # resolve at region level through the region segment of the location string.
    ("Santiago", "CL", "Metropolitana de Santiago", -33.4489, -70.6693, "America/Santiago"),
    ("San Bernardo", "CL", "Metropolitana de Santiago", -33.5922, -70.6996, "America/Santiago"),
    ("Colina", "CL", "Metropolitana de Santiago", -33.2027, -70.6749, "America/Santiago"),
    ("Melipilla", "CL", "Metropolitana de Santiago", -33.6891, -71.2167, "America/Santiago"),
    ("Talagante", "CL", "Metropolitana de Santiago", -33.6633, -70.9281, "America/Santiago"),
    ("Puente Alto", "CL", "Metropolitana de Santiago", -33.6117, -70.5758, "America/Santiago"),
    ("Antofagasta", "CL", "Antofagasta", -23.6509, -70.3975, "America/Santiago"),
    ("Calama", "CL", "Antofagasta", -22.4567, -68.9239, "America/Santiago"),
    ("Tocopilla", "CL", "Antofagasta", -22.0919, -70.1978, "America/Santiago"),
    ("Valparaíso", "CL", "Valparaíso", -33.0472, -71.6127, "America/Santiago"),
    ("San Antonio", "CL", "Valparaíso", -33.5928, -71.6094, "America/Santiago"),
    ("Quillota", "CL", "Valparaíso", -32.8808, -71.2486, "America/Santiago"),
    ("Quilpué", "CL", "Valparaíso", -33.0495, -71.4419, "America/Santiago"),
    ("Los Andes", "CL", "Valparaíso", -32.8338, -70.5983, "America/Santiago"),
    ("San Felipe", "CL", "Valparaíso", -32.7507, -70.7257, "America/Santiago"),
    ("La Ligua", "CL", "Valparaíso", -32.4536, -71.2311, "America/Santiago"),
    ("Hanga Roa", "CL", "Valparaíso", -27.1500, -109.4333, "Pacific/Easter"),
    ("Concepción", "CL", "Biobío", -36.8270, -73.0503, "America/Santiago"),
    ("Los Ángeles", "CL", "Biobío", -37.4697, -72.3537, "America/Santiago"),
    ("Lebu", "CL", "Biobío", -37.6083, -73.6500, "America/Santiago"),
    ("Puerto Montt", "CL", "Los Lagos", -41.4693, -72.9424, "America/Santiago"),
    ("Osorno", "CL", "Los Lagos", -40.5739, -73.1335, "America/Santiago"),
    ("Castro", "CL", "Los Lagos", -42.4721, -73.7732, "America/Santiago"),
    ("Chaitén", "CL", "Los Lagos", -42.9167, -72.7167, "America/Santiago"),
    ("Rancagua", "CL", "O'Higgins", -34.1708, -70.7444, "America/Santiago"),
    ("San Fernando", "CL", "O'Higgins", -34.5833, -70.9833, "America/Santiago"),
    ("Pichilemu", "CL", "O'Higgins", -34.3833, -72.0000, "America/Santiago"),
    ("La Serena", "CL", "Coquimbo", -29.9027, -71.2519, "America/Santiago"),
    ("Coquimbo", "CL", "Coquimbo", -29.9533, -71.3436, "America/Santiago"),
    ("Ovalle", "CL", "Coquimbo", -30.5983, -71.2003, "America/Santiago"),
    ("Illapel", "CL", "Coquimbo", -31.6333, -71.1667, "America/Santiago"),
    ("Copiapó", "CL", "Atacama", -27.3667, -70.3333, "America/Santiago"),
    ("Chañaral", "CL", "Atacama", -26.3479, -70.6224, "America/Santiago"),
    ("Vallenar", "CL", "Atacama", -28.5708, -70.7581, "America/Santiago"),
    ("Talca", "CL", "Maule", -35.4264, -71.6554, "America/Santiago"),
    ("Curicó", "CL", "Maule", -34.9828, -71.2394, "America/Santiago"),
    ("Linares", "CL", "Maule", -35.8500, -71.6000, "America/Santiago"),
    ("Cauquenes", "CL", "Maule", -35.9667, -72.3167, "America/Santiago"),
    ("Iquique", "CL", "Tarapacá", -20.2208, -70.1431, "America/Santiago"),
    ("Pozo Almonte", "CL", "Tarapacá", -20.2592, -69.7864, "America/Santiago"),
    ("Temuco", "CL", "La Araucanía", -38.7359, -72.5904, "America/Santiago"),
    ("Angol", "CL", "La Araucanía", -37.7983, -72.7086, "America/Santiago"),
    ("Chillán", "CL", "Ñuble", -36.6067, -72.1033, "America/Santiago"),
    ("San Carlos", "CL", "Ñuble", -36.4247, -71.9561, "America/Santiago"),
    ("Bulnes", "CL", "Ñuble", -36.7500, -72.3000, "America/Santiago"),
    ("Quirihue", "CL", "Ñuble", -36.2833, -72.5500, "America/Santiago"),
    ("Valdivia", "CL", "Los Ríos", -39.8142, -73.2459, "America/Santiago"),
    ("La Unión", "CL", "Los Ríos", -40.2931, -73.0817, "America/Santiago"),
    ("Punta Arenas", "CL", "Magallanes", -53.1638, -70.9171, "America/Santiago"),
    ("Puerto Natales", "CL", "Magallanes", -51.7292, -72.4875, "America/Santiago"),
    ("Porvenir", "CL", "Magallanes", -53.2833, -70.3667, "America/Santiago"),
    ("Puerto Williams", "CL", "Magallanes", -54.9333, -67.6167, "America/Santiago"),
    ("Arica", "CL", "Arica y Parinacota", -18.4783, -70.3126, "America/Santiago"),
    ("Putre", "CL", "Arica y Parinacota", -18.1964, -69.5594, "America/Santiago"),
    ("Coyhaique", "CL", "Aysén", -45.5752, -72.0662, "America/Santiago"),
    ("Puerto Aysén", "CL", "Aysén", -45.4000, -72.6833, "America/Santiago"),
    ("Cochrane", "CL", "Aysén", -47.2500, -72.5667, "America/Santiago"),
    ("Chile Chico", "CL", "Aysén", -46.5500, -71.7333, "America/Santiago"),
    # Switzerland, added with the jobup_ch source (2026-11-20). jobup.ch
    # publishes "<town>; <canton>; CH", but the board's addressLocality is
    # often absent and its addressRegion can hold a town, an internal
    # "EMEA > CHE > ..." path or prose. Before this ref.cities held exactly
    # one Swiss city ("Zurich"), so every Swiss posting resolved to
    # country-only. Regions match ref.regions exactly (seed/regions.py
    # _CH_CANTONS); the resolver matches them case-insensitively and a wrong
    # region would be invisible once cached, so only well-known town/canton
    # pairs are listed, and towns that exist in two cantons (Aesch, Buchs,
    # Gossau, Reinach) are deliberately left out -- the resolver treats two
    # rows with the same name as ambiguous and would match neither.
    ("Zürich", "CH", "Zürich", 47.3769, 8.5417, "Europe/Zurich"),
    ("Le Mont-sur-Lausanne", "CH", "Vaud", 46.5567, 6.6342, "Europe/Zurich"),
    ("Crissier", "CH", "Vaud", 46.5500, 6.5833, "Europe/Zurich"),
    ("Cully", "CH", "Vaud", 46.4833, 6.7333, "Europe/Zurich"),
    ("Grand-Lancy", "CH", "Genève", 46.1667, 6.1167, "Europe/Zurich"),
    ("Lenzburg", "CH", "Aargau", 47.3883, 8.1750, "Europe/Zurich"),
    ("Bienne", "CH", "Bern", 47.1368, 7.2467, "Europe/Zurich"),
    ("Winterthur", "CH", "Zürich", 47.5001, 8.7500, "Europe/Zurich"),
    ("Uster", "CH", "Zürich", 47.3500, 8.7167, "Europe/Zurich"),
    ("Dübendorf", "CH", "Zürich", 47.3972, 8.6186, "Europe/Zurich"),
    ("Dietikon", "CH", "Zürich", 47.4017, 8.4000, "Europe/Zurich"),
    ("Wetzikon", "CH", "Zürich", 47.3261, 8.7975, "Europe/Zurich"),
    ("Thalwil", "CH", "Zürich", 47.2917, 8.5667, "Europe/Zurich"),
    ("Kloten", "CH", "Zürich", 47.4515, 8.5847, "Europe/Zurich"),
    ("Schlieren", "CH", "Zürich", 47.3969, 8.4472, "Europe/Zurich"),
    ("Regensdorf", "CH", "Zürich", 47.4333, 8.4667, "Europe/Zurich"),
    ("Rümlang", "CH", "Zürich", 47.4500, 8.5333, "Europe/Zurich"),
    ("Bern", "CH", "Bern", 46.9480, 7.4474, "Europe/Zurich"),
    ("Biel", "CH", "Bern", 47.1368, 7.2467, "Europe/Zurich"),
    ("Thun", "CH", "Bern", 46.7580, 7.6280, "Europe/Zurich"),
    ("Burgdorf", "CH", "Bern", 47.0594, 7.6264, "Europe/Zurich"),
    ("Interlaken", "CH", "Bern", 46.6863, 7.8632, "Europe/Zurich"),
    ("Belp", "CH", "Bern", 46.8917, 7.4972, "Europe/Zurich"),
    ("Spiez", "CH", "Bern", 46.6847, 7.6797, "Europe/Zurich"),
    ("Luzern", "CH", "Luzern", 47.0502, 8.3093, "Europe/Zurich"),
    ("Kriens", "CH", "Luzern", 47.0333, 8.2833, "Europe/Zurich"),
    ("Emmen", "CH", "Luzern", 47.0781, 8.2761, "Europe/Zurich"),
    ("Weggis", "CH", "Luzern", 47.0319, 8.4331, "Europe/Zurich"),
    ("Altdorf", "CH", "Uri", 46.8804, 8.6444, "Europe/Zurich"),
    ("Schwyz", "CH", "Schwyz", 47.0208, 8.6536, "Europe/Zurich"),
    ("Lachen", "CH", "Schwyz", 47.1917, 8.8542, "Europe/Zurich"),
    ("Einsiedeln", "CH", "Schwyz", 47.1275, 8.7469, "Europe/Zurich"),
    ("Sarnen", "CH", "Obwalden", 46.8958, 8.2456, "Europe/Zurich"),
    ("Stans", "CH", "Nidwalden", 46.9581, 8.3661, "Europe/Zurich"),
    ("Glarus", "CH", "Glarus", 47.0402, 9.0689, "Europe/Zurich"),
    ("Zug", "CH", "Zug", 47.1662, 8.5155, "Europe/Zurich"),
    ("Baar", "CH", "Zug", 47.1953, 8.5294, "Europe/Zurich"),
    ("Cham", "CH", "Zug", 47.1822, 8.4619, "Europe/Zurich"),
    ("Steinhausen", "CH", "Zug", 47.1936, 8.4850, "Europe/Zurich"),
    ("Fribourg", "CH", "Fribourg", 46.8065, 7.1620, "Europe/Zurich"),
    ("Bulle", "CH", "Fribourg", 46.6189, 7.0572, "Europe/Zurich"),
    ("Solothurn", "CH", "Solothurn", 47.2088, 7.5323, "Europe/Zurich"),
    ("Olten", "CH", "Solothurn", 47.3513, 7.9045, "Europe/Zurich"),
    ("Grenchen", "CH", "Solothurn", 47.1925, 7.3950, "Europe/Zurich"),
    ("Bellach", "CH", "Solothurn", 47.2131, 7.5000, "Europe/Zurich"),
    ("Biberist", "CH", "Solothurn", 47.1828, 7.5633, "Europe/Zurich"),
    ("Basel", "CH", "Basel-Stadt", 47.5596, 7.5886, "Europe/Zurich"),
    ("Riehen", "CH", "Basel-Stadt", 47.5786, 7.5775, "Europe/Zurich"),
    ("Liestal", "CH", "Basel-Landschaft", 47.4844, 7.7356, "Europe/Zurich"),
    ("Allschwil", "CH", "Basel-Landschaft", 47.5500, 7.5333, "Europe/Zurich"),
    ("Muttenz", "CH", "Basel-Landschaft", 47.5228, 7.6425, "Europe/Zurich"),
    ("Pratteln", "CH", "Basel-Landschaft", 47.5208, 7.6931, "Europe/Zurich"),
    ("Schaffhausen", "CH", "Schaffhausen", 47.6974, 8.6346, "Europe/Zurich"),
    ("Herisau", "CH", "Appenzell Ausserrhoden", 47.3867, 9.2792, "Europe/Zurich"),
    ("Appenzell", "CH", "Appenzell Innerrhoden", 47.3303, 9.4097, "Europe/Zurich"),
    ("St. Gallen", "CH", "St. Gallen", 47.4245, 9.3767, "Europe/Zurich"),
    ("Wil", "CH", "St. Gallen", 47.4622, 9.0456, "Europe/Zurich"),
    ("Altstätten", "CH", "St. Gallen", 47.3789, 9.5444, "Europe/Zurich"),
    ("Rapperswil-Jona", "CH", "St. Gallen", 47.2267, 8.8183, "Europe/Zurich"),
    ("Chur", "CH", "Graubünden", 46.8499, 9.5329, "Europe/Zurich"),
    ("Ilanz", "CH", "Graubünden", 46.7742, 9.2042, "Europe/Zurich"),
    ("Davos", "CH", "Graubünden", 46.8027, 9.8360, "Europe/Zurich"),
    ("St. Moritz", "CH", "Graubünden", 46.4908, 9.8355, "Europe/Zurich"),
    ("Aarau", "CH", "Aargau", 47.3925, 8.0444, "Europe/Zurich"),
    ("Baden", "CH", "Aargau", 47.4733, 8.3061, "Europe/Zurich"),
    ("Wettingen", "CH", "Aargau", 47.4664, 8.3267, "Europe/Zurich"),
    ("Niederlenz", "CH", "Aargau", 47.3956, 8.1819, "Europe/Zurich"),
    ("Zetzwil", "CH", "Aargau", 47.3125, 8.1561, "Europe/Zurich"),
    ("Frauenfeld", "CH", "Thurgau", 47.5575, 8.8975, "Europe/Zurich"),
    ("Kreuzlingen", "CH", "Thurgau", 47.6500, 9.1750, "Europe/Zurich"),
    ("Amriswil", "CH", "Thurgau", 47.5456, 9.2961, "Europe/Zurich"),
    ("Weinfelden", "CH", "Thurgau", 47.5667, 9.1000, "Europe/Zurich"),
    ("Lugano", "CH", "Ticino", 46.0037, 8.9511, "Europe/Zurich"),
    ("Bellinzona", "CH", "Ticino", 46.1950, 9.0244, "Europe/Zurich"),
    ("Locarno", "CH", "Ticino", 46.1700, 8.8000, "Europe/Zurich"),
    ("Mendrisio", "CH", "Ticino", 45.8704, 8.9827, "Europe/Zurich"),
    ("Lausanne", "CH", "Vaud", 46.5197, 6.6323, "Europe/Zurich"),
    ("Nyon", "CH", "Vaud", 46.3833, 6.2333, "Europe/Zurich"),
    ("Vevey", "CH", "Vaud", 46.4628, 6.8419, "Europe/Zurich"),
    ("Morges", "CH", "Vaud", 46.5100, 6.4986, "Europe/Zurich"),
    ("Yverdon-les-Bains", "CH", "Vaud", 46.7785, 6.6412, "Europe/Zurich"),
    ("Renens", "CH", "Vaud", 46.5394, 6.5889, "Europe/Zurich"),
    ("Montreux", "CH", "Vaud", 46.4312, 6.9107, "Europe/Zurich"),
    ("Etagnières", "CH", "Vaud", 46.5906, 6.5667, "Europe/Zurich"),
    ("Sion", "CH", "Valais", 46.2333, 7.3667, "Europe/Zurich"),
    ("Sierre", "CH", "Valais", 46.2919, 7.5356, "Europe/Zurich"),
    ("Brig", "CH", "Valais", 46.3167, 7.9833, "Europe/Zurich"),
    ("Martigny", "CH", "Valais", 46.1000, 7.0667, "Europe/Zurich"),
    ("Visp", "CH", "Valais", 46.2933, 7.8814, "Europe/Zurich"),
    ("Neuchâtel", "CH", "Neuchâtel", 46.9926, 6.9313, "Europe/Zurich"),
    ("La Chaux-de-Fonds", "CH", "Neuchâtel", 47.0999, 6.8250, "Europe/Zurich"),
    ("Le Locle", "CH", "Neuchâtel", 47.0567, 6.7506, "Europe/Zurich"),
    ("Genève", "CH", "Genève", 46.2044, 6.1432, "Europe/Zurich"),
    ("Geneva", "CH", "Genève", 46.2044, 6.1432, "Europe/Zurich"),
    ("Carouge", "CH", "Genève", 46.1833, 6.1333, "Europe/Zurich"),
    ("Vernier", "CH", "Genève", 46.2167, 6.1000, "Europe/Zurich"),
    ("Meyrin", "CH", "Genève", 46.2333, 6.0833, "Europe/Zurich"),
    ("Delémont", "CH", "Jura", 47.3667, 7.3333, "Europe/Zurich"),
    ("Porrentruy", "CH", "Jura", 47.4167, 7.0833, "Europe/Zurich"),
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
