"""v7 format goldens — the writer must reproduce the lines from the v7 spec's
EXAMPLES section byte-for-byte, and OTHER CHARGES / discounts must be counted in
the money tie-out (gate 4). See prompts/multi_vendor_invoice_prompt v7.txt and
UPDATE_INSTRUCTIONS Part A.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from pdi_invoice_converter.model import Invoice, LineItem
from pdi_invoice_converter.validate import validate
from pdi_invoice_converter.writer import assemble, item_line, to_bytes

FIXTURES = Path(__file__).parent / "fixtures"


def _li(item_no, qty, price, counts_qty=True):
    return LineItem(item_no=item_no, qty=Decimal(str(qty)), price=Decimal(str(price)),
                    counts_qty=counts_qty)


# Each case is (LineItem, exact 1202 line text) taken verbatim from v7's EXAMPLES.
V7_EXAMPLE_LINES = [
    # zero-shipped: qty ".0000", real price KEPT (not 0.0000,0.0000)
    (_li("56691", 0, "29.30"),                 "1202,56691,,.0000,29.3000,,,,"),
    # OTHER CHARGES / fixed VINs -> ordinary 1202 lines, qty 1
    (_li("FUEL", 1, "12.50", counts_qty=False),        "1202,FUEL,,1.0000,12.5000,,,,"),
    (_li("SHIPPING", 1, "32.63", counts_qty=False),    "1202,SHIPPING,,1.0000,32.6300,,,,"),
    (_li("PICKING/DELIVERY CHARGE", 1, "70.00", counts_qty=False),
     "1202,PICKING/DELIVERY CHARGE,,1.0000,70.0000,,,,"),
    (_li("MIXED ITEMS", 1, "2044.51", counts_qty=False),
     "1202,MIXED ITEMS,,1.0000,2044.5100,,,,"),
    # VOLUME ADJ credit -> negative amount
    (_li("VOLUME ADJ", 1, "-15.00", counts_qty=False), "1202,VOLUME ADJ,,1.0000,-15.0000,,,,"),
    # coupon attached to an item -> ONE net-price line (7.04 - 1.00 - 0.25 = 5.79)
    (_li("1220190", 1, "5.79"),                "1202,1220190,,1.0000,5.7900,,,,"),
    # invoice-wide discount -> negative
    (_li("DISCOUNT", 1, "-20.00", counts_qty=False),   "1202,DISCOUNT,,1.0000,-20.0000,,,,"),
    # void / return -> same item#, NEGATIVE qty, positive price
    (_li("24888", -1, "16.44"),                "1202,24888,,-1.0000,16.4400,,,,"),
    # free / gratis unit -> second line at price 0 (".0000")
    (_li("1354", 23, "0"),                     "1202,1354,,23.0000,.0000,,,,"),
]


@pytest.mark.parametrize("li,expected", V7_EXAMPLE_LINES,
                         ids=[e.split(",")[1] or "empty" for _, e in V7_EXAMPLE_LINES])
def test_writer_reproduces_v7_example_line(li, expected):
    assert item_line(li) == expected


def _rd_charges_invoice() -> Invoice:
    """A Restaurant Depot invoice exercising the v7 line types together:
    coupon->net, void, zero-shipped, two PICKING/DELIVERY CHARGE lines, VOLUME ADJ.
    Header TOTAL includes the delivery charges (2204.51-style rule)."""
    return Invoice(
        vendor_id="1248", vendor_name="WIDGET WHOLESALE SUPPLY",
        site_id="0008", date="20260901", invoice_ref="RD-DEMO",
        total=Decimal("145.06"),
        items=[
            _li("1220190", 1, "5.79"),
            _li("32566", 1, "10.71"),
            _li("24888", -1, "16.44"),
            _li("56691", 0, "29.30"),
            _li("PICKING/DELIVERY CHARGE", 1, "70.00", counts_qty=False),
            _li("PICKING/DELIVERY CHARGE", 1, "90.00", counts_qty=False),
            _li("VOLUME ADJ", 1, "-15.00", counts_qty=False),
        ],
    )


def test_v7_restaurant_depot_golden_byte_for_byte():
    got = to_bytes(assemble([_rd_charges_invoice()]))
    assert got == (FIXTURES / "v7_restaurant_depot_charges.txt").read_bytes()


def test_other_charges_and_discounts_are_in_the_money_tie_out():
    # gate 4 sums EVERY 1202 line (charges + discounts + void + zero-shipped);
    # 5.79 + 10.71 - 16.44 + 0 + 70 + 90 - 15 == 145.06
    result = validate(_rd_charges_invoice())
    assert result.passed, result.reason_text()
