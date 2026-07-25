"""Laundry router - manage dirty items and washing."""
from fastapi import APIRouter, HTTPException, Request

from app.db import get_db, item_to_dict

router = APIRouter(tags=["laundry"])


@router.get("/laundry/dirty")
def get_dirty_items():
    """Get all active items marked as dirty."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM items WHERE status = 'dirty' AND lifecycle = 'active' ORDER BY number"
        ).fetchall()
        return [item_to_dict(row) for row in rows]


@router.post("/laundry")
async def wash_items(request: Request):
    """Mark active items as washed (clean)."""
    data = await request.json()

    mode = data.get("mode")
    if mode not in ("all", "select"):
        raise HTTPException(400, "mode must be 'all' or 'select'")

    with get_db() as db:
        if mode == "all":
            # Wash all dirty active items
            cursor = db.execute(
                """UPDATE items SET status = 'clean', wears_since_wash = 0
                   WHERE status = 'dirty' AND lifecycle = 'active'"""
            )
            count = cursor.rowcount
        else:
            # Wash selected active items
            item_ids = data.get("item_ids", [])
            if not item_ids:
                return {"washed": 0}

            placeholders = ",".join("?" * len(item_ids))
            cursor = db.execute(
                f"""UPDATE items SET status = 'clean', wears_since_wash = 0
                    WHERE status = 'dirty' AND lifecycle = 'active' AND id IN ({placeholders})""",
                item_ids
            )
            count = cursor.rowcount

        return {"washed": count}
