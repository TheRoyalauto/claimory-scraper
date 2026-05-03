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
            # Diagnostic: report what the page actually returned
            body_text = (page.css_first("body").text or "")[:500] if page.css_first("body") else ""
            return JSONResponse({
                "zip_code": zip_code,
                "page_title": page.css_first("title").text if page.css_first("title") else "",
                "url_after_load": str(getattr(page, "url", "unknown")),
                "result_card_count_v1": len(page.css('div[jsaction*="pane.place"]')),
                "result_card_count_v2": len(page.css('div[class*="Nv2PK"]')),
                "result_card_count_v3": len(page.css('a[href*="/maps/place/"]')),
                "body_text_preview": body_text,
                "html_length": len(page.body) if hasattr(page, "body") else 0,
            })

        shops = []
        seen = set()

        # Google Maps result cards (try multiple selector variants)
        results = (
            page.css('a[href*="/maps/place/"]')
            or page.css('div[jsaction*="pane.place"]')
            or page.css('div[class*="Nv2PK"]')
        )

        for el in results[:25]:
            try:
                name = ""
                for sel in ['div[class*="fontHeadlineSmall"]', 'h3', 'div[class*="qBF1Pd"]']:
                    name_el = el.css_first(sel)
                    if name_el:
                        name = name_el.text.strip()
                        break

                if not name or len(name) < 3 or name in seen:
                    continue

                is_collision = any(kw in name.lower() for kw in KEYWORDS)
                if not is_collision:
                    continue

                seen.add(name)

                rating, reviews = 0.0, 0
                rating_el = el.css_first('span[aria-label*="stars"]') or el.css_first('span[class*="MW4etd"]')
                if rating_el:
                    aria = rating_el.attrib.get("aria-label", "") or rating_el.text or ""
                    m = re.search(r"([\d.]+)", aria)
                    if m:
                        rating = float(m.group(1))

                reviews_el = el.css_first('span[aria-label*="reviews"]') or el.css_first('span[class*="UY7F9"]')
                if reviews_el:
                    aria = reviews_el.attrib.get("aria-label", "") or reviews_el.text or ""
                    m = re.search(r"[\d,]+", aria)
                    if m:
                        reviews = int(m.group().replace(",", ""))

                address = ""
                for sel in ['div[class*="W4Efsd"]:last-child', 'div[class*="fontBodyMedium"]']:
                    addr_el = el.css_first(sel)
                    if addr_el:
                        address = addr_el.text.strip()
                        break

                state = ""
                m = re.search(r",\s*([A-Z]{2})\s+\d{5}", address)
                if m:
                    state = m.group(1)

                shop = {
                    "name": name,
                    "address": address,
                    "zip_code": zip_code,
                    "state": state,
                    "rating": rating,
                    "reviews": reviews,
                    "phone": "",
                    "website": "",
                }
                shop["score"] = score_shop(shop)

                if shop["score"] >= 4:
                    shops.append(shop)

            except Exception:
                continue

        shops.sort(key=lambda x: x["score"], reverse=True)
        return JSONResponse({"zip_code": zip_code, "count": len(shops), "shops": shops[:15]})

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
