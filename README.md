# claimory-scraper

Self-hosted Google Maps business scraper. Vertical-agnostic — pass any
keyword, get back structured business records (name, address, phone,
website, rating, score) for any US location.

## Why this exists

The [emailer](https://github.com/TheRoyalauto/emailer) Lead Scraper page
calls this service over HTTPS. Free alternative to paid SERP / scraping
APIs (Outscraper, SerpApi, etc.). Powered by
[Scrapling](https://github.com/D4Vinci/Scrapling)'s `StealthyFetcher`
(Camoufox under the hood) so it bypasses Google's bot detection without
proxies.

Originally collision-shop-only; generalized 2026-05-05 to scrape any
business vertical (dentists, restaurants, lawyers, plumbers, …). The
default keyword preserves backward compatibility with the n8n lead-gen
workflow that calls `?zip_code=` only.

**Live deployment:** https://scraper-production-b94c.up.railway.app

## Endpoints

### `GET /api/health`

```json
{ "status": "ok", "service": "claimory-scraper" }
```

### `GET /api/scrape`

Scrape Google Maps for a keyword + location. Returns structured shop records.

**Query params:**

| Param | Required | Default | Description |
|---|---|---|---|
| `location` | yes¹ | — | ZIP code, city, or "City, ST" |
| `zip_code` | yes¹ | — | Legacy alias for `location` (n8n workflow uses this) |
| `keyword` | no | `collision repair shop` | Business type to search |
| `limit` | no | `15` | Max shops to return (1–60) |
| `debug` | no | `false` | Return raw card sample data for diagnostics |
| `nocache` | no | `false` | Bypass the 6-hour in-memory cache |

¹ One of `location` or `zip_code` must be set.

**Example response:**

```json
{
  "keyword": "dentist",
  "location": "90001",
  "zip_code": "90001",
  "count": 13,
  "shops": [
    {
      "name": "Florence Dental Group",
      "address": "1575 E Florence Ave Suite A",
      "zip_code": "90001",
      "state": "CA",
      "rating": 4.9,
      "reviews": 0,
      "phone": "(323) 537-4121",
      "website": "http://farzamdds.com/",
      "score": 6
    }
  ],
  "elapsed_ms": 2547,
  "cached": false,
  "rejected": { "no_name": 0, "dup_name": 0 }
}
```

The `score` is a 0–10 lead-quality heuristic based on review volume +
rating + has-website + has-phone (vertical-neutral as of v2).

## Search-term heuristics

Some Google Maps queries return very few results because the term is too
narrow. From smoke testing:

| Term | Results in 33101 |
|---|---|
| `law firm` | 1 |
| `lawyer` | 20 |
| `attorney` | 11 |

Prefer common consumer-facing terms over jargon. `dentist` works, `dental
practitioner` doesn't.

## Local development

```bash
pip install -r requirements.txt
scrapling install
uvicorn api.index:app --reload --port 8000
# then:
curl "http://localhost:8000/api/scrape?location=90001&keyword=dentist&limit=5"
```

## Deployment (Railway)

Source repo: `TheRoyalauto/claimory-scraper` on GitHub. Railway service
`scraper` (id `8dc6c6d1-894a-4045-85f0-453f60fd9fb8`) on environment
`production` (id `1bb107c6-f66e-46bc-b65e-1bc84a2a0312`).

**Auto-deploy from main is unreliable.** Always trigger redeploy explicitly:

```bash
git push origin main
SHA=$(git rev-parse HEAD)
curl -s https://backboard.railway.app/graphql/v2 -X POST \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"mutation { serviceInstanceDeployV2(serviceId: \\\"8dc6c6d1-894a-4045-85f0-453f60fd9fb8\\\", environmentId: \\\"1bb107c6-f66e-46bc-b65e-1bc84a2a0312\\\", commitSha: \\\"$SHA\\\") }\"}"
```

**Important:** pass `commitSha` explicitly. Without it,
`serviceInstanceDeployV2` defaults to redeploying the FIRST commit, not
the latest — silent rollback hazard.

**Verify deploy:**

```bash
curl -s "https://scraper-production-b94c.up.railway.app/api/scrape?location=90001&keyword=dentist&debug=true" | grep -q '"keyword"' && echo "NEW VERSION LIVE"
```

## Known issues

- **Camoufox crashes after long uptime** (`Page.goto: Page crashed`).
  Symptom: every scrape returns `{"error": "fetch failed: ... Page crashed"}`.
  Cause: 512MB Railway Trial memory cap + Camoufox heap fragmentation.
  Fix: trigger a redeploy. The emailer has a Convex cron that pings
  `/api/health` every 4h to prevent container hibernation, but it does
  NOT prevent the memory crash.
- **`reviews` field is always 0.** Google's card-view DOM only exposes
  "X.Y stars" aria-label, not the count. Getting the count requires
  clicking each card to open the detail panel (~5s/click). Not worth it.

## Performance notes

- `network_idle=False` — Maps long-polls and never goes idle. Wait on
  `wait_selector='div[class*="Nv2PK"]'`. Drops fetch from 45s → 2s.
- `disable_resources=True` — skip images/fonts/CSS. Page weight 5MB → 600KB.
- `page_action` callback scrolls the results panel 3× to load 20+ cards
  beyond the initial 12.
- 6-hour in-memory cache keyed by `(keyword, location)`. Resets on
  container restart.
- Material-icon glyphs in Unicode Private Use Area (U+E000–U+F8FF) get
  stripped from addresses — they LOOK like middle dots but are font
  glyphs.

## License

Internal use. Not published.
