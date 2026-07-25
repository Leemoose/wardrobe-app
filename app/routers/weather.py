"""Weather router - current weather and outfit suggestions."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter

from app.db import get_db, get_setting, get_categories, outfit_to_dict
from app.weather import fetch_weather, season_for, season_for_month

router = APIRouter(tags=["weather"])


@router.get("/weather")
async def get_weather():
    """Get current weather and calculated season."""
    with get_db() as db:
        lat = get_setting(db, "latitude")
        lon = get_setting(db, "longitude")
        location_name = get_setting(db, "location_name")
        bands = get_setting(db, "season_temp_bands")

    try:
        weather = await fetch_weather(lat, lon)
        season = season_for(date.today(), weather.get("high_f"), bands)

        return {
            "location_name": location_name,
            "temp_f": weather["temp_f"],
            "feels_like_f": weather["feels_like_f"],
            "high_f": weather["high_f"],
            "low_f": weather["low_f"],
            "precip_prob": weather["precip_prob"],
            "description": weather["description"],
            "season": season,
        }
    except Exception as e:
        # Fallback to month-based season on upstream failure
        season = season_for_month(date.today().month)
        return {
            "error": str(e),
            "season": season,
        }


@router.get("/suggest")
async def suggest_outfits(vibe: Optional[str] = None, include_recent: bool = False):
    """
    Suggest outfits based on current weather and optional vibe.

    Query params:
    - vibe: Filter by vibe tag
    - include_recent: If false (default), exclude outfits worn within no_repeat_days
    """
    with get_db() as db:
        lat = get_setting(db, "latitude")
        lon = get_setting(db, "longitude")
        bands = get_setting(db, "season_temp_bands")
        no_repeat_days = get_setting(db, "no_repeat_days") or 0
        weather_rules = get_setting(db, "weather_rules") or {}

        # Determine season
        weather = None
        weather_succeeded = False
        try:
            weather = await fetch_weather(lat, lon)
            season = season_for(date.today(), weather.get("high_f"), bands)
            weather_succeeded = True
        except Exception:
            season = season_for_month(date.today().month)

        # Get recently worn outfit_ids if no_repeat_days > 0
        recently_worn_ids = set()
        if no_repeat_days > 0 and not include_recent:
            cutoff_date = (date.today() - timedelta(days=no_repeat_days)).isoformat()
            recent_rows = db.execute(
                """SELECT DISTINCT outfit_id FROM wear_events
                   WHERE outfit_id IS NOT NULL AND date > ?""",
                (cutoff_date,)
            ).fetchall()
            recently_worn_ids = {row["outfit_id"] for row in recent_rows}

        # Per-category rest days (e.g. shoes rest 1 day between wears).
        # Hidden outfits are counted separately; include_recent overrides.
        rest_map = {
            c["name"].lower(): c["rest_days"]
            for c in get_categories(db)
            if c.get("rest_days", 0) > 0
        }
        today = date.today()

        # Vacation mode: if a trip is active, only suggest outfits made
        # entirely of packed items.
        active_trip = None
        trip_item_ids = None
        trip_row = db.execute(
            "SELECT * FROM trips WHERE status = 'active' LIMIT 1"
        ).fetchone()
        if trip_row:
            active_trip = {
                "id": trip_row["id"],
                "name": trip_row["name"],
                "destination": trip_row["destination"],
                "start_date": trip_row["start_date"],
                "end_date": trip_row["end_date"],
            }
            trip_item_ids = {
                r["item_id"]
                for r in db.execute(
                    "SELECT item_id FROM trip_items WHERE trip_id = ?",
                    (trip_row["id"],),
                ).fetchall()
            }

        # Get active outfits
        rows = db.execute(
            "SELECT * FROM outfits WHERE status = 'active' ORDER BY created_at DESC"
        ).fetchall()

        matching = []
        hidden_recent = 0
        hidden_trip = 0
        hidden_rest = 0

        for row in rows:
            outfit = outfit_to_dict(db, row)

            # Vacation mode filter: every item must be in the trip's packing list
            if trip_item_ids is not None:
                outfit_item_ids = {i["id"] for i in outfit.get("items", [])}
                if not outfit_item_ids or not outfit_item_ids <= trip_item_ids:
                    hidden_trip += 1
                    continue

            # Must be available
            if not outfit["available"]:
                continue

            # Season filter: match if season in tags OR empty tags
            outfit_seasons = outfit["season_tags"]
            if outfit_seasons and season not in outfit_seasons:
                continue

            # Vibe filter: match if no vibe given OR vibe in tags OR empty tags
            if vibe:
                outfit_vibes = outfit["vibe_tags"]
                if outfit_vibes and vibe not in outfit_vibes:
                    continue

            # Check if recently worn
            if outfit["id"] in recently_worn_ids:
                hidden_recent += 1
                continue

            # Rest-day filter: hide outfits containing an item whose category
            # needs more rest since its last wear (unless include_recent)
            if rest_map and not include_recent:
                if _needs_rest(outfit.get("items", []), rest_map, today):
                    hidden_rest += 1
                    continue

            # Compute warnings (only if weather succeeded)
            warnings = []
            if weather_succeeded and weather:
                warnings = _compute_warnings(outfit, weather, weather_rules)

            outfit["warnings"] = warnings
            matching.append(outfit)

        # Sort: warning-free outfits first, preserve existing order otherwise
        matching.sort(key=lambda o: (len(o["warnings"]) > 0,))

        return {
            "season": season,
            "weather": weather,
            "hidden_recent": hidden_recent,
            "hidden_trip": hidden_trip,
            "hidden_rest": hidden_rest,
            "active_trip": active_trip,
            "outfits": matching,
        }


def _needs_rest(items: list, rest_map: dict, today: date) -> bool:
    """True if any item's category still needs rest since its last wear."""
    for item in items:
        rest_days = rest_map.get((item.get("category") or "").lower())
        if not rest_days:
            continue
        last_worn = item.get("last_worn")
        if not last_worn:
            continue
        try:
            days_since = (today - date.fromisoformat(str(last_worn)[:10])).days
        except ValueError:
            continue
        if days_since <= rest_days:
            return True
    return False


def _compute_warnings(outfit: dict, weather: dict, rules: dict) -> list:
    """
    Compute weather-based warnings for an outfit.

    Returns a list of warning strings.
    """
    warnings = []

    rain_threshold = rules.get("rain_precip_threshold", 50)
    outerwear_below_f = rules.get("outerwear_below_f", 50)
    no_outerwear_above_f = rules.get("no_outerwear_above_f", 75)
    sensitive_materials = rules.get("sensitive_materials", ["suede", "leather"])

    precip_prob = weather.get("precip_prob") or 0
    feels_like_f = weather.get("feels_like_f")
    high_f = weather.get("high_f")

    items = outfit.get("items", [])

    # (a) Rain risk: precip >= threshold AND item has sensitive material
    if precip_prob >= rain_threshold:
        for item in items:
            # Check care_notes and name for sensitive materials
            care_notes = (item.get("care_notes") or "").lower()
            item_name = (item.get("name") or "").lower()
            text_to_check = care_notes + " " + item_name

            for material in sensitive_materials:
                if material.lower() in text_to_check:
                    warnings.append(f"Rain risk: {item.get('name', 'Unknown item')}")
                    break  # Only one warning per item

    # (b) Cold today: min(feels_like_f, high_f) <= outerwear_below_f AND no outerwear
    if feels_like_f is not None and high_f is not None:
        cold_temp = min(feels_like_f, high_f)
        if cold_temp <= outerwear_below_f:
            has_outerwear = any(
                (item.get("category") or "").lower() == "outerwear"
                for item in items
            )
            if not has_outerwear:
                warnings.append("Cold today - consider a layer")

    # (c) Too warm: high_f >= no_outerwear_above_f AND has outerwear
    if high_f is not None and high_f >= no_outerwear_above_f:
        has_outerwear = any(
            (item.get("category") or "").lower() == "outerwear"
            for item in items
        )
        if has_outerwear:
            warnings.append("May be too warm - includes outerwear")

    return warnings
