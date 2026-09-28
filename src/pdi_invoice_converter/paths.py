"""Resolve the data folder layout. Every path comes from settings.yaml —
never hardcoded (the base path is a sample placeholder; point it at your own data).
``Paths.for_base`` builds the same standard layout under any base dir, which is how
tests and the offline demo run without touching the configured data folder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings

# Supported invoice inputs (matches pdf_prep).
INPUT_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class Paths:
    incoming: Path
    converted: Path
    review: Path
    reprocess: Path
    archive: Path
    dropzone: Path
    logs: Path
    reports: Path

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "Paths":
        s = settings or Settings.load()
        p = s._d.get("paths") or {}
        return cls(
            incoming=Path(p["incoming_dir"]),
            converted=Path(p["converted_dir"]),
            review=Path(p["review_dir"]),
            reprocess=Path(p["reprocess_dir"]),
            archive=Path(p["archive_dir"]),
            dropzone=Path(p["dropzone_dir"]),
            logs=Path(p["log_dir"]),
            reports=Path(p["reports_dir"]),
        )

    @classmethod
    def for_base(cls, base: str | Path) -> "Paths":
        """Standard layout under a base dir (tests / offline demo)."""
        base = Path(base)
        inv = base / "invoices"
        return cls(
            incoming=inv / "1-incoming",
            converted=inv / "2-converted",
            review=inv / "3-review",
            reprocess=inv / "3-review" / "reprocess",
            archive=inv / "4-archive",
            dropzone=inv / "5-pdi-dropzone",
            logs=base / "logs",
            reports=base / "reports",
        )

    def ensure(self) -> None:
        for d in (self.incoming, self.converted, self.review, self.reprocess,
                  self.archive, self.dropzone, self.logs, self.reports):
            d.mkdir(parents=True, exist_ok=True)

    def discover_inputs(self, directory: Path) -> list[Path]:
        """Invoice files in a directory (sorted for deterministic batch order)."""
        return sorted(
            (f for f in directory.iterdir()
             if f.is_file() and f.suffix.lower() in INPUT_EXTS),
            key=lambda f: f.name.lower(),
        )
