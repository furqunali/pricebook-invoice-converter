"""The five validation gates (docs/CONVERSION_RULES.md section 8).

Every gate must pass before an invoice may enter a batch. Any failure routes the
invoice to review with a diagnostic — no silent bad output, ever. Money is
compared with a configurable tolerance (default 0.01, one cent) because scanned
invoices routinely round by a cent.

Gates:
  1. Per-line math      — round(ext) == round(qty*price) for lines that print an ext.
  2. Quantity count     — sum of product/return qty == the invoice's stated net qty.
  3. Totes count        — sum of tote-line qty == the invoice's stated totes count.
  4. Money tie-out      — sum(qty*price over all item lines) + tax == net total.
  5. Gross tie-out      — gross - discounts (+ fees + tax) == net total.

Gates 2, 3, 5 are skipped (not failed) when the invoice does not state the figure
they check. Gate 4 is universal and always runs — it is the main multi-vendor
safety net.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from .model import Invoice

_CENT = Decimal("0.01")

# Vendor-specific label for the quantity total, used in gate-2 diagnostics.
_QTY_LABELS = {
    "1101": 'Texas Jasmine "Total Item Count"',
    "147": 'Bimbo "TICKET TOTAL" qty (deliveries + returns)',
    "103": 'Coca-Cola "NET PRODUCT QTY"',
}


def _r2(v: Decimal) -> Decimal:
    return Decimal(v).quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class GateFailure:
    gate: int
    name: str
    detail: str
    expected: Optional[Decimal] = None
    actual: Optional[Decimal] = None


@dataclass
class ValidationResult:
    passed: bool
    failures: list[GateFailure] = field(default_factory=list)

    def reason_text(self) -> str:
        """Human-readable diagnostic for the .reason.txt written to review."""
        if self.passed:
            return "PASS: all validation gates passed."
        lines = ["FAIL: one or more validation gates failed."]
        for f in self.failures:
            exp = "" if f.expected is None else f"  expected={f.expected}"
            act = "" if f.actual is None else f"  actual={f.actual}"
            lines.append(f"  [gate {f.gate}] {f.name}: {f.detail}{exp}{act}")
        return "\n".join(lines)


def _gate1_line_math(inv: Invoice, tol: Decimal) -> list[GateFailure]:
    out: list[GateFailure] = []
    for i, it in enumerate(inv.items, start=1):
        if it.extended is None:
            continue
        computed = _r2(it.qty * it.price)
        printed = _r2(it.extended)
        if abs(computed - printed) > tol:
            out.append(GateFailure(
                1, "per-line math",
                f"line {i} (item {it.item_no}): qty*price != printed extended",
                expected=printed, actual=computed,
            ))
    return out


def _gate2_qty_count(inv: Invoice, tol: Decimal) -> Optional[GateFailure]:
    if inv.stated_qty_count is None:
        return None
    total = sum((it.qty for it in inv.items if it.counts_qty), Decimal(0))
    if abs(total - inv.stated_qty_count) > tol:
        label = _QTY_LABELS.get(inv.vendor_id, "stated quantity count")
        return GateFailure(
            2, "quantity count",
            f"sum of shipped qty != {label}",
            expected=inv.stated_qty_count, actual=total,
        )
    return None


def _gate3_totes(inv: Invoice, tol: Decimal) -> Optional[GateFailure]:
    if inv.stated_totes is None:
        return None
    totes = sum((it.qty for it in inv.items if it.is_tote), Decimal(0))
    if abs(totes - inv.stated_totes) > tol:
        return GateFailure(
            3, "totes count",
            "sum of tote-line qty != stated totes count",
            expected=inv.stated_totes, actual=totes,
        )
    return None


def _gate4_money(inv: Invoice, tol: Decimal) -> Optional[GateFailure]:
    line_sum = sum((it.qty * it.price for it in inv.items), Decimal(0))
    tax = inv.tax or Decimal(0)
    computed = _r2(line_sum + tax)
    net = _r2(inv.total)
    if abs(computed - net) > tol:
        return GateFailure(
            4, "money tie-out",
            "sum(qty*price) + tax != net total",
            expected=net, actual=computed,
        )
    return None


def _gate5_gross(inv: Invoice, tol: Decimal) -> Optional[GateFailure]:
    if inv.gross is None:
        return None
    discounts = inv.discounts or Decimal(0)
    fees = inv.fees or Decimal(0)
    tax = inv.tax or Decimal(0)
    computed = _r2(inv.gross - discounts + fees + tax)
    net = _r2(inv.total)
    if abs(computed - net) > tol:
        return GateFailure(
            5, "gross tie-out",
            "gross - discounts (+ fees + tax) != net total",
            expected=net, actual=computed,
        )
    return None


def validate(inv: Invoice, tolerance: Decimal = _CENT) -> ValidationResult:
    """Run all five gates. Returns a ValidationResult (passed + failures)."""
    tol = Decimal(tolerance)
    failures: list[GateFailure] = []
    failures.extend(_gate1_line_math(inv, tol))
    for g in (_gate2_qty_count, _gate3_totes, _gate4_money, _gate5_gross):
        f = g(inv, tol)
        if f is not None:
            failures.append(f)
    return ValidationResult(passed=not failures, failures=failures)
