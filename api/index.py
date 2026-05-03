import re
import asyncio
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

app = FastAPI()

PRIORITY_STATES = {"TX", "FL", "CA", "OH", "PA", "NY", "GA", "NC", "MI", "IL"}

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
                sample.append({
                    "i": i,
                    "aria_label": aria,
                    "text_first_300": (card.text or "")[:300] if hasattr(card, "text") else "",
                })
            return JSONResponse({
                "zip_code": zip_code,
                "card_count": len(cards),
                "samples": sample,
            })

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

                # Full visible text of the card — easier to regex than fight selectors
                card_text = card.text or ""

                # Rating + reviews like "4.7(123)" or "4.7 stars 123 reviews"
                rating, reviews = 0.0, 0
                rating_match = re.search(r"(\d\.\d)", card_text)
                if rating_match:
                    try:
                        rating = float(rating_match.group(1))
                    except ValueError:
                        pass
                reviews_match = re.search(r"\((\d{1,3}(?:[,\d]*))\)", card_text)
                if reviews_match:
                    try:
                        reviews = int(reviews_match.group(1).replace(",", ""))
                    except ValueError:
                        pass

                # Address: any span that ends in "<state> <zip>"
                address = ""
                addr_match = re.search(r"([\w\s.,#'-]+,\s*[A-Z]{2}\s*\d{5})", card_text)
                if addr_match:
                    address = addr_match.group(1).strip()

                state = ""
                state_match = re.search(r",\s*([A-Z]{2})\s*\d{5}", address or card_text)
                if state_match:
                    state = state_match.group(1)

                # Phone: US-style 555-555-5555 or (555) 555-5555
                phone = ""
                phone_match = re.search(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", card_text)
                if phone_match:
                    phone = phone_match.group(0)

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

                if shop["score"] >= 3:  # tier-warm threshold
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
