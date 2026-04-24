# Home Improvement Show Search (HISS)

Locally-run event discovery tool for home improvement companies that exhibit at trade shows, home expos, county fairs, and state fairs across VA, MD, PA, DC, and NJ.

See [CLAUDE.md](./CLAUDE.md) for the full project brief.

## Quick Start

1. Clone or download this repo.
2. Double-click `index.html` (or open it in any modern browser).
3. Paste your [Serper.dev](https://serper.dev) API key into the settings panel. The key is stored in your browser's localStorage — nothing is uploaded.
4. Pick the states, counties, and event categories you want to search.
5. Click **Search**. Results stream in query-by-query.
6. Use the **Served Counties** modal to mark which counties your company operates in. Events are then color-coded green (served) / red (not served) / gray (unconfigured).
7. Click **Export CSV** to download results.

## Requirements

- A modern browser (Chrome, Firefox, Safari, Edge).
- A free Serper.dev API key (2,500 searches/month).
- Internet connection while searching.

No install, no build step, no Node, no server.

## Data Sources

- **Event search:** Google Events via [Serper.dev](https://serper.dev).
- **ZIP → County enrichment:** U.S. Census Bureau ZCTA-to-County relationship file (public, free). Regenerate with `scripts/build-zip-county.sh`.

## Repository Layout

```
index.html              # The entire app
CLAUDE.md               # Project brief for Claude Code
README.md               # This file
docs/county-coverage.md # Notes on served-county configuration
scripts/                # Maintenance scripts (ZIP lookup build, etc.)
data/                   # Generated data (zip-county.json)
```

## Development

### Resuming in a fresh Claude Code session

This project is designed to be continued by Claude Code. When starting a new session:

1. **Read `CLAUDE.md`** — it's the authoritative project brief and the "What Needs to Be Built Next" section is the working TODO list.
2. **Generate `data/zip-county.json`** if it isn't already committed:
   ```bash
   ./scripts/build-zip-county.sh
   git add data/zip-county.json
   git commit -m "Regenerate ZIP→county lookup from Census 2020 data"
   ```
   The script downloads the U.S. Census ZCTA-to-County relationship file, filters it to VA/MD/PA/DC/NJ, and emits a compact JSON lookup. Requires `bash`, `curl`, `awk`, and `python3`. Runs in a few seconds on a normal connection — the fetch is the dominant cost; ~5 MB download, ~55k rows nationally, ~10–15k kept after filtering.
3. **Open `index.html`** in a browser to see the current mock-data prototype. The UI is built; the Serper API wiring is the next thing to implement.

### Branch conventions

Development work lives on feature branches under `claude/...`. The main branch tracks shippable state.

### Testing the frontend

Because `index.html` is pure static assets, two testing options:

- **Double-click:** opens via `file://`. Works for everything except `fetch('data/zip-county.json')` in some browsers (CORS restrictions on `file://`).
- **Local server** (preferred during development):
  ```bash
  python3 -m http.server 8000
  # then open http://localhost:8000/ in a browser
  ```

### What's next

See the **"What Needs to Be Built Next"** section of [`CLAUDE.md`](./CLAUDE.md) for the detailed build order and implementation notes (Serper request shape, localStorage key schema, dedup algorithm, error-handling rules).

## License

See [LICENSE](./LICENSE).
