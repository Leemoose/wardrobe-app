"""Shared image processing: upload normalization, thumbnails, collage cache.

Consolidates the process_image/invalidate helpers that were previously
duplicated across items, outfits, wear, and imports routers (v1.5), and adds
grid-size thumbnail generation so list views stop downloading 1024px images.
"""
import os
import threading
from io import BytesIO

from PIL import Image, ImageOps

from app.db import PHOTO_DIR

MAX_SIZE = (1024, 1024)   # full-size photo cap (unchanged from pre-v1.5)
THUMB_SIZE = (400, 400)   # grid/strip thumbnail cap
THUMB_DIR = os.path.join(PHOTO_DIR, "thumbs")


def process_image(contents: bytes) -> Image.Image:
    """Process uploaded image: apply EXIF orientation, convert to RGB, resize.

    Phone cameras store rotation as EXIF metadata rather than rotating pixels;
    without the transpose, portrait photos land sideways once the metadata is
    stripped by re-encoding.
    """
    img = Image.open(BytesIO(contents))
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail(MAX_SIZE)
    return img


def rotate_photo_file(filename: str, degrees: int) -> bool:
    """Rotate a stored photo clockwise by `degrees` and regenerate its thumbnail.

    Returns False if the file does not exist.
    """
    path = os.path.join(PHOTO_DIR, filename)
    if not os.path.exists(path):
        return False
    img = Image.open(path).convert("RGB")
    # PIL rotates counter-clockwise; UI semantics are clockwise.
    img = img.rotate(-degrees, expand=True)
    img.save(path, "JPEG", quality=85)
    try:
        save_thumb(img, filename)
    except Exception as e:
        print(f"[wardrobe] thumbnail regen failed for {filename}: {e}")
    return True


def save_thumb(img: Image.Image, filename: str):
    """Write a THUMB_SIZE thumbnail for an already-processed image."""
    os.makedirs(THUMB_DIR, exist_ok=True)
    t = img.copy()
    t.thumbnail(THUMB_SIZE)
    t.save(os.path.join(THUMB_DIR, filename), "JPEG", quality=80)


def save_photo(img: Image.Image, filename: str) -> str:
    """Save a processed image plus its thumbnail. Returns the public URL."""
    img.save(os.path.join(PHOTO_DIR, filename), "JPEG", quality=85)
    try:
        save_thumb(img, filename)
    except Exception as e:  # thumbnail failure must never block the upload
        print(f"[wardrobe] thumbnail generation failed for {filename}: {e}")
    return f"/photos/{filename}"


def delete_photo_files(filename: str):
    """Remove a stored photo and its thumbnail, ignoring missing files."""
    for path in (os.path.join(PHOTO_DIR, filename),
                 os.path.join(THUMB_DIR, filename)):
        if os.path.exists(path):
            os.remove(path)


def invalidate_collage_cache(outfit_id: int):
    """Remove cached collage file for an outfit."""
    collage_path = os.path.join(PHOTO_DIR, f"collage_{outfit_id}.jpg")
    if os.path.exists(collage_path):
        os.remove(collage_path)


def invalidate_outfit_collages(db, item_id: int):
    """Remove cached collage files for outfits containing this item."""
    outfit_rows = db.execute(
        "SELECT outfit_id FROM outfit_items WHERE item_id = ?", (item_id,)
    ).fetchall()
    for row in outfit_rows:
        invalidate_collage_cache(row["outfit_id"])


def _backfill_thumbs():
    """Generate missing thumbnails for photos uploaded before v1.5."""
    if not os.path.isdir(PHOTO_DIR):
        return
    os.makedirs(THUMB_DIR, exist_ok=True)
    count = 0
    for fn in os.listdir(PHOTO_DIR):
        full = os.path.join(PHOTO_DIR, fn)
        if not os.path.isfile(full):
            continue
        if fn.startswith("collage_"):
            continue  # collages are already small and regenerate on demand
        if os.path.exists(os.path.join(THUMB_DIR, fn)):
            continue
        try:
            img = Image.open(full).convert("RGB")
            save_thumb(img, fn)
            count += 1
        except Exception as e:
            print(f"[wardrobe] thumb backfill skipped {fn}: {e}")
    if count:
        print(f"[wardrobe] thumbnail backfill: generated {count} thumbnails")


def start_thumb_backfill():
    """Run the thumbnail backfill in a background thread (non-blocking)."""
    threading.Thread(target=_backfill_thumbs, daemon=True).start()
