"""Scents router - the fragrance journal: rate, write notes, and pick a scent.

Two things live here. The journal (every fragrance tried, with a rating and
dated impressions) is the point; the daily suggestion is what the collection
buys you once the journal has some substance in it.
"""
import json
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File

from app.db import (
    CONCENTRATIONS,
    SCENT_STATUSES,
    SILLAGES,
    TIMES_OF_DAY,
    clamp_rating,
    fragrance_to_dict,
    fragrances_to_dicts,
    get_db,
    get_setting,
    normalize_notes,
)
from app.images import delete_photo_files, process_image, save_photo
from app.scents import period_for_hour, rank_fragrances
from app.weather import fetch_weather, season_for, season_for_month

router = APIRouter(tags=["scents"])

# Free-text fields copied straight through from the request body.
_TEXT_FIELDS = ["name", "house", "concentration", "family", "impression", "tried_on"]
_NUMBER_FIELDS = ["longevity_hours", "size_ml", "remaining_ml", "price", "paid_price"]
_LIST_FIELDS = ["notes_top", "notes_heart", "notes_base"]


def _get_scent_or_404(db, scent_id: int):
    row = db.execute("SELECT * FROM fragrances WHERE id = ?", (scent_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Scent not found")
    return row


def _validate_enum(value, allowed, label):
    if value not in allowed:
        raise HTTPException(400, f"{label} must be one of: {', '.join(allowed)}")
    return value


def _number(value, default=0.0):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _recount(db, scent_id: int):
    """Recompute the denormalized wear counters from the journal.

    Cheaper to recompute than to keep three counters correct across every add,
    edit, and delete — the journal for one bottle is a handful of rows.
    """
    row = db.execute(
        """SELECT COUNT(*) AS entries,
                  COALESCE(SUM(sprays), 0) AS sprays,
                  MAX(date) AS last_worn
           FROM fragrance_notes WHERE fragrance_id = ?""",
        (scent_id,),
    ).fetchone()
    # Only entries that actually record a wearing count as wears; a note with
    # zero sprays may just be a shop sample or a second thought about a bottle.
    worn = db.execute(
        "SELECT COUNT(*) AS n, MAX(date) AS last FROM fragrance_notes "
        "WHERE fragrance_id = ? AND sprays > 0",
        (scent_id,),
    ).fetchone()
    db.execute(
        "UPDATE fragrances SET lifetime_wears = ?, lifetime_sprays = ?, last_worn = ? "
        "WHERE id = ?",
        (worn["n"], row["sprays"], worn["last"], scent_id),
    )


# --------------------------------------------------------------- suggestions
# Declared before /scents/{scent_id}: the path param is an int, so a literal
# segment reaching the typed route would 422 instead of matching.


@router.get("/scents/suggest")
async def suggest_scents(occasion: Optional[str] = None,
                         time_of_day: Optional[str] = None,
                         limit: int = 5):
    """Rank owned scents for today's weather, hour, and occasion.

    `time_of_day` should be supplied by the client (day/night), since the
    server's clock may be running in UTC inside the container.
    """
    with get_db() as db:
        lat = get_setting(db, "latitude")
        lon = get_setting(db, "longitude")
        bands = get_setting(db, "season_temp_bands")
        rules = get_setting(db, "scent_rules") or {}

        weather = None
        try:
            weather = await fetch_weather(lat, lon)
            season = season_for(date.today(), weather.get("high_f"), bands)
        except Exception:
            season = season_for_month(date.today().month)

        period = (time_of_day if time_of_day in ("day", "night")
                  else period_for_hour(datetime.now().hour))

        rows = db.execute(
            "SELECT * FROM fragrances WHERE status = 'owned'"
        ).fetchall()
        frags = fragrances_to_dicts(db, rows)
        ranked = rank_fragrances(frags, season, weather or {}, rules,
                                 occasion or "", period)

        # Every bottle tagged for another season would otherwise leave the card
        # blank. Rank them anyway and let the UI say the tags were ignored.
        relaxed = False
        if not ranked and frags:
            relaxed = True
            ranked = rank_fragrances(frags, season, weather or {}, rules,
                                     occasion or "", period, strict=False)

        return {
            "season": season,
            "weather": weather,
            "period": period,
            "occasion": occasion or "",
            "owned_count": len(frags),
            "relaxed": relaxed,
            "scents": ranked[:max(1, limit)],
        }


@router.get("/scents/stats")
def scent_stats():
    """Collection summary: counts by status, rating spread, top-rated, spend."""
    with get_db() as db:
        rows = db.execute("SELECT * FROM fragrances").fetchall()
        frags = fragrances_to_dicts(db, rows)

        by_status = {}
        by_family = {}
        rated = [f for f in frags if (f.get("rating") or 0) > 0]
        for f in frags:
            status = f.get("status") or "owned"
            by_status[status] = by_status.get(status, 0) + 1
            family = f.get("family") or "unspecified"
            by_family[family] = by_family.get(family, 0) + 1

        owned = [f for f in frags if (f.get("status") or "owned") == "owned"]
        journal_entries = db.execute(
            "SELECT COUNT(*) AS n FROM fragrance_notes"
        ).fetchone()["n"]

        top = sorted(rated, key=lambda f: (-(f.get("rating") or 0), f["name"].lower()))

        return {
            "total": len(frags),
            "by_status": by_status,
            "by_family": by_family,
            "journal_entries": journal_entries,
            "rated_count": len(rated),
            "average_rating": (
                round(sum(f["rating"] for f in rated) / len(rated), 2) if rated else None
            ),
            "total_spend": round(sum(f.get("paid_price") or 0 for f in owned), 2),
            "top_rated": top[:5],
            "unrated": [f for f in frags if not (f.get("rating") or 0)][:10],
        }


# ---------------------------------------------------------------------- CRUD


@router.get("/scents")
def list_scents(status: Optional[str] = None, family: Optional[str] = None,
                min_rating: Optional[int] = None, sort: str = "rating"):
    """List scents. Sort: rating (default), name, house, recent, worn."""
    with get_db() as db:
        query = "SELECT * FROM fragrances WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if family:
            query += " AND family = ?"
            params.append(family)
        if min_rating:
            query += " AND rating >= ?"
            params.append(int(min_rating))

        orders = {
            # Unrated last within a rating sort — a 0 is "no verdict yet", not
            # a bad one, so it does not belong at the bottom next to the 1s.
            "rating": "CASE WHEN rating = 0 THEN 1 ELSE 0 END, rating DESC, name COLLATE NOCASE",
            "name": "name COLLATE NOCASE",
            "house": "house COLLATE NOCASE, name COLLATE NOCASE",
            "recent": "created_at DESC, id DESC",
            "worn": "last_worn IS NULL, last_worn DESC, name COLLATE NOCASE",
        }
        query += " ORDER BY " + orders.get(sort, orders["rating"])
        return fragrances_to_dicts(db, db.execute(query, params).fetchall())


@router.post("/scents", status_code=201)
async def create_scent(request: Request):
    """Add a scent to the journal. Only `name` is required."""
    data = await request.json()

    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")

    status = _validate_enum(data.get("status", "owned"), SCENT_STATUSES, "status")
    time_of_day = _validate_enum(data.get("time_of_day", "any"), TIMES_OF_DAY, "time_of_day")
    sillage = _validate_enum(data.get("sillage", "moderate"), SILLAGES, "sillage")

    concentration = (data.get("concentration") or "").strip().lower()
    if concentration and concentration not in CONCENTRATIONS:
        raise HTTPException(400, f"concentration must be one of: {', '.join(CONCENTRATIONS)}")

    size_ml = _number(data.get("size_ml", 0))
    # An unopened bottle is full; only an explicit value overrides that.
    remaining_ml = _number(data.get("remaining_ml", size_ml), size_ml)

    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO fragrances
               (name, house, concentration, family, notes_top, notes_heart, notes_base,
                season_tags, vibe_tags, time_of_day, sillage, longevity_hours,
                size_ml, remaining_ml, price, paid_price, rating, impression,
                tried_on, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                (data.get("house") or "").strip(),
                concentration,
                (data.get("family") or "").strip().lower(),
                json.dumps(normalize_notes(data.get("notes_top"))),
                json.dumps(normalize_notes(data.get("notes_heart"))),
                json.dumps(normalize_notes(data.get("notes_base"))),
                json.dumps(data.get("season_tags") or []),
                json.dumps(data.get("vibe_tags") or []),
                time_of_day,
                sillage,
                _number(data.get("longevity_hours", 0)),
                size_ml,
                remaining_ml,
                _number(data.get("price", 0)),
                _number(data.get("paid_price", data.get("price", 0))),
                clamp_rating(data.get("rating", 0)),
                (data.get("impression") or "").strip(),
                (data.get("tried_on") or "").strip(),
                status,
            ),
        )
        scent_id = cursor.lastrowid

        # A first impression supplied at creation time becomes the opening
        # journal entry, so the history starts where the opinion did.
        first_note = (data.get("impression") or "").strip()
        if first_note:
            db.execute(
                "INSERT INTO fragrance_notes (fragrance_id, date, note, rating, sprays) "
                "VALUES (?, ?, ?, ?, 0)",
                (scent_id, (data.get("tried_on") or "").strip() or date.today().isoformat(),
                 first_note, clamp_rating(data.get("rating", 0))),
            )

        row = _get_scent_or_404(db, scent_id)
        return fragrance_to_dict(row)


@router.get("/scents/{scent_id}")
def get_scent(scent_id: int):
    """One scent with its full journal, newest entry first."""
    with get_db() as db:
        row = _get_scent_or_404(db, scent_id)
        scent = fragrance_to_dict(row)
        scent["notes"] = [
            dict(n) for n in db.execute(
                "SELECT * FROM fragrance_notes WHERE fragrance_id = ? "
                "ORDER BY date DESC, id DESC",
                (scent_id,),
            ).fetchall()
        ]
        scent["note_count"] = len(scent["notes"])
        return scent


@router.patch("/scents/{scent_id}")
async def update_scent(scent_id: int, request: Request):
    """Partial update."""
    data = await request.json()

    with get_db() as db:
        _get_scent_or_404(db, scent_id)

        updates = []
        params = []

        for field in _TEXT_FIELDS:
            if field in data:
                value = (data[field] or "").strip()
                if field == "name" and not value:
                    raise HTTPException(400, "name cannot be empty")
                if field in ("concentration", "family"):
                    value = value.lower()
                if field == "concentration" and value and value not in CONCENTRATIONS:
                    raise HTTPException(
                        400, f"concentration must be one of: {', '.join(CONCENTRATIONS)}")
                updates.append(f"{field} = ?")
                params.append(value)

        for field in _NUMBER_FIELDS:
            if field in data:
                updates.append(f"{field} = ?")
                params.append(_number(data[field]))

        for field in _LIST_FIELDS:
            if field in data:
                updates.append(f"{field} = ?")
                params.append(json.dumps(normalize_notes(data[field])))

        for field in ("season_tags", "vibe_tags"):
            if field in data:
                updates.append(f"{field} = ?")
                params.append(json.dumps(data[field] or []))

        if "rating" in data:
            updates.append("rating = ?")
            params.append(clamp_rating(data["rating"]))

        for field, allowed in (("status", SCENT_STATUSES),
                               ("time_of_day", TIMES_OF_DAY),
                               ("sillage", SILLAGES)):
            if field in data:
                updates.append(f"{field} = ?")
                params.append(_validate_enum(data[field], allowed, field))

        if updates:
            params.append(scent_id)
            db.execute(f"UPDATE fragrances SET {', '.join(updates)} WHERE id = ?", params)

        return fragrance_to_dict(_get_scent_or_404(db, scent_id))


@router.delete("/scents/{scent_id}")
def delete_scent(scent_id: int):
    """Delete a scent, its journal (FK cascade), and its photo file."""
    with get_db() as db:
        row = _get_scent_or_404(db, scent_id)
        if row["photo"]:
            delete_photo_files(row["photo"].split("/")[-1])
        db.execute("DELETE FROM fragrances WHERE id = ?", (scent_id,))
        return {"ok": True}


# -------------------------------------------------------------------- photos


@router.post("/scents/{scent_id}/photo")
async def upload_scent_photo(scent_id: int, file: UploadFile = File(...)):
    """Upload (or replace) the bottle photo."""
    with get_db() as db:
        row = _get_scent_or_404(db, scent_id)
        img = process_image(await file.read())
        filename = f"scent_{scent_id}.jpg"
        # Same filename on replace, so the old file is overwritten rather than
        # orphaned — but the URL then needs a cache-bust on the client.
        url = save_photo(img, filename)
        if row["photo"] != url:
            db.execute("UPDATE fragrances SET photo = ? WHERE id = ?", (url, scent_id))
        return fragrance_to_dict(_get_scent_or_404(db, scent_id))


@router.delete("/scents/{scent_id}/photo")
def delete_scent_photo(scent_id: int):
    """Remove the bottle photo."""
    with get_db() as db:
        row = _get_scent_or_404(db, scent_id)
        if row["photo"]:
            delete_photo_files(row["photo"].split("/")[-1])
            db.execute("UPDATE fragrances SET photo = '' WHERE id = ?", (scent_id,))
        return fragrance_to_dict(_get_scent_or_404(db, scent_id))


# ------------------------------------------------------------------- journal


@router.get("/scents/{scent_id}/notes")
def list_notes(scent_id: int):
    """Journal entries for one scent, newest first."""
    with get_db() as db:
        _get_scent_or_404(db, scent_id)
        return [
            dict(n) for n in db.execute(
                "SELECT * FROM fragrance_notes WHERE fragrance_id = ? "
                "ORDER BY date DESC, id DESC",
                (scent_id,),
            ).fetchall()
        ]


@router.post("/scents/{scent_id}/notes", status_code=201)
async def add_note(scent_id: int, request: Request):
    """Write a dated journal entry.

    Body: {date?, note, rating?, sprays?}. A rating here also becomes the
    scent's current rating — the latest verdict is the one that stands. Sprays
    above zero draw the bottle down and count the day as a wearing.
    """
    data = await request.json()

    note = (data.get("note") or "").strip()
    rating = clamp_rating(data.get("rating", 0))
    try:
        sprays = max(0, int(data.get("sprays") or 0))
    except (TypeError, ValueError):
        sprays = 0

    if not note and not rating and not sprays:
        raise HTTPException(400, "a journal entry needs a note, a rating, or sprays")

    entry_date = (data.get("date") or "").strip() or date.today().isoformat()

    with get_db() as db:
        _get_scent_or_404(db, scent_id)
        rules = get_setting(db, "scent_rules") or {}

        cursor = db.execute(
            "INSERT INTO fragrance_notes (fragrance_id, date, note, rating, sprays) "
            "VALUES (?, ?, ?, ?, ?)",
            (scent_id, entry_date, note, rating, sprays),
        )

        if sprays:
            ml_per_spray = float(rules.get("ml_per_spray", 0.1) or 0.1)
            db.execute(
                "UPDATE fragrances SET remaining_ml = MAX(0, remaining_ml - ?) "
                "WHERE id = ? AND size_ml > 0",
                (sprays * ml_per_spray, scent_id),
            )
        if rating:
            db.execute("UPDATE fragrances SET rating = ? WHERE id = ?", (rating, scent_id))

        _recount(db, scent_id)
        return {
            "entry": dict(db.execute(
                "SELECT * FROM fragrance_notes WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()),
            "scent": fragrance_to_dict(_get_scent_or_404(db, scent_id)),
        }


@router.delete("/scents/{scent_id}/notes/{note_id}")
def delete_note(scent_id: int, note_id: int):
    """Delete a journal entry and give back any volume it charged."""
    with get_db() as db:
        _get_scent_or_404(db, scent_id)
        entry = db.execute(
            "SELECT * FROM fragrance_notes WHERE id = ? AND fragrance_id = ?",
            (note_id, scent_id),
        ).fetchone()
        if not entry:
            raise HTTPException(404, "Journal entry not found")

        rules = get_setting(db, "scent_rules") or {}
        if entry["sprays"]:
            ml_per_spray = float(rules.get("ml_per_spray", 0.1) or 0.1)
            db.execute(
                "UPDATE fragrances SET remaining_ml = MIN(size_ml, remaining_ml + ?) "
                "WHERE id = ? AND size_ml > 0",
                (entry["sprays"] * ml_per_spray, scent_id),
            )

        db.execute("DELETE FROM fragrance_notes WHERE id = ?", (note_id,))
        _recount(db, scent_id)
        return {"ok": True, "scent": fragrance_to_dict(_get_scent_or_404(db, scent_id))}


@router.get("/scents/journal/recent")
def recent_journal(limit: int = 20):
    """The journal across all scents, newest first — the reading view."""
    rows_limit = max(1, min(200, limit))
    with get_db() as db:
        rows = db.execute(
            """SELECT n.*, f.name AS scent_name, f.house AS scent_house,
                      f.photo AS scent_photo, f.status AS scent_status
               FROM fragrance_notes n
               JOIN fragrances f ON f.id = n.fragrance_id
               ORDER BY n.date DESC, n.id DESC LIMIT ?""",
            (rows_limit,),
        ).fetchall()
        return [dict(r) for r in rows]
