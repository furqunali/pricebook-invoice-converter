"""Data models. Money is always Decimal — never float.

An ``Invoice`` is the vendor-agnostic representation the writer and validator
work on. Vendor-specific reading (which column is qty/price/net) happens during
extraction (Phase 2); by the time we have an Invoice, the fields already mean the
same thing for every vendor.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


def to_decimal(v) -> Decimal:
    """Coerce ints/strings/Decimals to Decimal. Rejects float (precision risk)."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):  # bool is an int subclass; disallow it explicitly
        raise TypeError("bool is not a valid money/quantity value")
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, str):
        return Decimal(v.strip())
    if isinstance(v, float):
        raise TypeError("money/quantity must be Decimal, int, or str — not float")
    raise TypeError(f"cannot convert {type(v)!r} to Decimal")


class LineItem(BaseModel):
    """One 1202 line: a product, return, discount, or extra-charge line.

    The SALES TAX line is NOT a LineItem — tax lives on ``Invoice.tax`` and the
    writer emits it separately, so validation never double-counts it.
    """

    model_config = ConfigDict(frozen=True)

    item_no: str                        # exactly as printed; keep leading zeros
    qty: Decimal                        # shipped qty; negative for returns
    price: Decimal                      # per-unit price (net where discounted)
    extended: Optional[Decimal] = None  # printed line total, if the invoice shows one
    is_tote: bool = False               # true if this line is a tote (for gate 3)
    counts_qty: bool = True             # products/returns count toward the qty
    #                                     total (gate 2); discount/charge lines do not

    @field_validator("item_no", mode="before")
    @classmethod
    def _item_no_str(cls, v):
        # IDs/item numbers are always strings; never let pydantic int-ify them.
        if isinstance(v, str):
            return v
        raise TypeError("item_no must be a string (preserve exact digits)")

    @field_validator("qty", "price", "extended", mode="before")
    @classmethod
    def _money(cls, v):
        if v is None:
            return v
        return to_decimal(v)


class Invoice(BaseModel):
    """One supplier invoice, ready to validate + write."""

    model_config = ConfigDict(frozen=True)

    vendor_id: str                    # from vendor_ids.csv; string, keep as-is
    vendor_name: str                  # seller name as matched (for manifests)
    site_id: str                      # 4-digit store id; string, keep leading zeros
    date: str                         # invoice date, YYYYMMDD
    invoice_ref: str                  # invoice number exactly as printed
    total: Decimal                    # the NET total (2 dp)
    items: tuple[LineItem, ...]       # product/return/discount/charge lines
    tax: Optional[Decimal] = None     # None = no tax line; 0 = show 0.0000 line

    # Optional stated figures the invoice prints, used by validation gates:
    stated_qty_count: Optional[Decimal] = None   # gate 2 (net qty total)
    stated_totes: Optional[Decimal] = None       # gate 3 (totes count)
    gross: Optional[Decimal] = None              # gate 5 (gross - adj == net)
    discounts: Optional[Decimal] = None          # gate 5
    fees: Optional[Decimal] = None               # gate 5

    @field_validator("vendor_id", "site_id", "invoice_ref", "date", mode="before")
    @classmethod
    def _keep_string(cls, v):
        if isinstance(v, str):
            return v
        raise TypeError("vendor_id/site_id/invoice_ref/date must be strings")

    @field_validator(
        "total", "tax", "stated_qty_count", "stated_totes",
        "gross", "discounts", "fees", mode="before",
    )
    @classmethod
    def _money(cls, v):
        if v is None:
            return v
        return to_decimal(v)

    @field_validator("items", mode="before")
    @classmethod
    def _tuple_items(cls, v):
        return tuple(v)
