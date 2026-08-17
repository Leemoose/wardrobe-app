"""FastAPI application for the Wardrobe manager."""
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db, PHOTO_DIR
from app.images import start_thumb_backfill
from app.routers import items, outfits, wear, laundry, weather, stats, settings, ai, backup, imports, trips, care, scents

app = FastAPI(title="Wardrobe")


@app.on_event("startup")
def startup():
    init_db()
    # v1.5: generate grid thumbnails for photos uploaded before thumbnails
    # existed. Runs in a background thread; startup is not blocked.
    start_thumb_backfill()


# Ensure PHOTO_DIR exists before mounting (init_db creates it at startup,
# but StaticFiles checks at mount time)
os.makedirs(PHOTO_DIR, exist_ok=True)

# Mount photo serving
app.mount("/photos", StaticFiles(directory=PHOTO_DIR), name="photos")

# Include all API routers under /api prefix
app.include_router(items.router, prefix="/api")
app.include_router(outfits.router, prefix="/api")
app.include_router(wear.router, prefix="/api")
app.include_router(laundry.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(backup.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(trips.router, prefix="/api")
app.include_router(care.router, prefix="/api")
app.include_router(scents.router, prefix="/api")

# Serve the frontend - mounted last so /api and /photos take precedence
# Use path relative to this module file
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
