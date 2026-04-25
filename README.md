# Home Improvement Show Search (HISS)

Event discovery tool for home improvement companies that exhibit at trade shows, home expos, county fairs, state fairs, food festivals, and other vendor-accepting events across VA, MD, PA, DC, NJ, and DE.

See [CLAUDE.md](./CLAUDE.md) for the full project brief.

## Quick Start (local)

1. Clone or download this repo.
2. Serve the folder locally (required for the ZIP lookup):
   ```bash
   python3 -m http.server 8000
   # then open http://localhost:8000/
   ```
3. Paste your [Serper.dev](https://serper.dev) API key into the settings panel. The key is stored in your browser's localStorage — nothing is sent to any server other than Serper.
4. Pick the state, counties, and event categories you want to search.
5. Click **Run Search**. Results stream in query-by-query.
6. Use the **Configure Served Counties** button to mark which counties your company services. Events are color-coded green (served) / red (not served) / gray (unconfigured).
7. Click **Export CSV** to download results.

## Requirements

- A modern browser (Chrome, Firefox, Safari, Edge).
- A free [Serper.dev](https://serper.dev) API key (2,500 searches/month on the free tier).
- Internet connection while searching.

No install, no build step, no Node, no server required for local use.

## Data Sources

- **Event search:** Google search results via [Serper.dev](https://serper.dev), with optional supplemental passes over Eventbrite and Facebook Events.
- **ZIP → County enrichment:** U.S. Census Bureau ZCTA-to-County relationship file (public domain). Regenerate with `scripts/build-zip-county.sh`.

## Repository Layout

```
index.html              # The entire app — single file, no build step
Dockerfile              # httpd:alpine image for containerized deployment
docker-compose.yml      # Compose file for server deployment
CLAUDE.md               # Project brief and build notes for Claude Code
README.md               # This file
docs/county-coverage.md # Served-county configuration spec
scripts/                # Maintenance scripts (ZIP lookup build, etc.)
data/zip-county.json    # ZIP → county lookup (generated from Census data)
.github/workflows/      # GitHub Actions — builds and pushes to GHCR on merge to main
```

## Deployment

The app is a static single-file frontend. The container is an `httpd:alpine` image
that serves `index.html` and `data/zip-county.json`. No secrets, no backend — the
Serper API key lives only in the user's browser localStorage.

A new image is built automatically and pushed to
`ghcr.io/distantgeek/home-improvement-search-system:latest` on every push to `main`
via GitHub Actions.

### Docker Compose — NPM / external network (recommended)

If your reverse proxy (e.g. Nginx Proxy Manager) runs in a separate stack, attach
the container directly to its Docker network — no host port binding needed.

1. Find your proxy network name:
   ```bash
   docker network ls
   ```
2. Edit `docker-compose.yml` and replace `YOUR_NPM_NETWORK_NAME` with that name.
3. Deploy:
   ```bash
   docker compose pull && docker compose up -d
   ```
4. In NPM, add a Proxy Host pointing to `hiss:80` (container name + internal port).

### Docker Compose — host port (standalone / no proxy network)

If you prefer a direct host port binding, replace the `networks` block in
`docker-compose.yml` with a `ports` mapping:

```yaml
services:
  hiss:
    image: ghcr.io/distantgeek/home-improvement-search-system:latest
    container_name: hiss
    restart: unless-stopped
    ports:
      - "8080:80"    # change 8080 if the port is already allocated
```

### Docker run (one-liner, host port)

```bash
docker run -d \
  --name hiss \
  --restart unless-stopped \
  -p 8080:80 \
  ghcr.io/distantgeek/home-improvement-search-system:latest
```

### NGINX reverse proxy snippet (host port)

```nginx
location / {
    proxy_pass         http://localhost:8080;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
}
```

### Updating

```bash
docker compose pull && docker compose up -d
```

## Development

### Local dev server

```bash
python3 -m http.server 8000
# open http://localhost:8000/
```

Double-clicking `index.html` works for most things but will fail on
`fetch('data/zip-county.json')` in some browsers due to `file://` CORS restrictions.
Use the local server instead.

### Regenerating ZIP → county data

```bash
./scripts/build-zip-county.sh
git add data/zip-county.json
git commit -m "Regenerate ZIP→county lookup from Census 2020 data"
```

Requires `bash`, `curl`, `awk`, and `python3`. Downloads ~5 MB from the Census Bureau
and emits a ~117 KB JSON lookup covering VA, MD, PA, DC, NJ, and DE.

### Resuming in a fresh Claude Code session

Read `CLAUDE.md` — it is the authoritative project brief and contains the working
TODO list under "What Needs to Be Built Next".

### Branch conventions

Development work lives on feature branches. `main` tracks shippable state and
triggers a Docker build on every push.

## License

See [LICENSE](./LICENSE).
