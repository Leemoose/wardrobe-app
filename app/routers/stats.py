"""Stats router - wardrobe statistics and insights."""
import json
from collections import defaultdict

from fastapi import APIRouter

from app.db import get_db, item_to_dict, get_setting, get_category_names

router = APIRouter(tags=["stats"])


def compute_gap_flags(db) -> list:
    """
    Compute wardrobe gap flags for essential categories.

    Returns a list of strings like "No spring tops", "No winter bottoms", etc.
    Shared between /api/analysis/gaps and wishlist fills_gap feature.
    """
    categories = get_category_names(db)
    seasons = get_setting(db, "season_tags") or []

    # Get all active items
    active_items = db.execute(
        "SELECT * FROM items WHERE lifecycle = 'active'"
    ).fetchall()

    # Build coverage: {category: {season: count}}
    coverage = {cat: {s: 0 for s in seasons} for cat in categories}

    for row in active_items:
        item = item_to_dict(row)
        cat = item["category"]
        if cat not in coverage:
            coverage[cat] = {s: 0 for s in seasons}

        item_seasons = item["season_tags"]
        if not item_seasons:
            # Empty tags = counts for all seasons
            for s in seasons:
                coverage[cat][s] += 1
        else:
            for s in item_seasons:
                if s in seasons:
                    coverage[cat][s] += 1

    # Generate flags for essential categories
    essential_categories = ["tops", "bottoms", "shoes"]
    flags = []
    for cat in essential_categories:
        if cat in coverage:
            for s in seasons:
                if coverage[cat].get(s, 0) == 0:
                    flags.append(f"No {s} {cat}")

    return flags


@router.get("/stats")
def get_stats():
    """Get wardrobe statistics."""
    with get_db() as db:
        # Total items
        item_count = db.execute("SELECT COUNT(*) as cnt FROM items").fetchone()["cnt"]

        # Total active outfits
        outfit_count = db.execute(
            "SELECT COUNT(*) as cnt FROM outfits WHERE status = 'active'"
        ).fetchone()["cnt"]

        # Total wear events
        wear_count = db.execute("SELECT COUNT(*) as cnt FROM wear_events").fetchone()["cnt"]

        # All items with cost per wear, sorted by lifetime_wears desc
        all_items = db.execute(
            "SELECT * FROM items ORDER BY lifetime_wears DESC"
        ).fetchall()

        items_with_cpw = []
        for row in all_items:
            item = item_to_dict(row)
            if item["lifetime_wears"] > 0 and item["price"]:
                item["cost_per_wear"] = round(item["price"] / item["lifetime_wears"], 2)
            else:
                item["cost_per_wear"] = None
            items_with_cpw.append(item)

        # Neglected items: least worn / longest since worn
        # Sort by (lifetime_wears asc, last_worn asc nulls first)
        neglected = db.execute(
            """SELECT * FROM items
               ORDER BY lifetime_wears ASC,
                        CASE WHEN last_worn IS NULL THEN 0 ELSE 1 END,
                        last_worn ASC
               LIMIT 10"""
        ).fetchall()

        neglected_items = []
        for row in neglected:
            item = item_to_dict(row)
            if item["lifetime_wears"] > 0 and item["price"]:
                item["cost_per_wear"] = round(item["price"] / item["lifetime_wears"], 2)
            else:
                item["cost_per_wear"] = None
            neglected_items.append(item)

        # --- NEW: total_value (active items only) ---
        total_value_row = db.execute(
            "SELECT COALESCE(SUM(price), 0) as total FROM items WHERE lifecycle = 'active'"
        ).fetchone()
        total_value = total_value_row["total"]

        # --- NEW: best_cpw and worst_cpw ---
        # Eligible: price > 0, lifetime_wears > 0, active lifecycle
        eligible_rows = db.execute(
            """SELECT * FROM items
               WHERE price > 0 AND lifetime_wears > 0 AND lifecycle = 'active'"""
        ).fetchall()

        eligible_items = []
        for row in eligible_rows:
            item = item_to_dict(row)
            item["cost_per_wear"] = round(item["price"] / item["lifetime_wears"], 2)
            eligible_items.append(item)

        # Sort by cost_per_wear
        eligible_items.sort(key=lambda x: x["cost_per_wear"])

        best_cpw = eligible_items[:5]
        worst_cpw = eligible_items[-5:][::-1] if len(eligible_items) >= 5 else eligible_items[::-1]

        # --- NEW: by_category (active items) ---
        active_items = db.execute(
            "SELECT * FROM items WHERE lifecycle = 'active'"
        ).fetchall()

        by_category = defaultdict(lambda: {"count": 0, "total_value": 0, "total_wears": 0, "cpw_sum": 0, "cpw_count": 0})
        for row in active_items:
            item = item_to_dict(row)
            cat = item["category"]
            by_category[cat]["count"] += 1
            by_category[cat]["total_value"] += item["price"] or 0
            by_category[cat]["total_wears"] += item["lifetime_wears"]
            if item["price"] and item["price"] > 0 and item["lifetime_wears"] > 0:
                by_category[cat]["cpw_sum"] += item["price"] / item["lifetime_wears"]
                by_category[cat]["cpw_count"] += 1

        # Compute avg_cpw
        by_category_result = {}
        for cat, data in by_category.items():
            by_category_result[cat] = {
                "count": data["count"],
                "total_value": round(data["total_value"], 2),
                "total_wears": data["total_wears"],
                "avg_cpw": round(data["cpw_sum"] / data["cpw_count"], 2) if data["cpw_count"] > 0 else None
            }

        # --- NEW: by_brand (active items, top 8 by count, skip empty brand) ---
        by_brand = defaultdict(lambda: {"count": 0, "total_value": 0, "total_wears": 0, "cpw_sum": 0, "cpw_count": 0})
        for row in active_items:
            item = item_to_dict(row)
            brand = item["brand"]
            if not brand:
                continue
            by_brand[brand]["count"] += 1
            by_brand[brand]["total_value"] += item["price"] or 0
            by_brand[brand]["total_wears"] += item["lifetime_wears"]
            if item["price"] and item["price"] > 0 and item["lifetime_wears"] > 0:
                by_brand[brand]["cpw_sum"] += item["price"] / item["lifetime_wears"]
                by_brand[brand]["cpw_count"] += 1

        # Sort by count desc, take top 8
        sorted_brands = sorted(by_brand.items(), key=lambda x: x[1]["count"], reverse=True)[:8]
        by_brand_result = {}
        for brand, data in sorted_brands:
            by_brand_result[brand] = {
                "count": data["count"],
                "total_value": round(data["total_value"], 2),
                "total_wears": data["total_wears"],
                "avg_cpw": round(data["cpw_sum"] / data["cpw_count"], 2) if data["cpw_count"] > 0 else None
            }

        return {
            "totals": {
                "items": item_count,
                "outfits": outfit_count,
                "wears": wear_count,
            },
            "items": items_with_cpw,
            "neglected": neglected_items,
            "total_value": round(total_value, 2),
            "best_cpw": best_cpw,
            "worst_cpw": worst_cpw,
            "by_category": by_category_result,
            "by_brand": by_brand_result,
        }


@router.get("/analysis/gaps")
def get_gaps():
    """
    Analyze wardrobe gaps and bottlenecks.

    Returns:
    - coverage: {category: {season: count}} for active items
    - flags: warnings like "No <season> <category>" for essential categories
    - bottlenecks: top 10 items appearing in most active outfits
    - outfit_seasons: {season: count of active outfits tagged}
    - outfit_vibes: {vibe: count}
    """
    with get_db() as db:
        categories = get_category_names(db)
        seasons = get_setting(db, "season_tags") or []

        # Get all active items
        active_items = db.execute(
            "SELECT * FROM items WHERE lifecycle = 'active'"
        ).fetchall()

        # --- coverage: {category: {season: count}} ---
        # Items with empty season_tags count toward every season
        coverage = {cat: {s: 0 for s in seasons} for cat in categories}

        for row in active_items:
            item = item_to_dict(row)
            cat = item["category"]
            if cat not in coverage:
                coverage[cat] = {s: 0 for s in seasons}

            item_seasons = item["season_tags"]
            if not item_seasons:
                # Empty tags = counts for all seasons
                for s in seasons:
                    coverage[cat][s] += 1
            else:
                for s in item_seasons:
                    if s in seasons:
                        coverage[cat][s] += 1

        # --- flags: use shared function ---
        flags = compute_gap_flags(db)

        # --- bottlenecks: top 10 active items by how many active outfits contain them ---
        # Only include items appearing in >= 2 active outfits
        bottleneck_rows = db.execute(
            """SELECT i.id, i.number, i.name, COUNT(DISTINCT oi.outfit_id) as outfit_count
               FROM items i
               JOIN outfit_items oi ON oi.item_id = i.id
               JOIN outfits o ON o.id = oi.outfit_id
               WHERE i.lifecycle = 'active' AND o.status = 'active'
               GROUP BY i.id
               HAVING outfit_count >= 2
               ORDER BY outfit_count DESC
               LIMIT 10"""
        ).fetchall()

        bottlenecks = [
            {
                "id": row["id"],
                "number": row["number"],
                "name": row["name"],
                "outfit_count": row["outfit_count"]
            }
            for row in bottleneck_rows
        ]

        # --- outfit_seasons: {season: count of active outfits tagged} ---
        # Untagged outfits count toward every season
        active_outfits = db.execute(
            "SELECT * FROM outfits WHERE status = 'active'"
        ).fetchall()

        outfit_seasons = {s: 0 for s in seasons}
        outfit_vibes_count = defaultdict(int)
        vibe_tags_setting = get_setting(db, "vibe_tags") or []

        for row in active_outfits:
            outfit_season_tags = json.loads(row["season_tags"])
            outfit_vibe_tags = json.loads(row["vibe_tags"])

            if not outfit_season_tags:
                # Empty = counts for all seasons
                for s in seasons:
                    outfit_seasons[s] += 1
            else:
                for s in outfit_season_tags:
                    if s in seasons:
                        outfit_seasons[s] += 1

            if not outfit_vibe_tags:
                # Empty = counts for all vibes
                for v in vibe_tags_setting:
                    outfit_vibes_count[v] += 1
            else:
                for v in outfit_vibe_tags:
                    outfit_vibes_count[v] += 1

        return {
            "coverage": coverage,
            "flags": flags,
            "bottlenecks": bottlenecks,
            "outfit_seasons": outfit_seasons,
            "outfit_vibes": dict(outfit_vibes_count),
        }
