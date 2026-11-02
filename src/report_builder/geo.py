"""Dhaka In / Out decision from latitude / longitude (with address-text fallback).

"In"  = inside the Dhaka metropolitan area (DNCC + DSCC outline, approximated below).
"Out" = anywhere else.
Every answer carries a `sure` flag. When the point is close to the boundary (within
NEAR_KM) or the coordinates disagree / are missing, `sure` is False and the report
shows the cell in yellow so a person checks it.

The outline is an approximation drawn from public maps; if the bank's own In/Out
list shows a different edge, edit DHAKA_POLYGON below (lat, lon pairs, in order).
"""
from __future__ import annotations

import math
import re

# (lat, lon) - clockwise outline of Dhaka city (Uttara - Demra - Jatrabari - Hazaribagh - Mirpur).
DHAKA_POLYGON = [
    (23.905, 90.375), (23.905, 90.420), (23.885, 90.455), (23.835, 90.465),
    (23.800, 90.462), (23.760, 90.458), (23.730, 90.492), (23.700, 90.502),
    (23.688, 90.470), (23.688, 90.430), (23.698, 90.395), (23.712, 90.368),
    (23.740, 90.338), (23.790, 90.333), (23.840, 90.333), (23.875, 90.348),
]
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
)
_OUT_WORDS = (
    "gazipur", "narayanganj", "savar", "ashulia", "keraniganj", "tongi", "narsingdi", "munshiganj", "manikganj",
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


def classify_point(lat: float, lon: float) -> tuple[str, bool]:
    """-> ("In"/"Out", sure)."""
    poly = [_xy(a, o) for a, o in DHAKA_POLYGON]
    px, py = _xy(lat, lon)
    inside = _inside(px, py, poly)
    d = min(_dist_seg(px, py, *poly[i], *poly[(i + 1) % len(poly)]) for i in range(len(poly)))
    return ("In" if inside else "Out"), d >= NEAR_KM


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
            area, sure = classify_point(float(lat), float(lon))
            cands.append((area, sure, label))
    text_hint = classify_text(trip.get("address", ""), trip.get("exact_address", ""),
                              trip.get("area", ""), trip.get("place_name", ""))
    if cands:
        area, sure, label = cands[0]
        why = f"লাট-লং ({label})"
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
