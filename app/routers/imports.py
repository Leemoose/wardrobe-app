"""Imports router - link import, wishlist, and CSV import."""
import csv
import io
import json
import os
import shutil
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import PlainTextResponse

from app.db import get_db, item_to_dict, get_setting, PHOTO_DIR
from app.images import THUMB_DIR, process_image, save_photo, delete_photo_files
from app.link_import import import_link, download_image, SSRFError
from app.routers.stats import compute_gap_flags

router = APIRouter(tags=["imports"])


def wishlist_to_dict(row, fills_gap: Optional[str] = None) -> dict:
    """Convert wishlist row to dict."""
    d = dict(row)
    d["fills_gap"] = fills_gap
    return d


# --- Link Import ---

@router.post("/import/link")
async def import_from_link(request: Request):
    """
    Import product info from a URL.

    Body: {"url": "https://..."}

    Returns:
    {
        "found": bool,
        "name": str,
        "brand": str,
        "price": float,
        "image_url": str,
        "source": "jsonld" | "opengraph" | "ai" | null,
        "error": str | null
    }
    """
    data = await request.json()
    url = data.get("url")

    if not url:
        raise HTTPException(400, "url is required")

    result = await import_link(url)
    return result


# --- Wishlist ---

@router.get("/wishlist")
def list_wishlist():
    """List all wishlist entries with fills_gap computed."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM wishlist ORDER BY created_at DESC"
        ).fetchall()

        # Compute gap flags once
        gap_flags = compute_gap_flags(db)

        results = []
        for row in rows:
            entry = dict(row)
            # Compute fills_gap: first flag containing the category name
            fills_gap = None
            if entry["category"]:
                cat = entry["category"].lower()
                for flag in gap_flags:
                    if cat in flag.lower():
                        fills_gap = flag
                        break
            entry["fills_gap"] = fills_gap
            results.append(entry)

        return results


@router.post("/wishlist", status_code=201)
async def create_wishlist(request: Request):
    """
    Create a wishlist entry.

    Body: {"url": "...", optional: name, brand, price, category, notes}

    Runs link import to fill missing fields, downloads image best-effort.
    """
    data = await request.json()
    url = data.get("url")

    if not url:
        raise HTTPException(400, "url is required")

    # Run link import to fill missing fields
    imported = await import_link(url)

    name = data.get("name") or imported.get("name", "")
    brand = data.get("brand") or imported.get("brand", "")
    price = data.get("price")
    if price is None:
        price = imported.get("price", 0)
    category = data.get("category", "")
    notes = data.get("notes", "")
    image_url = imported.get("image_url", "")

    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO wishlist (url, name, brand, price, image, category, notes)
               VALUES (?, ?, ?, ?, '', ?, ?)""",
            (url, name, brand, price, category, notes),
        )
        entry_id = cursor.lastrowid

        # Try to download image
        if image_url:
            try:
                img_data = await download_image(image_url)
                if img_data:
                    img = process_image(img_data)
                    image_url_saved = save_photo(img, f"wish_{entry_id}.jpg")
                    db.execute(
                        "UPDATE wishlist SET image = ? WHERE id = ?",
                        (image_url_saved, entry_id),
                    )
            except Exception:
                # Best effort - ignore errors
                pass

        row = db.execute("SELECT * FROM wishlist WHERE id = ?", (entry_id,)).fetchone()

        # Compute fills_gap
        gap_flags = compute_gap_flags(db)
        fills_gap = None
        if category:
            cat_lower = category.lower()
            for flag in gap_flags:
                if cat_lower in flag.lower():
                    fills_gap = flag
                    break

        return wishlist_to_dict(row, fills_gap)


@router.patch("/wishlist/{entry_id}")
async def update_wishlist(entry_id: int, request: Request):
    """Update a wishlist entry."""
    data = await request.json()

    with get_db() as db:
        existing = db.execute("SELECT * FROM wishlist WHERE id = ?", (entry_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Wishlist entry not found")

        updates = []
        params = []

        for field in ["name", "brand", "price", "category", "notes"]:
            if field in data:
                updates.append(f"{field} = ?")
                params.append(data[field])

        if updates:
            params.append(entry_id)
            db.execute(f"UPDATE wishlist SET {', '.join(updates)} WHERE id = ?", params)

        row = db.execute("SELECT * FROM wishlist WHERE id = ?", (entry_id,)).fetchone()

        # Compute fills_gap
        gap_flags = compute_gap_flags(db)
        fills_gap = None
        category = row["category"]
        if category:
            cat_lower = category.lower()
            for flag in gap_flags:
                if cat_lower in flag.lower():
                    fills_gap = flag
                    break

        return wishlist_to_dict(row, fills_gap)


@router.delete("/wishlist/{entry_id}")
def delete_wishlist(entry_id: int):
    """Delete a wishlist entry and its image."""
    with get_db() as db:
        existing = db.execute("SELECT id FROM wishlist WHERE id = ?", (entry_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Wishlist entry not found")

        # Delete image files (original + thumb)
        delete_photo_files(f"wish_{entry_id}.jpg")

        db.execute("DELETE FROM wishlist WHERE id = ?", (entry_id,))
        return {"ok": True}


@router.post("/wishlist/{entry_id}/purchase", status_code=201)
async def purchase_wishlist(entry_id: int, request: Request):
    """
    Convert a wishlist entry to an item.

    Body: {"number": int}

    Creates an item with name/brand/price/category from the wishlist entry.
    Moves the wishlist image to be the item's cover photo.
    Deletes the wishlist entry.
    """
    data = await request.json()
    number = data.get("number")

    if number is None:
        raise HTTPException(400, "number is required")

    with get_db() as db:
        # Get wishlist entry
        entry = db.execute("SELECT * FROM wishlist WHERE id = ?", (entry_id,)).fetchone()
        if not entry:
            raise HTTPException(404, "Wishlist entry not found")

        # Validate category is set
        if not entry["category"]:
            raise HTTPException(400, "Wishlist entry must have a category to purchase")

        # Validate number is unique
        existing = db.execute("SELECT id FROM items WHERE number = ?", (number,)).fetchone()
        if existing:
            raise HTTPException(400, f"Item with number {number} already exists")

        # Create the item
        cursor = db.execute(
            """INSERT INTO items (number, name, category, brand, price, lifecycle)
               VALUES (?, ?, ?, ?, ?, 'active')""",
            (number, entry["name"], entry["category"], entry["brand"], entry["price"]),
        )
        item_id = cursor.lastrowid

        # Handle image: move wish image to item photo
        wish_image_path = os.path.join(PHOTO_DIR, f"wish_{entry_id}.jpg")
        if os.path.exists(wish_image_path):
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

            # Move the file (and its thumbnail, if present)
            new_path = os.path.join(PHOTO_DIR, filename)
            shutil.move(wish_image_path, new_path)
            old_thumb = os.path.join(THUMB_DIR, f"wish_{entry_id}.jpg")
            if os.path.exists(old_thumb):
                shutil.move(old_thumb, os.path.join(THUMB_DIR, filename))

            # Set as cover
            photo_url = f"/photos/{filename}"
            db.execute("UPDATE items SET photo = ? WHERE id = ?", (photo_url, item_id))

        # Delete wishlist entry
        db.execute("DELETE FROM wishlist WHERE id = ?", (entry_id,))

        # Return item
        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return item_to_dict(row, db)


# --- CSV Import ---

CSV_TEMPLATE_HEADER = "number,name,category,brand,color,size,price,care_notes,season_tags,vibe_tags"
CSV_TEMPLATE_EXAMPLE = "# 101,Example Tee,tops,Uniqlo,white,M,25,,summer;spring,casual"


@router.get("/import/csv/template")
def get_csv_template():
    """Download a CSV template for bulk item import."""
    content = f"{CSV_TEMPLATE_HEADER}\n{CSV_TEMPLATE_EXAMPLE}\n"
    return PlainTextResponse(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=wardrobe-import-template.csv"},
    )


@router.post("/import/csv")
async def import_csv(
    dry_run: bool = True,
    file: UploadFile = File(...),
):
    """
    Import items from a CSV file.

    Query: dry_run=true (default) to validate only, dry_run=false to create items.

    CSV columns: number,name,category,brand,color,size,price,care_notes,season_tags,vibe_tags
    - number: required, integer, unique
    - name: required, non-empty
    - category: required, must be in settings categories
    - price: optional, default 0
    - season_tags/vibe_tags: semicolon-separated (e.g. "summer;spring")

    Returns: {"valid": n, "errors": [{"row": n, "reason": str}], "created": n}
    """
    contents = await file.read()
    text = contents.decode("utf-8")

    # Parse CSV
    reader = csv.DictReader(io.StringIO(text))

    with get_db() as db:
        from app.db import get_category_names
        categories = get_category_names(db)

        # Get existing item numbers
        existing_numbers = set()
        for row in db.execute("SELECT number FROM items").fetchall():
            existing_numbers.add(row["number"])

        errors = []
        valid_rows = []
        seen_numbers = set()

        for idx, row in enumerate(reader, start=2):  # Start at 2 (1-based + header)
            # Skip comment rows
            number_str = row.get("number", "").strip()
            if number_str.startswith("#"):
                continue

            # Validate number
            try:
                number = int(number_str)
            except ValueError:
                errors.append({"row": idx, "reason": f"Invalid number: {number_str}"})
                continue

            # Check uniqueness (existing + within file)
            if number in existing_numbers:
                errors.append({"row": idx, "reason": f"Number {number} already exists"})
                continue
            if number in seen_numbers:
                errors.append({"row": idx, "reason": f"Duplicate number {number} in file"})
                continue
            seen_numbers.add(number)

            # Validate name
            name = row.get("name", "").strip()
            if not name:
                errors.append({"row": idx, "reason": "Name is required"})
                continue

            # Validate category
            category = row.get("category", "").strip()
            if not category:
                errors.append({"row": idx, "reason": "Category is required"})
                continue
            if category not in categories:
                errors.append({"row": idx, "reason": f"Invalid category: {category}"})
                continue

            # Parse price
            price_str = row.get("price", "").strip()
            try:
                price = float(price_str) if price_str else 0
            except ValueError:
                price = 0

            # Parse tags (semicolon-separated)
            season_tags_str = row.get("season_tags", "").strip()
            season_tags = [t.strip() for t in season_tags_str.split(";") if t.strip()] if season_tags_str else []

            vibe_tags_str = row.get("vibe_tags", "").strip()
            vibe_tags = [t.strip() for t in vibe_tags_str.split(";") if t.strip()] if vibe_tags_str else []

            # Collect valid row data
            valid_rows.append({
                "number": number,
                "name": name,
                "category": category,
                "brand": row.get("brand", "").strip(),
                "color": row.get("color", "").strip(),
                "size": row.get("size", "").strip(),
                "price": price,
                "care_notes": row.get("care_notes", "").strip(),
                "season_tags": season_tags,
                "vibe_tags": vibe_tags,
            })

        created = 0
        if not dry_run:
            for item_data in valid_rows:
                db.execute(
                    """INSERT INTO items (number, name, category, brand, color, size,
                       price, care_notes, season_tags, vibe_tags)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item_data["number"],
                        item_data["name"],
                        item_data["category"],
                        item_data["brand"],
                        item_data["color"],
                        item_data["size"],
                        item_data["price"],
                        item_data["care_notes"],
                        json.dumps(item_data["season_tags"]),
                        json.dumps(item_data["vibe_tags"]),
                    ),
                )
                created += 1

        return {
            "valid": len(valid_rows),
            "errors": errors,
            "created": created,
        }
