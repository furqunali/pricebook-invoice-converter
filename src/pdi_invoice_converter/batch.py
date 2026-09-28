"""Batch assembly (Phase 1 = in-memory / offline).

Takes a set of invoices, validates each, assembles the PASSING ones into one
vendor-grouped CSV, and reports the failing ones for review with their reason.
Partial batches are normal: one bad invoice never blocks the good ones.

File movement, archiving, and reading the shared drive happen in Phase 3
(batch.py's runner) once the real drive letter is confirmed. This module owns the
decision logic and the deterministic assembly that the runner will call.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

from .config import Settings
from .counter import next_id, today_mmddyyyy
from .model import Invoice
from .paths import Paths
from .pipeline import STATUS_REVIEW, PipelineResult
from .validate import ValidationResult, validate
from .writer import assemble, to_bytes

# A converter maps one invoice file -> a PipelineResult. Defaults to the real
# vision pipeline; tests/offline demos inject a stub so the runner's file
# orchestration can be exercised without the API or the shared drive.
ConvertFn = Callable[[Path], PipelineResult]


@dataclass
class ReviewItem:
    invoice: Invoice
    result: ValidationResult

    @property
    def reason(self) -> str:
        return self.result.reason_text()


@dataclass
class BatchResult:
    batch_id: str
    filename: str
    in_batch: list[Invoice] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    csv_text: str = ""

    @property
    def has_output(self) -> bool:
        """True only if at least one invoice passed (else no dropzone file)."""
        return bool(self.in_batch)

    def manifest_text(self) -> str:
        """Per-invoice line: vendor, site, invoice #, net total, IN-BATCH/REVIEW."""
        lines = [f"MANIFEST {self.batch_id}", f"file: {self.filename}", ""]
        for inv in self.in_batch:
            lines.append(
                f"IN-BATCH  vendor={inv.vendor_id}  site={inv.site_id}  "
                f"inv={inv.invoice_ref}  net={inv.total}"
            )
        for item in self.review:
            inv = item.invoice
            gates = ",".join(str(f.gate) for f in item.result.failures)
            lines.append(
                f"REVIEW    vendor={inv.vendor_id}  site={inv.site_id}  "
                f"inv={inv.invoice_ref}  net={inv.total}  failed_gates=[{gates}]"
            )
        lines.append("")
        lines.append(f"totals: in_batch={len(self.in_batch)}  review={len(self.review)}")
        return "\n".join(lines)


def assemble_batch(
    invoices: list[Invoice],
    batch_id: str,
    filename: str,
    tolerance: Decimal = Decimal("0.01"),
) -> BatchResult:
    """Validate every invoice; assemble the passers into one vendor-grouped CSV."""
    in_batch: list[Invoice] = []
    review: list[ReviewItem] = []

    for inv in invoices:
        res = validate(inv, tolerance=tolerance)
        if res.passed:
            in_batch.append(inv)
        else:
            review.append(ReviewItem(inv, res))

    csv_text = assemble(in_batch) if in_batch else ""
    return BatchResult(
        batch_id=batch_id,
        filename=filename,
        in_batch=in_batch,
        review=review,
        csv_text=csv_text,
    )


# ---------------------------------------------------------------------------
# Filesystem runners (Phase 3) — the batch & review re-run share this machinery.
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Outcome of a batch or review-run over the incoming/reprocess folder."""
    kind: str                       # "B" or "R"
    batch_id: str                   # e.g. B-1_08-29-2026
    filename: str                   # dropzone file name (even if not written)
    dropzone_file: Optional[Path]   # None when nothing passed
    manifest_file: Path
    archive_dir: Path
    in_batch: list = field(default_factory=list)   # [(Path, PipelineResult)]
    review: list = field(default_factory=list)      # [(Path, PipelineResult)]

    @property
    def has_output(self) -> bool:
        return self.dropzone_file is not None


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def _route_review(paths: Paths, src: Path, result: PipelineResult) -> None:
    """Move a failed invoice to review with a written reason + extracted JSON."""
    paths.review.mkdir(parents=True, exist_ok=True)
    dest = paths.review / src.name
    shutil.move(str(src), str(dest))
    _write_bytes(dest.with_suffix(dest.suffix + ".reason.txt"),
                 result.reason_text().encode("utf-8"))
    if result.extracted is not None:
        _write_bytes(dest.with_suffix(dest.suffix + ".extracted.json"),
                     json.dumps(result.extracted, indent=2).encode("utf-8"))


def _archive(paths: Paths, src: Path, batch_id: str) -> Path:
    dest_dir = paths.archive / batch_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.move(str(src), str(dest))
    return dest


def _manifest_text(kind: str, batch_id: str, filename: str,
                   in_batch: list, review: list) -> str:
    label = "BATCH" if kind == "B" else "REVIEW-RUN"
    lines = [f"{label} MANIFEST {batch_id}", f"file: {filename}", ""]
    for src, res in in_batch:
        inv = res.invoice
        approved = "  [MANUALLY APPROVED]" if getattr(res, "manual_approval", False) else ""
        lines.append(
            f"IN-BATCH  {src.name}  vendor={inv.vendor_id}  site={inv.site_id}  "
            f"inv={inv.invoice_ref}  net={inv.total}{approved}"
        )
    for src, res in review:
        gates = ",".join(str(f.gate) for f in res.validation.failures) if res.validation else "-"
        first_reason = (res.reasons[0] if res.reasons else
                        (res.validation.reason_text().splitlines()[1].strip()
                         if res.validation and not res.validation.passed else "unknown"))
        lines.append(
            f"REVIEW    {src.name}  failed_gates=[{gates}]  reason: {first_reason}"
        )
    lines.append("")
    lines.append(f"totals: in_batch={len(in_batch)}  review={len(review)}")
    return "\n".join(lines) + "\n"


def _finalize(kind: str, batch_id: str, in_batch: list, review: list,
              paths: Paths, settings: Settings) -> RunResult:
    """Shared tail for batch and review-run: assemble the passing invoices, drop
    the combined file, archive their PDFs, route failures, and write the manifest.
    """
    ext = settings.output_extension.lstrip(".")
    filename = f"{batch_id}.{ext}"

    invoices = [res.invoice for _src, res in in_batch]
    dropzone_file: Optional[Path] = None
    if invoices:
        csv_bytes = to_bytes(assemble(invoices))
        dropzone_file = paths.dropzone / filename
        _write_bytes(dropzone_file, csv_bytes)
        _write_bytes(paths.converted / filename, csv_bytes)  # keep a copy

    # Archive the passing invoices' source files; route the failures to review.
    for src, _res in in_batch:
        if src.exists():
            _archive(paths, src, batch_id)
    for src, res in review:
        if src.exists():
            _route_review(paths, src, res)

    manifest_file = paths.logs / f"{batch_id}.manifest.txt"
    _write_bytes(manifest_file, _manifest_text(kind, batch_id, filename,
                                               in_batch, review).encode("utf-8"))

    return RunResult(
        kind=kind, batch_id=batch_id, filename=filename,
        dropzone_file=dropzone_file, manifest_file=manifest_file,
        archive_dir=paths.archive / batch_id, in_batch=in_batch, review=review,
    )


def _default_convert_fn(settings: Settings) -> ConvertFn:
    # Lazy import keeps the SDK/extract path out of module import time.
    from .pipeline import convert_file
    return lambda f: convert_file(f, settings=settings)


def run_batch(
    convert_fn: Optional[ConvertFn] = None,
    settings: Optional[Settings] = None,
    paths: Optional[Paths] = None,
    run_date: Optional[str] = None,
    counter_path: Optional[Path] = None,
) -> RunResult:
    """Daily batch: convert + validate every file in 1-incoming, assemble the
    passing invoices into one vendor-grouped B-n file, archive their PDFs, route
    failures to review, and write a manifest. Partial success is normal.
    """
    settings = settings or Settings.load()
    paths = paths or Paths.from_settings(settings)
    paths.ensure()
    run_date = run_date or today_mmddyyyy()
    counter_path = counter_path or settings.counter_file
    convert_fn = convert_fn or _default_convert_fn(settings)

    batch_id = next_id("B", run_date, counter_path)

    in_batch: list = []
    review: list = []
    for src in paths.discover_inputs(paths.incoming):
        try:
            res = convert_fn(src)
        except Exception as exc:  # never let one bad file kill the batch
            res = PipelineResult(source=str(src), status=STATUS_REVIEW,
                                 reasons=[f"extraction/processing error: {exc}"])
        (in_batch if res.ok else review).append((src, res))

    return _finalize("B", batch_id, in_batch, review, paths, settings)
