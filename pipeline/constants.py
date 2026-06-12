import json
from pathlib import Path

_DATA = json.loads(
    (Path(__file__).parent.parent / "data" / "counties.json").read_text()
)

COUNTIES: dict[str, list[str]] = _DATA["COUNTIES"]

STATE_ORDER: list[str] = _DATA["STATE_ORDER"]

STATE_NAMES: dict[str, str] = _DATA["STATE_NAMES"]

EVENT_TYPES: list[str] = _DATA["EVENT_TYPES"]
