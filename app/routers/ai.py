"""AI router - AI-powered and rule-based outfit generation."""
import json
import os

from fastapi import APIRouter, HTTPException, Request

from app.db import get_db, item_to_dict, outfit_to_dict
from app.ai import (
    generate_outfits,
    anthropic_available,
    openai_available,
    openai_model,
)
from app.local_gen import generate_local_outfits

router = APIRouter(tags=["ai"])


@router.get("/ai/status")
def ai_status():
    """Which AI providers are configured (for the frontend engine selector)."""
    return {
        "anthropic": anthropic_available(),
        "anthropic_model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
        "openai": openai_available(),
        "openai_model": openai_model() if openai_available() else None,
    }


@router.post("/ai/generate")
async def generate_ai_outfits(request: Request):
    """
    Generate new outfit suggestions.

    Accepts optional "engine" parameter:
    - "auto" (default): Claude if ANTHROPIC_API_KEY set, else OpenAI-compatible
      (Ollama/LM Studio) if OPENAI_BASE_URL set, else rule-based local
    - "anthropic": Force Claude (requires ANTHROPIC_API_KEY)
    - "openai": Force the OpenAI-compatible endpoint (requires OPENAI_BASE_URL)
    - "ai": Legacy alias - any configured AI provider (Claude preferred)
    - "local": Force rule-based local generation
    """
    data = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    count = data.get("count", 5)
    engine = data.get("engine", "auto")

    # Determine which provider to use (None = rule-based local)
    has_anthropic = anthropic_available()
    has_openai = openai_available()

    if engine == "auto":
        provider = "anthropic" if has_anthropic else ("openai" if has_openai else None)
    elif engine == "ai":
        provider = "anthropic" if has_anthropic else ("openai" if has_openai else None)
        if provider is None:
            raise HTTPException(
                400,
                "No AI provider configured. Set ANTHROPIC_API_KEY or OPENAI_BASE_URL, "
                "or use engine='local' for rule-based generation."
            )
    elif engine == "anthropic":
        if not has_anthropic:
            raise HTTPException(400, "ANTHROPIC_API_KEY not set.")
        provider = "anthropic"
    elif engine == "openai":
        if not has_openai:
            raise HTTPException(
                400,
                "OPENAI_BASE_URL not set. Point it at an OpenAI-compatible server "
                "such as Ollama (http://host:11434/v1)."
            )
        provider = "openai"
    elif engine == "local":
        provider = None
    else:
        raise HTTPException(
            400,
            f"Invalid engine: {engine}. Use 'auto', 'anthropic', 'openai', 'ai', or 'local'."
        )

    use_ai = provider is not None
    engine_used = provider or "local"

    with get_db() as db:
        # Get all items
        item_rows = db.execute("SELECT * FROM items ORDER BY number").fetchall()
        items = [item_to_dict(row) for row in item_rows]

        if not items:
            raise HTTPException(400, "No items in wardrobe")

        # Build number -> id mapping
        number_to_id = {item["number"]: item["id"] for item in items}

        # Get ALL existing outfits (active, pending, rejected)
        outfit_rows = db.execute("SELECT * FROM outfits").fetchall()
        existing_outfits = [outfit_to_dict(db, row) for row in outfit_rows]

        # Build set of existing item-id combinations
        existing_combos = set()
        for outfit in existing_outfits:
            item_ids = frozenset(item["id"] for item in outfit["items"])
            existing_combos.add(item_ids)

        # Generate candidates
        if use_ai:
            try:
                candidates = await generate_outfits(
                    items, existing_outfits, count, provider=provider
                )
            except ValueError as e:
                raise HTTPException(400, str(e))
            except Exception as e:
                raise HTTPException(502, f"AI service error: {str(e)}")
        else:
            try:
                candidates = generate_local_outfits(db, count)
            except ValueError as e:
                raise HTTPException(400, str(e))

        # Process candidates
        created = []
        for candidate in candidates:
            name = candidate.get("name", "Generated Outfit")
            item_numbers = candidate.get("item_numbers", [])
            season_tags = candidate.get("season_tags", [])
            vibe_tags = candidate.get("vibe_tags", [])
            note = candidate.get("note", "")

            # Map numbers to ids, skip if any unknown
            item_ids = []
            valid = True
            for num in item_numbers:
                if num not in number_to_id:
                    valid = False
                    break
                item_ids.append(number_to_id[num])

            if not valid or not item_ids:
                continue

            # Skip if exact match with existing outfit
            item_id_set = frozenset(item_ids)
            if item_id_set in existing_combos:
                continue

            # Create outfit
            cursor = db.execute(
                """INSERT INTO outfits (name, season_tags, vibe_tags, source, status, ai_note)
                   VALUES (?, ?, ?, 'ai', 'pending', ?)""",
                (name, json.dumps(season_tags), json.dumps(vibe_tags), note)
            )
            outfit_id = cursor.lastrowid

            # Add outfit items
            for item_id in item_ids:
                db.execute(
                    "INSERT INTO outfit_items (outfit_id, item_id) VALUES (?, ?)",
                    (outfit_id, item_id)
                )

            # Add to tracking set to prevent duplicates within this batch
            existing_combos.add(item_id_set)

            # Fetch created outfit
            row = db.execute("SELECT * FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
            outfit_dict = outfit_to_dict(db, row)
            outfit_dict["engine_used"] = engine_used
            created.append(outfit_dict)

        return created


@router.get("/ai/pending")
def get_pending_outfits():
    """Get all pending AI-generated outfits."""
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM outfits WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        return [outfit_to_dict(db, row) for row in rows]


@router.post("/ai/{outfit_id}/approve")
def approve_outfit(outfit_id: int):
    """Approve a pending AI outfit."""
    with get_db() as db:
        outfit = db.execute(
            "SELECT * FROM outfits WHERE id = ? AND status = 'pending'",
            (outfit_id,)
        ).fetchone()

        if not outfit:
            raise HTTPException(404, "Pending outfit not found")

        db.execute("UPDATE outfits SET status = 'active' WHERE id = ?", (outfit_id,))

        row = db.execute("SELECT * FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        return outfit_to_dict(db, row)


@router.post("/ai/{outfit_id}/reject")
def reject_outfit(outfit_id: int):
    """Reject a pending AI outfit."""
    with get_db() as db:
        outfit = db.execute(
            "SELECT * FROM outfits WHERE id = ? AND status = 'pending'",
            (outfit_id,)
        ).fetchone()

        if not outfit:
            raise HTTPException(404, "Pending outfit not found")

        db.execute("UPDATE outfits SET status = 'rejected' WHERE id = ?", (outfit_id,))

        row = db.execute("SELECT * FROM outfits WHERE id = ?", (outfit_id,)).fetchone()
        return outfit_to_dict(db, row)
