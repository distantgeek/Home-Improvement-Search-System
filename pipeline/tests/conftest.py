"""Shared test fixtures."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DATA_DIR = Path(__file__).parent.parent.parent / "data"


@pytest.fixture
def serper_events_payload() -> dict:
    return json.loads((FIXTURES_DIR / "serper_events_response.json").read_text())


@pytest.fixture
def serper_organic_payload() -> dict:
    return json.loads((FIXTURES_DIR / "serper_organic_response.json").read_text())


@pytest.fixture
def eventbrite_payload() -> dict:
    return json.loads((FIXTURES_DIR / "eventbrite_response.json").read_text())


@pytest.fixture
def festivalnet_html_path() -> Path:
    return FIXTURES_DIR / "festivalnet_sample.html"


@pytest.fixture
def tmp_db(tmp_path) -> str:
    """Temporary SQLite database path (file, not :memory:, for WAL compat)."""
    return str(tmp_path / "test.db")


@pytest.fixture
def data_dir() -> Path:
    """Path to the real Census lookup JSON files."""
    return DATA_DIR


@pytest.fixture
def enricher(data_dir):
    from pipeline.enrich import Enricher

    return Enricher(data_dir)
