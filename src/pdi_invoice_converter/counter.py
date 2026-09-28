"""Daily-reset batch counters.

Persists ``{date, b, r}`` in config/batch_counter.json. The B (daily batch) and R
(review re-run) counters both reset to 0 when the system date changes, then the
requested one is incremented. Batch id format: ``B-1_08-28-2026`` (prefix-number_
MM-DD-YYYY). Date is passed in so runs are deterministic and testable.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .config import Settings


def today_mmddyyyy() -> str:
    """System date as MM-DD-YYYY (used by real runs; tests pass their own date)."""
    return date.today().strftime("%m-%d-%Y")


def _read(path: Path) -> dict:
    if not path.exists():
        return {"date": "", "b": 0, "r": 0}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {"date": "", "b": 0, "r": 0}
    return {"date": data.get("date", ""), "b": int(data.get("b", 0)),
            "r": int(data.get("r", 0))}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def next_id(kind: str, run_date: str, path: Path | None = None) -> str:
    """Bump the ``kind`` counter ('B' or 'R') for ``run_date`` and return the id.

    A new date resets BOTH counters before the increment, so the first run on any
    day is always number 1.
    """
    kind = kind.upper()
    if kind not in ("B", "R"):
        raise ValueError(f"counter kind must be 'B' or 'R', got {kind!r}")

    p = Path(path) if path else Settings.load().counter_file
    state = _read(p)

    if state["date"] != run_date:
        state = {"date": run_date, "b": 0, "r": 0}

    key = "b" if kind == "B" else "r"
    state[key] += 1
    _write(p, state)

    return f"{kind}-{state[key]}_{run_date}"


def batch_filename(batch_id: str, extension: str = "csv") -> str:
    """`B-1_08-28-2026` -> `B-1_08-28-2026.csv`."""
    return f"{batch_id}.{extension.lstrip('.')}"
