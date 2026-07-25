"""Trips router - packing lists and vacation mode.

A trip has a destination, dates, and a packing list (items with packed
checkboxes, optionally grouped via linked outfits). Exactly one trip can be
"active" at a time: while active, the whole app (suggestions, closet,
outfits) filters down to packed-for-trip items - vacation mode.
"""
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request

from app.db import (
    get_db,
    get_setting,
    get_categories,
    item_to_dict,
    outfit_to_dict,
)
from app.weather import (
    fetch_forecast_range,
    geocode,
    season_for,
    season_for_month,
    MAX_FORECAST_DAYS_AHEAD,
)

router = APIRouter(tags=["trips"])

MAX_TRIP_DAYS = 30
MAX_SUGGESTED_OUTFITS = 14

# Weather codes meaning "sunny enough for sunglasses" (clear / partly cloudy)
SUNNY_CODES = {0, 1, 2}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_dates(start_date: str, end_date: str):
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError):
        raise HTTPException(400, "start_date and end_date must be ISO dates (YYYY-MM-DD)")
    if end < start:
        raise HTTPException(400, "end_date must be on or after start_date")
    if (end - start).days + 1 > MAX_TRIP_DAYS:
        raise HTTPException(400, f"Trips are capped at {MAX_TRIP_DAYS} days")
    return start, end


def _get_trip_row(db, trip_id: int):
    row = db.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Trip not found")
    return row


def _trip_items(db, trip_id: int) -> list:
    rows = db.execute(
        """SELECT i.*, ti.packed, ti.source FROM items i
           JOIN trip_items ti ON ti.item_id = i.id
           WHERE ti.trip_id = ? ORDER BY i.category, i.number""",
        (trip_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        packed = d.pop("packed", 0)
        source = d.pop("source", "manual")
        item = item_to_dict_from_joined(d, db)
        item["packed"] = bool(packed)
        item["source"] = source
        result.append(item)
    return result


def item_to_dict_from_joined(d: dict, db) -> dict:
    """Like item_to_dict but for an already-dict row (from a JOIN)."""
    import json as _json

    d = dict(d)
    d["season_tags"] = _json.loads(d["season_tags"]) if isinstance(d["season_tags"], str) else d["season_tags"]
    d["vibe_tags"] = _json.loads(d["vibe_tags"]) if isinstance(d["vibe_tags"], str) else d["vibe_tags"]
    if "lifecycle" not in d or d["lifecycle"] is None:
        d["lifecycle"] = "active"
    photo_rows = db.execute(
        "SELECT id, filename FROM item_photos WHERE item_id = ? ORDER BY sort, id",
        (d["id"],),
    ).fetchall()
    d["photos"] = [{"id": p["id"], "url": f"/photos/{p['filename']}"} for p in photo_rows]
    return d


def _trip_outfits(db, trip_id: int) -> list:
    rows = db.execute(
        """SELECT o.* FROM outfits o
           JOIN trip_outfits t ON t.outfit_id = o.id
           WHERE t.trip_id = ? ORDER BY o.name""",
        (trip_id,),
    ).fetchall()
    return [outfit_to_dict(db, row) for row in rows]


def _trip_to_dict(db, row, include_detail: bool = False) -> dict:
    d = dict(row)
    counts = db.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(packed), 0) AS packed "
        "FROM trip_items WHERE trip_id = ?",
        (d["id"],),
    ).fetchone()
    d["item_count"] = counts["total"]
    d["packed_count"] = counts["packed"]
    start = date.fromisoformat(d["start_date"])
    end = date.fromisoformat(d["end_date"])
    d["num_days"] = (end - start).days + 1
    if include_detail:
        d["items"] = _trip_items(db, d["id"])
        d["outfits"] = _trip_outfits(db, d["id"])
    return d


async def _trip_forecast(trip: dict) -> tuple:
    """Return (forecast_days_or_None, note)."""
    lat, lon = trip.get("latitude"), trip.get("longitude")
    if lat is None or lon is None:
        return None, "No destination coordinates - set a destination to get a forecast"
    try:
        days = await fetch_forecast_range(lat, lon, trip["start_date"], trip["end_date"])
    except Exception as e:
        return None, f"Forecast unavailable: {e}"
    if days is None:
        return None, (
            f"Trip is beyond the {MAX_FORECAST_DAYS_AHEAD}-day forecast window - "
            "using calendar season instead"
        )
    note = ""
    start = date.fromisoformat(trip["start_date"])
    end = date.fromisoformat(trip["end_date"])
    if len(days) < (end - start).days + 1:
        note = "Partial forecast - remaining days use calendar season"
    return days, note


def _day_seasons(trip: dict, forecast, bands) -> set:
    """Season per trip day, from forecast where available else calendar."""
    start = date.fromisoformat(trip["start_date"])
    end = date.fromisoformat(trip["end_date"])
    by_date = {d["date"]: d for d in (forecast or [])}
    seasons = set()
    cur = start
    while cur <= end:
        f = by_date.get(cur.isoformat())
        if f and f.get("high_f") is not None:
            seasons.add(season_for(cur, f["high_f"], bands))
        else:
            seasons.add(season_for_month(cur.month))
        cur += timedelta(days=1)
    return seasons


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

@router.get("/trips/geocode")
async def geocode_destination(q: str):
    """Look up destination candidates by name."""
    if not q or not q.strip():
        raise HTTPException(400, "q is required")
    try:
        results = await geocode(q.strip())
    except Exception as e:
        raise HTTPException(502, f"Geocoding failed: {e}")
    return {"results": results}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("/trips")
def list_trips():
    """All trips, active first, then by start date descending."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM trips ORDER BY (status = 'active') DESC, start_date DESC"
        ).fetchall()
        return [_trip_to_dict(db, row) for row in rows]


@router.get("/trips/active")
def get_active_trip():
    """The currently active trip (vacation mode), with packed item ids."""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM trips WHERE status = 'active' LIMIT 1"
        ).fetchone()
        if row is None:
            return {"active": None}
        trip = _trip_to_dict(db, row)
        item_rows = db.execute(
            "SELECT item_id FROM trip_items WHERE trip_id = ?", (trip["id"],)
        ).fetchall()
        trip["item_ids"] = [r["item_id"] for r in item_rows]
        return {"active": trip}


@router.post("/trips")
async def create_trip(request: Request):
    """
    Create a trip. Body: name, start_date, end_date, destination (optional),
    latitude/longitude (optional - geocoded from destination when omitted).
    """
    data = await request.json()
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    _validate_dates(data.get("start_date"), data.get("end_date"))

    destination = (data.get("destination") or "").strip()
    lat = data.get("latitude")
    lon = data.get("longitude")

    # Geocode destination if coordinates not supplied
    geocode_note = ""
    if destination and (lat is None or lon is None):
        try:
            candidates = await geocode(destination, count=1)
            if candidates:
                lat = candidates[0]["latitude"]
                lon = candidates[0]["longitude"]
                parts = [candidates[0]["name"], candidates[0]["admin1"], candidates[0]["country"]]
                geocode_note = ", ".join(p for p in parts if p)
        except Exception:
            pass  # trip still works without coordinates, just no forecast

    with get_db() as db:
        cur = db.execute(
            """INSERT INTO trips (name, destination, latitude, longitude,
                                  start_date, end_date, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                destination,
                lat,
                lon,
                data["start_date"],
                data["end_date"],
                (data.get("notes") or "").strip(),
            ),
        )
        trip = _trip_to_dict(db, _get_trip_row(db, cur.lastrowid), include_detail=True)
        trip["geocode_note"] = geocode_note
        return trip


@router.get("/trips/{trip_id}")
async def get_trip(trip_id: int):
    """Trip detail: packing list, linked outfits, and destination forecast."""
    with get_db() as db:
        trip = _trip_to_dict(db, _get_trip_row(db, trip_id), include_detail=True)
    forecast, note = await _trip_forecast(trip)
    trip["forecast"] = forecast
    trip["forecast_note"] = note
    return trip


@router.patch("/trips/{trip_id}")
async def update_trip(trip_id: int, request: Request):
    """Update trip fields (name, destination, dates, notes)."""
    data = await request.json()
    with get_db() as db:
        row = _get_trip_row(db, trip_id)
        start_date = data.get("start_date", row["start_date"])
        end_date = data.get("end_date", row["end_date"])
        _validate_dates(start_date, end_date)

        destination = data.get("destination", row["destination"])
        lat = data.get("latitude", row["latitude"])
        lon = data.get("longitude", row["longitude"])

    # Re-geocode when destination changed but no explicit coordinates given
    if (
        destination != row["destination"]
        and "latitude" not in data
        and "longitude" not in data
        and (destination or "").strip()
    ):
        try:
            candidates = await geocode(destination.strip(), count=1)
            if candidates:
                lat = candidates[0]["latitude"]
                lon = candidates[0]["longitude"]
        except Exception:
            pass

    with get_db() as db:
        db.execute(
            """UPDATE trips SET name = ?, destination = ?, latitude = ?,
               longitude = ?, start_date = ?, end_date = ?, notes = ?
               WHERE id = ?""",
            (
                (data.get("name", row["name"]) or "").strip() or row["name"],
                destination,
                lat,
                lon,
                start_date,
                end_date,
                data.get("notes", row["notes"]),
                trip_id,
            ),
        )
        return _trip_to_dict(db, _get_trip_row(db, trip_id), include_detail=True)


@router.delete("/trips/{trip_id}")
def delete_trip(trip_id: int):
    """Delete a trip (packing list rows cascade; items are untouched)."""
    with get_db() as db:
        _get_trip_row(db, trip_id)
        db.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
        return {"deleted": trip_id}


# ---------------------------------------------------------------------------
# Vacation mode (activation)
# ---------------------------------------------------------------------------

@router.post("/trips/{trip_id}/activate")
def activate_trip(trip_id: int):
    """Activate vacation mode for this trip (deactivates any other trip)."""
    with get_db() as db:
        _get_trip_row(db, trip_id)
        db.execute(
            "UPDATE trips SET status = 'planning' WHERE status = 'active'"
        )
        db.execute("UPDATE trips SET status = 'active' WHERE id = ?", (trip_id,))
        return _trip_to_dict(db, _get_trip_row(db, trip_id))


@router.post("/trips/{trip_id}/deactivate")
def deactivate_trip(trip_id: int):
    """Turn off vacation mode."""
    with get_db() as db:
        row = _get_trip_row(db, trip_id)
        if row["status"] == "active":
            db.execute(
                "UPDATE trips SET status = 'planning' WHERE id = ?", (trip_id,)
            )
        return _trip_to_dict(db, _get_trip_row(db, trip_id))


# ---------------------------------------------------------------------------
# Packing list - items
# ---------------------------------------------------------------------------

@router.post("/trips/{trip_id}/items")
async def add_trip_items(trip_id: int, request: Request):
    """Add items to the packing list. Body: {item_ids: [...]}"""
    data = await request.json()
    item_ids = data.get("item_ids") or []
    if not isinstance(item_ids, list) or not item_ids:
        raise HTTPException(400, "item_ids must be a non-empty list")
    with get_db() as db:
        _get_trip_row(db, trip_id)
        added = 0
        for item_id in item_ids:
            exists = db.execute(
                "SELECT 1 FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if not exists:
                continue
            cur = db.execute(
                "INSERT OR IGNORE INTO trip_items (trip_id, item_id, source) "
                "VALUES (?, ?, 'manual')",
                (trip_id, item_id),
            )
            added += cur.rowcount
        return {"added": added, "items": _trip_items(db, trip_id)}


@router.delete("/trips/{trip_id}/items/{item_id}")
def remove_trip_item(trip_id: int, item_id: int):
    """Remove an item from the packing list."""
    with get_db() as db:
        _get_trip_row(db, trip_id)
        db.execute(
            "DELETE FROM trip_items WHERE trip_id = ? AND item_id = ?",
            (trip_id, item_id),
        )
        return {"items": _trip_items(db, trip_id)}


@router.patch("/trips/{trip_id}/items/{item_id}")
async def update_trip_item(trip_id: int, item_id: int, request: Request):
    """Toggle packed state. Body: {packed: true/false}"""
    data = await request.json()
    packed = 1 if data.get("packed") else 0
    with get_db() as db:
        _get_trip_row(db, trip_id)
        cur = db.execute(
            "UPDATE trip_items SET packed = ? WHERE trip_id = ? AND item_id = ?",
            (packed, trip_id, item_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Item not on this trip's packing list")
        return {"item_id": item_id, "packed": bool(packed)}


@router.post("/trips/{trip_id}/pack_all")
async def pack_all(trip_id: int, request: Request):
    """Set packed state for every list item. Body: {packed: true/false}"""
    data = await request.json()
    packed = 1 if data.get("packed") else 0
    with get_db() as db:
        _get_trip_row(db, trip_id)
        db.execute(
            "UPDATE trip_items SET packed = ? WHERE trip_id = ?",
            (packed, trip_id),
        )
        return {"items": _trip_items(db, trip_id)}


# ---------------------------------------------------------------------------
# Packing list - outfits
# ---------------------------------------------------------------------------

@router.post("/trips/{trip_id}/outfits")
async def add_trip_outfits(trip_id: int, request: Request):
    """
    Link outfits to the trip and pull their items into the packing list.
    Body: {outfit_ids: [...]}
    """
    data = await request.json()
    outfit_ids = data.get("outfit_ids") or []
    if not isinstance(outfit_ids, list) or not outfit_ids:
        raise HTTPException(400, "outfit_ids must be a non-empty list")
    with get_db() as db:
        _get_trip_row(db, trip_id)
        added_outfits = 0
        for outfit_id in outfit_ids:
            exists = db.execute(
                "SELECT 1 FROM outfits WHERE id = ?", (outfit_id,)
            ).fetchone()
            if not exists:
                continue
            cur = db.execute(
                "INSERT OR IGNORE INTO trip_outfits (trip_id, outfit_id) VALUES (?, ?)",
                (trip_id, outfit_id),
            )
            added_outfits += cur.rowcount
            item_rows = db.execute(
                "SELECT item_id FROM outfit_items WHERE outfit_id = ?", (outfit_id,)
            ).fetchall()
            for r in item_rows:
                db.execute(
                    "INSERT OR IGNORE INTO trip_items (trip_id, item_id, source) "
                    "VALUES (?, ?, 'outfit')",
                    (trip_id, r["item_id"]),
                )
        return {
            "added": added_outfits,
            "items": _trip_items(db, trip_id),
            "outfits": _trip_outfits(db, trip_id),
        }


@router.delete("/trips/{trip_id}/outfits/{outfit_id}")
def remove_trip_outfit(trip_id: int, outfit_id: int):
    """
    Unlink an outfit. Its items are removed too, unless they were added
    manually/automatically or belong to another linked outfit.
    """
    with get_db() as db:
        _get_trip_row(db, trip_id)
        db.execute(
            "DELETE FROM trip_outfits WHERE trip_id = ? AND outfit_id = ?",
            (trip_id, outfit_id),
        )
        # Items still needed by other linked outfits
        still_needed = {
            r["item_id"]
            for r in db.execute(
                """SELECT DISTINCT oi.item_id FROM outfit_items oi
                   JOIN trip_outfits t ON t.outfit_id = oi.outfit_id
                   WHERE t.trip_id = ?""",
                (trip_id,),
            ).fetchall()
        }
        outfit_item_ids = [
            r["item_id"]
            for r in db.execute(
                "SELECT item_id FROM outfit_items WHERE outfit_id = ?", (outfit_id,)
            ).fetchall()
        ]
        for item_id in outfit_item_ids:
            if item_id in still_needed:
                continue
            db.execute(
                """DELETE FROM trip_items
                   WHERE trip_id = ? AND item_id = ? AND source = 'outfit'""",
                (trip_id, item_id),
            )
        return {
            "items": _trip_items(db, trip_id),
            "outfits": _trip_outfits(db, trip_id),
        }


# ---------------------------------------------------------------------------
# Auto-suggest packing list
# ---------------------------------------------------------------------------

@router.post("/trips/{trip_id}/suggest")
async def suggest_packing(trip_id: int):
    """
    Build a weather-aware packing list:
    - one outfit per trip day (capped), chosen to maximize item re-use so
      you pack less
    - weather extras from category affinities (cold days pull scarf/gloves/
      beanie/outerwear, sunny days pull sunglasses/sun hat)
    Existing list entries are kept; suggestions add on top.
    """
    import random

    with get_db() as db:
        trip = _trip_to_dict(db, _get_trip_row(db, trip_id))
        bands = get_setting(db, "season_temp_bands") or {}
        weather_rules = get_setting(db, "weather_rules") or {}
        categories = get_categories(db)

    forecast, forecast_note = await _trip_forecast(trip)
    needed_seasons = _day_seasons(trip, forecast, bands)

    cold_threshold = weather_rules.get("outerwear_below_f", 50)
    cold_trip = any(
        d.get("low_f") is not None and d["low_f"] <= cold_threshold
        for d in (forecast or [])
    ) or ("winter" in needed_seasons)
    sunny_trip = any(
        d.get("weather_code") in SUNNY_CODES for d in (forecast or [])
    ) or ("summer" in needed_seasons)

    with get_db() as db:
        # Already on the list
        existing_item_ids = {
            r["item_id"]
            for r in db.execute(
                "SELECT item_id FROM trip_items WHERE trip_id = ?", (trip_id,)
            ).fetchall()
        }
        linked_outfit_ids = {
            r["outfit_id"]
            for r in db.execute(
                "SELECT outfit_id FROM trip_outfits WHERE trip_id = ?", (trip_id,)
            ).fetchall()
        }

        # Candidate outfits: active, available, season-compatible
        rows = db.execute(
            "SELECT * FROM outfits WHERE status = 'active' ORDER BY created_at DESC"
        ).fetchall()
        candidates = []
        for row in rows:
            if row["id"] in linked_outfit_ids:
                continue
            outfit = outfit_to_dict(db, row)
            if not outfit["available"]:
                continue
            seasons = outfit["season_tags"]
            if seasons and not (set(seasons) & needed_seasons):
                continue
            candidates.append(outfit)

        # Greedy selection maximizing overlap with already-selected items
        target = min(trip["num_days"], MAX_SUGGESTED_OUTFITS)
        target = max(0, target - len(linked_outfit_ids))
        selected = []
        selected_item_ids = set(existing_item_ids)
        random.shuffle(candidates)
        for _ in range(target):
            if not candidates:
                break
            best = max(
                candidates,
                key=lambda o: len(
                    {i["id"] for i in o["items"]} & selected_item_ids
                ),
            )
            candidates.remove(best)
            selected.append(best)
            selected_item_ids |= {i["id"] for i in best["items"]}

        # Persist outfits + their items
        for outfit in selected:
            db.execute(
                "INSERT OR IGNORE INTO trip_outfits (trip_id, outfit_id) VALUES (?, ?)",
                (trip_id, outfit["id"]),
            )
            for item in outfit["items"]:
                db.execute(
                    "INSERT OR IGNORE INTO trip_items (trip_id, item_id, source) "
                    "VALUES (?, ?, 'outfit')",
                    (trip_id, item["id"]),
                )

        # Weather extras from category affinities
        extras_added = []
        wanted_weathers = []
        if cold_trip:
            wanted_weathers.append("cold")
        if sunny_trip:
            wanted_weathers.append("sun")

        current_ids = {
            r["item_id"]
            for r in db.execute(
                "SELECT item_id FROM trip_items WHERE trip_id = ?", (trip_id,)
            ).fetchall()
        }
        # Categories already covered by the list
        covered_categories = {
            r["category"].lower()
            for r in db.execute(
                """SELECT DISTINCT i.category FROM items i
                   JOIN trip_items ti ON ti.item_id = i.id
                   WHERE ti.trip_id = ?""",
                (trip_id,),
            ).fetchall()
        }

        for cat in categories:
            if cat.get("weather") not in wanted_weathers:
                continue
            if cat["name"].lower() in covered_categories:
                continue
            # Prefer clean items; fall back to any active one
            row = db.execute(
                """SELECT * FROM items
                   WHERE LOWER(category) = ? AND lifecycle = 'active'
                   ORDER BY (status = 'clean') DESC, lifetime_wears ASC
                   LIMIT 1""",
                (cat["name"].lower(),),
            ).fetchone()
            if row is None or row["id"] in current_ids:
                continue
            db.execute(
                "INSERT OR IGNORE INTO trip_items (trip_id, item_id, source) "
                "VALUES (?, ?, 'auto')",
                (trip_id, row["id"]),
            )
            extras_added.append({"item": row["name"], "reason": cat["weather"]})

        result = _trip_to_dict(db, _get_trip_row(db, trip_id), include_detail=True)

    result["forecast"] = forecast
    result["forecast_note"] = forecast_note
    result["suggestion_summary"] = {
        "outfits_added": len(selected),
        "seasons": sorted(needed_seasons),
        "cold_trip": cold_trip,
        "sunny_trip": sunny_trip,
        "extras_added": extras_added,
        "forecast_available": forecast is not None,
    }
    return result
