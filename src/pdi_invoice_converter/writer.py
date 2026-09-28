"""PDI record writer — the byte-deterministic output core.

Emits 0000 / 1200 / 1202 records EXACTLY per docs/CONVERSION_RULES.md:
  - 0000,MI,<VENDOR_ID>                               (once per vendor block)
  - 1200,<DATE>,<SITE>,<REF>,I,,<TOTAL> + 27 trailing commas   (34 fields)
  - 1202,<ITEM#>,,<QTY>,<PRICE>,,,,                   (9 fields: 4 trailing commas)
  - SALES TAX line, when Invoice.tax is not None: 1202,SALES TAX,,1.0000,<tax>,,,,

Rules baked in: qty/price at 4 decimals; net total at 2 decimals; returns keep a
negative qty; a zero item qty/price is written as ".0000" (v7 — e.g. a 0-shipped
line keeps its real price: 1202,56691,,.0000,29.3000,,,,); no spaces; no blank
lines; LF newlines with a trailing newline; grouped by vendor with one 0000 per
vendor. NOTE: the SALES TAX line keeps a leading zero when the tax is 0
(1.0000,0.0000) — only item qty/price use the ".0000" short form.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from .model import Invoice, LineItem

# Header = 7 real fields (1200,DATE,SITE,REF,I,<empty>,TOTAL) then 27 trailing
# commas -> 34 fields / 33 commas total. Verified against the golden fixtures.
_HEADER_TRAILING_COMMAS = 27
_NEWLINE = "\n"


def _q4(v: Decimal) -> str:
    """4-decimal number, leading zero kept. -6 -> '-6.0000', 0 -> '0.0000'.
    Used for the SALES TAX amount (v7 shows a zero tax as 1.0000,0.0000)."""
    return str(Decimal(v).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _q4_item(v: Decimal) -> str:
    """4-decimal qty/price for a 1202 item line. Same as _q4 EXCEPT an exact zero
    is written as '.0000' (no leading zero) to match v7's format goldens — a
    0-shipped qty (1202,56691,,.0000,29.3000,,,,) and a free/gratis price
    (1202,1354,,23.0000,.0000,,,,). A non-zero fraction keeps its zero (0.8600)."""
    s = _q4(v)
    return ".0000" if s == "0.0000" else s


def _q2(v: Decimal) -> str:
    """Net total / tax at exactly 2 decimals. 7379 -> '7379.00'."""
    return str(Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def vendor_block_header(vendor_id: str) -> str:
    """The 0000 line that opens a vendor block."""
    return f"0000,MI,{vendor_id}"


def invoice_header(inv: Invoice) -> str:
    """The 1200 line for one invoice."""
    base = f"1200,{inv.date},{inv.site_id},{inv.invoice_ref},I,,{_q2(inv.total)}"
    return base + ("," * _HEADER_TRAILING_COMMAS)


def item_line(item: LineItem) -> str:
    """A 1202 product/return/discount/charge line. FUEL, SHIPPING, PICKING/DELIVERY
    CHARGE, MIXED ITEMS, VOLUME ADJ and invoice-wide DISCOUNT lines are ordinary
    1202 lines too — their VIN is just the charge/discount name in item_no."""
    return f"1202,{item.item_no},,{_q4_item(item.qty)},{_q4_item(item.price)},,,,"


def tax_line(tax: Decimal) -> str:
    """The SALES TAX 1202 line (only emitted when Invoice.tax is not None)."""
    return f"1202,SALES TAX,,1.0000,{_q4(tax)},,,,"


def invoice_lines(inv: Invoice) -> list[str]:
    """Every line for a single invoice: header, items, then tax (if present).
    Does NOT include the vendor 0000 header — the assembler owns vendor grouping.
    """
    lines = [invoice_header(inv)]
    lines.extend(item_line(it) for it in inv.items)
    if inv.tax is not None:
        lines.append(tax_line(inv.tax))
    return lines


def assemble(invoices: Iterable[Invoice]) -> str:
    """Assemble invoices into one vendor-grouped file (string form).

    - Vendors appear in first-seen order; invoices keep upload order within a vendor.
    - Exactly one 0000,MI,<vid> per vendor, right before that vendor's first invoice.
    - No blank lines; LF newlines; a single trailing newline. Byte-deterministic.
    """
    invoices = list(invoices)
    order: list[str] = []
    grouped: dict[str, list[Invoice]] = {}
    for inv in invoices:
        if inv.vendor_id not in grouped:
            grouped[inv.vendor_id] = []
            order.append(inv.vendor_id)
        grouped[inv.vendor_id].append(inv)

    out: list[str] = []
    for vid in order:
        out.append(vendor_block_header(vid))
        for inv in grouped[vid]:
            out.extend(invoice_lines(inv))

    if not out:
        return ""
    return _NEWLINE.join(out) + _NEWLINE


def to_bytes(text: str) -> bytes:
    """Encode for writing to disk. UTF-8, LF preserved (no CRLF translation)."""
    return text.encode("utf-8")
