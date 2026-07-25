"""Backup router - export wardrobe data."""
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import date

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.db import get_db, item_to_dict, outfit_to_dict, get_setting, DEFAULT_SETTINGS, DB_PATH, PHOTO_DIR

router = APIRouter(tags=["backup"])

# Tables cleared by a reset, ordered so child rows are removed before parents.
RESET_TABLES = [
    "trip_outfits",
    "trip_items",
    "trips",
    "wear_event_items",
    "wear_events",
    "outfit_items",
    "outfits",
    "item_photos",
    "wishlist",
    "items",
]


class ResetRequest(BaseModel):
    confirm: bool = False
    delete_photos: bool = True


@router.post("/reset")
def reset_wardrobe(payload: ResetRequest):
    """Clear all wardrobe data for a clean slate.

    Deletes items, outfits, wear history, wishlist, and trips. Settings are
    preserved. Requires an explicit ``{"confirm": true}`` body to avoid
    accidental wipes. Optionally removes stored photo files too.
    """
    if not payload.confirm:
        return JSONResponse(
            status_code=400,
            content={"error": "Reset requires confirm=true."},
        )

    deleted = {}
    with get_db() as db:
        for table in RESET_TABLES:
            cur = db.execute(f"DELETE FROM {table}")
            deleted[table] = cur.rowcount
        # Reset AUTOINCREMENT counters so new items start at 1.
        db.execute(
            "DELETE FROM sqlite_sequence WHERE name IN "
            "('items','outfits','wear_events','trips')"
        )

    photos_removed = 0
    if payload.delete_photos and os.path.isdir(PHOTO_DIR):
        for filename in os.listdir(PHOTO_DIR):
            file_path = os.path.join(PHOTO_DIR, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
                photos_removed += 1
        thumbs_dir = os.path.join(PHOTO_DIR, "thumbs")
        if os.path.isdir(thumbs_dir):
            for filename in os.listdir(thumbs_dir):
                fp = os.path.join(thumbs_dir, filename)
                if os.path.isfile(fp):
                    os.remove(fp)

    return {"status": "reset", "deleted": deleted, "photos_removed": photos_removed}


def _build_export_dict(db) -> dict:
    """Build the full export dictionary."""
    # Settings
    settings = {}
    for key in DEFAULT_SETTINGS:
        settings[key] = get_setting(db, key)

    # Items
    item_rows = db.execute("SELECT * FROM items ORDER BY number").fetchall()
    items = [item_to_dict(row) for row in item_rows]

    # Outfits with item ids
    outfit_rows = db.execute("SELECT * FROM outfits ORDER BY id").fetchall()
    outfits = []
    for row in outfit_rows:
        outfit = outfit_to_dict(db, row)
        # Replace full items with just item_ids for export
        outfit["item_ids"] = [item["id"] for item in outfit["items"]]
        del outfit["items"]
        outfits.append(outfit)

    # Wear events with items
    event_rows = db.execute(
        "SELECT * FROM wear_events ORDER BY date DESC, id DESC"
    ).fetchall()
    wear_events = []
    for event in event_rows:
        event_items = db.execute(
            """SELECT wei.item_id, wei.marked_dirty
               FROM wear_event_items wei
               WHERE wei.wear_event_id = ?""",
            (event["id"],)
        ).fetchall()

        wear_events.append({
            "id": event["id"],
            "date": event["date"],
            "outfit_id": event["outfit_id"],
            "created_at": event["created_at"],
            "items": [
                {"item_id": ei["item_id"], "marked_dirty": bool(ei["marked_dirty"])}
                for ei in event_items
            ]
        })

    return {
        "exported_at": date.today().isoformat(),
        "settings": settings,
        "items": items,
        "outfits": outfits,
        "wear_events": wear_events,
    }


@router.get("/backup/json")
def export_json():
    """Export full wardrobe data as JSON."""
    with get_db() as db:
        export_data = _build_export_dict(db)

    filename = f"wardrobe-export-{date.today().isoformat()}.json"

    return JSONResponse(
        content=export_data,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.get("/backup/zip")
def export_zip(background_tasks: BackgroundTasks):
    """
    Export full wardrobe backup as ZIP.

    Contains:
    - wardrobe.db: Consistent copy via sqlite3 backup()
    - export.json: Same as /backup/json
    - photos/: All photo files
    """
    # Create temp directory for building the zip
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, f"wardrobe-backup-{date.today().isoformat()}.zip")

    try:
        with get_db() as db:
            export_data = _build_export_dict(db)

        # Create a consistent copy of the database using sqlite3 backup
        db_copy_path = os.path.join(temp_dir, "wardrobe.db")
        if os.path.exists(DB_PATH):
            source_conn = sqlite3.connect(DB_PATH)
            dest_conn = sqlite3.connect(db_copy_path)
            source_conn.backup(dest_conn)
            source_conn.close()
            dest_conn.close()

        # Write export.json
        json_path = os.path.join(temp_dir, "export.json")
        with open(json_path, "w") as f:
            json.dump(export_data, f, indent=2)

        # Create the zip file
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add database
            if os.path.exists(db_copy_path):
                zf.write(db_copy_path, "wardrobe.db")

            # Add export.json
            zf.write(json_path, "export.json")

            # Add photos directory
            if os.path.isdir(PHOTO_DIR):
                for filename in os.listdir(PHOTO_DIR):
                    file_path = os.path.join(PHOTO_DIR, filename)
                    if os.path.isfile(file_path):
                        zf.write(file_path, f"photos/{filename}")

        # Schedule cleanup after response is sent
        def cleanup():
            shutil.rmtree(temp_dir, ignore_errors=True)

        background_tasks.add_task(cleanup)

        return FileResponse(
            path=zip_path,
            filename=f"wardrobe-backup-{date.today().isoformat()}.zip",
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="wardrobe-backup-{date.today().isoformat()}.zip"'
            }
        )

    except Exception as e:
        # Clean up on error
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise e
