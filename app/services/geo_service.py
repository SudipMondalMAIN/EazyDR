"""
Simple Haversine-distance based geo filtering. Works fine at Bolpur-launch
scale with a handful of facilities. When scaling to all-India, swap the
`facilities_within_radius` query for a PostGIS ST_DWithin query (see comment
below) — the function signature can stay identical so callers don't change.
"""
import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --- Future PostGIS migration note ---
# Once facility count grows beyond a few thousand, add a `geography(Point,4326)`
# column + GIST index and replace the Python-side filtering in
# facilities/service.py with:
#   SELECT * FROM facilities
#   WHERE ST_DWithin(location, ST_MakePoint(:lng,:lat)::geography, :radius_m)
# This keeps the API contract (lat/lng/radius_km in, list of facilities out)
# unchanged — only the repository implementation changes.
