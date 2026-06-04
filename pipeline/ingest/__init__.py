"""
Structured file ingest pipeline.

Supports HTML (FestivalNet My List), CSV, and JSON event imports.
Run via:  python3 -m pipeline.run --ingest-file path/to/file.[html|csv|json]
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.models import EventItem

logger = logging.getLogger(__name__)

_EXT_MAP: dict[str, str] = {
    ".html": "html",
    ".htm": "html",
    ".csv": "csv",
    ".json": "json",
}


def _resolve_path(path: str) -> Path:
    p = Path(path)
    if not p.exists():
        logger.error("Ingest file not found: %s", p)
        sys.exit(1)
    if p.is_dir():
        files = sorted(p.glob("*"), key=lambda x: x.name)
        html_files = [f for f in files if f.suffix.lower() in (".html", ".htm")]
        if not html_files:
            logger.error("No HTML/CSV/JSON files found in directory: %s", p)
            sys.exit(1)
        return html_files[0]
    return p


def ingest_file(path: str) -> list[EventItem]:
    from pipeline.models import EventItem

    resolved = _resolve_path(path)
    ext = resolved.suffix.lower()
    handler_name = _EXT_MAP.get(ext)
    if handler_name is None:
        supported = ", ".join(_EXT_MAP.keys())
        logger.error(
            "Unsupported file extension '%s' — supported: %s",
            ext,
            supported,
        )
        sys.exit(1)

    logger.info("Ingesting %s (%s format)…", resolved.name, handler_name)

    if handler_name == "html":
        from .html_handler import parse_html

        events = parse_html(resolved)
    elif handler_name == "csv":
        from .csv_handler import parse_csv

        events = parse_csv(resolved)
    elif handler_name == "json":
        from .json_handler import parse_json

        events = parse_json(resolved)
    else:
        logger.error("Unknown handler: %s", handler_name)
        sys.exit(1)

    if not events:
        logger.warning("No events extracted from %s", resolved.name)
        return []

    logger.info("Extracted %d events from %s", len(events), resolved.name)
    return events
