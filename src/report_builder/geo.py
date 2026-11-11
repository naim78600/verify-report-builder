"""In / Out decision from latitude / longitude (with address-text fallback).

"In"  = inside ONE of two city areas: Dhaka City Corporation (DNCC + DSCC) or Chattogram City Corporation.
"Out" = anywhere else (Gazipur, Narayanganj, Savar, Tongi ... are all Out).

Every answer carries a `sure` flag. When the point is close to the edge of the In-area (within
NEAR_KM) or the coordinates disagree / are missing, `sure` is False and the internal report shows the
cell light-blue so a person checks it.

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
    (23.898, 90.372), (23.893, 90.405), (23.872, 90.440), (23.835, 90.465),
    (23.800, 90.462), (23.765, 90.480), (23.745, 90.508), (23.715, 90.518),
    (23.695, 90.512), (23.688, 90.470), (23.688, 90.430), (23.698, 90.395), (23.712, 90.368),
    (23.740, 90.338), (23.790, 90.333), (23.840, 90.333), (23.875, 90.348),
]
# Chattogram City Corporation: Patenga - Halishahar - Agrabad - Kotwali - Bakalia - Chandgaon - Pahartali - Khulshi (approx.)
CHATTOGRAM_POLYGON = [
    (22.225, 91.772), (22.232, 91.812), (22.268, 91.830), (22.305, 91.838), (22.335, 91.848),
    (22.355, 91.878), (22.392, 91.892), (22.425, 91.875), (22.435, 91.822), (22.432, 91.790),
    (22.402, 91.768), (22.350, 91.758), (22.295, 91.758), (22.250, 91.762),
]
AREAS = {"Dhaka": DHAKA_POLYGON, "Chattogram": CHATTOGRAM_POLYGON}


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
    "old dhaka", "sutrapur", "gendaria", "tikatuly", "ramna", "segunbagicha", "bangshal", "newmarket",
    "elephant road", "kamalapur", "mugda", "basabo", "shahjahanpur", "banasree", "aftabnagar", "nikunja",
    "cantonment", "airport", "turag", "dakshinkhan", "uttarkhan", "vatara", "satarkul", "tejkunipara",
    # Chattogram City Corporation
    "agrabad", "pahartali", "khulshi", "kulshi", "halishahar", "patenga", "panchlaish", "chandgaon", "bakalia",
    "kotwali", "double mooring", "nasirabad", "muradpur", "bayazid", "bahaddarhat", "sadarghat", "chawkbazar",
    "andarkilla", "firingi bazar", "jamal khan", "lalkhan bazar", "oxygen", "akbarshah", "baluchara",
)
_OUT_WORDS = (
    "gazipur", "narayanganj", "savar", "ashulia", "keraniganj", "narsingdi", "munshiganj", "manikganj",
    "joydebpur", "joydevpur", "board bazar", "konabari", "siddhirganj", "fatullah", "chashara", "tongi", "sitakunda",
    "hathazari", "raozan", "anwara", "sylhet", "rajshahi", "khulna", "barishal", "barisal", "rangpur", "mymensingh",
    "comilla", "cumilla", "bogura", "bogra", "jessore", "jashore", "cox", "dinajpur", "tangail", "faridpur",
    "kishoreganj", "narail", "pabna", "kushtia", "noakhali", "feni", "brahmanbaria", "habiganj", "gopalganj",
    "madaripur", "shariatpur", "jamalpur", "netrokona", "sherpur", "tarakandi", "purbachal", "rupganj",
    "sonargaon", "kaliakoir", "dhamrai", "nabinagar", "araihazar", "sreepur", "kapasia",
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
        # v6.1: a pin that is In but close to the edge, or whose two points disagree, is Out when the last part of the map
        # address (the administrative area the map itself gives, e.g. "Tongi Paurashava, Gazipur Sadar" or "Washpur, Keraniganj")
        # names a place outside the two cities.  Only the tail is read - a road name such as "Hathazari Road" never decides.
        if area == "In" and (not sure or (len(cands) > 1 and cands[1][0] != area)):
            tail = ", ".join([p.strip() for p in (trip.get("exact_address") or "").split(",") if p.strip()][-2:])
            if classify_text(tail) == "Out":
                return "Out", False, "সীমানার কাছে, ম্যাপের ঠিকানা অনুযায়ী বাইরে (" + tail + ")"
        if len(cands) > 1 and cands[1][0] != area:
            return area, False, "ঠিকানা ও ভিজিটের স্থানাঙ্ক আলাদা"
        if text_hint and text_hint != area:
            # The outlines above are rough, so an address that NAMES a place wins over a pin that lies on or
            # near the edge, and an address that names a place outside the two cities (Keraniganj, Gazipur ...)
            # wins over a pin that merely falls inside the rough Dhaka outline.  Always shown as "not sure".
            if not sure or (area == "In" and text_hint == "Out"):
                return text_hint, False, "ঠিকানার লেখা অনুযায়ী (স্থানাঙ্ক সীমানার কাছে/ভিন্ন)"
            return area, False, "স্থানাঙ্ক ও ঠিকানার লেখা মেলেনি"
        if not sure:
            why = "সীমানার কাছাকাছি"
        return area, sure, why
    if text_hint:
        return text_hint, False, "শুধু ঠিকানার লেখা"
    return "In", False, "স্থানাঙ্ক ও ঠিকানা নেই"
