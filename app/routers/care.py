"""Care router - care guides, per-item matching, and maintenance tracking."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from app.care_guides import GUIDES, get_guide, match_guides
from app.db import get_db, get_setting, item_to_dict, items_to_dicts

router = APIRouter(tags=["care"])

# Event kinds for the maintenance/repair log (P4).
# Must match the CHECK constraint from the v1.5 migration.
# 'care' = routine upkeep; 'professional' = cobbler, dry cleaner, tailor service.
EVENT_KINDS = ("care", "repair", "alteration", "professional")


# ----------------------------------------------------------------------
# Guide library
# ----------------------------------------------------------------------

@router.get("/care/guides")
def list_guides():
    """List all care guides (summary view)."""
    return [
        {
            "id": g["id"],
            "title": g["title"],
            "summary": g["summary"],
            "materials": g["materials"],
            "categories": g["categories"],
        }
        for g in GUIDES
    ]


@router.get("/care/guides/{guide_id}")
def guide_detail(guide_id: str):
    """Full detail for one guide."""
    guide = get_guide(guide_id)
    if not guide:
        raise HTTPException(404, "Guide not found")
    return guide


# ----------------------------------------------------------------------
# Task status computation
# ----------------------------------------------------------------------

def _care_prefetch(db, item_ids: list):
    """
    Batch-load care state for many items in two queries:
    - maint_map: {item_id: {task: last_done_date}}
    - wear_map:  {item_id: [wear dates]}
    """
    maint_map = {i: {} for i in item_ids}
    wear_map = {i: [] for i in item_ids}
    if not item_ids:
        return maint_map, wear_map

    placeholders = ",".join("?" * len(item_ids))
    for r in db.execute(
        f"""SELECT item_id, task, MAX(date) AS last_date
            FROM maintenance_events
            WHERE item_id IN ({placeholders})
            GROUP BY item_id, task""",
        item_ids,
    ).fetchall():
        maint_map[r["item_id"]][r["task"]] = r["last_date"]

    for r in db.execute(
        f"""SELECT wei.item_id, we.date
            FROM wear_event_items wei
            JOIN wear_events we ON we.id = wei.wear_event_id
            WHERE wei.item_id IN ({placeholders})""",
        item_ids,
    ).fetchall():
        wear_map[r["item_id"]].append(r["date"])

    return maint_map, wear_map


def _task_statuses(item_id: int, guides: list, last_by_task: dict, wear_dates: list) -> list:
    """
    Aggregate trackable tasks across matched guides (deduped by task key,
    most-specific guide wins) and compute due status for each.

    last_by_task/wear_dates come from _care_prefetch — no DB access here.
    """
    # Dedupe: guides are pre-sorted by specificity, first occurrence wins
    tasks = {}
    for g in guides:
        for t in g.get("tasks", []):
            if t["task"] not in tasks:
                tasks[t["task"]] = {**t, "guide_id": g["id"]}

    today = date.today()
    statuses = []
    for key, t in tasks.items():
        last_done = last_by_task.get(key)

        status = {
            "task": key,
            "label": t["label"],
            "guide_id": t["guide_id"],
            "every_wears": t.get("every_wears"),
            "every_days": t.get("every_days"),
            "last_done": last_done,
            "wears_since": None,
            "days_since": None,
            "due": False,
        }

        if t.get("every_wears") is not None:
            if last_done:
                # ISO date strings compare correctly as text
                n = sum(1 for d in wear_dates if d > last_done)
            else:
                n = len(wear_dates)
            status["wears_since"] = n
            if n >= t["every_wears"]:
                status["due"] = True

        if t.get("every_days") is not None:
            baseline = last_done
            if baseline is None:
                # Never logged: baseline is the item's first recorded wear.
                # Never-worn items are never "due".
                baseline = min(wear_dates) if wear_dates else None
            if baseline:
                try:
                    days = (today - date.fromisoformat(baseline[:10])).days
                    status["days_since"] = days
                    if days >= t["every_days"]:
                        status["due"] = True
                except ValueError:
                    pass

        statuses.append(status)

    # Due tasks first
    statuses.sort(key=lambda s: (not s["due"], s["task"]))
    return statuses


# ----------------------------------------------------------------------
# Per-item care
# ----------------------------------------------------------------------

@router.get("/items/{item_id}/care")
def item_care(item_id: int):
    """Matched care guides, task due status, and maintenance history for an item."""
    with get_db() as db:
        row = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Item not found")
        item = item_to_dict(row, db)

        guides = match_guides(item.get("materials", []), item.get("category"))
        maint_map, wear_map = _care_prefetch(db, [item_id])
        tasks = _task_statuses(item_id, guides, maint_map[item_id], wear_map[item_id])

        history = [
            dict(r)
            for r in db.execute(
                """SELECT id, task, date, notes, kind, cost FROM maintenance_events
                   WHERE item_id = ? ORDER BY date DESC, id DESC LIMIT 50""",
                (item_id,),
            ).fetchall()
        ]

        return {
            "item": {
                "id": item["id"],
                "name": item["name"],
                "category": item["category"],
                "materials": item.get("materials", []),
                "photo": item.get("photo"),
            },
            "guides": guides,
            "tasks": tasks,
            "history": history,
        }


@router.post("/items/{item_id}/care/log", status_code=201)
async def log_maintenance(item_id: int, request: Request):
    """Log a maintenance event. Body: {task, date?, notes?, kind?, cost?}."""
    data = await request.json()
    task = data.get("task")
    if not task:
        raise HTTPException(400, "task is required")
    event_date = data.get("date") or date.today().isoformat()
    notes = data.get("notes", "")

    kind = (data.get("kind") or "care").strip().lower()
    if kind not in EVENT_KINDS:
        raise HTTPException(400, f"kind must be one of: {', '.join(EVENT_KINDS)}")
    try:
        cost = max(0.0, float(data.get("cost") or 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "cost must be a number")

    with get_db() as db:
        item = db.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")

        cursor = db.execute(
            """INSERT INTO maintenance_events (item_id, task, date, notes, kind, cost)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item_id, task, event_date, notes, kind, cost),
        )
        event = db.execute(
            """SELECT id, item_id, task, date, notes, kind, cost
               FROM maintenance_events WHERE id = ?""",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(event)


@router.delete("/care/log/{event_id}")
def delete_maintenance(event_id: int):
    """Delete a maintenance log entry."""
    with get_db() as db:
        event = db.execute(
            "SELECT id FROM maintenance_events WHERE id = ?", (event_id,)
        ).fetchone()
        if not event:
            raise HTTPException(404, "Event not found")
        db.execute("DELETE FROM maintenance_events WHERE id = ?", (event_id,))
        return {"ok": True}


# ----------------------------------------------------------------------
# Due list
# ----------------------------------------------------------------------

@router.get("/care/due")
def care_due(lifecycle: Optional[str] = "active"):
    """
    Items with at least one maintenance task currently due.
    Only considers items matching the given lifecycle (default: active).
    """
    with get_db() as db:
        query = "SELECT * FROM items"
        params = []
        if lifecycle:
            query += " WHERE lifecycle = ?"
            params.append(lifecycle)
        rows = db.execute(query, params).fetchall()

        items = items_to_dicts(rows, db)
        maint_map, wear_map = _care_prefetch(db, [i["id"] for i in items])

        due_items = []
        for item in items:
            guides = match_guides(item.get("materials", []), item.get("category"))
            if not guides:
                continue
            tasks = _task_statuses(
                item["id"], guides, maint_map[item["id"]], wear_map[item["id"]]
            )
            due_tasks = [t for t in tasks if t["due"]]
            if due_tasks:
                due_items.append({
                    "item": {
                        "id": item["id"],
                        "name": item["name"],
                        "category": item["category"],
                        "materials": item.get("materials", []),
                        "photo": item.get("photo"),
                    },
                    "due_tasks": due_tasks,
                })

        # Most overdue first (by max wears_since or days_since ratio)
        def overdue_score(entry):
            best = 0.0
            for t in entry["due_tasks"]:
                if t["every_wears"] and t["wears_since"] is not None:
                    best = max(best, t["wears_since"] / t["every_wears"])
                if t["every_days"] and t["days_since"] is not None:
                    best = max(best, t["days_since"] / t["every_days"])
            return -best

        due_items.sort(key=overdue_score)
        return {"count": len(due_items), "items": due_items}


# ----------------------------------------------------------------------
# Care kit (supplies checklist)
# ----------------------------------------------------------------------

@router.get("/care/supplies")
def care_supplies():
    """
    Union of supplies across guides that match the user's active items,
    with owned/needed state from the 'care_supplies_owned' setting.
    """
    with get_db() as db:
        rows = db.execute("SELECT * FROM items WHERE lifecycle = 'active'").fetchall()
        items = items_to_dicts(rows, db)
        owned = get_setting(db, "care_supplies_owned") or []

    owned_set = {str(s).strip().lower() for s in owned}
    supplies = {}  # lower-cased name -> entry
    for item in items:
        guides = match_guides(item.get("materials", []), item.get("category"))
        seen_for_item = set()
        for g in guides:
            for s in g.get("supplies", []):
                key = s.strip().lower()
                if not key:
                    continue
                entry = supplies.setdefault(
                    key, {"name": s.strip(), "guides": set(), "item_count": 0}
                )
                entry["guides"].add(g["title"])
                if key not in seen_for_item:
                    entry["item_count"] += 1
                    seen_for_item.add(key)

    result = [
        {
            "name": e["name"],
            "owned": key in owned_set,
            "item_count": e["item_count"],
            "guides": sorted(e["guides"]),
        }
        for key, e in supplies.items()
    ]
    # Needed first, then most-used, then alphabetical
    result.sort(key=lambda s: (s["owned"], -s["item_count"], s["name"].lower()))
    return {"count": len(result), "supplies": result}


# ----------------------------------------------------------------------
# Seasonal storage assistant
# ----------------------------------------------------------------------

COLD_MATERIALS = {
    "wool", "cashmere", "merino", "mohair", "alpaca", "down",
    "corduroy", "velvet", "flannel", "tweed", "shearling", "fleece",
}

STORE_CHECKLIST = [
    "Clean or launder everything first - moths seek out worn fibers, and stains set over the summer",
    "Fold knitwear flat; never hang wool or cashmere long-term (it stretches shoulders)",
    "Use breathable cotton garment bags or lidded boxes - avoid sealed plastic",
    "Add cedar blocks or lavender sachets (lightly sand old cedar to refresh it)",
    "Store in a cool, dry, dark place away from radiators and damp walls",
    "Mark each item as Stored in the app so it leaves your active closet",
]

REACTIVATE_CHECKLIST = [
    "Inspect each piece for moth damage, musty smells, and forgotten stains",
    "Air out for a day, then steam to relax wrinkles and refresh fibers",
    "Brush wool coats and jackets with a garment brush to lift the nap",
    "Condition leather boots and shoes before their first wear of the season",
    "Mark items as Active in the app to bring them back into rotation",
]


def _is_cold_weather(item: dict) -> bool:
    """Cold-weather if materials match, or season tags are only fall/winter."""
    materials = {str(m).strip().lower() for m in item.get("materials", [])}
    if materials & COLD_MATERIALS:
        return True
    tags = set(item.get("season_tags") or [])
    return bool(tags) and tags <= {"fall", "winter"}


@router.get("/care/seasonal")
def care_seasonal():
    """
    Month-driven storage prompt:
    - Spring (Mar-May): active cold-weather items that should be stored
    - Fall (Sep-Nov): stored cold-weather items to bring back out
    - Otherwise: no prompt
    """
    month = date.today().month
    if month in (3, 4, 5):
        mode, lifecycle = "store", "active"
    elif month in (9, 10, 11):
        mode, lifecycle = "reactivate", "stored"
    else:
        return {"mode": None, "month": month, "items": [], "checklist": []}

    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM items WHERE lifecycle = ?", (lifecycle,)
        ).fetchall()
        items = items_to_dicts(rows, db)

    matched = [
        {
            "id": i["id"],
            "name": i["name"],
            "category": i["category"],
            "materials": i.get("materials", []),
            "photo": i.get("photo"),
        }
        for i in items
        if _is_cold_weather(i)
    ]
    return {
        "mode": mode,
        "month": month,
        "items": matched,
        "checklist": STORE_CHECKLIST if mode == "store" else REACTIVATE_CHECKLIST,
    }
