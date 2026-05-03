import re
import asyncio
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()

PRIORITY_STATES = {"TX", "FL", "CA", "OH", "PA", "NY", "GA", "NC", "MI", "IL"}

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


def _state_from_zip(zip_code: str) -> str:
    if not zip_code or len(zip_code) < 3:
        return ""
    return _ZIP_PREFIX_STATE.get(zip_code[:3], "")


KEYWORDS = [
    "collision repair", "collision shop", "body shop", "auto body",
    "collision center", "paint and body"
]


def score_shop(shop: dict) -> int:
    score = 0
    reviews = shop.get("reviews", 0) or 0
    rating = shop.get("rating", 0) or 0
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


@app.get("/api/scrape")
async def scrape_shops(
    zip_code: str = Query(..., description="US ZIP code to search"),
    debug: bool = Query(False, description="Return raw page info for diagnostics"),
):
    try:
        from scrapling.fetchers import StealthyFetcher

        url = f"https://www.google.com/maps/search/collision+repair+shop+near+{zip_code}"

        page = await StealthyFetcher.async_fetch(
            url,
            headless=True,
            network_idle=True,
            timeout=45000,
        )

        if debug:
            cards = page.css('div[class*="Nv2PK"]') or page.css('a[href*="/maps/place/"]')
            sample = []
            for i, card in enumerate(cards[:5]):
                anchor_list = card.css('a[href*="/maps/place/"]') if hasattr(card, "css") else []
                aria = anchor_list[0].attrib.get("aria-label", "") if anchor_list else ""
                joined = ""
                if hasattr(card, "css"):
                    parts = []
                    for child in card.css("span") + card.css("div"):
                        t = (child.text or "").strip()
                        if t:
                            parts.append(t)
                    joined = " ".join(parts)[:600]
                sample.append({"i": i, "aria_label": aria, "joined_text": joined})
            return JSONResponse({"zip_code": zip_code, "card_count": len(cards), "samples": sample})

        shops = []
        seen = set()
        errors: list[str] = []

        # Google Maps wraps each result in an `<a href="/maps/place/...">` link.
        # The shop name lives in the link's aria-label; rating/reviews/address
        # are in sibling elements within the same Nv2PK card.
        # Strategy: find each Nv2PK card, then extract from anchor + text content.
        cards = page.css('div[class*="Nv2PK"]') or page.css('a[href*="/maps/place/"]')

        for card in cards[:30]:
            try:
                # Name from aria-label of the place anchor
                anchor = card.css_first('a[href*="/maps/place/"]') if hasattr(card, "css_first") else None
                if not anchor:
                    anchor_list = card.css('a[href*="/maps/place/"]')
                    anchor = anchor_list[0] if anchor_list else None
                name = ""
                if anchor is not None:
                    name = (anchor.attrib.get("aria-label", "") or "").strip()
                if not name:
                    # Fall back: any heading text
                    headings = card.css('div[class*="qBF1Pd"]') or card.css('div[class*="fontHeadlineSmall"]')
                    if headings:
                        name = (headings[0].text or "").strip()

                if not name or len(name) < 3 or name in seen:
                    continue

                if not any(kw in name.lower() for kw in KEYWORDS):
                    continue

                seen.add(name)

                # Build full visible text by joining every span/div text node.
                text_parts: list[str] = []
                if hasattr(card, "css"):
                    for child in card.css("span") + card.css("div"):
                        t = (child.text or "").strip()
                        if t:
                            text_parts.append(t)
                card_text = " ".join(text_parts)

                # Rating + reviews come from the rating span's aria-label,
                # e.g. "4.8 stars 323 Reviews" — far more reliable than regex on text.
                rating, reviews = 0.0, 0
                rating_aria = ""
                if hasattr(card, "css"):
                    for s in card.css('span[role="img"]') + card.css('span[aria-label*="star"]'):
                        a = s.attrib.get("aria-label", "")
                        if a:
                            rating_aria = a
                            break
                if rating_aria:
                    m = re.search(r"(\d\.\d)\s*stars?\s*([\d,]+)\s*review", rating_aria, re.IGNORECASE)
                    if m:
                        try:
                            rating = float(m.group(1))
                            reviews = int(m.group(2).replace(",", ""))
                        except ValueError:
                            pass

                # Fallback: bare leading rating in text if aria-label missing.
                if rating == 0.0:
                    m = re.match(r"^\s*(\d\.\d)", card_text)
                    if m:
                        try:
                            rating = float(m.group(1))
                        except ValueError:
                            pass

                # Phone: only match a real US format with separator (skips area-code-only "(323)")
                phone = ""
                phone_match = re.search(r"\(\d{3}\)\s?\d{3}[-.\s]?\d{4}|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b", card_text)
                if phone_match:
                    phone = phone_match.group(0).strip()

                # Address: between the type ("Auto body shop · ·") and the hours ("Closed" / "Open").
                # Format observed: "<rating> Auto body shop ·  · <ADDRESS> (Closed|Open) ..."
                address = ""
                addr_match = re.search(
                    r"(?:body shop|collision (?:repair|center)|paint and body)\s*·\s*·?\s*(.+?)\s+(?:Closed|Open|Opens|Closes)",
                    card_text,
                    re.IGNORECASE,
                )
                if addr_match:
                    address = addr_match.group(1).strip()

                # State: try parsing from address; fallback to ZIP→state via known prefix table.
                state = ""
                state_match = re.search(r",\s*([A-Z]{2})\s*\d{5}", address or card_text)
                if state_match:
                    state = state_match.group(1)
                else:
                    state = _state_from_zip(zip_code)

                # Website: look for any non-Google a[href] inside the card
                website = ""
                if hasattr(card, "css"):
                    for link in card.css('a[href^="http"]'):
                        href = link.attrib.get("href", "")
                        if href and "google.com" not in href and "/maps/" not in href:
                            website = href
                            break

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

                # No threshold filter here — n8n's Score Lead step does the filtering.
                # The scraper's job is to surface every collision-related shop it finds.
                shops.append(shop)

            except Exception as ex:
                errors.append(f"{type(ex).__name__}: {ex}")
                continue

        shops.sort(key=lambda x: x["score"], reverse=True)
        payload = {"zip_code": zip_code, "count": len(shops), "shops": shops[:15]}
        if errors:
            payload["parse_errors"] = errors[:5]
        return JSONResponse(payload)

    except ImportError:
        return JSONResponse(
            {"error": "scrapling not installed — run: pip install 'scrapling[fetchers]' && scrapling install"},
            status_code=500
        )
    except Exception as e:
        return JSONResponse({"error": str(e), "zip_code": zip_code, "shops": []}, status_code=500)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "claimory-scraper"}
