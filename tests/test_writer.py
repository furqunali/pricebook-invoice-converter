"""Writer must reproduce the format goldens byte-for-byte, incl. comma counts,
negative-qty returns, and vendor grouping."""

from decimal import Decimal
from pathlib import Path

from pdi_invoice_converter.model import Invoice, LineItem
from pdi_invoice_converter.writer import assemble, invoice_header, item_line, to_bytes

FIXTURES = Path(__file__).parent / "fixtures"


def _golden(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _li(item_no, qty, price):
    return LineItem(item_no=item_no, qty=Decimal(str(qty)), price=Decimal(str(price)))


def bimbo_invoice() -> Invoice:
    return Invoice(
        vendor_id="147", vendor_name="SAMPLE SNACKS LLC",
        site_id="0010", date="20260728", invoice_ref="84071790010652",
        total=Decimal("451.61"),
        items=[
            _li("008788", 10, "2.41"),
            _li("008771", 5, "2.41"),
            _li("008788", -6, "2.41"),  # return -> negative qty
        ],
    )


def coca_cola_invoice() -> Invoice:
    return Invoice(
        vendor_id="103", vendor_name="DEMO DAIRY DISTRIBUTORS",
        site_id="0010", date="20260827", invoice_ref="53989641004",
        total=Decimal("4445.59"),
        items=[
            _li("858176002157", 1, "20.40"),
            _li("070847811169", 4, "42.35"),
            _li("049000031652", 168, "4.60"),
        ],
    )


def texas_jasmine_invoice() -> Invoice:
    prices = [
        ("002986", "22.99"), ("002985", "22.99"), ("002991", "22.99"),
        ("026741", "22.99"), ("024283", "19.99"), ("024447", "19.99"),
        ("026337", "19.99"), ("024448", "19.99"), ("026218", "19.99"),
        ("027038", "19.99"), ("025989", "19.99"), ("026320", "19.99"),
        ("026319", "19.99"), ("024446", "19.99"), ("026673", "19.99"),
        ("024525", "19.99"), ("024524", "19.99"), ("024526", "19.99"),
        ("024449", "19.99"), ("024285", "19.99"), ("024286", "19.99"),
        ("024284", "19.99"), ("008640", "19.99"), ("017272", "34.99"),
        ("027177", "32.99"), ("018379", "32.99"),
    ]
    return Invoice(
        vendor_id="1101", vendor_name="ORCHARD FRUIT CO",
        site_id="0003", date="20260813", invoice_ref="00841982",
        total=Decimal("7379.00"),
        items=[_li(no, 1, pr) for no, pr in prices],
    )


def test_bimbo_matches_golden_byte_for_byte():
    assert to_bytes(assemble([bimbo_invoice()])) == _golden("bimbo_sample.txt")


def test_coca_cola_matches_golden_byte_for_byte():
    assert to_bytes(assemble([coca_cola_invoice()])) == _golden("coca_cola_sample.txt")


def test_texas_jasmine_matches_golden_byte_for_byte():
    assert to_bytes(assemble([texas_jasmine_invoice()])) == \
        _golden("texas_jasmine_header_sample.txt")


def test_header_has_exactly_34_fields_and_27_trailing_commas():
    h = invoice_header(bimbo_invoice())
    assert h.count(",") == 33            # 34 fields
    body, sep, tail = h.partition("451.61")
    assert tail == "," * 27              # exactly 27 trailing commas after TOTAL


def test_item_line_has_9_fields_and_returns_keep_negative_qty():
    line = item_line(_li("008788", -6, "2.41"))
    assert line == "1202,008788,,-6.0000,2.4100,,,,"
    assert line.count(",") == 8          # 9 fields


def test_zero_shipped_qty_is_dot_0000_keeping_real_price():
    # v7: a 0-shipped item keeps its real PRICE and uses qty ".0000"
    # (NOT the old 0.0000,0.0000). See v7 EXAMPLES.
    assert item_line(_li("56691", 0, "29.30")) == "1202,56691,,.0000,29.3000,,,,"


def test_output_uses_lf_and_trailing_newline():
    out = to_bytes(assemble([bimbo_invoice()]))
    assert b"\r\n" not in out
    assert out.endswith(b"\n")
    assert b"\n\n" not in out            # no blank lines


def test_vendor_grouping_one_0000_per_vendor_in_first_seen_order():
    b2 = bimbo_invoice().model_copy(update={"invoice_ref": "84071790010653"})
    text = assemble([bimbo_invoice(), coca_cola_invoice(), b2])
    lines = text.splitlines()
    # Vendors grouped: both Bimbo invoices under a single 0000,MI,147, then 0000,MI,103.
    assert lines[0] == "0000,MI,147"
    assert lines.count("0000,MI,147") == 1
    assert lines.count("0000,MI,103") == 1
    assert lines.index("0000,MI,147") < lines.index("0000,MI,103")
    # both bimbo invoice headers appear before the coca-cola block
    cc = lines.index("0000,MI,103")
    assert any("84071790010652" in ln for ln in lines[:cc])
    assert any("84071790010653" in ln for ln in lines[:cc])


def test_sales_tax_line_emitted_only_when_tax_present():
    with_tax = bimbo_invoice().model_copy(update={"tax": Decimal("1.07")})
    assert "1202,SALES TAX,,1.0000,1.0700,,,," in assemble([with_tax])
    assert "SALES TAX" not in assemble([bimbo_invoice()])
    zero_tax = bimbo_invoice().model_copy(update={"tax": Decimal("0")})
    assert "1202,SALES TAX,,1.0000,0.0000,,,," in assemble([zero_tax])
