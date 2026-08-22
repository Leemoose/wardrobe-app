# Wardrobe

A self-hosted, single-user wardrobe manager you run on your home NAS with Docker and access from your iPhone as a PWA over Tailscale. No cloud dependency, no subscriptions, your data stays on your hardware.

## Features

- **Item inventory** — Add clothing items with photos, categories, colors, seasons, and purchase info; items are auto-numbered for quick reference
- **Outfit library** — Combine items into complete outfits; save favorites for quick access
- **AI batch outfit generation** — Generate outfit suggestions using Claude; approve or reject each one before it saves
- **Morning suggestions** — Get outfit recommendations filtered by today's weather, season, vibe, and what's clean
- **Laundry tracking** — Mark items dirty/clean; set wear-count thresholds per category for "needs washing" alerts
- **Wear stats** — Track cost-per-wear, total wears, and view your wear history on a calendar
- **Scent journal** — Rate every fragrance you've tried and keep dated notes on it, whether or not you own a bottle; get a scent suggested for today's weather

### v1.1 Additions

- **Ad-hoc wear logging** — "Wore something else" on Today tab lets you log items directly without a pre-made outfit; optionally save the combo as a new outfit in one step
- **No-repeat window** — Suggestions hide outfits worn in the last N days (Settings > Suggestions, `no_repeat_days`; 0 disables); "Show anyway" override on Today tab via `include_recent` parameter
- **Weather-aware warnings** — When live weather is available, suggestions show warnings: rain risk for items with suede/leather in name or care notes, cold-without-layer, warm-with-outerwear; thresholds and sensitive-materials list editable in Settings > Weather rules (`rain_precip_threshold`, `outerwear_below_f`, `no_outerwear_above_f`, `sensitive_materials`); weather failure degrades gracefully (no warnings, suggestions still work)
- **Item lifecycle** — Items can be Active, Stored, or Retired; stored and retired items are excluded from suggestions, outfit generation, laundry list, and outfit availability, but history and stats are preserved; filter chips in Closet
- **Undo wear** — Calendar day detail in Stats (Settings → Stats): undo reverses wear counters, wears-since-wash, and dirty marks
- **Backup & export** — Settings > Backup: full `.zip` (consistent SQLite snapshot via `sqlite3.backup()` + photos + JSON export) and standalone JSON export; recommended before container updates
- **Wardrobe analysis** — Stats (Settings → Stats): total value (active items), best/worst cost-per-wear, per-category and per-brand breakdowns (top 8 brands by count), category x season coverage gaps, bottleneck items (appearing in 2+ outfits)
- **Auto-migration** — Existing databases migrate automatically on startup (lifecycle column added if missing)

### v1.2 Additions

- **Multiple photos per item** — Items now support a photo gallery; add multiple angles or detail shots via the item detail screen; swipe through the photo strip; tap any photo to set it as the cover; delete individual photos (cover auto-promotes to the next photo)
- **Wear photos & outfit previews** — Attach mirror selfies when logging wears; optionally set a wear photo as the outfit's preview image; outfit photos can also be added directly; calendar thumbnails show your actual outfit photos
- **Auto-collages** — Outfits without a photo automatically generate a 600×750 collage from member item photos; collages are cached and regenerate when items or photos change; outfit previews use priority: real photo → collage → item thumbnails
- **Retailer link import** — Paste a product URL to auto-fill item details; supports Shopify and most brand sites via JSON-LD schema.org and OpenGraph metadata; optionally uses Claude API for fallback parsing if `ANTHROPIC_API_KEY` is set; downloads product images automatically; includes SSRF protection (private/loopback IPs rejected; `ALLOW_PRIVATE_URLS=1` env var to override for testing only); note that large retailers like Amazon often block scraping
- **Wishlist** — Save product links for later; track items you're considering before purchase; convert wishlist entries into real closet items with one tap (assigns category and imports details); wishlist management available via Closet tab segmented control
- **CSV bulk import** — Download a CSV template from Settings; validate your import with dry-run mode (returns row-by-row errors); bulk-import items with photos via CSV; useful for migrating from spreadsheets or other wardrobe apps

**Note:** v1.2 updates the service worker cache to `wardrobe-v4`; browsers may need a hard refresh (Cmd+Shift+R / Ctrl+Shift+R) after upgrading to clear old cached assets.

**Database schema:** v1.2 adds the `item_photos` table (for multi-photo support), `wear_events.photo` and `outfits.photo` columns (for wear and outfit photos), and the `wishlist` table. Migrations run automatically on container startup.

### v1.3 Additions

- **Trips & packing lists** — New Trips tab: create a trip with a destination, dates, and notes; destination is geocoded automatically (Open-Meteo geocoding) so trips within the next 16 days show a per-day weather forecast; trips further out fall back to calendar-based seasons with a note explaining why
- **Auto-suggest packing** — One tap builds a packing list from your saved outfits: picks outfits matching the trip's seasons while maximizing item overlap (so you pack fewer pieces), then adds weather extras (scarf/gloves/beanie for cold trips, sunglasses/sun hat for sunny ones); everything remains editable — add or remove items and outfits manually, check things off as you pack, "Pack all" for the suitcase moment
- **Vacation mode** — Activate a trip and the whole app filters to what you packed: Today suggestions only show outfits you can fully assemble from packed items, and Closet/Outfits filter to packed pieces (with a "Show all" override); a banner shows the active trip everywhere; deactivate to return to normal — only one trip can be active at a time
- **Accessories in outfits** — Outfit generation now includes watches, bracelets, necklaces, belts, scarves, gloves, beanies, sun hats, sunglasses, and bags: up to 2 accessory-group pieces per outfit, never two of the same type, and weather-aware (untagged scarves imply fall/winter; sun hats imply summer)
- **Categories with behavior** — Every category now carries rules you can edit in Settings: role (required in every outfit vs. optional), weather affinity (any/cold/sun), max per outfit, pick chance, and whether it counts toward the accessory cap; the rule-based generator is fully driven by these settings, so you can tune how outfits are built without touching code; new default accessory categories (watch, bracelet, necklace, belt, scarf, gloves, beanie, sun hat, sunglasses, bag) are added automatically on upgrade, and existing custom categories are preserved

**Note:** v1.3 updates the service worker cache to `wardrobe-v5`; hard-refresh after upgrading.

**Database schema:** v1.3 adds the `trips`, `trip_items`, and `trip_outfits` tables, converts the `categories` setting from a list of names to a list of behavior objects, and merges default dirty-wash thresholds for the new accessory categories. Migrations run automatically on container startup; existing items, outfits, and custom categories are preserved.

### v1.4 Additions

- **Care guides** — A curated library of 18 maintenance guides covering material-specific care (leather shoes incl. white leather, suede, canvas, wool, cashmere, denim, silk, linen, cotton, synthetics, down, velvet/corduroy, leather goods) plus category fallbacks (shoes, tops, bottoms, outerwear, accessories) for items without a material set; each guide has step-by-step sections, a supplies list, and recommended maintenance intervals
- **Materials on items** — Items now carry material tags (leather, suede, wool, etc.) editable as chips on the item form; on upgrade, materials are inferred once from item names and care notes (e.g. "Tan Suede Chukkas" → suede), and new items are auto-tagged the same way unless you set materials explicitly
- **Care button on items** — Every item's detail view has a Care section: matched guides sorted most-specific-first (material+category beats material-only beats category fallback), trackable tasks with due badges, one-tap logging, and a deletable maintenance history
- **Maintenance tab** — New "Care" tab with a "Needs attention" list (items whose tasks are due, based on wears-since or days-since last done, most overdue first, with quick "Done" buttons) and the browsable guide library

**Note:** v1.4 updates the service worker cache to `wardrobe-v6`; hard-refresh after upgrading.

**Database schema:** v1.4 adds the `materials` column to `items` (with one-time keyword inference) and the `maintenance_events` table. Migrations run automatically on startup; all existing data is preserved.

### v1.5 Additions

**Performance**

- **Database indexes + WAL mode** — 8 indexes on the hot query paths and write-ahead logging; noticeably faster once your wardrobe and wear history grow
- **Real thumbnails** — Uploads now also generate a 400px thumbnail used in all grids and strips (existing photos are backfilled automatically on first startup); combined with `loading="lazy"` everywhere, the Closet tab loads far less data, especially over Tailscale away from home
- **Far fewer queries** — List endpoints (items, outfits, care) were rewritten from per-row queries to 2–4 batched queries total; parallelized data loading on the Stats, Care, Closet, and Outfits tabs
- **Correct dates** — The container now runs in your timezone (`TZ` in `.env`, defaults to America/New_York) and the app logs wears using your phone's local date, so a 9 PM wear no longer lands on tomorrow

**Dressing well**

- **Color-aware generation** — The rule-based engine now checks color harmony: neutrals go with everything, statement colors are capped (default 1), and you can define "never pair" combinations — all editable in Settings → Color Rules
- **Rest days** — Categories can require rest between wears (shoes default to 1 day); suggestions hide outfits whose items need rest, with a "show anyway" override

**Caring for nice clothes**

- **Repair & alteration log** — Care history entries now have a kind (repair, alteration, professional service, routine care) and a cost; each item shows its total spent on care, so you'll know when those shoes were last resoled and what your tailor has cost you
- **Care Kit** — Care → Maintenance aggregates the supplies lists from every guide matching items you actually own into one checklist with owned/needed state
- **Seasonal storage assistant** — In spring (Mar–May) Care → Maintenance prompts you to store still-active cold-weather items with a proper storage checklist (clean first, cedar, breathable bags); in fall (Sep–Nov) it prompts you to bring stored items back out

**Local AI**

- **Ollama / LM Studio support** — The AI engine now speaks the OpenAI-compatible API, so you can point it at a model running on your own hardware for free outfit generation — no subscription needed. See [Outfit Generation](#outfit-generation)

**Note:** v1.5 updates the service worker cache to `wardrobe-v7`; hard-refresh after upgrading.

**Database schema:** v1.5 adds `kind` and `cost` columns to `maintenance_events`. Migrations run automatically on startup and are now logged to the container output; all existing data is preserved.

### v1.9 Additions — Scents

A fragrance journal, under **Closet → Scents**. The point is writing down what you
thought of something and giving it a rating; the daily suggestion is a bonus once
you have a few bottles in there.

- **Rate and write** — Every scent gets a 1–5 rating and an *impression*: the free-text headline of what you think of it. Tapping a star saves immediately.
- **Scents you don't own** — A scent's **status** is `owned`, `tried`, `wishlist`, or `retired`. Something sampled at a counter still gets a rating and notes; it just never shows up in the daily suggestion. Status defaults to `owned`, so change it when journaling a sample.
- **Dated journal** — Each scent keeps a log of dated entries, so a verdict can change over time without erasing what you thought the first time. An entry can carry its own rating (which becomes the current one) and a spray count. The **Journal** button shows every entry across all scents, newest first.
- **Bottle tracking** — Logging sprays draws the bottle down (0.1 ml per spray by default) and counts as a wearing, giving you a remaining percentage and a cost per wear. Deleting an entry gives the volume back. Entirely optional: leave sprays at 0 and it's purely a notebook.
- **Scent for today** — The Today tab suggests one owned scent, ranked on today's temperature and season, the time of day, your rating, and how recently you wore it (something worn in the last two days is pushed down — you stop smelling it). Untagged scents are candidates for anything; if everything you own is tagged for another season it relaxes the filter and says so rather than showing nothing.
- **Optional detail** — House, concentration, olfactory family, the top/heart/base pyramid, sillage, longevity, season and occasion tags, bottle size, price, and a photo. Only the name is required.

Tunable in Settings' stored values (`scent_rules`): `ml_per_spray`, `default_sprays`,
`rotation_days`, the `hot_above_f` / `cold_below_f` temperature bands, and
`low_bottle_pct`. The olfactory family list lives in `fragrance_families`.

**Database schema:** v1.9 adds two new tables, `fragrances` and `fragrance_notes`.
They are created on startup alongside the existing ones; nothing else is touched.
Scents and their journals are included in JSON and ZIP backups — the written notes
exist nowhere else, so back up as usual.

**Note:** v1.9 updates the service worker cache to `wardrobe-v15`; hard-refresh after upgrading.

### v2.0 Additions — Slimmer Tab Bar

The bottom bar went from eight tabs to six. Nothing was removed; two things moved.

- **Laundry and Care are one tab** — The **Care** tab now has a Laundry / Maintenance
  segmented control at the top, the same pattern as Closet → Wishlist → Scents. It
  opens on Laundry, since that's the day-to-day half. Maintenance holds everything
  the old Care tab had: Needs Attention, the Care Kit checklist, the seasonal storage
  banner, and the care guides.
- **Stats moved into Settings** — Open it with **Settings → Stats → Open Stats**. The
  view itself is unchanged (totals, value and cost-per-wear, per-category and
  per-brand breakdowns, gaps, wear calendar) and has a back link to Settings. The
  Settings tab stays highlighted while it's open.

- **Counts on the Care segments** — Each half of the Care tab shows how many
  items are waiting in the other one, so nothing goes unnoticed just because
  it's behind a segment you aren't looking at.
- **Settings folds up** — The twelve settings sections collapse to a list of
  headings (about six phone screens of scrolling down to one). Tap a heading to
  open it; it stays open while you work, including across a Save. Stats and
  Backup stay open, since they're a link and two download buttons rather than
  settings.

- **A count on the Care tab** — The Care icon carries a small red count of
  everything waiting inside it — items past their wash threshold plus items with
  a maintenance task due. It's there from launch without opening the tab, and it
  updates as you wear, wash, and log care. No count, no badge.

**Note:** v2.0 updates the service worker cache to `wardrobe-v19`; hard-refresh after upgrading.

---

## Requirements

- A NAS or any machine that can run Docker + Docker Compose (Synology, QNAP, Raspberry Pi, old laptop, whatever)
- Tailscale already configured on both the NAS and your iPhone
- *Optional:* Anthropic API key if you want AI outfit generation

---

## Quick Start

1. **Copy the project folder to your NAS**

   Use whatever method works for you — SMB share, `scp`, Synology File Station, etc. Put it somewhere like `/volume1/docker/wardrobe-app/`.

2. **Create your `.env` file**

   In the same folder as `docker-compose.yml`, create a file named `.env`:

   ```env
   # Optional: for AI outfit generation and fallback retailer link parsing
   ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx

   # Optional: override the default model
   # ANTHROPIC_MODEL=claude-sonnet-5

   # Optional: allow private/loopback URLs for retailer import (testing only)
   # ALLOW_PRIVATE_URLS=1
   ```

   > **Warning:** Never commit `.env` to version control. It contains your API key.

3. **Build and start the container**

   SSH into your NAS (or use the terminal in Container Manager/Container Station) and run:

   ```bash
   cd /path/to/wardrobe-app
   docker compose up -d --build
   ```

   The first build takes a few minutes. Subsequent starts are fast.

4. **Open in your browser**

   Navigate to:

   ```
   http://<your-nas-tailscale-name-or-ip>:8321
   ```

   Example: `http://nas.tailnet-name.ts.net:8321` or `http://100.x.x.x:8321`

---

## Synology-Specific Notes

You have two options:

**Option A: Container Manager "Project" feature (DSM 7.2+)**

1. Open Container Manager → Project → Create
2. Set the path to your `wardrobe-app` folder containing `docker-compose.yml`
3. Container Manager will detect the compose file and build/run it
4. You can start/stop/rebuild from the GUI

**Option B: SSH + CLI**

1. SSH into your Synology (`ssh user@nas-ip`)
2. Navigate to the folder and run `docker compose up -d --build`
3. Manage with standard docker compose commands

> Note: Synology's Docker package uses `docker compose` (v2), not the old `docker-compose` command.

---

## QNAP Notes

Use Container Station's "Create Application" with your `docker-compose.yml`, or SSH in and use the docker compose CLI directly. Same process as Synology.

---

## iPhone Installation (PWA)

1. Make sure Tailscale is connected on your iPhone
2. Open Safari and navigate to `http://<your-nas-tailscale-name>:8321`
3. Tap the Share button (square with arrow)
4. Scroll down and tap **Add to Home Screen**
5. Name it "Wardrobe" and tap Add

You now have an app icon that opens the full-screen PWA. Tailscale must be connected for it to work — if you're off your Tailscale network, the app won't load.

---

## First-Run Setup

Once the app is running, do these things in order:

### 1. Configure Settings

Open the **Settings** tab and:

- **Set your location** — Enter latitude and longitude for weather data (use Google Maps: right-click any spot → coordinates). Example: `40.7128, -74.0060` for NYC.
- **Review categories** — Default categories (tops, bottoms, shoes, etc.) work for most people; add or rename as needed.
- **Review vibes** — These are style tags like "casual," "formal," "workout." Customize to match how you think about your clothes.
- **Set dirty thresholds** — How many wears before an item needs washing? Jeans might be 5, t-shirts might be 1.

### 2. Add Your Items

Go to the **Items** tab and start adding clothes:

- Take a photo or upload one
- Set category, colors, seasons, and vibes
- Optionally add purchase date and price (for cost-per-wear tracking)

### 3. Build Outfits

You can either:

- **Manually create outfits** — Go to Outfits tab, tap Create, select items
- **Use AI generation** — Tap Generate to have Claude suggest outfits based on your inventory (requires API key)

---

## Data and Backups

All your data lives in the `./data` folder:

```
data/
├── wardrobe.db    # SQLite database (items, outfits, settings, wear history)
└── photos/        # All uploaded photos (items, wear events, outfits) and generated collages
```

### Backing Up

**Recommended: Use the in-app backup** (Settings > Backup) which produces a `.zip` containing a consistent SQLite snapshot (via `sqlite3.backup()`), all photos, and a JSON export. This is the safest option and doesn't require stopping the container.

Alternatively, back up the entire `data/` folder however you normally back up your NAS. For extra safety, you can stop the container first:

```bash
docker compose down
# ... copy data/ folder ...
docker compose up -d
```

### Updating the App

When there's a new version:

1. **Back up first** — Use Settings > Backup to download a `.zip` before updating
2. Pull and rebuild:
   ```bash
   cd /path/to/wardrobe-app
   git pull   # or copy the new files manually
   docker compose up -d --build
   ```

Your `data/` folder is bind-mounted, so it's untouched by container rebuilds. The new code runs against your existing database and photos. Schema migrations (like the lifecycle column) run automatically on startup.

---

## Outfit Generation

The app can generate outfit combinations using three engines:

### Rule-Based Engine (No API Key Required)

The built-in rule-based engine generates outfits locally without any external API:

- Combines items following wardrobe rules: top + bottom + shoes, optionally outerwear (~40%) and accessories (~30%)
- Respects season compatibility (items with matching season tags, or empty tags = fits all)
- Respects color harmony rules when enabled (Settings → Color Rules)
- Prefers vibe-compatible combinations when possible
- Ensures variety: no duplicate item combinations, limits item reuse within a batch
- Works completely offline and is always available

### Local AI Engine (Ollama / LM Studio, Free)

If you run [Ollama](https://ollama.com) or LM Studio anywhere on your network (the NAS itself, a desktop, a Mac), the app can use it for AI outfit generation at no cost:

1. Install Ollama and pull a model, e.g. `ollama pull llama3.1`
2. Add to your `.env` file:
   ```env
   OPENAI_BASE_URL=http://192.168.1.10:11434/v1
   OPENAI_MODEL=llama3.1
   ```
   (Use the LAN or Tailscale IP of the machine running Ollama. `OPENAI_API_KEY` is only needed if your server requires one — Ollama doesn't.)
3. Restart the container: `docker compose up -d`

Any server that speaks the OpenAI `/chat/completions` API works. Local models can take a minute on modest hardware — the app waits up to 3 minutes.

### Claude AI Engine (Optional)

For more creative suggestions, you can optionally use Anthropic's Claude API:

1. Get an API key from [console.anthropic.com](https://console.anthropic.com)
2. Add it to your `.env` file:
   ```env
   ANTHROPIC_API_KEY=sk-ant-your-key-here
   ```
3. Restart the container: `docker compose up -d`

Claude analyzes your items and suggests complete outfits with styling notes. Pay-per-use based on Anthropic's pricing; typical generation costs fractions of a cent.

### Engine Selector

In the Outfits tab, the selector shows only the engines you've configured:

- **Auto**: Claude AI if an API key is set, otherwise Local AI if configured, otherwise rule-based
- **Claude AI**: Forces the Claude API (shown only when `ANTHROPIC_API_KEY` is set)
- **Local AI**: Forces your Ollama/LM Studio server (shown only when `OPENAI_BASE_URL` is set)
- **Rule-based**: Forces the local rule-based engine (always available)

After generation, a toast message shows which engine was used and how many outfits were created.

### How It Works

- Generation is **only triggered when you tap Generate** — it never runs automatically
- Both engines output suggestions that go into a pending queue
- You see each suggestion and can **Approve** (saves to your library) or **Reject** (discarded)
- The approve/reject flow is identical regardless of which engine generated the outfit

---

## Troubleshooting

### Port 8321 is already in use

Something else on your NAS is using that port. Edit `docker-compose.yml` and change the host port:

```yaml
ports:
  - "8322:8000"   # Change 8321 to any free port
```

Then `docker compose up -d` and access via the new port.

### Weather shows blank or "unavailable"

1. **Check your coordinates** — Go to Settings and verify lat/lon are correct. Use decimal format (40.7128, not 40°42'46").
2. **Check NAS internet access** — Weather comes from Open-Meteo (free, no API key needed). Make sure your NAS can reach the internet.
3. **Wait a minute** — Weather updates periodically; if you just set coordinates, give it a moment.

### AI returns 400 error or "unauthorized"

- **Missing API key** — Check that `ANTHROPIC_API_KEY` is set in `.env` and the container was restarted after adding it.
- **Invalid key** — Verify the key is correct and active in your Anthropic console.
- **No credits** — Check your Anthropic account has usage credits available.

### Photos not showing

1. **Check permissions** — The `data/photos/` folder needs to be readable by the container. On Linux/NAS, try:
   ```bash
   chmod -R 755 data/
   ```
2. **Check the path** — Photos should be in `data/photos/`, not somewhere else.
3. **Check the bind mount** — Make sure `docker-compose.yml` has `./data:/data` in the volumes section.

### Container won't start

Check the logs:

```bash
docker compose logs
```

Common issues:

- Missing `requirements.txt` or `Dockerfile`
- Syntax error in `.env` file
- Port already in use (see above)

### App works on desktop but not iPhone

- **Tailscale not connected** — Open Tailscale on your iPhone and make sure it's connected
- **Using wrong URL** — Use the Tailscale IP or hostname, not a local IP like 192.168.x.x
- **Safari caching old version** — Clear Safari cache or force-refresh

---

## Architecture Reference

```
wardrobe-app/
├── docker-compose.yml    # Container orchestration
├── Dockerfile            # Python 3.12-slim base, multi-arch (x86 + ARM)
├── requirements.txt      # Python dependencies
├── .env                  # Your API key (create this, don't commit it)
├── data/                 # Persistent data (bind-mounted)
│   ├── wardrobe.db
│   └── photos/
└── app/
    ├── main.py           # FastAPI application entry
    ├── db.py             # SQLite database layer
    ├── weather.py        # Open-Meteo integration
    ├── scents.py         # Fragrance scoring for the daily pick
    ├── ai.py             # Anthropic/Claude integration
    ├── routers/          # API route handlers
    └── static/           # Vanilla JS PWA frontend
```

---

## Security Reminder

This app has **no authentication** in v1. Tailscale is your security boundary.

**Do NOT:**

- Port-forward 8321 to the public internet
- Expose this on a public IP
- Share your Tailscale network with untrusted people

If someone can reach your NAS on port 8321, they have full access to your wardrobe data. Keep it on Tailscale only.

---

## License

Do whatever you want with it. It's your clothes.
