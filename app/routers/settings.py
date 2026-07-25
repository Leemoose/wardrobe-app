"""Settings router - app configuration."""
from fastapi import APIRouter, HTTPException, Request

from app.db import get_db, get_setting, set_setting, DEFAULT_SETTINGS, normalize_categories

router = APIRouter(tags=["settings"])


def _all_settings(db):
    result = {}
    for key in DEFAULT_SETTINGS:
        result[key] = get_setting(db, key)
    # Categories are always served normalized (handles legacy string lists)
    result["categories"] = normalize_categories(result.get("categories"))
    return result


@router.get("/settings")
def get_all_settings():
    """Get all settings."""
    with get_db() as db:
        return _all_settings(db)


@router.put("/settings")
async def update_settings(request: Request):
    """Update settings (partial update)."""
    data = await request.json()

    # Validate latitude/longitude if provided
    if "latitude" in data:
        try:
            lat = float(data["latitude"])
            if lat < -90 or lat > 90:
                raise ValueError()
        except (TypeError, ValueError):
            raise HTTPException(400, "latitude must be a number between -90 and 90")

    if "longitude" in data:
        try:
            lon = float(data["longitude"])
            if lon < -180 or lon > 180:
                raise ValueError()
        except (TypeError, ValueError):
            raise HTTPException(400, "longitude must be a number between -180 and 180")

    # Normalize categories if provided (accepts strings or behavior objects)
    if "categories" in data:
        if not isinstance(data["categories"], list):
            raise HTTPException(400, "categories must be a list")
        data["categories"] = normalize_categories(data["categories"])

    with get_db() as db:
        # Only update keys that exist in DEFAULT_SETTINGS
        for key, value in data.items():
            if key in DEFAULT_SETTINGS:
                set_setting(db, key, value)

        return _all_settings(db)
