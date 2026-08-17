"""Scent picking: score a fragrance against today's weather and occasion.

The garment side of the app answers "what is clean and seasonal?". A bottle is
never dirty, so the question here is different — which of the things you own
suits this temperature, this hour, and this occasion, and which have you worn
too recently to smell on yourself any more.

Kept separate from the router for the same reason `weather.py` is: the rules
are the interesting part and they are worth reading without FastAPI noise.
"""
from datetime import date

# Concentration ordered light -> heavy. The index is what the temperature rules
# read: hot weather wants the low end, cold weather the high end.
_CONCENTRATION_WEIGHT = {
    "cologne": 0,
    "edc": 0,
    "edt": 1,
    "edp": 2,
    "parfum": 3,
    "oil": 3,
}

# Families that read as light/fresh and the ones that read as heavy. Used the
# same way as concentration, because a citrus EDP still wears lighter than a
# tobacco one.
_LIGHT_FAMILIES = {"citrus", "aquatic", "fresh", "green", "aromatic", "fougere"}
_HEAVY_FAMILIES = {"amber", "oriental", "gourmand", "leather", "tobacco", "woody", "spicy"}

_SILLAGE_WEIGHT = {"intimate": 0, "moderate": 1, "strong": 2}


def period_for_hour(hour: int) -> str:
    """Day or night, by local hour. Evening starts at 17:00."""
    return "day" if 5 <= hour < 17 else "night"


def _days_since(last_worn, today: date):
    """Whole days between `last_worn` (YYYY-MM-DD or None) and today."""
    if not last_worn:
        return None
    try:
        return (today - date.fromisoformat(str(last_worn)[:10])).days
    except ValueError:
        return None


def score_fragrance(frag: dict, season: str, weather: dict, rules: dict,
                    occasion: str = "", period: str = "day",
                    today: date = None, strict: bool = True) -> dict:
    """Score one fragrance for today. Returns {score, reasons, skip_reason}.

    A `skip_reason` means the bottle is disqualified outright (not owned, empty,
    or tagged for a season/occasion that isn't today's) and the caller should
    leave it out of the suggestions rather than ranking it low.

    With `strict=False` the season and occasion tags stop disqualifying and only
    contribute to the score. That is the fallback for a small collection where
    every bottle is tagged for some other season — better to rank what you have
    and say so than to show an empty card.
    """
    today = today or date.today()
    reasons = []

    # Only bottles you actually own can be suggested. A scent you rated after
    # sampling it in a shop belongs in the journal, not in this morning's pick.
    if (frag.get("status") or "owned") != "owned":
        return {"score": 0, "reasons": [], "skip_reason": "not owned"}

    size = frag.get("size_ml") or 0
    if size > 0 and (frag.get("remaining_ml") or 0) <= 0:
        return {"score": 0, "reasons": [], "skip_reason": "bottle empty"}

    # Tags are an opt-in constraint: an untagged bottle is a candidate for
    # everything, exactly as untagged garments behave in /suggest.
    season_tags = frag.get("season_tags") or []
    season_match = season in season_tags
    if strict and season_tags and not season_match:
        return {"score": 0, "reasons": [], "skip_reason": f"not tagged for {season}"}

    vibe_tags = frag.get("vibe_tags") or []
    occasion_match = bool(occasion) and occasion in vibe_tags
    if strict and occasion and vibe_tags and not occasion_match:
        return {"score": 0, "reasons": [], "skip_reason": f"not tagged for {occasion}"}

    score = 0.0

    if season_match:
        score += 2
        reasons.append(f"tagged for {season}")
    elif season_tags:
        score -= 1.5
    if occasion_match:
        score += 2
        reasons.append(f"suits {occasion}")
    elif occasion and vibe_tags:
        score -= 1.5

    # Time of day. A night-only scent at 9am is wrong in a way that outranks
    # most other signals, so the mismatch penalty is larger than the match bonus.
    tod = frag.get("time_of_day") or "any"
    if tod != "any":
        if tod == period:
            score += 1.5
            reasons.append(f"a {tod} scent")
        else:
            score -= 2.5

    # Temperature. Heat amplifies projection and flattens sweet/heavy notes;
    # cold swallows light ones.
    high_f = (weather or {}).get("high_f")
    weight = _CONCENTRATION_WEIGHT.get((frag.get("concentration") or "").lower())
    family = (frag.get("family") or "").lower()
    sillage = _SILLAGE_WEIGHT.get((frag.get("sillage") or "moderate").lower(), 1)

    if high_f is not None:
        hot_above = rules.get("hot_above_f", 80)
        cold_below = rules.get("cold_below_f", 50)
        if high_f >= hot_above:
            if weight is not None:
                score += 1.5 if weight <= 1 else -1.5
            if family in _LIGHT_FAMILIES:
                score += 1.5
                reasons.append(f"light enough for {round(high_f)}°F")
            elif family in _HEAVY_FAMILIES:
                score -= 1.5
            score += (1 - sillage) * 0.5
        elif high_f <= cold_below:
            if weight is not None:
                score += 1.5 if weight >= 2 else -1.0
            if family in _HEAVY_FAMILIES:
                score += 1.5
                reasons.append(f"has the weight for {round(high_f)}°F")
            elif family in _LIGHT_FAMILIES:
                score -= 1.0
            score += (sillage - 1) * 0.5

    # Rotation. Wearing the same thing two days running mostly means you stop
    # smelling it, so recency is a strong negative and neglect is a mild positive.
    rotation_days = rules.get("rotation_days", 2)
    days = _days_since(frag.get("last_worn"), today)
    if days is None:
        score += 1
        reasons.append("never worn")
    elif days <= rotation_days:
        score -= 3
    else:
        score += min(days / 30.0, 1.0)
        if days >= 21:
            reasons.append(f"not worn in {days} days")

    # Your own verdict, centred on 3 so a scent you disliked is pushed down
    # rather than merely un-boosted. Straight multiplication would make a
    # 1-star bottle a weak positive, and "never worn" alone could then float
    # something you already decided against to the top of the day.
    # 0 means unrated, which stays neutral.
    rating = frag.get("rating") or 0
    if rating:
        score += (rating - 3) * 0.6

    return {"score": round(score, 2), "reasons": reasons, "skip_reason": None}


def rank_fragrances(frags: list, season: str, weather: dict, rules: dict,
                    occasion: str = "", period: str = "day",
                    today: date = None, strict: bool = True) -> list:
    """Score every fragrance and return the eligible ones, best first."""
    ranked = []
    for frag in frags:
        result = score_fragrance(frag, season, weather, rules, occasion, period,
                                 today, strict)
        if result["skip_reason"]:
            continue
        entry = dict(frag)
        entry["score"] = result["score"]
        entry["reasons"] = result["reasons"]
        ranked.append(entry)
    ranked.sort(key=lambda f: (-f["score"], f["name"].lower()))
    return ranked
