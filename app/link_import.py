"""Link import utilities for parsing product pages and downloading images.

SSRF Guard: By default, all URL fetches are validated to ensure they don't
target private/internal IP addresses. This prevents Server-Side Request Forgery
attacks. Set ALLOW_PRIVATE_URLS=1 in environment to disable this guard
(useful for local testing only).
"""
import ipaddress
import json
import os
import re
import socket
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlparse

import httpx

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class SSRFError(Exception):
    """Raised when a URL targets a private/reserved IP address."""
    pass


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private, loopback, link-local, or reserved."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        )
    except ValueError:
        # Invalid IP address string
        return True


def validate_url_ssrf(url: str) -> None:
    """
    Validate URL against SSRF attacks.

    Raises SSRFError if:
    - Scheme is not http or https
    - Hostname resolves to a private/loopback/link-local/reserved IP

    Set ALLOW_PRIVATE_URLS=1 environment variable to skip this check
    (for local testing only).
    """
    # Check for override (for local testing)
    if os.environ.get("ALLOW_PRIVATE_URLS") == "1":
        return

    parsed = urlparse(url)

    # Validate scheme
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Invalid URL scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("Invalid URL: no hostname")

    # Resolve hostname and check all addresses
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFError(f"Could not resolve hostname: {e}")

    for family, socktype, proto, canonname, sockaddr in addr_info:
        ip_str = sockaddr[0]
        if is_private_ip(ip_str):
            raise SSRFError(f"URL resolves to private/reserved IP: {ip_str}")


class MetaTagParser(HTMLParser):
    """Parse HTML to extract meta tags and JSON-LD scripts."""

    def __init__(self):
        super().__init__()
        self.meta_tags = {}
        self.json_ld_blocks = []
        self.title = ""
        self._in_title = False
        self._in_script = False
        self._script_type = ""
        self._script_content = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "title":
            self._in_title = True

        elif tag == "meta":
            # OpenGraph: <meta property="og:title" content="...">
            prop = attrs_dict.get("property", "")
            name = attrs_dict.get("name", "")
            content = attrs_dict.get("content", "")

            if prop:
                self.meta_tags[prop] = content
            if name:
                self.meta_tags[name] = content

        elif tag == "script":
            script_type = attrs_dict.get("type", "")
            if script_type == "application/ld+json":
                self._in_script = True
                self._script_type = script_type
                self._script_content = ""

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_script:
            self._in_script = False
            if self._script_content.strip():
                try:
                    data = json.loads(self._script_content)
                    self.json_ld_blocks.append(data)
                except json.JSONDecodeError:
                    pass
            self._script_content = ""

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_script:
            self._script_content += data


def find_product_in_jsonld(blocks: list) -> Optional[dict]:
    """
    Find a Product schema in JSON-LD blocks.
    Handles @graph arrays and nested structures.
    Returns dict with name, brand, price, image or None.
    """
    def extract_product(obj):
        if not isinstance(obj, dict):
            return None

        obj_type = obj.get("@type", "")
        # Handle both "Product" and ["Product", "SomeOtherType"]
        if isinstance(obj_type, list):
            is_product = "Product" in obj_type
        else:
            is_product = obj_type == "Product"

        if is_product:
            result = {}

            # Name
            if "name" in obj:
                result["name"] = obj["name"]

            # Brand
            brand = obj.get("brand")
            if isinstance(brand, dict):
                result["brand"] = brand.get("name", "")
            elif isinstance(brand, str):
                result["brand"] = brand

            # Price from offers
            offers = obj.get("offers")
            if isinstance(offers, list) and offers:
                offers = offers[0]
            if isinstance(offers, dict):
                price = offers.get("price")
                if price is not None:
                    try:
                        result["price"] = float(price)
                    except (ValueError, TypeError):
                        pass

            # Image
            image = obj.get("image")
            if isinstance(image, list) and image:
                image = image[0]
            if isinstance(image, dict):
                image = image.get("url", "")
            if isinstance(image, str):
                result["image"] = image

            return result if result else None

        return None

    for block in blocks:
        # Handle @graph arrays
        if isinstance(block, dict) and "@graph" in block:
            graph = block["@graph"]
            if isinstance(graph, list):
                for item in graph:
                    result = extract_product(item)
                    if result:
                        return result

        # Direct product
        result = extract_product(block)
        if result:
            return result

        # Handle arrays at top level
        if isinstance(block, list):
            for item in block:
                result = extract_product(item)
                if result:
                    return result

    return None


def parse_opengraph(meta_tags: dict, title: str) -> dict:
    """Extract product info from OpenGraph/meta tags."""
    result = {}

    # Name: og:title or page title
    og_title = meta_tags.get("og:title", "")
    if og_title:
        result["name"] = og_title
    elif title:
        result["name"] = title.strip()

    # Image: og:image
    og_image = meta_tags.get("og:image", "")
    if og_image:
        result["image"] = og_image

    # Price: product:price:amount
    price_str = meta_tags.get("product:price:amount", "")
    if price_str:
        try:
            result["price"] = float(price_str)
        except ValueError:
            pass

    # Brand: og:site_name as fallback
    site_name = meta_tags.get("og:site_name", "")
    if site_name:
        result["brand"] = site_name

    return result


async def fetch_page(url: str) -> str:
    """Fetch a web page with SSRF protection."""
    validate_url_ssrf(url)

    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        resp = await client.get(
            url,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()

        # Limit body size to ~2MB
        content = resp.text
        if len(content) > 2 * 1024 * 1024:
            content = content[:2 * 1024 * 1024]

        return content


async def import_link(url: str) -> dict:
    """
    Import product info from a URL.

    Returns:
    {
        "found": bool,
        "name": str,
        "brand": str,
        "price": float,
        "image_url": str,
        "source": "jsonld" | "opengraph" | "ai" | null,
        "error": str | null
    }
    """
    result = {
        "found": False,
        "name": "",
        "brand": "",
        "price": 0,
        "image_url": "",
        "source": None,
        "error": None,
    }

    try:
        html = await fetch_page(url)
    except SSRFError as e:
        result["error"] = str(e)
        return result
    except Exception as e:
        result["error"] = f"Failed to fetch URL: {e}"
        return result

    # Parse HTML
    parser = MetaTagParser()
    try:
        parser.feed(html)
    except Exception:
        pass

    # Try JSON-LD first
    product = find_product_in_jsonld(parser.json_ld_blocks)
    if product and product.get("name"):
        result["found"] = True
        result["source"] = "jsonld"
        result["name"] = product.get("name", "")
        result["brand"] = product.get("brand", "")
        result["price"] = product.get("price", 0)
        result["image_url"] = product.get("image", "")
        return result

    # Try OpenGraph/meta tags
    og_data = parse_opengraph(parser.meta_tags, parser.title)
    if og_data.get("name"):
        result["found"] = True
        result["source"] = "opengraph"
        result["name"] = og_data.get("name", "")
        result["brand"] = og_data.get("brand", "")
        result["price"] = og_data.get("price", 0)
        result["image_url"] = og_data.get("image", "")
        return result

    # Fall back to AI if API key is set
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            # Strip HTML tags for AI
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            text = text[:15000]  # Limit to 15k chars

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    ANTHROPIC_API_URL,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
                        "max_tokens": 200,
                        "messages": [
                            {
                                "role": "user",
                                "content": (
                                    "Extract product info from this text. "
                                    "Return ONLY a JSON object with keys: name, brand, price (number). "
                                    "If you can't find a value, use empty string or 0.\n\n"
                                    f"Text: {text}"
                                ),
                            }
                        ],
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                ai_result = resp.json()

                # Extract text content
                ai_text = ""
                for block in ai_result.get("content", []):
                    if block.get("type") == "text":
                        ai_text += block.get("text", "")

                # Parse JSON from AI response
                json_match = re.search(r"\{[^}]+\}", ai_text)
                if json_match:
                    ai_data = json.loads(json_match.group())
                    if ai_data.get("name"):
                        result["found"] = True
                        result["source"] = "ai"
                        result["name"] = ai_data.get("name", "")
                        result["brand"] = ai_data.get("brand", "")
                        try:
                            result["price"] = float(ai_data.get("price", 0))
                        except (ValueError, TypeError):
                            pass
                        return result

        except Exception as e:
            # Don't raise - just return not found
            result["error"] = f"AI extraction failed: {e}"

    return result


async def download_image(url: str) -> Optional[bytes]:
    """
    Download an image from a URL with SSRF protection.

    Returns image bytes or None if download fails.
    Validates:
    - SSRF guard
    - Content-Type starts with image/
    - Size <= 10MB
    """
    validate_url_ssrf(url)

    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        resp = await client.get(
            url,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise ValueError(f"Invalid content type: {content_type}")

        content = resp.content
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("Image too large (>10MB)")

        return content
