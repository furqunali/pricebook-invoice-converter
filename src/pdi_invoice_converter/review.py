"""Review re-run (Phase 3). Processes the invoices a reviewer moved into
3-review/reprocess/ and produces an R-n file.

A reviewer handles a flagged invoice one of two ways:
  - FIX: correct the cause (better scan, add a site/vendor) and drop the file in
    reprocess/. It simply re-runs.
  - OVERRIDE: if the invoice's own printed numbers are wrong (vendor error) but the
    true figures are verified, drop a ``<file>.override.json`` beside it. The
    override supplies authoritative fields (net_total / stated_qty_count / ...) that
    replace the extracted values before re-validation, and/or ``"approve": true`` to
    force-include a still-failing invoice, flagged as MANUALLY APPROVED.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .batch import ConvertFn, RunResult, _default_convert_fn, _finalize
from .config import Settings
from .counter import next_id, today_mmddyyyy
from .paths import Paths
from .pipeline import STATUS_OK, STATUS_REVIEW, PipelineResult, convert_extracted

# Fields a reviewer may authoritatively correct via an override sidecar.
_OVERRIDE_FIELDS = {
    "net_total", "tax", "stated_qty_count", "stated_totes",
    "gross", "discounts", "fees",
}


def _load_override(src: Path) -> Optional[dict]:
    sidecar = src.with_suffix(src.suffix + ".override.json")
    if not sidecar.exists():
        return None
    with open(sidecar, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _apply_override(base: PipelineResult, override: dict,
                    settings: Settings) -> PipelineResult:
    """Re-validate with the reviewer's corrected figures; honour an explicit
    approve. Requires the base extraction (needs both IDs resolved)."""
    note = override.get("note", "manual override")
    if base.extracted is None:
        # Couldn't even extract/resolve IDs — an override can't rescue that here.
        base.reasons.append(f"OVERRIDE could not be applied ({note}): no extraction")
        return base

    corrected = dict(base.extracted)
    for k in _OVERRIDE_FIELDS:
        if k in override:
            corrected[k] = override[k]

    res = convert_extracted(corrected, source=base.source, settings=settings)
    if res.ok:
        res.manual_approval = True
        res.reasons.append(f"MANUALLY APPROVED: {note}")
        return res

    if override.get("approve") and res.invoice is not None:
        # Force-include despite remaining gate failures (verified vendor error).
        res.status = STATUS_OK
        res.manual_approval = True
        res.reasons.append(f"MANUALLY APPROVED (forced): {note}")
    return res


def run_review(
    convert_fn: Optional[ConvertFn] = None,
    settings: Optional[Settings] = None,
    paths: Optional[Paths] = None,
    run_date: Optional[str] = None,
    counter_path: Optional[Path] = None,
) -> RunResult:
    """Re-run everything in 3-review/reprocess/ -> R-n. Overrides are applied and
    flagged; anything still failing goes back to review with an updated reason."""
    settings = settings or Settings.load()
    paths = paths or Paths.from_settings(settings)
    paths.ensure()
    run_date = run_date or today_mmddyyyy()
    counter_path = counter_path or settings.counter_file
    convert_fn = convert_fn or _default_convert_fn(settings)

    batch_id = next_id("R", run_date, counter_path)

    in_batch: list = []
    review: list = []
    for src in paths.discover_inputs(paths.reprocess):
        try:
            res = convert_fn(src)
            override = _load_override(src)
            if override is not None and not res.ok:
                res = _apply_override(res, override, settings)
            elif override is not None and res.ok:
                res.manual_approval = True  # reviewer touched it; note it
        except Exception as exc:
            res = PipelineResult(source=str(src), status=STATUS_REVIEW,
                                 reasons=[f"review processing error: {exc}"])
        (in_batch if res.ok else review).append((src, res))

    return _finalize("R", batch_id, in_batch, review, paths, settings)
