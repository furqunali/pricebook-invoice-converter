"""Phase 5 (Part 1) reporting engine — subscription-only, NO paid API.

Reads the converter's own output (the PDI import CSVs in 2-converted/ and the
batch/review manifests in logs/) and produces:
  * a store-wise + vendor-wise purchase report,
  * a reconciliation FRAMEWORK (converter column filled now; PDI-posted and
    vendor-statement columns are configurable stubs for the real 3-way match),
  * professional PDF + Excel in the reports folder,
  * a clean, refreshable Power BI dataset (flat CSV + suggested DAX).

Everything here is pure Python + openpyxl/reportlab (the ``reports`` extra). No
model call is involved, so it runs on the subscription/offline like the core.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .config import Settings

log = logging.getLogger(__name__)

# Corporate theme (teal / navy brand).
NAVY = "1F3A5F"
TEAL = "0E7C7B"
LIGHT = "EAF2F1"
GREY = "6B7280"
_MONEY = "$#,##0.00"


# --------------------------------------------------------------------------- #
# Parsing the converter's own output
# --------------------------------------------------------------------------- #

@dataclass
class InvoiceLine:
    item_no: str
    qty: Decimal
    price: Decimal

    @property
    def ext(self) -> Decimal:
        return self.qty * self.price


@dataclass
class PurchaseInvoice:
    vendor_id: str
    site_id: str
    date: str
    invoice_ref: str
    total: Decimal
    lines: list[InvoiceLine] = field(default_factory=list)
    batch_id: str = ""

    @property
    def returns(self) -> Decimal:
        return sum((ln.ext for ln in self.lines if ln.qty < 0), Decimal(0))

    @property
    def discounts(self) -> Decimal:
        return sum((ln.ext for ln in self.lines if ln.price < 0 and ln.qty >= 0), Decimal(0))

    @property
    def gross(self) -> Decimal:
        return sum((ln.ext for ln in self.lines if ln.qty >= 0 and ln.price >= 0), Decimal(0))


def parse_pdi_csv(text: str, batch_id: str = "") -> list[PurchaseInvoice]:
    """Parse a 0000/1200/1202 PDI import file into purchase invoices."""
    out: list[PurchaseInvoice] = []
    vendor: Optional[str] = None
    cur: Optional[PurchaseInvoice] = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        p = raw.split(",")
        if p[0] == "0000":
            vendor = p[2] if len(p) > 2 else None
        elif p[0] == "1200" and len(p) >= 7:
            cur = PurchaseInvoice(vendor_id=vendor or "?", site_id=p[2], date=p[1],
                                  invoice_ref=p[3], total=Decimal(p[6] or "0"),
                                  batch_id=batch_id)
            out.append(cur)
        elif p[0] == "1202" and cur is not None and len(p) >= 5:
            cur.lines.append(InvoiceLine(item_no=p[1], qty=Decimal(p[3] or "0"),
                                         price=Decimal(p[4] or "0")))
    return out


def load_converted(converted_dir: Path) -> list[PurchaseInvoice]:
    """Every purchase invoice from the CSVs the converter has produced."""
    invoices: list[PurchaseInvoice] = []
    if not converted_dir.exists():
        return invoices
    for f in sorted(converted_dir.glob("*.csv")):
        invoices.extend(parse_pdi_csv(f.read_text(encoding="utf-8"), batch_id=f.stem))
    return invoices


@dataclass
class ManifestInfo:
    batch_id: str
    kind: str
    in_batch: int
    review: int
    approved: int
    review_entries: list[tuple[str, str]]  # (source file, reason)


def parse_manifest(text: str) -> ManifestInfo:
    lines = text.splitlines()
    head = lines[0] if lines else ""
    kind = "REVIEW-RUN" if head.startswith("REVIEW-RUN") else "BATCH"
    batch_id = head.split("MANIFEST", 1)[1].strip() if "MANIFEST" in head else ""
    in_batch = review = approved = 0
    reviews: list[tuple[str, str]] = []
    for ln in lines:
        if ln.startswith("REVIEW ") or ln.startswith("REVIEW\t") or ln.startswith("REVIEW  "):
            src = ln[len("REVIEW"):].strip().split("  ")[0].strip()
            reason = ln.split("reason:", 1)[1].strip() if "reason:" in ln else ln.strip()
            reviews.append((src, reason))
        if "[MANUALLY APPROVED]" in ln:
            approved += 1
        m = re.search(r"totals:\s*in_batch=(\d+)\s+review=(\d+)", ln)
        if m:
            in_batch, review = int(m.group(1)), int(m.group(2))
    return ManifestInfo(batch_id, kind, in_batch, review, approved, reviews)


def load_manifests(logs_dir: Path) -> list[ManifestInfo]:
    if not logs_dir.exists():
        return []
    return [parse_manifest(f.read_text(encoding="utf-8"))
            for f in sorted(logs_dir.glob("*.manifest.txt"))]


# --------------------------------------------------------------------------- #
# Id -> name lookups (reverse of the matcher tables)
# --------------------------------------------------------------------------- #

def _reverse_lookup(csv_path: Path, id_col: int, name_col: int) -> dict[str, str]:
    m: dict[str, str] = {}
    if not csv_path.exists():
        return m
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    for r in rows[1:]:
        if len(r) > max(id_col, name_col):
            m[r[id_col].strip()] = r[name_col].strip()
    return m


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

@dataclass
class Aggregates:
    period: str
    invoices: list[PurchaseInvoice]
    vendor_names: dict[str, str]
    site_names: dict[str, str]
    manifests: list[ManifestInfo]

    def total_purchases(self) -> Decimal:
        return sum((iv.total for iv in self.invoices), Decimal(0))

    def by_site(self) -> list[dict]:
        agg: dict[str, dict] = {}
        for iv in self.invoices:
            a = agg.setdefault(iv.site_id, {"count": 0, "total": Decimal(0),
                                            "returns": Decimal(0)})
            a["count"] += 1
            a["total"] += iv.total
            a["returns"] += iv.returns
        rows = [{"site_id": s, "site": self.site_names.get(s, s), **v}
                for s, v in agg.items()]
        return sorted(rows, key=lambda r: r["total"], reverse=True)

    def by_vendor(self) -> list[dict]:
        agg: dict[str, dict] = {}
        for iv in self.invoices:
            a = agg.setdefault(iv.vendor_id, {"count": 0, "total": Decimal(0)})
            a["count"] += 1
            a["total"] += iv.total
        rows = [{"vendor_id": v, "vendor": self.vendor_names.get(v, v), **d}
                for v, d in agg.items()]
        return sorted(rows, key=lambda r: r["total"], reverse=True)

    def review_rate(self) -> float:
        ib = sum(m.in_batch for m in self.manifests)
        rv = sum(m.review for m in self.manifests)
        return (rv / (ib + rv)) if (ib + rv) else 0.0

    def exceptions(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for m in self.manifests:
            out.extend(m.review_entries)
        return out


def build_aggregates(converted_dir: Path, logs_dir: Path, settings: Settings,
                     period: str) -> Aggregates:
    return Aggregates(
        period=period,
        invoices=load_converted(converted_dir),
        vendor_names=_reverse_lookup(settings.vendor_ids_file, 1, 0),
        site_names=_reverse_lookup(settings.site_ids_file, 1, 0),
        manifests=load_manifests(logs_dir),
    )


# --------------------------------------------------------------------------- #
# Reconciliation framework (3-way) — converter filled, others are stubs
# --------------------------------------------------------------------------- #

def _opt_dir(settings: Settings, key: str) -> Optional[Path]:
    raw = (settings._d.get("paths") or {}).get(key)
    return Path(raw) if raw else None


def load_pdi_export(settings: Settings) -> Optional[dict[str, Decimal]]:
    """STUB for the real 3-way match. Returns vendor_id -> posted total once a
    ``pdi_export_dir`` is configured AND holds data; None means 'not wired yet'."""
    d = _opt_dir(settings, "pdi_export_dir")
    if not d or not d.exists() or not any(d.glob("*")):
        return None
    return None  # real PDI-Export parser lands here in Part 2


def load_vendor_statements(settings: Settings) -> Optional[dict[str, Decimal]]:
    """STUB, as above, for ``vendor_statements_dir``."""
    d = _opt_dir(settings, "vendor_statements_dir")
    if not d or not d.exists() or not any(d.glob("*")):
        return None
    return None


def reconciliation_rows(agg: Aggregates, settings: Settings) -> tuple[list[dict], str]:
    """Per-vendor 3-way rows. PDI/vendor columns show PENDING until wired."""
    pdi = load_pdi_export(settings)
    stmt = load_vendor_statements(settings)
    status = "READY" if (pdi is not None and stmt is not None) else "PENDING (stub)"
    rows = []
    for v in agg.by_vendor():
        conv = v["total"]
        p = pdi.get(v["vendor_id"]) if pdi else None
        s = stmt.get(v["vendor_id"]) if stmt else None
        rows.append({
            "vendor": v["vendor"], "vendor_id": v["vendor_id"], "converter": conv,
            "pdi_posted": p, "vendor_stmt": s,
            "variance": (conv - p) if p is not None else None,
        })
    return rows, status


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #

def _money(v: Optional[Decimal]) -> str:
    return "PENDING" if v is None else f"${v:,.2f}"


def _f(v: Decimal) -> float:
    return float(v)
