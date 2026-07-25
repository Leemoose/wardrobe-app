"""SQLite layer. Plain sqlite3, no ORM — easy to read and hack on."""
import json
import os
import sqlite3
from contextlib import contextmanager

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "wardrobe.db")
PHOTO_DIR = os.path.join(DATA_DIR, "photos")

# Categories carry behavior (v1.3):
#   role: "required" | "optional" - required categories form the core of every
#         generated outfit; optional ones are added probabilistically.
#   weather: "any" | "cold" | "sun" - affinity used by the generator (as a
#         default season constraint for untagged items), daily suggestions,
#         and trip packing (cold days pull in scarves, sunny days sunglasses).
#   max_per_outfit: exclusivity - you wear one watch, but maybe two bracelets.
#   pick_prob: chance the generator includes this optional category.
#   group: display grouping in the UI ("" = top-level, "accessories" collapses
#         into one closet filter chip).
DEFAULT_CATEGORIES = [
    {"name": "tops", "role": "required", "weather": "any", "max_per_outfit": 1, "pick_prob": 1.0, "group": ""},
    {"name": "bottoms", "role": "required", "weather": "any", "max_per_outfit": 1, "pick_prob": 1.0, "group": ""},
    {"name": "shoes", "role": "required", "weather": "any", "max_per_outfit": 1, "pick_prob": 1.0, "group": "", "rest_days": 1},
    {"name": "outerwear", "role": "optional", "weather": "cold", "max_per_outfit": 1, "pick_prob": 0.4, "group": ""},
    {"name": "accessories", "role": "optional", "weather": "any", "max_per_outfit": 1, "pick_prob": 0.15, "group": "accessories"},
    {"name": "watch", "role": "optional", "weather": "any", "max_per_outfit": 1, "pick_prob": 0.25, "group": "accessories"},
    {"name": "bracelet", "role": "optional", "weather": "any", "max_per_outfit": 2, "pick_prob": 0.15, "group": "accessories"},
    {"name": "necklace", "role": "optional", "weather": "any", "max_per_outfit": 1, "pick_prob": 0.15, "group": "accessories"},
    {"name": "belt", "role": "optional", "weather": "any", "max_per_outfit": 1, "pick_prob": 0.3, "group": "accessories"},
    {"name": "scarf", "role": "optional", "weather": "cold", "max_per_outfit": 1, "pick_prob": 0.3, "group": "accessories"},
    {"name": "gloves", "role": "optional", "weather": "cold", "max_per_outfit": 1, "pick_prob": 0.2, "group": "accessories"},
    {"name": "beanie", "role": "optional", "weather": "cold", "max_per_outfit": 1, "pick_prob": 0.2, "group": "accessories"},
    {"name": "sun hat", "role": "optional", "weather": "sun", "max_per_outfit": 1, "pick_prob": 0.2, "group": "accessories"},
    {"name": "sunglasses", "role": "optional", "weather": "sun", "max_per_outfit": 1, "pick_prob": 0.3, "group": "accessories"},
    {"name": "bag", "role": "optional", "weather": "any", "max_per_outfit": 1, "pick_prob": 0.2, "group": "accessories"},
]

DEFAULT_SETTINGS = {
    "location_name": "Philadelphia, PA",
    "latitude": 39.9526,
    "longitude": -75.1652,
    "categories": DEFAULT_CATEGORIES,
    "season_tags": ["spring", "summer", "fall", "winter"],
    "vibe_tags": ["casual", "work", "smart", "athletic", "going-out", "cozy"],
    # Material tags available on items; used to match care guides.
    "materials": [
        "leather", "suede", "canvas", "cotton", "denim", "wool", "cashmere",
        "silk", "linen", "synthetic", "down", "velvet", "corduroy", "metal",
        "rubber",
    ],
    # Wears since wash after which the app suggests "now dirty". 0 = never suggest.
    "dirty_thresholds": {
        "tops": 1,
        "bottoms": 3,
        "shoes": 0,
        "outerwear": 8,
        "accessories": 0,
        "watch": 0,
        "bracelet": 0,
        "necklace": 0,
        "belt": 0,
        "scarf": 5,
        "gloves": 5,
        "beanie": 5,
        "sun hat": 8,
        "sunglasses": 0,
        "bag": 0,
    },
    # Temperature (F) bands used to pick today's season from live weather.
    "season_temp_bands": {"summer_min_f": 75, "winter_max_f": 45},
    # Number of days before an outfit can be re-suggested (0 = disabled).
    "no_repeat_days": 3,
    # Color harmony rules used by local outfit generation.
    # neutrals: colors that pair with anything (substring match, lowercase).
    # max_statement_colors: max distinct non-neutral colors per outfit.
    # never_pair: list of [colorA, colorB] pairs that must not appear together.
    "color_rules": {
        "enabled": True,
        "neutrals": [
            "black", "white", "gray", "grey", "navy", "beige", "tan",
            "cream", "brown", "khaki", "denim", "charcoal", "olive",
        ],
        "max_statement_colors": 1,
        "never_pair": [],
    },
    # Care-kit supplies the user already owns (lower-cased names).
    "care_supplies_owned": [],
    # Weather-based outfit warnings configuration.
    "weather_rules": {
        "rain_precip_threshold": 50,
        "outerwear_below_f": 50,
        "no_outerwear_above_f": 75,
        "sensitive_materials": ["suede", "leather"],
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT DEFAULT '',
    color TEXT DEFAULT '',
    size TEXT DEFAULT '',
    price REAL DEFAULT 0,
    paid_price REAL DEFAULT 0,
    materials TEXT DEFAULT '[]',
    measurements TEXT DEFAULT '{}',
    care_notes TEXT DEFAULT '',
    photo TEXT DEFAULT '',
    season_tags TEXT DEFAULT '[]',
    vibe_tags TEXT DEFAULT '[]',
    status TEXT DEFAULT 'clean' CHECK (status IN ('clean','dirty')),
    lifecycle TEXT DEFAULT 'active' CHECK (lifecycle IN ('active','stored','retired')),
    wears_since_wash INTEGER DEFAULT 0,
    lifetime_wears INTEGER DEFAULT 0,
    last_worn TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS item_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    sort INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS outfits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    season_tags TEXT DEFAULT '[]',
    vibe_tags TEXT DEFAULT '[]',
    source TEXT DEFAULT 'manual' CHECK (source IN ('manual','ai')),
    status TEXT DEFAULT 'active' CHECK (status IN ('active','pending','rejected')),
    ai_note TEXT DEFAULT '',
    photo TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS outfit_items (
    outfit_id INTEGER NOT NULL REFERENCES outfits(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    PRIMARY KEY (outfit_id, item_id)
);

CREATE TABLE IF NOT EXISTS wear_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    outfit_id INTEGER REFERENCES outfits(id) ON DELETE SET NULL,
    photo TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wear_event_items (
    wear_event_id INTEGER NOT NULL REFERENCES wear_events(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    marked_dirty INTEGER DEFAULT 0,
    PRIMARY KEY (wear_event_id, item_id)
);

CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    name TEXT DEFAULT '',
    brand TEXT DEFAULT '',
    price REAL DEFAULT 0,
    image TEXT DEFAULT '',
    category TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    destination TEXT DEFAULT '',
    latitude REAL DEFAULT NULL,
    longitude REAL DEFAULT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    notes TEXT DEFAULT '',
    status TEXT DEFAULT 'planning' CHECK (status IN ('planning','active','archived')),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trip_items (
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    packed INTEGER DEFAULT 0,
    source TEXT DEFAULT 'manual' CHECK (source IN ('manual','outfit','auto')),
    PRIMARY KEY (trip_id, item_id)
);

CREATE TABLE IF NOT EXISTS trip_outfits (
    trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    outfit_id INTEGER NOT NULL REFERENCES outfits(id) ON DELETE CASCADE,
    PRIMARY KEY (trip_id, outfit_id)
);

CREATE TABLE IF NOT EXISTS maintenance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    task TEXT NOT NULL,
    date TEXT NOT NULL,
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Indexes (v1.5): all idempotent; cover the hot filter/join paths.
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
CREATE INDEX IF NOT EXISTS idx_items_lifecycle ON items(lifecycle);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_item_photos_item ON item_photos(item_id);
CREATE INDEX IF NOT EXISTS idx_outfit_items_item ON outfit_items(item_id);
CREATE INDEX IF NOT EXISTS idx_wear_events_date ON wear_events(date);
CREATE INDEX IF NOT EXISTS idx_wear_event_items_item ON wear_event_items(item_id);
CREATE INDEX IF NOT EXISTS idx_maintenance_events_item ON maintenance_events(item_id);
"""

# Properties applied to categories that only exist as bare strings
# (user-created via old UI, or CSV imports).
_CATEGORY_DEFAULTS = {"role": "optional", "weather": "any", "max_per_outfit": 1, "pick_prob": 0.2, "group": "", "rest_days": 0}


def normalize_category(cat):
    """Coerce a category entry (string or dict) into a full behavior dict."""
    if isinstance(cat, str):
        base = {"name": cat}
    else:
        base = dict(cat)
    known = next((d for d in DEFAULT_CATEGORIES if d["name"] == base.get("name")), None)
    template = known or _CATEGORY_DEFAULTS
    for key, val in template.items():
        base.setdefault(key, val)
    # Clamp/sanitize
    base["role"] = base["role"] if base["role"] in ("required", "optional") else "optional"
    base["weather"] = base["weather"] if base["weather"] in ("any", "cold", "sun") else "any"
    try:
        base["max_per_outfit"] = max(1, int(base["max_per_outfit"]))
    except (TypeError, ValueError):
        base["max_per_outfit"] = 1
    try:
        base["pick_prob"] = min(1.0, max(0.0, float(base["pick_prob"])))
    except (TypeError, ValueError):
        base["pick_prob"] = 0.2
    base["group"] = str(base.get("group") or "")
    try:
        base["rest_days"] = max(0, int(base.get("rest_days", 0)))
    except (TypeError, ValueError):
        base["rest_days"] = 0
    return base


def normalize_categories(raw):
    """Normalize a categories setting value (handles legacy list-of-strings)."""
    if not isinstance(raw, list):
        return [dict(c) for c in DEFAULT_CATEGORIES]
    seen = set()
    result = []
    for cat in raw:
        norm = normalize_category(cat)
        if norm["name"] and norm["name"] not in seen:
            seen.add(norm["name"])
            result.append(norm)
    return result


def get_categories(db):
    """Return the categories setting as a normalized list of behavior dicts."""
    return normalize_categories(get_setting(db, "categories"))


def get_category_names(db):
    """Return just the category names, in order."""
    return [c["name"] for c in get_categories(db)]


# Keyword -> material used for the one-time inference migration.
_MATERIAL_KEYWORDS = {
    "suede": "suede",
    "nubuck": "suede",
    "leather": "leather",
    "canvas": "canvas",
    "denim": "denim",
    "jean": "denim",
    "wool": "wool",
    "merino": "wool",
    "cashmere": "cashmere",
    "silk": "silk",
    "linen": "linen",
    "cotton": "cotton",
    "nylon": "synthetic",
    "polyester": "synthetic",
    "fleece": "synthetic",
    "down": "down",
    "puffer": "down",
    "velvet": "velvet",
    "corduroy": "corduroy",
}


def infer_materials(name, care_notes=""):
    """Guess material tags from free text (item name + care notes)."""
    text = f"{name or ''} {care_notes or ''}".lower()
    found = []
    for keyword, material in _MATERIAL_KEYWORDS.items():
        if keyword in text and material not in found:
            found.append(material)
    return found


def _infer_materials_for_existing_items(db):
    """One-time inference, run only when the materials column is created."""
    rows = db.execute("SELECT id, name, care_notes FROM items").fetchall()
    for row in rows:
        materials = infer_materials(row["name"], row["care_notes"])
        if materials:
            db.execute(
                "UPDATE items SET materials = ? WHERE id = ?",
                (json.dumps(materials), row["id"]),
            )


def _add_column(db, table, column_def, label):
    """Idempotent ALTER TABLE ADD COLUMN with logging. Returns True if added."""
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        print(f"[wardrobe] migration applied: {label}")
        return True
    except sqlite3.OperationalError:
        # Column already exists
        return False


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(PHOTO_DIR, exist_ok=True)
    with get_db() as db:
        # WAL journal mode (v1.5): persistent setting stored in the DB file.
        # Readers no longer block writers; more robust to abrupt container stops.
        mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if mode != "wal":
            print(f"[wardrobe] warning: journal_mode is {mode}, expected wal")
        db.executescript(SCHEMA)
        # Migration: add lifecycle column to existing databases
        _add_column(
            db, "items",
            "lifecycle TEXT DEFAULT 'active' CHECK (lifecycle IN ('active','stored','retired'))",
            "items.lifecycle (v1.1)",
        )

        # Migration: add photo column to wear_events
        _add_column(db, "wear_events", "photo TEXT DEFAULT ''", "wear_events.photo (v1.2)")

        # Migration: add photo column to outfits
        _add_column(db, "outfits", "photo TEXT DEFAULT ''", "outfits.photo (v1.2)")

        # Migration (v1.4): add materials column to items. When the column is
        # first created, infer materials once from item name + care notes so
        # existing wardrobes get sensible starting values (user can edit).
        if _add_column(db, "items", "materials TEXT DEFAULT '[]'", "items.materials (v1.4)"):
            _infer_materials_for_existing_items(db)

        # Migration (v1.6): paid_price tracks the actual amount paid, separate
        # from `price` (retail/list). Backfill existing rows with price so
        # cost-per-wear stays accurate for items added before this column.
        if _add_column(db, "items", "paid_price REAL DEFAULT 0", "items.paid_price (v1.6)"):
            db.execute("UPDATE items SET paid_price = price WHERE paid_price = 0")

        # Migration (v1.7): measurements stores category-specific garment
        # dimensions as a JSON object, e.g. pants:
        # {"waist": "32", "inseam": "32.5", "leg_opening": "15",
        #  "front_rise": "10.5", "back_rise": "15", "fit": "slim straight"}.
        # Keys are free-form so each category can hold its own relevant fields.
        _add_column(db, "items", "measurements TEXT DEFAULT '{}'", "items.measurements (v1.7)")

        # Migration (v1.5): maintenance event kind + cost (repair/alteration log).
        _add_column(
            db, "maintenance_events",
            "kind TEXT DEFAULT 'care' CHECK (kind IN ('care','repair','alteration','professional'))",
            "maintenance_events.kind (v1.5)",
        )
        _add_column(db, "maintenance_events", "cost REAL DEFAULT 0", "maintenance_events.cost (v1.5)")

        # Migration: migrate legacy item photos to item_photos table
        # Items with photo != '' but no corresponding item_photos row
        legacy_items = db.execute(
            """SELECT id, photo FROM items
               WHERE photo != ''
               AND NOT EXISTS (SELECT 1 FROM item_photos WHERE item_id = items.id)"""
        ).fetchall()
        for item in legacy_items:
            # Extract filename from photo URL (e.g., "/photos/123.jpg" -> "123.jpg")
            photo_url = item["photo"]
            filename = photo_url.split("/")[-1] if "/" in photo_url else photo_url
            db.execute(
                "INSERT INTO item_photos (item_id, filename, sort) VALUES (?, ?, 0)",
                (item["id"], filename),
            )

        for key, val in DEFAULT_SETTINGS.items():
            db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, json.dumps(val)),
            )

        # Migration (v1.3): categories string-list -> behavior objects.
        # Preserves user-created categories, upgrades known ones with default
        # behavior, and adds the new default accessory categories once.
        raw_cats = get_setting(db, "categories")
        if isinstance(raw_cats, list) and any(isinstance(c, str) for c in raw_cats):
            migrated = normalize_categories(raw_cats)
            existing_names = {c["name"] for c in migrated}
            for default_cat in DEFAULT_CATEGORIES:
                if default_cat["name"] not in existing_names:
                    migrated.append(dict(default_cat))
            set_setting(db, "categories", migrated)

            # Merge new per-category dirty threshold defaults (keep user values)
            thresholds = get_setting(db, "dirty_thresholds") or {}
            for name, val in DEFAULT_SETTINGS["dirty_thresholds"].items():
                thresholds.setdefault(name, val)
            set_setting(db, "dirty_thresholds", thresholds)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_setting(db, key):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return DEFAULT_SETTINGS.get(key)
    return json.loads(row["value"])


def set_setting(db, key, value):
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


def photo_url(filename):
    """Public URL for a stored photo filename."""
    return f"/photos/{filename}"


def thumb_url_for(photo):
    """Thumbnail URL for a photo URL/filename, if the thumb exists on disk.

    Falls back to the original URL when no thumbnail is present (e.g. photos
    uploaded before v1.5, until the startup backfill has run).
    """
    if not photo:
        return photo
    filename = photo.split("/")[-1]
    if os.path.exists(os.path.join(PHOTO_DIR, "thumbs", filename)):
        return f"/photos/thumbs/{filename}"
    return photo if photo.startswith("/") else photo_url(filename)


def _photos_for_items(db, item_ids):
    """Batch-fetch photos for many items in one query -> {item_id: [dicts]}."""
    ids = list(item_ids)
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT id, item_id, filename FROM item_photos "
        f"WHERE item_id IN ({placeholders}) ORDER BY sort, id",
        ids,
    ).fetchall()
    result = {}
    for p in rows:
        result.setdefault(p["item_id"], []).append(
            {"id": p["id"], "url": photo_url(p["filename"]),
             "thumb": thumb_url_for(p["filename"])}
        )
    return result


def item_to_dict(row, db=None, photos_map=None):
    """Convert item row to dict.

    Photos are included when either `photos_map` (batch-prefetched via
    `_photos_for_items`) or a `db` connection is provided. Prefer passing
    `photos_map` when serializing lists to avoid N+1 queries.
    """
    d = dict(row)
    d.pop("_outfit_id", None)  # internal join alias, never expose
    d["season_tags"] = json.loads(d["season_tags"])
    d["vibe_tags"] = json.loads(d["vibe_tags"])
    # Ensure lifecycle is present (may be None for old DBs before migration runs)
    if "lifecycle" not in d or d["lifecycle"] is None:
        d["lifecycle"] = "active"
    # Materials (may be absent/None before v1.4 migration runs)
    d["materials"] = json.loads(d.get("materials") or "[]")
    # Measurements (may be absent/None before v1.7 migration runs)
    d["measurements"] = json.loads(d.get("measurements") or "{}")
    # Small thumbnail for grid views (v1.5); falls back to full photo.
    d["photo_thumb"] = thumb_url_for(d.get("photo") or "")
    if photos_map is not None:
        d["photos"] = photos_map.get(d["id"], [])
    elif db is not None:
        photo_rows = db.execute(
            "SELECT id, filename FROM item_photos WHERE item_id = ? ORDER BY sort, id",
            (d["id"],),
        ).fetchall()
        d["photos"] = [
            {"id": p["id"], "url": photo_url(p["filename"]),
             "thumb": thumb_url_for(p["filename"])}
            for p in photo_rows
        ]
    return d


def items_to_dicts(rows, db):
    """Serialize many item rows with photos using exactly one extra query."""
    photos_map = _photos_for_items(db, [r["id"] for r in rows])
    return [item_to_dict(r, photos_map=photos_map) for r in rows]


def _outfit_dict(row, item_dicts):
    """Assemble an outfit dict from its row and pre-serialized member items."""
    d = dict(row)
    d["season_tags"] = json.loads(d["season_tags"])
    d["vibe_tags"] = json.loads(d["vibe_tags"])
    # Ensure photo field exists (may be None for old DBs before migration runs)
    if "photo" not in d or d["photo"] is None:
        d["photo"] = ""
    d["items"] = item_dicts
    # Outfit is available only if all items are clean AND active lifecycle
    d["available"] = (
        len(item_dicts) > 0
        and all(i["status"] == "clean" for i in item_dicts)
        and all((i["lifecycle"] or "active") == "active" for i in item_dicts)
    )
    # has_collage: True if any member item has a cover photo
    d["has_collage"] = any(i.get("photo") for i in item_dicts)
    return d


def outfits_to_dicts(db, rows):
    """Serialize many outfit rows using three queries total (not 2 per outfit).

    Replaces the per-outfit item query + per-item photo query pattern.
    """
    rows = list(rows)
    if not rows:
        return []
    outfit_ids = [r["id"] for r in rows]
    placeholders = ",".join("?" * len(outfit_ids))
    item_rows = db.execute(
        f"SELECT oi.outfit_id AS _outfit_id, i.* FROM items i "
        f"JOIN outfit_items oi ON oi.item_id = i.id "
        f"WHERE oi.outfit_id IN ({placeholders}) ORDER BY i.number",
        outfit_ids,
    ).fetchall()
    photos_map = _photos_for_items(db, {r["id"] for r in item_rows})
    by_outfit = {}
    for r in item_rows:
        by_outfit.setdefault(r["_outfit_id"], []).append(
            item_to_dict(r, photos_map=photos_map)
        )
    return [_outfit_dict(row, by_outfit.get(row["id"], [])) for row in rows]


def outfit_to_dict(db, row):
    """Single-outfit serialization (kept for existing call sites)."""
    return outfits_to_dicts(db, [row])[0]
