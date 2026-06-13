#!/usr/bin/env python3
"""
HISS pipeline entry point.

Required environment variables:
    SERPER_API_KEY      Serper.dev API key
    MEILI_MASTER_KEY    Meilisearch master key

Optional:
    EVENTBRITE_API_KEY  Eventbrite API key (Tier 1 skipped if absent)
    MEILI_URL           Meilisearch URL (default: http://hiss-meilisearch:7700)
    DB_PATH             SQLite path (default: /data/hiss.db)
    DATA_DIR            Census lookup files dir (default: ../data relative to this file)
    PIPELINE_SCHEDULE   Cron expression (default: 0 3 * * 0  = weekly Sunday 3am)
    DRY_RUN             Set to 'true' to skip all API calls and writes

CLI flags:
    --once              Run once and exit (no scheduler)
    --dry-run           Skip all API calls and writes
    --ingest-file PATH  Ingest a structured file (HTML/CSV/JSON) before fetchers
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .dedup import exact_dedup, fuzzy_merge_results
from .enrich import Enricher
from .fetchers import eventbrite as eb_fetcher
from .fetchers import serper as serper_fetcher
from .fetchers import url_enrich
from .ingest import ingest_file
from .store import Store
from .sync import MeilisearchSync
from .constants import STATE_ORDER
from .models import EventItem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


_ALLOWED_MEILI_SCHEMES = ("http://", "https://")
_PLACEHOLDER_KEY_FRAGMENT = "change-me"


def _load_config() -> dict:
    dry_run = os.environ.get("DRY_RUN", "").lower() == "true"
    meili_url = os.environ.get("MEILI_URL", "http://hiss-meilisearch:7700")
    meili_master_key = os.environ.get("MEILI_MASTER_KEY", "")
    config = {
        "serper_api_key": os.environ.get("SERPER_API_KEY", ""),
        "eventbrite_api_key": os.environ.get("EVENTBRITE_API_KEY", ""),
        "meili_url": meili_url,
        "meili_master_key": meili_master_key,
        "db_path": os.environ.get("DB_PATH", "/data/hiss.db"),
        "data_dir": os.environ.get("DATA_DIR", str(_DEFAULT_DATA_DIR)),
        "schedule": os.environ.get("PIPELINE_SCHEDULE", "0 3 * * 0"),
        "dry_run": dry_run,
    }
    if not dry_run:
        missing = [k for k in ("serper_api_key", "meili_master_key") if not config[k]]
        if missing:
            logger.error("Missing required env vars: %s", ", ".join(missing).upper())
            sys.exit(1)
        if not any(meili_url.startswith(s) for s in _ALLOWED_MEILI_SCHEMES):
            logger.error("MEILI_URL must start with http:// or https://: %r", meili_url)
            sys.exit(1)
        if _PLACEHOLDER_KEY_FRAGMENT in meili_master_key:
            logger.error(
                "MEILI_MASTER_KEY appears to be the placeholder value — set a real key"
            )
            sys.exit(1)
    sidecar_url = os.environ.get("SIDECAR_URL", "")
    if sidecar_url and not sidecar_url.startswith(("http://", "https://")):
        logger.error("SIDECAR_URL must start with http:// or https://: %r", sidecar_url)
        sys.exit(1)
    return config


def run_pipeline(config: dict, ingest_path: str | None = None) -> None:
    """One full pipeline pass: fetch → enrich → dedup → store → sync."""
    dry_run = config["dry_run"]
    fetched_at = datetime.now(timezone.utc).isoformat()
    year_prefix = str(date.today().year)

    logger.info("=== HISS pipeline run started (dry_run=%s) ===", dry_run)

    enricher = Enricher(config["data_dir"])
    events = []

    # ── Ingest: manual structured file ──────────────────────────────────────
    if ingest_path:
        logger.info("Ingesting structured file: %s", ingest_path)
        ingested = ingest_file(ingest_path)
        if ingested and not dry_run:
            for event in ingested:
                event.fetched_at = fetched_at
                enricher.enrich(event)
        events.extend(ingested)
        logger.info("Ingested %d events", len(ingested))

    # ── Tier 1: Eventbrite ───────────────────────────────────────────────────
    if config["eventbrite_api_key"]:
        logger.info("Fetching Tier 1 (Eventbrite)…")
        eb = eb_fetcher.fetch_all(config["eventbrite_api_key"], dry_run=dry_run)
        logger.info("Eventbrite raw: %d", len(eb))
        events.extend(eb)
    else:
        logger.info("EVENTBRITE_API_KEY not set — skipping Tier 1")

    # ── Tier 2: Serper.dev ───────────────────────────────────────────────────
    logger.info("Fetching Tier 2 (Serper.dev)…")
    queries = serper_fetcher.build_all_queries()
    logger.info("Built %d Serper queries", len(queries))
    serper = serper_fetcher.fetch_all(
        config["serper_api_key"], queries, dry_run=dry_run
    )
    logger.info("Serper raw: %d", len(serper))
    events.extend(serper)

    logger.info("Total raw events: %d", len(events))
    if not events and not dry_run:
        logger.warning("No events fetched — aborting")
        return

    # ── URL dedup: keep best event per URL ────────────────────────────────────
    # Aggregator pages (e.g. K-State PDF listing all KS county fairs) and listing
    # pages (e.g. vafairs.us/fair-dates) can create dozens of events from a single
    # URL. Keep only the best event per primary_url (highest page_score, then
    # longest name as tiebreaker). Events with empty URLs are not deduped here.
    pre_url_dedup = len(events)
    by_url: dict[str, EventItem] = {}
    no_url: list[EventItem] = []
    for event in events:
        url = event.primary_url
        if not url:
            no_url.append(event)
            continue
        if url not in by_url:
            by_url[url] = event
        else:
            existing = by_url[url]
            new_p = event.page_score
            ex_p = existing.page_score
            if new_p > ex_p or (new_p == ex_p and len(event.name) > len(existing.name)):
                by_url[url] = event
    events = list(by_url.values()) + no_url
    url_dedup_dropped = pre_url_dedup - len(events)
    if url_dedup_dropped:
        logger.info(
            "URL dedup: dropped %d events (same URL, kept best)", url_dedup_dropped
        )

    # ── URL enrichment (scrape event pages for address data) ──────────────────
    # For events still missing ZIP/county/city, fetch their web pages and extract
    # structured address data from JSON-LD, microdata, or heuristic regex.
    if not dry_run:
        logger.info("Enriching events with address data from web pages…")
        url_updated = url_enrich.enrich_from_urls(events)
        logger.info("URL enrichment: updated %d events", url_updated)

    # ── Enrich ───────────────────────────────────────────────────────────────
    logger.info("Enriching…")
    for event in events:
        event.fetched_at = fetched_at
        enricher.enrich(event)

    pre_filter = len(events)
    events = [
        e for e in events if not e.start_date or e.start_date >= f"{year_prefix}-01-01"
    ]
    logger.info("Date filter: kept %d of %d", len(events), pre_filter)

    # Drop events with no state or non-target state after enrichment.
    # Events with empty state contaminate all state filters; events in
    # non-target states (e.g. NY, FL) are outside the coverage area.
    pre_state = len(events)
    events = [e for e in events if e.state in STATE_ORDER]
    dropped_state = pre_state - len(events)
    if dropped_state:
        logger.info(
            "State filter: dropped %d events (no state or non-target)", dropped_state
        )

    # ── Dedup ────────────────────────────────────────────────────────────────
    events = exact_dedup(events)
    logger.info("After exact dedup: %d", len(events))
    events = fuzzy_merge_results(events)
    logger.info("After fuzzy dedup: %d", len(events))

    if dry_run:
        logger.info("[dry-run] Sample (up to 5):")
        for e in events[:5]:
            logger.info("  %s | %s | %s %s", e.name, e.start_date, e.county, e.state)
        logger.info("[dry-run] Complete — no writes")
        return

    # ── Store ────────────────────────────────────────────────────────────────
    store = Store(config["db_path"])
    try:
        written = store.upsert_events(events)
        logger.info("Upserted %d events to SQLite", written)
        purged = store.purge_expired(days=30)
        logger.info("Purged %d expired events", purged)

        # ── Sync ─────────────────────────────────────────────────────────────
        syncer = MeilisearchSync(config["meili_url"], config["meili_master_key"])
        syncer.configure_index()
        synced = syncer.sync_from_store(store)
        logger.info("Synced %d events to Meilisearch", synced)
    finally:
        store.close()

    logger.info("=== Pipeline run complete ===")


def main() -> None:
    config = _load_config()

    ingest_path = None
    args = []
    for arg in sys.argv[1:]:
        if arg == "--ingest-file":
            idx = sys.argv.index(arg)
            if idx + 1 < len(sys.argv):
                ingest_path = sys.argv[idx + 1]
        elif arg.startswith("--ingest-file="):
            ingest_path = arg.split("=", 1)[1]
        else:
            args.append(arg)

    once = "--once" in args or "--dry-run" in args or config["dry_run"]
    if once:
        run_pipeline(config, ingest_path=ingest_path)
        return

    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    parts = config["schedule"].split()
    if len(parts) != 5:
        logger.error(
            "Invalid PIPELINE_SCHEDULE '%s' — expected 5-part cron", config["schedule"]
        )
        sys.exit(1)

    minute, hour, day, month, dow = parts
    try:
        trigger = CronTrigger(
            minute=minute, hour=hour, day=day, month=month, day_of_week=dow
        )
    except ValueError as exc:
        logger.error("Invalid PIPELINE_SCHEDULE '%s': %s", config["schedule"], exc)
        sys.exit(1)

    scheduler = BlockingScheduler()
    scheduler.add_job(run_pipeline, trigger, args=[config, None])
    logger.info("Scheduler started — cron: %s", config["schedule"])

    # Run once immediately so data is available right after deploy
    logger.info("Running immediately on startup…")
    try:
        run_pipeline(config, ingest_path=None)
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception:
        logger.exception("Startup pipeline run failed — scheduler will still start")

    scheduler.start()


if __name__ == "__main__":
    main()
