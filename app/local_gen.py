"""Rule-based local outfit generation - no API key required.

Slots are data-driven (v1.3): each category in settings carries a role
(required/optional), a pick probability, a weather affinity, and a display
group. Tune them in Settings -> Categories.
"""
import math
import random
from typing import Optional


# At most this many items from the "accessories" group per generated outfit,
# regardless of individual category probabilities.
MAX_ACCESSORY_PICKS = 2

# Weather affinity -> implied seasons for items with no season tags.
# A scarf with no tags still shouldn't land in a summer outfit.
WEATHER_IMPLIED_SEASONS = {
    "cold": ["fall", "winter"],
    "sun": ["summer"],
}


def _effective_season_tags(item: dict, category: dict) -> list:
    """Item's season tags, falling back to the category's weather affinity."""
    if item.get("season_tags"):
        return item["season_tags"]
    return WEATHER_IMPLIED_SEASONS.get(category.get("weather", "any"), [])


def generate_local_outfits(db, count: int) -> list:
    """
    Generate outfits using rule-based logic.

    Args:
        db: Database connection (from get_db context)
        count: Number of outfits to generate

    Returns:
        List of outfit dicts with keys: name, item_numbers, season_tags, vibe_tags, note

    Raises:
        ValueError: If required categories are missing items
    """
    from app.db import item_to_dict, get_setting, get_categories
    import json

    # Load category behavior rules from settings
    categories = get_categories(db)
    cat_by_name = {c["name"].lower(): c for c in categories}
    required_slots = [c["name"].lower() for c in categories if c["role"] == "required"]
    optional_slots = [c for c in categories if c["role"] == "optional"]

    if not required_slots:
        raise ValueError(
            "No required categories configured - mark at least one category "
            "as 'required' in Settings"
        )

    # Load all active items (clean + dirty - generation is about the library)
    item_rows = db.execute(
        "SELECT * FROM items WHERE lifecycle = 'active' ORDER BY number"
    ).fetchall()
    items = [item_to_dict(row) for row in item_rows]

    if not items:
        raise ValueError("No items in wardrobe")

    # Group items by category
    items_by_category = {}
    for item in items:
        cat = item["category"].lower()
        if cat not in items_by_category:
            items_by_category[cat] = []
        items_by_category[cat].append(item)

    # Verify required slots have items
    missing = []
    for slot in required_slots:
        if slot not in items_by_category or not items_by_category[slot]:
            missing.append(slot)

    if missing:
        raise ValueError(
            f"Cannot generate outfits: missing items in required categories: {', '.join(missing)}"
        )

    # Load existing non-rejected outfits to avoid duplicates
    existing_rows = db.execute(
        "SELECT o.id FROM outfits o WHERE o.status IN ('active', 'pending')"
    ).fetchall()

    existing_combos = set()
    for row in existing_rows:
        outfit_id = row["id"]
        item_ids = db.execute(
            "SELECT item_id FROM outfit_items WHERE outfit_id = ?", (outfit_id,)
        ).fetchall()
        existing_combos.add(frozenset(r["item_id"] for r in item_ids))

    # Track item usage within this batch
    item_usage = {}  # item_id -> count
    max_usage_per_item = math.ceil(count / 2)

    # Track batch combos
    batch_combos = set()
    batch_outfits = []  # list of (frozenset of ids, outfit_dict)

    # Get season tags from settings for reference
    season_tags_setting = get_setting(db, "season_tags") or []

    # Color harmony rules (neutrals, statement-color cap, never-pair list)
    color_rules = get_setting(db, "color_rules") or {}

    for _ in range(count):
        outfit = _try_generate_one(
            items_by_category,
            existing_combos,
            batch_combos,
            batch_outfits,
            item_usage,
            max_usage_per_item,
            season_tags_setting,
            required_slots,
            optional_slots,
            cat_by_name,
            color_rules,
        )
        if outfit is None:
            # Could not generate a valid outfit (exhausted options)
            break

        item_ids, outfit_dict = outfit
        batch_combos.add(item_ids)
        batch_outfits.append((item_ids, outfit_dict))

        # Update usage
        for item_id in item_ids:
            item_usage[item_id] = item_usage.get(item_id, 0) + 1

    return [o[1] for o in batch_outfits]


def _try_generate_one(
    items_by_category: dict,
    existing_combos: set,
    batch_combos: set,
    batch_outfits: list,
    item_usage: dict,
    max_usage: int,
    all_seasons: list,
    required_slots: list,
    optional_slots: list,
    cat_by_name: dict,
    color_rules: Optional[dict] = None,
    max_attempts: int = 200,
) -> Optional[tuple]:
    """
    Try to generate one valid outfit.

    Returns:
        Tuple of (frozenset of item_ids, outfit_dict) or None if failed
    """
    for _ in range(max_attempts):
        outfit_items = []

        # Pick required items
        valid = True
        for slot in required_slots:
            candidates = _get_available_candidates(
                items_by_category.get(slot, []), item_usage, max_usage
            )
            if not candidates:
                valid = False
                break
            outfit_items.append(random.choice(candidates))

        if not valid:
            continue

        # Pick optional items, respecting per-category probability, the
        # accessories-group cap, and max_per_outfit exclusivity.
        accessory_picks = 0
        shuffled_optional = list(optional_slots)
        random.shuffle(shuffled_optional)
        for cat in shuffled_optional:
            slot = cat["name"].lower()
            if slot not in items_by_category:
                continue
            is_accessory = cat.get("group") == "accessories"
            if is_accessory and accessory_picks >= MAX_ACCESSORY_PICKS:
                continue
            if random.random() >= cat.get("pick_prob", 0.2):
                continue
            candidates = _get_available_candidates(
                items_by_category[slot], item_usage, max_usage
            )
            # Exclusivity: don't exceed max_per_outfit for this category
            already = sum(
                1 for i in outfit_items if i["category"].lower() == slot
            )
            if already >= cat.get("max_per_outfit", 1) or not candidates:
                continue
            outfit_items.append(random.choice(candidates))
            if is_accessory:
                accessory_picks += 1

        # Color harmony check (neutrals pair with anything; cap statement
        # colors; respect never-pair list). Retry loop handles rejects.
        if not _color_ok(outfit_items, color_rules):
            continue

        # Compute season compatibility. Untagged items inherit an implied
        # season from their category's weather affinity (scarf -> fall/winter).
        effective_tags = []
        for item in outfit_items:
            cat = cat_by_name.get(item["category"].lower(), {})
            effective_tags.append(_effective_season_tags(item, cat))
        outfit_seasons = _compute_tag_intersection(effective_tags, all_seasons)
        # If intersection is empty but not all items have empty tags, skip
        if outfit_seasons is None:
            continue

        # Compute vibe compatibility (soft - we allow empty)
        outfit_vibes = _compute_tag_intersection(
            [item["vibe_tags"] for item in outfit_items], None
        )
        if outfit_vibes is None:
            outfit_vibes = []

        # Check for duplicate item-set
        item_ids = frozenset(item["id"] for item in outfit_items)

        if item_ids in existing_combos or item_ids in batch_combos:
            continue

        # Check overlap with batch outfits (>=2 shared items)
        # Only reject if alternatives exist (we're in a retry loop anyway)
        too_similar = False
        for existing_ids, _ in batch_outfits:
            shared = len(item_ids & existing_ids)
            if shared >= 2:
                too_similar = True
                break

        if too_similar:
            continue

        # Build outfit dict
        top = next((i for i in outfit_items if i["category"].lower() == "tops"), None)
        bottom = next(
            (i for i in outfit_items if i["category"].lower() == "bottoms"), None
        )

        # Name generation
        name = _generate_name(outfit_items, top, bottom, outfit_vibes)

        # Note generation
        note_parts = []
        if outfit_vibes:
            note_parts.append(f"shared vibe '{outfit_vibes[0]}'")
        if outfit_seasons:
            note_parts.append(f"{'/'.join(outfit_seasons)}-compatible")

        note = "Rule-based: " + (", ".join(note_parts) if note_parts else "mixed items")

        outfit_dict = {
            "name": name,
            "item_numbers": [item["number"] for item in outfit_items],
            "season_tags": outfit_seasons,
            "vibe_tags": outfit_vibes,
            "note": note,
        }

        return (item_ids, outfit_dict)

    return None


def _color_ok(outfit_items: list, rules: Optional[dict]) -> bool:
    """
    Check color harmony for a candidate outfit.

    - Items with no color set are ignored.
    - A color containing any neutral keyword (substring match) is neutral.
    - At most `max_statement_colors` distinct non-neutral colors allowed.
    - No two colors from any `never_pair` [a, b] entry may co-occur.
    """
    if not rules or not rules.get("enabled", False):
        return True

    neutrals = [str(n).strip().lower() for n in rules.get("neutrals", []) if str(n).strip()]
    colors = [
        i.get("color", "").strip().lower()
        for i in outfit_items
        if i.get("color", "").strip()
    ]
    if not colors:
        return True

    def is_neutral(color):
        return any(n in color for n in neutrals)

    statement = {c for c in colors if not is_neutral(c)}
    try:
        max_statement = max(0, int(rules.get("max_statement_colors", 1)))
    except (TypeError, ValueError):
        max_statement = 1
    if len(statement) > max_statement:
        return False

    for pair in rules.get("never_pair", []):
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        a = str(pair[0]).strip().lower()
        b = str(pair[1]).strip().lower()
        if not a or not b:
            continue
        has_a = any(a in c for c in colors)
        has_b = any(b in c for c in colors)
        if has_a and has_b:
            return False

    return True


def _get_available_candidates(items: list, usage: dict, max_usage: int) -> list:
    """Filter items that haven't exceeded max usage."""
    return [i for i in items if usage.get(i["id"], 0) < max_usage]


def _compute_tag_intersection(tag_lists: list, all_tags: Optional[list]) -> Optional[list]:
    """
    Compute intersection of tag sets.

    - Empty tags on an item = fits all (universal)
    - Returns the intersection of non-empty tag sets
    - If all are empty, returns []
    - If intersection would be empty (incompatible), returns None
    """
    non_empty = [set(tags) for tags in tag_lists if tags]

    if not non_empty:
        # All items have empty tags
        return []

    result = non_empty[0]
    for tag_set in non_empty[1:]:
        result = result & tag_set

    if not result:
        # Incompatible tags
        return None

    return sorted(result)


def _generate_name(
    outfit_items: list,
    top: Optional[dict],
    bottom: Optional[dict],
    vibes: list,
) -> str:
    """Generate a readable outfit name."""
    # Try color + name approach
    if top and bottom:
        top_color = top.get("color", "").strip()
        top_name = top.get("name", "Top")
        bottom_name = bottom.get("name", "Bottom")

        # Only add color prefix if name doesn't already start with it
        if top_color and not top_name.lower().startswith(top_color.lower()):
            name = f"{top_color.title()} {top_name} + {bottom_name}"
        else:
            name = f"{top_name} + {bottom_name}"

        # Truncate if too long
        if len(name) > 50:
            if vibes:
                return f"{vibes[0].title()} combo"
            return name[:47] + "..."

        return name

    # Fallback: vibe-based or generic
    if vibes:
        return f"{vibes[0].title()} combo"

    return "Mixed outfit"
