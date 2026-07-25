"""AI outfit generation utilities.

Two providers are supported (P5):
- "anthropic": the Claude API (premium option, used when ANTHROPIC_API_KEY is set)
- "openai": any OpenAI-compatible /chat/completions endpoint, e.g. Ollama or
  LM Studio running on the NAS. Enabled by setting OPENAI_BASE_URL
  (e.g. http://nas:11434/v1). OPENAI_API_KEY is optional (Ollama ignores it);
  OPENAI_MODEL picks the model (default llama3.1).
"""
import json
import os
import re
from typing import Optional

import httpx

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


def anthropic_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def openai_available() -> bool:
    return bool(os.environ.get("OPENAI_BASE_URL"))


def openai_model() -> str:
    return os.environ.get("OPENAI_MODEL", "llama3.1")


def build_prompt(items: list, existing_outfits: list, count: int) -> str:
    """Build the prompt for outfit generation."""
    # Format inventory
    inventory_lines = []
    for item in items:
        line = f"#{item['number']}: {item['name']} ({item['category']})"
        if item.get("color"):
            line += f", color: {item['color']}"
        if item.get("brand"):
            line += f", brand: {item['brand']}"
        if item.get("season_tags"):
            line += f", seasons: {item['season_tags']}"
        if item.get("vibe_tags"):
            line += f", vibes: {item['vibe_tags']}"
        inventory_lines.append(line)

    inventory_text = "\n".join(inventory_lines)

    # Format existing outfits
    existing_lines = []
    for outfit in existing_outfits:
        item_nums = [item["number"] for item in outfit.get("items", [])]
        existing_lines.append(f"- {outfit['name']}: items {item_nums}")

    existing_text = "\n".join(existing_lines) if existing_lines else "(none)"

    prompt = f"""You are a fashion assistant helping to create outfit combinations from a wardrobe.

INVENTORY (format: #number: name (category), details):
{inventory_text}

EXISTING OUTFITS (do NOT duplicate these exact item combinations):
{existing_text}

Generate exactly {count} NEW outfit combinations. HARD REQUIREMENTS:
1. Each outfit MUST be meaningfully different from ALL existing outfits AND from each other
2. HIGH VARIETY is essential - vary anchor pieces, don't reuse the same top/bottom pairing
3. Each outfit needs at least a top + bottom + shoes (or sensible equivalent like a dress + shoes)
4. Use item numbers from the inventory above

Respond with ONLY a JSON array, no other text. Format:
[
  {{"name": "Outfit Name", "item_numbers": [1, 2, 3], "season_tags": ["fall", "winter"], "vibe_tags": ["casual"], "note": "Short styling note"}},
  ...
]"""

    return prompt


def extract_json_array(text: str) -> Optional[list]:
    """Extract JSON array from text, handling code fences."""
    # Remove code fences if present
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Best case: the whole response is the JSON array
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: find a JSON array embedded in prose
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


async def _call_anthropic(prompt: str) -> str:
    """Call the Anthropic Messages API, return the response text."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        result = resp.json()

    text = ""
    for block in result.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
    return text


async def _call_openai(prompt: str) -> str:
    """Call an OpenAI-compatible /chat/completions endpoint (Ollama, LM Studio,
    OpenAI itself). Returns the response text."""
    base_url = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    if not base_url:
        raise ValueError("OPENAI_BASE_URL not set")

    headers = {"content-type": "application/json"}
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": openai_model(),
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}],
            },
            # Local models on NAS-grade hardware can be slow
            timeout=180.0,
        )
        resp.raise_for_status()
        result = resp.json()

    choices = result.get("choices") or []
    if not choices:
        raise ValueError("AI response contained no choices")
    return (choices[0].get("message") or {}).get("content") or ""


async def generate_outfits(
    items: list,
    existing_outfits: list,
    count: int = 5,
    provider: Optional[str] = None,
) -> list:
    """
    Generate outfit suggestions via an AI provider.

    provider: "anthropic", "openai", or None (= prefer anthropic, then openai).
    """
    if provider is None:
        if anthropic_available():
            provider = "anthropic"
        elif openai_available():
            provider = "openai"
        else:
            raise ValueError(
                "No AI provider configured. Set ANTHROPIC_API_KEY or OPENAI_BASE_URL."
            )

    prompt = build_prompt(items, existing_outfits, count)

    if provider == "anthropic":
        text = await _call_anthropic(prompt)
    elif provider == "openai":
        text = await _call_openai(prompt)
    else:
        raise ValueError(f"Unknown AI provider: {provider}")

    candidates = extract_json_array(text)
    if candidates is None:
        raise ValueError("Failed to parse AI response as JSON array")

    return candidates
