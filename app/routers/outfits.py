"""Outfits router - CRUD for outfit combinations."""
import json
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from PIL import Image

from app.db import get_db, outfit_to_dict, outfits_to_dicts, PHOTO_DIR
from app.images import (
    process_image,
    save_photo,
    delete_photo_files,
    invalidate_collage_cache,
)

router = APIRouter(tags=["outfits"])


@router.get("/outfits")
def list_outfits(
    status: str = "active",
    available: Optional[str] = None,
    season: Optional[str] = None,
    vibe: Optional[str] = None
):
    """List outfits with filters."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM outfits WHERE status = ? ORDER BY created_at DESC",
            (status,)
        ).fetchall()

        results = []
        for outfit in outfits_to_dicts(db, rows):
            # Filter by available
            if available == "true" and not outfit["available"]:
                continue

            # Filter by season (match if tag present OR outfit has empty tags)
            if season:
                outfit_seasons = outfit["season_tags"]
                if outfit_seasons and season not in outfit_seasons:
                    continue

            # Filter by vibe (match if tag present OR outfit has empty tags)
            if vibe:
                outfit_vibes = outfit["vibe_tags"]
                if outfit_vibes and vibe not in outfit_vibes:
                    continue

            results.append(outfit)

        return results


@router.post("/outfits", status_code=201)
async def create_outfit(request: Request):
    """Create a new outfit."""
    data = await request.json()

    name = data.get("name")
    item_ids = data.get("item_ids", [])
    season_tags = data.get("season_tags")
    vibe_tags = data.get("vibe_tags")

    if not name:
        raise HTTPException(400, "name is required")
    if not item_ids:
        raise HTTPException(400, "item_ids is required and cannot be empty")

    with get_db() as db:
        # Validate all item_ids exist
        placeholders = ",".join("?" * len(item_ids))
        existing = db.execute(
            f"SELECT id, season_tags, vibe_tags FROM items WHERE id IN ({placeholders})",
            item_ids
        ).fetchall()

        if len(existing) != len(item_ids):
            raise HTTPException(400, "One or more item_ids do not exist")

        # Auto-derive tags if not provided or empty
        if not season_tags:
            all_seasons = set()
            for item in existing:
                all_seasons.update(json.loads(item["season_tags"]))
            season_tags = list(all_seasons)

        if not vibe_tags:
            all_vibes = set()
            for item in existing:
                all_vibes.update(json.loads(item["vibe_tags"]))
            vibe_tags = list(all_vibes)

        # Create outfit
        cursor = db.execute(
            """INSERT INTO outfits (name, season_tags, vibe_tags, source, status)
               VALUES (?, ?, ?, 'manual', 'active')""",
            (name, json.dumps(season_tags), json.dumps(vibe_tags))
        )
        outfit_id = cursor.lastrowid

        # Add outfit items
        for item_id in item_ids:
            db.execute(
                "INSERT INTO outfit_items (outfit_id, item_id) VALUES (?, ?)",
                (outfit_id, item_id)
            )

        row = db.execute("SELECT * FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        return outfit_to_dict(db, row)


@router.patch("/outfits/{outfit_id}")
async def update_outfit(outfit_id: int, request: Request):
    """Partial update of an outfit."""
    data = await request.json()

    with get_db() as db:
        # Check outfit exists
        existing = db.execute("SELECT * FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Outfit not found")

        # Build update query dynamically
        updates = []
        params = []

        if "name" in data:
            updates.append("name = ?")
            params.append(data["name"])

        if "season_tags" in data:
            updates.append("season_tags = ?")
            params.append(json.dumps(data["season_tags"]))

        if "vibe_tags" in data:
            updates.append("vibe_tags = ?")
            params.append(json.dumps(data["vibe_tags"]))

        if updates:
            params.append(outfit_id)
            db.execute(f"UPDATE outfits SET {', '.join(updates)} WHERE id = ?", params)

        # Replace item memberships if provided
        if "item_ids" in data:
            item_ids = data["item_ids"]

            # Validate all item_ids exist
            if item_ids:
                placeholders = ",".join("?" * len(item_ids))
                existing_items = db.execute(
                    f"SELECT id FROM items WHERE id IN ({placeholders})",
                    item_ids
                ).fetchall()

                if len(existing_items) != len(item_ids):
                    raise HTTPException(400, "One or more item_ids do not exist")

            # Delete existing memberships
            db.execute("DELETE FROM outfit_items WHERE outfit_id = ?", (outfit_id,))

            # Add new memberships
            for item_id in item_ids:
                db.execute(
                    "INSERT INTO outfit_items (outfit_id, item_id) VALUES (?, ?)",
                    (outfit_id, item_id)
                )

            # Invalidate collage cache when item_ids change
            invalidate_collage_cache(outfit_id)

        row = db.execute("SELECT * FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        return outfit_to_dict(db, row)


@router.delete("/outfits/{outfit_id}")
def delete_outfit(outfit_id: int):
    """Delete an outfit and its photo/collage files."""
    with get_db() as db:
        existing = db.execute("SELECT id FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Outfit not found")

        # Delete photo and collage files (including any thumbs)
        delete_photo_files(f"outfit_{outfit_id}.jpg")
        invalidate_collage_cache(outfit_id)

        db.execute("DELETE FROM outfits WHERE id = ?", (outfit_id,))
        return {"ok": True}


@router.post("/outfits/{outfit_id}/photo")
async def upload_outfit_photo(outfit_id: int, file: UploadFile = File(...)):
    """Upload a preview photo for an outfit."""
    with get_db() as db:
        # Check outfit exists
        outfit = db.execute("SELECT id FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        if not outfit:
            raise HTTPException(404, "Outfit not found")

        # Read and process image
        contents = await file.read()
        img = process_image(contents)

        # Save as outfit photo (also generates a grid thumbnail)
        filename = f"outfit_{outfit_id}.jpg"
        photo_url = save_photo(img, filename)

        # Update outfit photo field
        db.execute("UPDATE outfits SET photo = ? WHERE id = ?", (photo_url, outfit_id))

        row = db.execute("SELECT * FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        return outfit_to_dict(db, row)


@router.delete("/outfits/{outfit_id}/photo")
def delete_outfit_photo(outfit_id: int):
    """Delete an outfit's preview photo."""
    with get_db() as db:
        # Check outfit exists
        outfit = db.execute("SELECT id, photo FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        if not outfit:
            raise HTTPException(404, "Outfit not found")

        # Delete the files (original + thumb)
        delete_photo_files(f"outfit_{outfit_id}.jpg")

        # Clear the photo field
        db.execute("UPDATE outfits SET photo = '' WHERE id = ?", (outfit_id,))

        row = db.execute("SELECT * FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        return outfit_to_dict(db, row)


@router.get("/outfits/{outfit_id}/collage")
def get_outfit_collage(outfit_id: int):
    """
    Get or generate a collage image from outfit member cover photos.

    Canvas: 600x400px, background #1a1d24
    Grid layouts:
    - 1 photo: centered
    - 2 photos: 2 across
    - 3 photos: 3 across
    - 4 photos: 2x2 grid
    - 5-6 photos: 3x2 grid

    Landscape because the card preview renders this into a wide, short box; a
    portrait canvas there gets almost entirely cropped away by object-fit.

    Uses 12px gutters. Serves cached collage if available.
    Returns 404 if no member photos exist.
    """
    cache_path = os.path.join(PHOTO_DIR, f"collage_{outfit_id}.jpg")

    # Serve cached version if exists
    if os.path.exists(cache_path):
        return FileResponse(cache_path, media_type="image/jpeg")

    with get_db() as db:
        # Check outfit exists
        outfit = db.execute("SELECT id FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        if not outfit:
            raise HTTPException(404, "Outfit not found")

        # Get member items with photos (cover photos)
        items_with_photos = db.execute(
            """SELECT i.photo FROM items i
               JOIN outfit_items oi ON oi.item_id = i.id
               WHERE oi.outfit_id = ? AND i.photo != ''
               ORDER BY i.number
               LIMIT 6""",
            (outfit_id,),
        ).fetchall()

        if not items_with_photos:
            raise HTTPException(404, "No member photos available for collage")

        # Load the photos
        photos = []
        for item in items_with_photos:
            # Extract filename from URL (e.g., "/photos/1_2.jpg" -> "1_2.jpg")
            filename = item["photo"].split("/")[-1]
            photo_path = os.path.join(PHOTO_DIR, filename)
            if os.path.exists(photo_path):
                try:
                    img = Image.open(photo_path).convert("RGB")
                    photos.append(img)
                except Exception:
                    pass

        if not photos:
            raise HTTPException(404, "No member photos available for collage")

        # Create collage canvas
        canvas_width = 600
        canvas_height = 400
        gutter = 12
        bg_color = (26, 29, 36)  # #1a1d24

        canvas = Image.new("RGB", (canvas_width, canvas_height), bg_color)

        n = len(photos)

        # Grid shape by photo count. A landscape canvas means laying pieces out
        # side by side rather than stacking them.
        if n == 1:
            cols, rows = 1, 1
        elif n == 2:
            cols, rows = 2, 1
        elif n == 3:
            cols, rows = 3, 1
        elif n == 4:
            cols, rows = 2, 2
        else:
            cols, rows = 3, 2

        cell_w = (canvas_width - (cols + 1) * gutter) // cols
        cell_h = (canvas_height - (rows + 1) * gutter) // rows

        for i, img in enumerate(photos[: cols * rows]):
            img = img.copy()
            img.thumbnail((cell_w, cell_h))
            col = i % cols
            row = i // cols
            x = gutter + col * (cell_w + gutter) + (cell_w - img.width) // 2
            y = gutter + row * (cell_h + gutter) + (cell_h - img.height) // 2
            canvas.paste(img, (x, y))

        # Save to cache
        canvas.save(cache_path, "JPEG", quality=85)

        return FileResponse(cache_path, media_type="image/jpeg")
