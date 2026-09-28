"""Single-invoice pipeline: prep -> extract -> model -> sites/vendors -> validate
-> writer. Shared by the batch and review runners (Phase 3).

Two entry points:
  - ``convert_extracted`` runs everything AFTER extraction on an already-parsed
    JSON dict. It has no API dependency, so it is what the tests and the
    (no-API) Phase-2 demo drive.
  - ``convert_file`` adds the vision step in front and retries once with the
    escalate model on a validation failure before routing to review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .config import Settings
from .model import Invoice, LineItem
from .sites import SiteLookup
from .validate import ValidationResult, validate
from .vendors import VendorLookup
from .writer import assemble

log = logging.getLogger(__name__)

STATUS_OK = "in_batch"
STATUS_REVIEW = "review"


@dataclass
class PipelineResult:
    source: str
    status: str                                   # STATUS_OK | STATUS_REVIEW
    invoice: Optional[Invoice] = None
    validation: Optional[ValidationResult] = None
    csv_text: str = ""
    reasons: list[str] = field(default_factory=list)
    model_used: Optional[str] = None
    extracted: Optional[dict] = None
    manual_approval: bool = False   # set by review-run when a human override applies

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def reason_text(self) -> str:
        parts = list(self.reasons)
        if self.validation and not self.validation.passed:
            parts.append(self.validation.reason_text())
        return "\n".join(parts) if parts else "PASS"


def _opt(d: dict, key: str):
    v = d.get(key)
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none")):
        return None
    return v


def build_line_items(rows: list[dict]) -> tuple[LineItem, ...]:
    items = []
    for r in rows:
        items.append(LineItem(
            item_no=str(r["item_no"]),
            qty=Decimal(str(r["qty"])),
            price=Decimal(str(r["price"])),
            extended=None if _opt(r, "extended") is None else Decimal(str(r["extended"])),
            is_tote=bool(r.get("is_tote", False)),
            counts_qty=bool(r.get("counts_qty", True)),
        ))
    return tuple(items)


def resolve_ids(
    extracted: dict,
    vendors: VendorLookup,
    sites: SiteLookup,
    vendor_override: Optional[str] = None,
    site_override: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], Optional[str], list[str]]:
    """Return (vendor_id, vendor_name, site_id, reasons). A missing/ambiguous id
    produces a reason and a None id -> the caller routes to review."""
    reasons: list[str] = []

    if vendor_override:
        vendor_id, vendor_name = vendor_override, extracted.get("vendor_name", "")
    else:
        vm = vendors.match(extracted.get("vendor_name", "") or "")
        vendor_id, vendor_name = vm.vendor_id, vm.vendor_name
        if not vm.matched:
            reasons.append(f"VENDOR: {vm.reason}")

    if site_override:
        site_id = site_override
    else:
        sm = sites.match(name=_opt(extracted, "store_name"),
                         address=_opt(extracted, "store_address"))
        site_id = sm.site_id
        if not sm.matched:
            reasons.append(f"SITE: {sm.reason}")

    return vendor_id, vendor_name, site_id, reasons


def convert_extracted(
    extracted: dict,
    source: str = "<extracted>",
    settings: Optional[Settings] = None,
    vendors: Optional[VendorLookup] = None,
    sites: Optional[SiteLookup] = None,
    vendor_override: Optional[str] = None,
    site_override: Optional[str] = None,
) -> PipelineResult:
    """Run model -> sites/vendors -> validate -> writer on parsed JSON."""
    settings = settings or Settings.load()
    vendors = vendors or VendorLookup.load(settings.vendor_ids_file)
    sites = sites or SiteLookup.load(settings.site_ids_file)

    vendor_id, vendor_name, site_id, reasons = resolve_ids(
        extracted, vendors, sites, vendor_override, site_override)

    if vendor_id is None or site_id is None:
        # Cannot even build the record without both IDs -> straight to review.
        return PipelineResult(source=source, status=STATUS_REVIEW, reasons=reasons,
                              extracted=extracted)

    invoice = Invoice(
        vendor_id=vendor_id,
        vendor_name=vendor_name or extracted.get("vendor_name", ""),
        site_id=site_id,
        date=str(extracted["invoice_date"]),
        invoice_ref=str(extracted["invoice_ref"]),
        total=Decimal(str(extracted["net_total"])),
        items=build_line_items(extracted["line_items"]),
        tax=None if _opt(extracted, "tax") is None else Decimal(str(extracted["tax"])),
        stated_qty_count=None if _opt(extracted, "stated_qty_count") is None
        else Decimal(str(extracted["stated_qty_count"])),
        stated_totes=None if _opt(extracted, "stated_totes") is None
        else Decimal(str(extracted["stated_totes"])),
        gross=None if _opt(extracted, "gross") is None else Decimal(str(extracted["gross"])),
        discounts=None if _opt(extracted, "discounts") is None
        else Decimal(str(extracted["discounts"])),
        fees=None if _opt(extracted, "fees") is None else Decimal(str(extracted["fees"])),
    )

    result = validate(invoice, tolerance=settings.money_tolerance)
    if result.passed:
        return PipelineResult(source=source, status=STATUS_OK, invoice=invoice,
                              validation=result, csv_text=assemble([invoice]),
                              reasons=reasons, extracted=extracted)
    return PipelineResult(source=source, status=STATUS_REVIEW, invoice=invoice,
                          validation=result, reasons=reasons, extracted=extracted)


def convert_file(
    path: str | Path,
    settings: Optional[Settings] = None,
    vendor_override: Optional[str] = None,
    site_override: Optional[str] = None,
    api_key: Optional[str] = None,
) -> PipelineResult:
    """Full path incl. vision extraction. On validation failure, retry ONCE with
    the escalate model, then route to review."""
    from . import extract  # lazy: keeps the offline core import-free of the SDK

    settings = settings or Settings.load()
    vendors = VendorLookup.load(settings.vendor_ids_file)
    sites = SiteLookup.load(settings.site_ids_file)
    source = str(path)

    provider = settings._d.get("provider", "anthropic")
    prov_cfg = settings._d.get(provider) or {}
    _defaults = {
        "anthropic": ("claude-sonnet-5", "claude-opus-4-8"),
        "gemini": ("gemini-2.5-flash", "gemini-flash-latest"),
    }
    d_extract, d_escalate = _defaults.get(provider, ("", ""))
    extract_model = prov_cfg.get("extract_model", d_extract)
    escalate_model = prov_cfg.get("escalate_model", d_escalate)

    last: Optional[PipelineResult] = None
    for attempt, model in enumerate((extract_model, escalate_model), start=1):
        try:
            out = extract.extract_file(path, model=model, dpi=settings._d.get("pdf", {}).get("dpi", 220),
                                       do_deskew=settings._d.get("pdf", {}).get("deskew", True),
                                       api_key=api_key, provider=provider)
        except Exception as exc:
            # A bad/truncated model reply (or a transient API error) must not crash
            # the run: record it and let the escalate attempt try before review.
            log.warning("attempt %d (%s) extraction error for %s: %s",
                        attempt, model, source, exc)
            last = PipelineResult(source=source, status=STATUS_REVIEW,
                                  reasons=[f"extraction error ({model}): {exc}"])
            continue
        res = convert_extracted(out.data, source=source, settings=settings,
                                vendors=vendors, sites=sites,
                                vendor_override=vendor_override, site_override=site_override)
        res.model_used = out.model_used
        if res.ok:
            return res
        log.warning("attempt %d (%s) failed validation for %s", attempt, model, source)
        last = res
    return last  # review, from the escalate attempt
