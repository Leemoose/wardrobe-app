"""Seed the wardrobe DB with realistic demo data for testing.

Usage (from the wardrobe-app folder):
    DATA_DIR="$PWD/data" python seed_demo.py

Refuses to run against a non-empty database — delete the data folder
(or the wardrobe.db inside it) to reseed from scratch.
"""
import json
import sys
from datetime import date, timedelta

from app.db import init_db, get_db

# number, name, category, brand, color, size, price, care, seasons, vibes, lifecycle
ITEMS = [
    (1, "White Oxford Shirt", "tops", "J.Crew", "white", "M", 80, "", ["spring", "summer", "fall"], ["work", "smart"], "active"),
    (2, "Navy Polo", "tops", "Uniqlo", "navy", "M", 30, "", ["summer"], ["casual", "work"], "active"),
    (3, "Grey Crewneck Tee", "tops", "Buck Mason", "grey", "M", 35, "", ["spring", "summer"], ["casual"], "active"),
    (4, "Cream Cable Sweater", "tops", "L.L.Bean", "cream", "M", 90, "", ["fall", "winter"], ["cozy", "casual"], "active"),
    (5, "Red Flannel Shirt", "tops", "Patagonia", "red plaid", "M", 70, "", ["fall", "winter"], ["casual", "cozy"], "active"),
    (6, "Dark Wash Jeans", "bottoms", "Levi's", "indigo", "32x32", 70, "", [], ["casual", "smart"], "active"),
    (7, "Khaki Chinos", "bottoms", "Bonobos", "khaki", "32x32", 90, "", ["spring", "summer", "fall"], ["work", "smart", "casual"], "active"),
    (8, "Charcoal Shorts", "bottoms", "Lululemon", "charcoal", "32", 60, "", ["summer"], ["casual", "athletic"], "active"),
    (9, "Grey Wool Trousers", "bottoms", "SuitSupply", "grey", "32", 140, "Dry clean only", ["fall", "winter"], ["work", "smart"], "active"),
    (10, "White Sneakers", "shoes", "Veja", "white", "10", 150, "", [], ["casual", "smart"], "active"),
    (11, "Brown Loafers", "shoes", "Meermin", "brown", "10", 180, "Leather — avoid heavy rain", ["spring", "summer", "fall"], ["work", "smart"], "active"),
    (12, "Trail Runners", "shoes", "Salomon", "black", "10", 130, "", [], ["athletic", "casual"], "active"),
    (13, "Tan Suede Chukkas", "shoes", "Clarks", "tan", "10", 120, "Suede — keep dry", ["spring", "fall"], ["casual", "smart"], "active"),
    (14, "Green Rain Shell", "outerwear", "Patagonia", "green", "M", 180, "", ["spring", "fall"], ["casual", "athletic"], "active"),
    (15, "Navy Blazer", "outerwear", "Spier & Mackay", "navy", "38R", 250, "", ["spring", "fall", "winter"], ["work", "smart"], "active"),
    (16, "Camel Wool Overcoat", "outerwear", "Uniqlo", "camel", "M", 300, "Dry clean only", ["winter"], ["work", "smart", "cozy"], "stored"),
    (17, "Brown Leather Belt", "accessories", "Anson", "brown", "34", 40, "Leather", [], ["work", "smart", "casual"], "active"),
    (18, "Navy Ball Cap", "accessories", "Ebbets Field", "navy", "OS", 25, "", ["spring", "summer"], ["casual", "athletic"], "active"),
    (19, "Old College Hoodie", "tops", "Champion", "grey", "L", 45, "", ["fall", "winter"], ["cozy", "casual"], "retired"),
]

# name, item numbers, seasons, vibes
OUTFITS = [
    ("Summer Casual", [3, 8, 10, 18], ["summer"], ["casual"]),
    ("Errand Run", [2, 6, 10], ["summer"], ["casual"]),
    ("Office Standard", [1, 7, 11, 17], ["spring", "summer", "fall"], ["work", "smart"]),
    ("Smart Dinner", [1, 6, 11, 15], ["spring", "fall"], ["smart"]),
    ("Rainy Day Walk", [3, 6, 12, 14], ["spring", "fall"], ["casual", "athletic"]),
    ("Fall Flannel", [5, 6, 13], ["fall"], ["casual"]),
]

# days_ago, outfit name (None = ad-hoc), item numbers, numbers marked dirty at the time
WEARS = [
    (20, "Office Standard", [1, 7, 11, 17], [1]),
    (18, "Summer Casual", [3, 8, 10, 18], [3, 8]),
    (15, "Errand Run", [2, 6, 10], [2]),
    (12, "Office Standard", [1, 7, 11, 17], [1, 7]),
    (9, "Smart Dinner", [1, 6, 11, 15], [1]),
    (7, None, [2, 8, 12], [2]),  # ad-hoc: polo + shorts + trail runners
    (4, "Errand Run", [2, 6, 10], [2]),
    (1, "Summer Casual", [3, 8, 10, 18], [3, 8]),
]

# Currently-dirty items so Laundry has content and one outfit is blocked.
DIRTY_NOW = [3, 8]  # blocks "Summer Casual"

# Extra lifetime wears predating the logged history (so stats look lived-in).
BASELINE_WEARS = {1: 14, 2: 9, 3: 11, 6: 30, 7: 16, 8: 7, 10: 38, 11: 12,
                  12: 22, 13: 4, 14: 6, 15: 5, 17: 40, 18: 10, 19: 60}


def main():
    init_db()
    with get_db() as db:
        if db.execute("SELECT COUNT(*) c FROM items").fetchone()["c"] > 0:
            sys.exit("Database is not empty — delete the data folder to reseed.")

        ids = {}
        for (num, name, cat, brand, color, size, price, care, seasons, vibes, life) in ITEMS:
            cur = db.execute(
                "INSERT INTO items (number, name, category, brand, color, size, price,"
                " care_notes, season_tags, vibe_tags, lifecycle) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (num, name, cat, brand, color, size, price, care,
                 json.dumps(seasons), json.dumps(vibes), life),
            )
            ids[num] = cur.lastrowid

        outfit_ids = {}
        for (name, members, seasons, vibes) in OUTFITS:
            cur = db.execute(
                "INSERT INTO outfits (name, season_tags, vibe_tags, source, status)"
                " VALUES (?,?,?, 'manual', 'active')",
                (name, json.dumps(seasons), json.dumps(vibes)),
            )
            outfit_ids[name] = cur.lastrowid
            for num in members:
                db.execute("INSERT INTO outfit_items (outfit_id, item_id) VALUES (?,?)",
                           (cur.lastrowid, ids[num]))

        wear_counts = {num: 0 for num in ids}
        last_worn = {}
        for (days_ago, outfit_name, members, dirty) in WEARS:
            d = (date.today() - timedelta(days=days_ago)).isoformat()
            cur = db.execute(
                "INSERT INTO wear_events (date, outfit_id) VALUES (?,?)",
                (d, outfit_ids[outfit_name] if outfit_name else None),
            )
            for num in members:
                db.execute(
                    "INSERT INTO wear_event_items (wear_event_id, item_id, marked_dirty)"
                    " VALUES (?,?,?)",
                    (cur.lastrowid, ids[num], 1 if num in dirty else 0),
                )
                wear_counts[num] += 1
                last_worn[num] = d

        for num, item_id in ids.items():
            lifetime = BASELINE_WEARS.get(num, 0) + wear_counts[num]
            dirty_now = num in DIRTY_NOW
            db.execute(
                "UPDATE items SET lifetime_wears=?, wears_since_wash=?, status=?,"
                " last_worn=? WHERE id=?",
                (lifetime,
                 2 if dirty_now else (1 if wear_counts[num] else 0),
                 "dirty" if dirty_now else "clean",
                 last_worn.get(num), item_id),
            )

    print(f"Seeded {len(ITEMS)} items, {len(OUTFITS)} outfits, {len(WEARS)} wear events.")
    print("Dirty right now: Grey Crewneck Tee, Charcoal Shorts (so 'Summer Casual' is blocked).")


if __name__ == "__main__":
    main()
