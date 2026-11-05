"""In / Out decision from latitude / longitude (with address-text fallback).

"In"  = inside ONE of three city areas: Dhaka city, Gazipur city, Narayanganj city.
"Out" = anywhere else.

Every answer carries a `sure` flag. When the point is close to the edge of the In-area (within
NEAR_KM) or the coordinates disagree / are missing, `sure` is False and the internal report shows the
cell in yellow so a person checks it.

The outlines are approximations drawn from public maps (city-corporation areas). If the bank's own
In/Out list shows a different edge, edit the polygons below (lat, lon pairs, in order) or use the
file  ~/.verify_report_builder/areas.json  ({"Dhaka": [[lat, lon], ...], ...}) - it replaces the built-in outline.
"""
from __future__ import annotations

import json
import math
import re

from . import config

# (lat, lon) outlines
DHAKA_POLYGON = [
    (23.905, 90.375), (23.905, 90.420), (23.885, 90.455), (23.835, 90.465),
    (23.800, 90.462), (23.765, 90.480), (23.745, 90.508), (23.715, 90.518),
    (23.695, 90.512), (23.688, 90.470), (23.688, 90.430), (23.698, 90.395), (23.712, 90.368),
    (23.740, 90.338), (23.790, 90.333), (23.840, 90.333), (23.875, 90.348),
]
# Gazipur City Corporation: Tongi - Board Bazar - Joydebpur - Chandana - Konabari - Pubail (approx.)
GAZIPUR_POLYGON = [
    (23.905, 90.372), (23.905, 90.425), (23.925, 90.470), (23.965, 90.495), (24.030, 90.490),
    (24.085, 90.455), (24.095, 90.395), (24.075, 90.335), (24.025, 90.310), (23.965, 90.330),
    (23.925, 90.350),
]
# Narayanganj City Corporation: Siddhirganj - Narayanganj Sadar - Fatullah - Bandar (approx.)
NARAYANGANJ_POLYGON = [
    (23.700, 90.505), (23.698, 90.535), (23.665, 90.548), (23.612, 90.540), (23.592, 90.508),
    (23.600, 90.468), (23.640, 90.452), (23.688, 90.458),
]
AREAS = {"Dhaka": DHAKA_POLYGON, "Gazipur": GAZIPUR_POLYGON, "Narayanganj": NARAYANGANJ_POLYGON}


def _load_user_areas() -> dict:
    try:
        raw = json.loads((config.SETTINGS_DIR / "areas.json").read_text(encoding="utf-8"))
        out = {}
        for name, pts in raw.items():
            poly = [(float(a), float(b)) for a, b in pts]
            if len(poly) >= 3:
                out[str(name)] = poly
        return out
    except Exception:
        return {}


NEAR_KM = 2.0           # closer to the edge than this = "not sure"
BD_BOX = (20.5, 26.8, 88.0, 92.8)   # lat_min, lat_max, lon_min, lon_max (valid Bangladesh coordinates)

_IN_WORDS = (
    "gulshan", "banani", "baridhara", "uttara", "mirpur", "mohammadpur", "dhanmondi", "motijheel",
    "farmgate", "tejgaon", "badda", "rampura", "khilgaon", "malibagh", "mogbazar", "shantinagar", "paltan",
    "bashundhara", "khilkhet", "mohakhali", "kawran", "kafrul", "pallabi", "shyamoli", "adabor", "kalabagan",
    "lalmatia", "jatrabari", "demra", "sabujbagh", "shahbagh", "azimpur", "lalbagh", "hazaribagh", "wari",
    "old dhaka", "joydebpur", "joydevpur", "board bazar", "konabari", "siddhirganj", "fatullah", "chashara", "sutrapur", "gendaria", "tikatuly", "ramna", "segunbagicha", "bangshal", "newmarket",
    "elephant road", "kamalapur", "mugda", "basabo", "shahjahanpur", "banasree", "aftabnagar", "nikunja",
    "cantonment", "airport", "turag", "dakshinkhan", "uttarkhan", "vatara", "satarkul", "tejkunipara",
)
_OUT_WORDS = (
    "gazipur", "narayanganj", "savar", "ashulia", "keraniganj", "narsingdi", "munshiganj", "manikganj",
    "chattogram", "chittagong", "sylhet", "rajshahi", "khulna", "barishal", "barisal", "rangpur", "mymensingh",
    "comilla", "cumilla", "bogura", "bogra", "jessore", "jashore", "cox", "dinajpur", "tangail", "faridpur",
    "kishoreganj", "narail", "pabna", "kushtia", "noakhali", "feni", "brahmanbaria", "habiganj", "gopalganj",
    "madaripur", "shariatpur", "jamalpur", "netrokona", "sherpur", "tarakandi", "purbachal", "rupganj",
    "sonargaon", "bandar", "kaliakoir", "dhamrai", "nabinagar", "araihazar", "sreepur", "kapasia",
)


def valid_coord(lat, lon) -> bool:
    if lat is None or lon is None:
        return False
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return BD_BOX[0] <= lat <= BD_BOX[1] and BD_BOX[2] <= lon <= BD_BOX[3]


def _xy(lat: float, lon: float, lat0: float = 23.78):
    """Local flat km coordinates (good enough for a ~40 km area)."""
    return (lon * 111.32 * math.cos(math.radians(lat0)), lat * 110.57)


def _inside(px, py, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > py) != (y2 > py) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _dist_seg(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _in_any(lat: float, lon: float, polys) -> str | None:
    px, py = _xy(lat, lon)
    for name, poly in polys:
        if _inside(px, py, poly):
            return name
    return None


def classify_point(lat: float, lon: float) -> tuple[str, bool, str]:
    """-> ("In"/"Out", sure, city name or "").

    A point is "sure" only if eight points on a NEAR_KM circle around it fall on the same side, so the
    shared border between two neighbouring In-cities does not cause a false doubt.
    """
    areas = dict(AREAS)
    areas.update(_load_user_areas())
    polys = [(n, [_xy(a, o) for a, o in p]) for n, p in areas.items()]
    here = _in_any(lat, lon, polys)
    dlat = NEAR_KM / 110.57
    dlon = NEAR_KM / (111.32 * math.cos(math.radians(lat)))
    same = True
    for k in range(8):
        ang = math.radians(45 * k)
        other = _in_any(lat + dlat * math.sin(ang), lon + dlon * math.cos(ang), polys)
        if (other is None) != (here is None):
            same = False
            break
    return ("In" if here else "Out"), same, here or ""


def _word_hit(text: str, words) -> bool:
    return any(re.search(r"\b" + re.escape(w) + r"\b", text) for w in words)


def classify_text(*texts: str) -> str | None:
    """Address words -> "In"/"Out"/None (only a hint, always unsure)."""
    t = " ".join(x for x in texts if x).lower()
    if not t.strip():
        return None
    out, inn = _word_hit(t, _OUT_WORDS), _word_hit(t, _IN_WORDS)
    if out and not inn:
        return "Out"
    if inn and not out:
        return "In"
    return None


def trip_area(trip: dict) -> tuple[str, bool, str]:
    """Decide In/Out for one trip -> (area, sure, why).

    Uses the address coordinates first, then the end-of-visit coordinates, then text.
    """
    cands = []
    for lat, lon, label in ((trip.get("lat"), trip.get("lon"), "address"),
                            (trip.get("end_lat"), trip.get("end_lon"), "visit")):
        if valid_coord(lat, lon):
            area, sure, city = classify_point(float(lat), float(lon))
            cands.append((area, sure, label, city))
    text_hint = classify_text(trip.get("address", ""), trip.get("exact_address", ""),
                              trip.get("area", ""), trip.get("place_name", ""))
    if cands:
        area, sure, label, city = cands[0]
        why = f"লাট-লং ({label})" + (f" - {city}" if city else "")
        if len(cands) > 1 and cands[1][0] != area:
            return area, False, "ঠিকানা ও ভিজিটের স্থানাঙ্ক আলাদা"
        if not sure:
            why = "সীমানার কাছাকাছি"
        elif text_hint and text_hint != area:
            return area, False, "স্থানাঙ্ক ও ঠিকানার লেখা মেলেনি"
        return area, sure, why
    if text_hint:
        return text_hint, False, "শুধু ঠিকানার লেখা"
    return "In", False, "স্থানাঙ্ক ও ঠিকানা নেই"
