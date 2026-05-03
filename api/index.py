"""
Claimory Scrapling lead-gen API.

Scrapes Google Maps for collision-repair shops near a US ZIP code and returns
structured shop records (name, address, state, rating, reviews, phone, website,
score). Built on Scrapling's StealthyFetcher (Camoufox under the hood) to
bypass Google's bot detection without paying for a third-party scraping API.

Performance notes:
- We avoid `network_idle=True` because Google Maps long-polls and never goes
  idle — that single flag was costing ~40s per request. We instead wait for
  the first result card to appear (`wait_selector`).
- `disable_resources=True` skips fonts, images, and most CSS. Page weight
  drops from ~5MB to ~600KB and load time from ~8s to ~2s.
- A `page_action` callback scrolls the results panel three times so we get
  30-60 cards instead of the initial 12.
- Successful scrapes are cached in memory for 6 hours, keyed by ZIP. Repeat
  calls inside the TTL return instantly. Cache clears on container restart.
"""

import re
import time
from typing import Any
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()


# ---------------------------------------------------------------------------
# Static data
# ---------------------------------------------------------------------------

PRIORITY_STATES = {"TX", "FL", "CA", "OH", "PA", "NY", "GA", "NC", "MI", "IL"}

KEYWORDS = (
    "collision repair", "collision shop", "body shop", "auto body",
    "collision center", "paint and body",
)

# Coarse ZIP-prefix to state lookup (covers the workflow's seeded ZIPs).
_ZIP_PREFIX_STATE = {
    "770": "TX", "771": "TX", "772": "TX", "773": "TX", "774": "TX", "775": "TX",
    "776": "TX", "777": "TX", "778": "TX", "779": "TX",
    "330": "FL", "331": "FL", "332": "FL", "333": "FL", "334": "FL", "335": "FL",
    "336": "FL", "337": "FL", "338": "FL", "339": "FL", "342": "FL",
    "900": "CA", "901": "CA", "902": "CA", "903": "CA", "904": "CA", "905": "CA",
    "906": "CA", "907": "CA", "908": "CA", "909": "CA", "910": "CA", "911": "CA",
    "912": "CA", "913": "CA", "914": "CA", "915": "CA", "916": "CA", "917": "CA",
    "918": "CA", "919": "CA", "920": "CA", "921": "CA", "922": "CA", "923": "CA",
    "924": "CA", "925": "CA", "926": "CA", "927": "CA", "928": "CA", "930": "CA",
    "931": "CA", "932": "CA", "933": "CA", "934": "CA", "935": "CA", "936": "CA",
    "937": "CA", "938": "CA", "939": "CA", "940": "CA", "941": "CA", "942": "CA",
    "943": "CA", "944": "CA", "945": "CA", "946": "CA", "947": "CA", "948": "CA",
    "949": "CA", "950": "CA", "951": "CA", "952": "CA", "953": "CA", "954": "CA",
    "955": "CA", "959": "CA", "960": "CA", "961": "CA",
    "430": "OH", "431": "OH", "432": "OH", "433": "OH", "434": "OH", "435": "OH",
    "436": "OH", "437": "OH", "438": "OH", "439": "OH", "440": "OH", "441": "OH",
    "442": "OH", "443": "OH", "444": "OH", "445": "OH", "446": "OH", "447": "OH",
    "448": "OH", "449": "OH", "450": "OH", "451": "OH", "452": "OH", "453": "OH",
    "454": "OH", "455": "OH", "456": "OH", "457": "OH", "458": "OH",
    "150": "PA", "151": "PA", "152": "PA", "153": "PA", "154": "PA", "155": "PA",
    "156": "PA", "157": "PA", "158": "PA", "159": "PA", "160": "PA", "161": "PA",
    "162": "PA", "163": "PA", "164": "PA", "165": "PA", "166": "PA", "167": "PA",
    "168": "PA", "169": "PA", "170": "PA", "171": "PA", "172": "PA", "173": "PA",
    "174": "PA", "175": "PA", "176": "PA", "177": "PA", "178": "PA", "179": "PA",
    "180": "PA", "181": "PA", "182": "PA", "183": "PA", "184": "PA", "185": "PA",
    "186": "PA", "187": "PA", "188": "PA", "189": "PA", "190": "PA", "191": "PA",
    "192": "PA", "193": "PA", "194": "PA", "195": "PA", "196": "PA",
    "600": "IL", "601": "IL", "602": "IL", "603": "IL", "604": "IL", "605": "IL",
    "606": "IL", "607": "IL", "608": "IL", "609": "IL", "610": "IL", "611": "IL",
    "612": "IL", "613": "IL", "614": "IL", "615": "IL", "616": "IL", "617": "IL",
    "618": "IL", "619": "IL", "620": "IL", "622": "IL", "623": "IL", "624": "IL",
    "625": "IL", "626": "IL", "627": "IL", "628": "IL", "629": "IL",
    "100": "NY", "101": "NY", "102": "NY", "103": "NY", "104": "NY", "105": "NY",
    "106": "NY", "107": "NY", "108": "NY", "109": "NY", "110": "NY", "111": "NY",
    "112": "NY", "113": "NY", "114": "NY", "115": "NY", "116": "NY", "117": "NY",
    "118": "NY", "119": "NY", "120": "NY", "121": "NY", "122": "NY", "123": "NY",
    "124": "NY", "125": "NY", "126": "NY", "127": "NY", "128": "NY", "129": "NY",
    "130": "NY", "131": "NY", "132": "NY", "133": "NY", "134": "NY", "135": "NY",
    "136": "NY", "137": "NY", "138": "NY", "139": "NY", "140": "NY", "141": "NY",
    "142": "NY", "143": "NY", "144": "NY", "145": "NY", "146": "NY", "147": "NY",
    "148": "NY", "149": "NY",
    "300": "GA", "301": "GA", "302": "GA", "303": "GA", "304": "GA", "305": "GA",
    "306": "GA", "307": "GA", "308": "GA", "309": "GA", "310": "GA", "311": "GA",
    "312": "GA", "313": "GA", "314": "GA", "315": "GA", "316": "GA", "317": "GA",
    "318": "GA", "319": "GA", "398": "GA", "399": "GA",
    "270": "NC", "271": "NC", "272": "NC", "273": "NC", "274": "NC", "275": "NC",
    "276": "NC", "277": "NC", "278": "NC", "279": "NC", "280": "NC", "281": "NC",
    "282": "NC", "283": "NC", "284": "NC", "285": "NC", "286": "NC", "287": "NC",
    "288": "NC", "289": "NC",
    "480": "MI", "481": "MI", "482": "MI", "483": "MI", "484": "MI", "485": "MI",
    "486": "MI", "487": "MI", "488": "MI", "489": "MI", "490": "MI", "491": "MI",
    "492": "MI", "493": "MI", "494": "MI", "495": "MI", "496": "MI", "497": "MI",
    "498": "MI", "499": "MI",
}


# ---------------------------------------------------------------------------
# In-memory cache (clears on container restart)
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = 6 * 3600
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _cache_get(zip_code: str) -> list[dict[str, Any]] | None:
    entry = _cache.get(zip_code)
    if not entry:
        return None
    inserted_at, shops = entry
    if (time.time() - inserted_at) > _CACHE_TTL_SECONDS:
        _cache.pop(zip_code, None)
        return None
    return shops


def _cache_put(zip_code: str, shops: list[dict[str, Any]]) -> None:
    _cache[zip_code] = (time.time(), shops)


# ---------------------------------------------------------------------------
# Pure parsing helpers
# ---------------------------------------------------------------------------

_LEADING_RATING_RE = re.compile(r"^\s*(\d\.\d)\b")
_REVIEWS_ARIA_RE = re.compile(
    r"(?:(\d\.\d)\s*stars?\s*)?([\d,]+)\s+review",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"\(\d{3}\)\s?\d{3}[-.\s]?\d{4}|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b")
_ADDRESS_BETWEEN_RE = re.compile(
    r"(?:auto repair shop|auto body shop|body shop|collision (?:repair|center)|paint and body)\s*·?\s*·?\s*(.+?)\s+(?:Closed|Open|Opens|Closes)",
    re.IGNORECASE,
)
_STATE_FROM_ADDR_RE = re.compile(r",\s*([A-Z]{2})\s*\d{5}")
_LEADING_DOT_RE = re.compile(r"^[·\s]+")


def state_from_zip(zip_code: str) -> str:
    if not zip_code or len(zip_code) < 3:
        return ""
    return _ZIP_PREFIX_STATE.get(zip_code[:3], "")


def extract_rating_reviews(card, body: str) -> tuple[float, int]:
    """
    Rating is the leading `<digit>.<digit>` in the card's visible text
    (`4.8 Auto body shop · · 6016 S Central Ave …`). Reviews count is hidden:
    Google renders it in an `aria-label` like `"4.8 stars 323 Reviews"` on
    a star-icon span, OR `"123 reviews"` on a separate review-count span.
    Walk every element with an `aria-label` until we find a match.
    """
    rating = 0.0
    m = _LEADING_RATING_RE.match(body)
    if m:
        try:
            rating = float(m.group(1))
        except ValueError:
            pass

    reviews = 0
    if hasattr(card, "css"):
        candidates = (
            card.css("[role='img'][aria-label]")
            + card.css("span[aria-label]")
            + card.css("button[aria-label]")
            + card.css("a[aria-label]")
        )
        for el in candidates:
            label = el.attrib.get("aria-label") or ""
            if "review" not in label.lower():
                continue
            m2 = _REVIEWS_ARIA_RE.search(label)
            if not m2:
                continue
            try:
                if rating == 0.0 and m2.group(1):
                    rating = float(m2.group(1))
                reviews = int(m2.group(2).replace(",", ""))
                break
            except ValueError:
                continue
    return rating, reviews


def card_full_text(card) -> str:
    """Concatenate every span/div text node in a card. Scrapling's `.text` is shallow."""
    if not hasattr(card, "css"):
        return ""
    parts: list[str] = []
    for child in card.css("span") + card.css("div"):
        t = (child.text or "").strip()
        if t:
            parts.append(t)
    return " ".join(parts)


def card_first_anchor(card):
    """Find the first `<a href="/maps/place/...">` inside a card, or None."""
    if hasattr(card, "css_first"):
        a = card.css_first('a[href*="/maps/place/"]')
        if a is not None:
            return a
    if hasattr(card, "css"):
        anchors = card.css('a[href*="/maps/place/"]')
        if anchors:
            return anchors[0]
    return None


def card_external_website(card) -> str:
    """Return the first non-Google http link inside the card, or empty string."""
    if not hasattr(card, "css"):
        return ""
    for link in card.css('a[href^="http"]'):
        href = link.attrib.get("href", "") or ""
        if href and "google.com" not in href and "/maps/" not in href:
            return href
    return ""


def score_shop(shop: dict[str, Any]) -> int:
    score = 0
    reviews = shop.get("reviews", 0) or 0
    rating = shop.get("rating", 0) or 0.0
    state = shop.get("state", "")
    if reviews >= 100:
        score += 4
    elif reviews >= 50:
        score += 3
    elif reviews >= 20:
        score += 2
    elif reviews >= 5:
        score += 1
    if rating >= 4.5:
        score += 2
    elif rating >= 4.0:
        score += 1
    if state in PRIORITY_STATES:
        score += 2
    if shop.get("website"):
        score += 1
    if shop.get("phone"):
        score += 1
    return min(score, 10)


def parse_card(card, zip_code: str, seen: set[str]) -> dict[str, Any] | None:
    """Extract a structured shop record from one Google Maps card. None = skip."""
    anchor = card_first_anchor(card)
    name = ""
    if anchor is not None:
        name = (anchor.attrib.get("aria-label") or "").strip()
    if not name and hasattr(card, "css"):
        # Fallback to a heading element if the anchor lacks an aria-label.
        headings = card.css('div[class*="qBF1Pd"]') or card.css('div[class*="fontHeadlineSmall"]')
        if headings:
            name = (headings[0].text or "").strip()

    if not name or len(name) < 3 or name in seen:
        return None
    if not any(kw in name.lower() for kw in KEYWORDS):
        return None
    seen.add(name)

    body = card_full_text(card)
    rating, reviews = extract_rating_reviews(card, body)

    phone_m = _PHONE_RE.search(body)
    phone = phone_m.group(0).strip() if phone_m else ""

    address = ""
    addr_m = _ADDRESS_BETWEEN_RE.search(body)
    if addr_m:
        address = _LEADING_DOT_RE.sub("", addr_m.group(1).strip())

    state_m = _STATE_FROM_ADDR_RE.search(address or body)
    state = state_m.group(1) if state_m else state_from_zip(zip_code)

    website = card_external_website(card)

    shop = {
        "name": name,
        "address": address,
        "zip_code": zip_code,
        "state": state,
        "rating": rating,
        "reviews": reviews,
        "phone": phone,
        "website": website,
    }
    shop["score"] = score_shop(shop)
    return shop


# ---------------------------------------------------------------------------
# Browser interaction (Playwright via Scrapling)
# ---------------------------------------------------------------------------

async def scroll_results_panel(page) -> None:
    """
    Run inside Scrapling's `page_action` callback. Scrolls the Google Maps
    results panel three times to trigger lazy-loading of additional cards.
    """
    js = """
    (async () => {
      const panel = document.querySelector('div[role="feed"]')
        || document.querySelector('div[aria-label*="Results"]');
      if (!panel) return false;
      for (let i = 0; i < 3; i++) {
        panel.scrollBy(0, panel.clientHeight);
        await new Promise(r => setTimeout(r, 700));
      }
      return true;
    })()
    """
    try:
        await page.evaluate(js)
    except Exception:
        pass


async def fetch_maps_page(url: str):
    """
    Fetch the Google Maps results page using Scrapling's stealth fetcher.
    Returns the parsed Response object, or raises if the fetcher itself fails.
    """
    from scrapling.fetchers import StealthyFetcher

    return await StealthyFetcher.async_fetch(
        url,
        headless=True,
        network_idle=False,
        timeout=30000,
        wait_selector='div[class*="Nv2PK"], a[href*="/maps/place/"]',
        wait_selector_state="attached",
        disable_resources=True,
        page_action=scroll_results_panel,
        google_search=True,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "claimory-scraper"}


@app.get("/api/scrape")
async def scrape_shops(
    zip_code: str = Query(..., description="US ZIP code to search"),
    debug: bool = Query(False, description="Return raw card data for diagnostics"),
    nocache: bool = Query(False, description="Bypass the in-memory cache"),
):
    if not nocache and not debug:
        cached = _cache_get(zip_code)
        if cached is not None:
            return JSONResponse({
                "zip_code": zip_code,
                "count": len(cached),
                "shops": cached[:15],
                "cached": True,
            })

    started = time.time()
    url = f"https://www.google.com/maps/search/collision+repair+shop+near+{zip_code}"

    try:
        page = await fetch_maps_page(url)
    except ImportError:
        return JSONResponse(
            {"error": "scrapling not installed — run: pip install 'scrapling[fetchers]' && scrapling install"},
            status_code=500,
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"fetch failed: {type(e).__name__}: {e}", "zip_code": zip_code, "shops": []},
            status_code=500,
        )

    cards = page.css('div[class*="Nv2PK"]') or page.css('a[href*="/maps/place/"]')

    if debug:
        sample = []
        for i, card in enumerate(cards[:8]):
            anchor = card_first_anchor(card)
            sample.append({
                "i": i,
                "aria_label": anchor.attrib.get("aria-label", "") if anchor else "",
                "joined_text": card_full_text(card)[:300],
            })
        return JSONResponse({
            "zip_code": zip_code,
            "card_count": len(cards),
            "elapsed_ms": int((time.time() - started) * 1000),
            "samples": sample,
        })

    shops: list[dict[str, Any]] = []
    seen: set[str] = set()
    parse_errors: list[str] = []
    for card in cards[:60]:
        try:
            shop = parse_card(card, zip_code, seen)
            if shop is not None:
                shops.append(shop)
        except Exception as ex:
            parse_errors.append(f"{type(ex).__name__}: {ex}")

    shops.sort(key=lambda x: x["score"], reverse=True)
    if shops:
        _cache_put(zip_code, shops)

    payload: dict[str, Any] = {
        "zip_code": zip_code,
        "count": len(shops),
        "shops": shops[:15],
        "elapsed_ms": int((time.time() - started) * 1000),
        "cached": False,
    }
    if parse_errors:
        payload["parse_errors"] = parse_errors[:5]
    return JSONResponse(payload)
