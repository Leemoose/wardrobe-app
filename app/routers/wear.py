"""Wear events router - track outfit wearing history."""
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File

from app.db import get_db, outfit_to_dict
from app.images import process_image, save_photo, delete_photo_files

router = APIRouter(tags=["wear"])


@router.post("/wear", status_code=201)
async def record_wear(request: Request):
    """
    Record a wear event.

    Body:
    - outfit_id (optional): Link to an existing outfit
    - date (optional): "YYYY-MM-DD", defaults to today
    - items: [{item_id, dirty}] - non-empty list required
    - save_as_outfit (optional): {name (required), season_tags?, vibe_tags?}
      If provided, creates a new manual active outfit from these item ids
      and sets the event's outfit_id to the new outfit.
    """
    data = await request.json()

    outfit_id = data.get("outfit_id")  # Now optional
    wear_date = data.get("date", date.today().isoformat())
    items = data.get("items", [])
    save_as_outfit = data.get("save_as_outfit")

    if not items:
        raise HTTPException(400, "items list is required and cannot be empty")

    with get_db() as db:
        # Validate outfit exists if provided
        if outfit_id is not None:
            outfit = db.execute("SELECT id FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
            if not outfit:
                raise HTTPException(404, "Outfit not found")

        # Validate all items exist
        item_ids = [item_data.get("item_id") for item_data in items]
        placeholders = ",".join("?" * len(item_ids))
        existing_items = db.execute(
            f"SELECT id FROM items WHERE id IN ({placeholders})",
            item_ids
        ).fetchall()
        existing_ids = {row["id"] for row in existing_items}

        for item_id in item_ids:
            if item_id not in existing_ids:
                raise HTTPException(404, f"Item {item_id} not found")

        created_outfit = None

        # Handle save_as_outfit
        if save_as_outfit:
            outfit_name = save_as_outfit.get("name")
            if not outfit_name:
                raise HTTPException(400, "save_as_outfit.name is required")

            season_tags = save_as_outfit.get("season_tags", [])
            vibe_tags = save_as_outfit.get("vibe_tags", [])

            # Create the outfit
            cursor = db.execute(
                """INSERT INTO outfits (name, season_tags, vibe_tags, source, status)
                   VALUES (?, ?, ?, 'manual', 'active')""",
                (outfit_name, json.dumps(season_tags), json.dumps(vibe_tags))
            )
            new_outfit_id = cursor.lastrowid

            # Add outfit items
            for item_id in item_ids:
                db.execute(
                    "INSERT INTO outfit_items (outfit_id, item_id) VALUES (?, ?)",
                    (new_outfit_id, item_id)
                )

            # Set this as the event's outfit_id
            outfit_id = new_outfit_id

            # Fetch created outfit for response
            outfit_row = db.execute("SELECT * FROM outfits WHERE id = ?", (new_outfit_id,)).fetchone()
            created_outfit = outfit_to_dict(db, outfit_row)

        # Create wear event
        cursor = db.execute(
            "INSERT INTO wear_events (date, outfit_id) VALUES (?, ?)",
            (wear_date, outfit_id)
        )
        event_id = cursor.lastrowid

        # Process each item
        for item_data in items:
            item_id = item_data.get("item_id")
            dirty = item_data.get("dirty", False)

            # Insert wear_event_item
            db.execute(
                "INSERT INTO wear_event_items (wear_event_id, item_id, marked_dirty) VALUES (?, ?, ?)",
                (event_id, item_id, 1 if dirty else 0)
            )

            # Update item stats
            db.execute(
                """UPDATE items SET
                   lifetime_wears = lifetime_wears + 1,
                   wears_since_wash = wears_since_wash + 1,
                   last_worn = ?
                   WHERE id = ?""",
                (wear_date, item_id)
            )

            # Mark dirty if specified
            if dirty:
                db.execute("UPDATE items SET status = 'dirty' WHERE id = ?", (item_id,))

        return {
            "event_id": event_id,
            "date": wear_date,
            "outfit_id": outfit_id,
            "created_outfit": created_outfit
        }


@router.get("/wear/history")
def get_wear_history(year: Optional[int] = None, month: Optional[int] = None):
    """Get wear history for a given month (defaults to current month)."""
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    # Build date range for the month
    start_date = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end_date = f"{year + 1:04d}-01-01"
    else:
        end_date = f"{year:04d}-{month + 1:02d}-01"

    with get_db() as db:
        events = db.execute(
            """SELECT we.id, we.date, we.outfit_id, we.photo, o.name as outfit_name
               FROM wear_events we
               LEFT JOIN outfits o ON o.id = we.outfit_id
               WHERE we.date >= ? AND we.date < ?
               ORDER BY we.date DESC""",
            (start_date, end_date)
        ).fetchall()

        results = []
        for event in events:
            # Get items for this event (include item names)
            items = db.execute(
                """SELECT wei.item_id, wei.marked_dirty, i.name, i.number
                   FROM wear_event_items wei
                   JOIN items i ON i.id = wei.item_id
                   WHERE wei.wear_event_id = ?""",
                (event["id"],)
            ).fetchall()

            results.append({
                "id": event["id"],
                "date": event["date"],
                "outfit_id": event["outfit_id"],
                "outfit_name": event["outfit_name"],  # Will be null for ad-hoc events
                "photo": event["photo"] or "",
                "items": [
                    {
                        "item_id": item["item_id"],
                        "number": item["number"],
                        "name": item["name"],
                        "marked_dirty": bool(item["marked_dirty"])
                    }
                    for item in items
                ]
            })

        return results


@router.delete("/wear/{event_id}")
def delete_wear_event(event_id: int):
    """
    Delete a wear event and undo its effects.

    For each item in the event:
    - Decrement lifetime_wears and wears_since_wash (floor 0)
    - If the event marked it dirty AND it is currently dirty, set status 'clean'
    - Recompute last_worn to date of most recent REMAINING wear event, else NULL
    Also deletes the wear photo file if present.
    """
    with get_db() as db:
        # Check event exists
        event = db.execute("SELECT * FROM wear_events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            raise HTTPException(404, "Wear event not found")

        # Delete wear photo file if present (original + thumb)
        if event["photo"]:
            delete_photo_files(event["photo"].split("/")[-1])

        # Get items from this event
        event_items = db.execute(
            """SELECT wei.item_id, wei.marked_dirty, i.status
               FROM wear_event_items wei
               JOIN items i ON i.id = wei.item_id
               WHERE wei.wear_event_id = ?""",
            (event_id,)
        ).fetchall()

        reversed_count = 0

        for event_item in event_items:
            item_id = event_item["item_id"]
            marked_dirty = event_item["marked_dirty"]
            current_status = event_item["status"]

            # Decrement counters (floor at 0)
            db.execute(
                """UPDATE items SET
                   lifetime_wears = MAX(0, lifetime_wears - 1),
                   wears_since_wash = MAX(0, wears_since_wash - 1)
                   WHERE id = ?""",
                (item_id,)
            )

            # If this event marked the item dirty AND it's currently dirty, clean it
            if marked_dirty and current_status == "dirty":
                db.execute("UPDATE items SET status = 'clean' WHERE id = ?", (item_id,))

            # Recompute last_worn: find most recent REMAINING wear event for this item
            # (excluding the event we're deleting)
            last_worn_row = db.execute(
                """SELECT MAX(we.date) as last_date
                   FROM wear_event_items wei
                   JOIN wear_events we ON we.id = wei.wear_event_id
                   WHERE wei.item_id = ? AND we.id != ?""",
                (item_id, event_id)
            ).fetchone()

            new_last_worn = last_worn_row["last_date"] if last_worn_row else None
            db.execute("UPDATE items SET last_worn = ? WHERE id = ?", (new_last_worn, item_id))

            reversed_count += 1

        # Delete the event (cascade deletes wear_event_items)
        db.execute("DELETE FROM wear_events WHERE id = ?", (event_id,))

        return {"ok": True, "reversed_items": reversed_count}


@router.post("/wear/{event_id}/photo")
async def upload_wear_photo(
    event_id: int,
    set_outfit_preview: bool = False,
    file: UploadFile = File(...),
):
    """
    Upload a photo for a wear event.

    If set_outfit_preview=true and the event has an outfit_id,
    also copies the file as the outfit's preview photo.
    """
    with get_db() as db:
        # Check event exists
        event = db.execute(
            "SELECT id, outfit_id FROM wear_events WHERE id = ?", (event_id,)
        ).fetchone()
        if not event:
            raise HTTPException(404, "Wear event not found")

        # Read and process image
        contents = await file.read()
        img = process_image(contents)

        # Save as wear photo (also generates a grid thumbnail)
        wear_filename = f"wear_{event_id}.jpg"
        wear_photo_url = save_photo(img, wear_filename)

        # Update wear event photo
        db.execute(
            "UPDATE wear_events SET photo = ? WHERE id = ?",
            (wear_photo_url, event_id),
        )

        outfit_photo_url = None

        # If set_outfit_preview and event has outfit_id, also set outfit photo
        if set_outfit_preview and event["outfit_id"]:
            outfit_id = event["outfit_id"]
            # Save the same processed image as the outfit's preview photo
            outfit_photo_url = save_photo(img, f"outfit_{outfit_id}.jpg")
            db.execute(
                "UPDATE outfits SET photo = ? WHERE id = ?",
                (outfit_photo_url, outfit_id),
            )

        return {
            "ok": True,
            "photo": wear_photo_url,
            "outfit_photo": outfit_photo_url,
        }
