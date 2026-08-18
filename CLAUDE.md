# Wardrobe app — working notes

A single-user wardrobe manager: FastAPI + SQLite on the back end, a vanilla-JS
PWA on the front. Runs in Docker on a home server, reached over Tailscale from
an iPhone. `README.md` is the user/operator manual — this file is the stuff you
only learn by reading the code.

## Deliberately boring

There is **no ORM, no build step, and no frontend framework**. `app/db.py` is
plain `sqlite3` with row factories; `app/static/app.js` is one ~5,500-line file
of functions loaded with a `<script>` tag. Keep it that way unless there's a
reason not to — the whole thing is meant to stay readable and hackable without
a toolchain. Don't introduce npm, a bundler, or SQLAlchemy casually.

## Running and testing

```bash
# Dev server (DATA_DIR must be set; it defaults to /data for the container)
DATA_DIR=/tmp/wtest PYTHONPATH="$PWD" .venv/bin/python -m uvicorn app.main:app --port 8912

# The whole test suite — 13 end-to-end tests against a real server
DATA_DIR=/tmp/wtest ALLOW_PRIVATE_URLS=1 PYTHONPATH="$PWD" .venv/bin/python test_e2e.py
```

`test_e2e.py` boots a live app and drives it over HTTP. Run it before every
push; it is the only safety net. Two things about it:

- **`test_n8_api_paths` greps `app.js` for `api('...')` calls and checks each
  against an allowlist.** Add new route prefixes to `valid_patterns` or the
  suite fails on a correct change.
- New feature? Add a test alongside `test_n10_scents` and call it from `main()`.

## Invariants that bite

**Bump the asset version AND the cache name together.** `index.html` loads
`app.js?v=N` and `style.css?v=M`; `sw.js` has `CACHE_NAME`. Changing JS or CSS
without bumping both ships code that phones never see. The service worker is
network-first for the document precisely so this is recoverable — don't revert
it to cache-first (see the `2bb5e22` commit message for what that broke).

**Migrations are additive and run on every startup.** `SCHEMA` in `db.py` is all
`CREATE TABLE IF NOT EXISTS`; column changes go through the idempotent
`_add_column()` helper. There is no migration framework and no down-migration.
Never write a migration that drops or rewrites a column — the live database on
the server holds the only copy of real data.

**`data/` is gitignored and is not backed up by git.** The deploy does
`git reset --hard`, which is only safe because of that. The database and photos
exist solely on the server; `/api/backup/zip` is the backup.

**Route order matters.** Path params are typed (`{scent_id}: int`), so a literal
segment like `/scents/suggest` must be declared *before* `/scents/{scent_id}` or
FastAPI 422s on it.

**Dates are local, not UTC.** A bare `YYYY-MM-DD` parsed with `new Date()` is
UTC midnight, which renders as the previous day in Eastern time. The frontend
has `localToday()` for writing and `formatDate()` handles date-only strings
explicitly. Don't "simplify" either back to a plain `new Date(str)`.

## Backend conventions

- **Settings are JSON blobs** in a key-value `settings` table. `DEFAULT_SETTINGS`
  in `db.py` is the gate: `PUT /api/settings` silently ignores any key not in it,
  so a new setting must be added there to be reachable at all.
- **Serialize lists in bounded queries, not per row.** `items_to_dicts()`,
  `outfits_to_dicts()` and `fragrances_to_dicts()` batch-fetch their children
  (see `_photos_for_items`). Adding a per-row query inside a list endpoint is a
  regression — that pattern was deliberately removed in v1.5.
- Routers are thin; scoring/rules logic lives in a sibling module
  (`weather.py`, `scents.py`, `care_guides.py`) so it reads without FastAPI noise.
- Photo writes go through `app/images.py` (`process_image` applies EXIF rotation,
  `save_photo` also writes a 400px thumbnail).

## Frontend conventions

One global `state` object; `renderCurrentView()` switches on `state.currentTab`.
Each view is `async function renderXView(container)` that sets `innerHTML` and
then attaches listeners — there's no diffing, re-render is wholesale.

- `api(path, {method, body})` prefixes `/api` and throws on non-2xx.
- `openModal(html, full)` / `closeModal()`; `toast(msg, 'error')` for feedback.
- **`escapeHtml()` every interpolated value.** All markup is built with template
  strings, so this is the only thing standing between a fragrance note and an
  injection.
- Photo URLs are reused across writes, so cache-bust with `bustedPhotoUrl()` and
  set `state.photoBust[key]` after any in-place image change.

## Deploying

`git push` to `main`. A cron job on the server fetches every 5 minutes and, if
`origin/main` moved, does `git reset --hard` + `docker compose up -d --build`.
There is no webhook — the server has no public inbound address. See `DEPLOY.md`.

Verify a deploy actually landed rather than assuming, e.g.
`curl -s $BASE/sw.js | grep CACHE_NAME`.

## Repo hygiene

`ORDER2_ASSESSMENT.md` and `ORDER3_ASSESSMENT.md` are shopping write-ups of
Nordstrom orders, not code documentation. They're unrelated to the app and are
candidates for moving out of the repo.
