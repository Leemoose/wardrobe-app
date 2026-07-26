"""Items router - CRUD for wardrobe items."""
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File

from app.db import get_db, item_to_dict, items_to_dicts
from app.images import (
    process_image,
    save_photo,
    delete_photo_files,
    invalidate_outfit_collages,
)

router = APIRouter(tags=["items"])


@router.get("/items")
def list_items(
    category: Optional[str] = None,
    status: Optional[str] = None,
    lifecycle: Optional[str] = None,
):
    """List all items, with optional category, status, and lifecycle filters."""
    with get_db() as db:
        query = "SELECT * FROM items WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if status:
            query += " AND status = ?"
            params.append(status)
        if lifecycle:
            query += " AND lifecycle = ?"
            params.append(lifecycle)
        query += " ORDER BY number"
        rows = db.execute(query, params).fetchall()
        return items_to_dicts(rows, db)


@router.post("/items", status_code=201)
async def create_item(request: Request):
    """Create a new item."""
    data = await request.json()

    # Required fields
    number = data.get("number")
    name = data.get("name")
    category = data.get("category")

    if number is None or name is None or category is None:
        raise HTTPException(400, "number, name, and category are required")

    # Optional fields with defaults
    brand = data.get("brand", "")
    color = data.get("color", "")
    size = data.get("size", "")
    price = data.get("price", 0)
    # paid_price defaults to price (retail) when not explicitly provided.
    paid_price = data.get("paid_price", price)
    care_notes = data.get("care_notes", "")
    season_tags = json.dumps(data.get("season_tags", []))
    vibe_tags = json.dumps(data.get("vibe_tags", []))

    # Materials: use provided list, or infer from name/care_notes if absent.
    # Provided values are normalized so raw fibre names off a care label land on
    # the vocabulary the UI renders from.
    if "materials" in data:
        from app.db import normalize_materials
        materials = json.dumps(normalize_materials(data.get("materials")))
    else:
        from app.db import infer_materials
        materials = json.dumps(infer_materials(name, care_notes))

    # Measurements: category-specific dimensions as a JSON object (optional).
    measurements = json.dumps(data.get("measurements") or {})

    # Optional image_url for downloading
    image_url = data.get("image_url")

    with get_db() as db:
        # Check for duplicate number
        existing = db.execute("SELECT id FROM items WHERE number = ?", (number,)).fetchone()
        if existing:
            raise HTTPException(409, f"Item with number {number} already exists")

        cursor = db.execute(
            """INSERT INTO items (number, name, category, brand, color, size, price,
               paid_price, care_notes, season_tags, vibe_tags, materials, measurements)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (number, name, category, brand, color, size, price, paid_price,
             care_notes, season_tags, vibe_tags, materials, measurements)
        )
        item_id = cursor.lastrowid

        image_error = None
        if image_url:
            # Import here to avoid circular imports
            from app.link_import import download_image
            try:
                img_data = await download_image(image_url)
                if img_data:
                    img = process_image(img_data)
                    # Create item_photos row
                    photo_cursor = db.execute(
                        "INSERT INTO item_photos (item_id, filename, sort) VALUES (?, ?, 0)",
                        (item_id, "placeholder"),
                    )
                    photo_id = photo_cursor.lastrowid
                    filename = f"{item_id}_{photo_id}.jpg"
                    db.execute(
                        "UPDATE item_photos SET filename = ? WHERE id = ?",
                        (filename, photo_id),
                    )
                    photo_url = save_photo(img, filename)
                    # Set as cover
                    db.execute("UPDATE items SET photo = ? WHERE id = ?", (photo_url, item_id))
            except Exception as e:
                image_error = str(e)

        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        result = item_to_dict(row, db)
        if image_error:
            result["image_error"] = image_error
        return result


@router.patch("/items/{item_id}")
async def update_item(item_id: int, request: Request):
    """Partial update of an item."""
    data = await request.json()

    with get_db() as db:
        # Check item exists
        existing = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Item not found")

        # Build update query dynamically
        updates = []
        params = []

        for field in ["name", "category", "brand", "color", "size", "price", "paid_price", "care_notes"]:
            if field in data:
                updates.append(f"{field} = ?")
                params.append(data[field])

        if "number" in data:
            # Check for duplicate number
            dup = db.execute(
                "SELECT id FROM items WHERE number = ? AND id != ?",
                (data["number"], item_id)
            ).fetchone()
            if dup:
                raise HTTPException(409, f"Item with number {data['number']} already exists")
            updates.append("number = ?")
            params.append(data["number"])

        if "season_tags" in data:
            updates.append("season_tags = ?")
            params.append(json.dumps(data["season_tags"]))

        if "vibe_tags" in data:
            updates.append("vibe_tags = ?")
            params.append(json.dumps(data["vibe_tags"]))

        if "materials" in data:
            from app.db import normalize_materials
            updates.append("materials = ?")
            params.append(json.dumps(normalize_materials(data["materials"])))

        if "measurements" in data:
            updates.append("measurements = ?")
            params.append(json.dumps(data["measurements"] or {}))

        if "status" in data:
            if data["status"] not in ("clean", "dirty"):
                raise HTTPException(400, "status must be 'clean' or 'dirty'")
            updates.append("status = ?")
            params.append(data["status"])
            # Reset wears_since_wash when marking clean
            if data["status"] == "clean":
                updates.append("wears_since_wash = 0")

        if "lifecycle" in data:
            if data["lifecycle"] not in ("active", "stored", "retired"):
                raise HTTPException(400, "lifecycle must be 'active', 'stored', or 'retired'")
            updates.append("lifecycle = ?")
            params.append(data["lifecycle"])

        if updates:
            params.append(item_id)
            db.execute(f"UPDATE items SET {', '.join(updates)} WHERE id = ?", params)

        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return item_to_dict(row, db)


@router.delete("/items/{item_id}")
def delete_item(item_id: int):
    """Delete an item and all its photo files."""
    with get_db() as db:
        # Get item to check it exists
        item = db.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")

        # Delete all photo files for this item
        photo_rows = db.execute(
            "SELECT filename FROM item_photos WHERE item_id = ?", (item_id,)
        ).fetchall()
        for p in photo_rows:
            delete_photo_files(p["filename"])

        # Also delete legacy photo file if it exists (old format: {item_id}.jpg)
        delete_photo_files(f"{item_id}.jpg")

        # Delete item (FK cascade handles outfit_items and item_photos)
        db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return {"ok": True}


@router.post("/items/{item_id}/photo")
async def upload_photo(item_id: int, file: UploadFile = File(...)):
    """Upload a photo for an item. Creates item_photos row, sets cover if item has none."""
    with get_db() as db:
        # Check item exists
        item = db.execute("SELECT id, photo FROM items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")

        # Read and process image
        contents = await file.read()
        img = process_image(contents)

        # Create item_photos row with placeholder filename
        cursor = db.execute(
            "INSERT INTO item_photos (item_id, filename, sort) VALUES (?, ?, 0)",
            (item_id, "placeholder"),
        )
        photo_id = cursor.lastrowid

        # Save with proper filename: {item_id}_{photo_id}.jpg
        filename = f"{item_id}_{photo_id}.jpg"
        db.execute(
            "UPDATE item_photos SET filename = ? WHERE id = ?",
            (filename, photo_id),
        )

        photo_url = save_photo(img, filename)

        # If item has no cover photo, set this as cover
        if not item["photo"]:
            db.execute("UPDATE items SET photo = ? WHERE id = ?", (photo_url, item_id))

        # Invalidate collage cache for outfits containing this item
        invalidate_outfit_collages(db, item_id)

        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return item_to_dict(row, db)


@router.delete("/items/{item_id}/photos/{photo_id}")
def delete_photo(item_id: int, photo_id: int):
    """Delete a photo from an item. If it was the cover, promote next remaining photo."""
    with get_db() as db:
        # Check item exists
        item = db.execute("SELECT id, photo FROM items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")

        # Check photo exists and belongs to this item
        photo = db.execute(
            "SELECT id, filename FROM item_photos WHERE id = ? AND item_id = ?",
            (photo_id, item_id),
        ).fetchone()
        if not photo:
            raise HTTPException(404, "Photo not found")

        # Delete the files (original + thumb)
        delete_photo_files(photo["filename"])

        # Delete the row
        db.execute("DELETE FROM item_photos WHERE id = ?", (photo_id,))

        # Check if this was the cover
        deleted_url = f"/photos/{photo['filename']}"
        if item["photo"] == deleted_url:
            # Promote next remaining photo as cover
            next_photo = db.execute(
                "SELECT filename FROM item_photos WHERE item_id = ? ORDER BY sort, id LIMIT 1",
                (item_id,),
            ).fetchone()
            if next_photo:
                new_cover = f"/photos/{next_photo['filename']}"
                db.execute("UPDATE items SET photo = ? WHERE id = ?", (new_cover, item_id))
            else:
                db.execute("UPDATE items SET photo = '' WHERE id = ?", (item_id,))

        # Invalidate collage cache
        invalidate_outfit_collages(db, item_id)

        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return item_to_dict(row, db)


@router.post("/items/{item_id}/photos/{photo_id}/cover")
def set_cover(item_id: int, photo_id: int):
    """Set a specific photo as the item's cover."""
    with get_db() as db:
        # Check item exists
        item = db.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")

        # Check photo exists and belongs to this item
        photo = db.execute(
            "SELECT id, filename FROM item_photos WHERE id = ? AND item_id = ?",
            (photo_id, item_id),
        ).fetchone()
        if not photo:
            raise HTTPException(404, "Photo not found")

        # Set as cover
        photo_url = f"/photos/{photo['filename']}"
        db.execute("UPDATE items SET photo = ? WHERE id = ?", (photo_url, item_id))

        # Invalidate collage cache
        invalidate_outfit_collages(db, item_id)

        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return item_to_dict(row, db)
