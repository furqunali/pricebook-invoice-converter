"""Settings loader. Every data path is read from settings.yaml — never hardcode a
drive letter (CONFIRMED ANSWER #3). Falls back to settings.example.yaml so the
offline core and its tests run without a real settings.yaml present.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

# project root = .../pdi-invoice-converter/  (this file is src/pdi_invoice_converter/config.py)
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


def _settings_path() -> Path:
    real = CONFIG_DIR / "settings.yaml"
    return real if real.exists() else CONFIG_DIR / "settings.example.yaml"


class Settings:
    """Thin, read-only view over settings.yaml with project-relative resolution."""

    def __init__(self, data: dict[str, Any], path: Path):
        self._d = data
        self.path = path

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        p = Path(path) if path else _settings_path()
        with open(p, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(data, p)

    def _resolve(self, value: str) -> Path:
        """Resolve a config path. Relative paths hang off the project root; absolute
        (shared-drive) paths are returned as-is."""
        pth = Path(value)
        return pth if pth.is_absolute() else (ROOT / pth)

    @property
    def money_tolerance(self) -> Decimal:
        # Read as str to keep Decimal exact even if the YAML holds a float.
        raw = (self._d.get("validation") or {}).get("money_tolerance", "0.01")
        return Decimal(str(raw))

    @property
    def output_extension(self) -> str:
        return (self._d.get("output") or {}).get("extension", "csv")

    @property
    def daily_prefix(self) -> str:
        return (self._d.get("batch") or {}).get("daily_prefix", "B")

    @property
    def review_prefix(self) -> str:
        return (self._d.get("batch") or {}).get("review_prefix", "R")

    @property
    def counter_file(self) -> Path:
        raw = (self._d.get("batch") or {}).get("counter_file", "config/batch_counter.json")
        return self._resolve(raw)

    @property
    def vendor_ids_file(self) -> Path:
        raw = (self._d.get("lookups") or {}).get("vendor_ids", "config/vendor_ids.csv")
        return self._resolve(raw)

    @property
    def site_ids_file(self) -> Path:
        raw = (self._d.get("lookups") or {}).get("site_ids", "config/site_ids.csv")
        return self._resolve(raw)
