"""Batch assembly: a mix of good invoices + one bad one -> the good ones are
grouped into the CSV, the bad one is routed to review, naming is correct."""

from decimal import Decimal

from pdi_invoice_converter.batch import assemble_batch
from pdi_invoice_converter.counter import batch_filename, next_id
from pdi_invoice_converter.model import Invoice, LineItem


def _li(item_no, qty, price, ext=None):
    return LineItem(item_no=item_no, qty=Decimal(str(qty)), price=Decimal(str(price)),
                    extended=None if ext is None else Decimal(str(ext)))


def good_bimbo() -> Invoice:
    return Invoice(
        vendor_id="147", vendor_name="BIMBO BAKERIES USA", site_id="0062",
        date="20260728", invoice_ref="BIMBO-GOOD", total=Decimal("23.00"),
        stated_qty_count=Decimal("9"),
        items=[_li("008788", 10, "2.00", "20.00"),
               _li("008771", 5, "3.00", "15.00"),
               _li("008788", -6, "2.00", "-12.00")],
    )


def good_coca() -> Invoice:
    return Invoice(
        vendor_id="103", vendor_name="COCA-COLA SOUTHWEST BEVERAGES LLC",
        site_id="0062", date="20260827", invoice_ref="COCA-GOOD",
        total=Decimal("35.00"), stated_qty_count=Decimal("5"),
        items=[_li("858176002157", 2, "10.00", "20.00"),
               _li("070847811169", 3, "5.00", "15.00")],
    )


def bad_coca() -> Invoice:
    # Money does not tie out (sum 40.00 != net 35.00) -> must go to review.
    return Invoice(
        vendor_id="103", vendor_name="COCA-COLA SOUTHWEST BEVERAGES LLC",
        site_id="0062", date="20260827", invoice_ref="COCA-BAD",
        total=Decimal("35.00"), stated_qty_count=Decimal("5"),  # qty is fine; money is not
        items=[_li("858176002157", 3, "10.00", "30.00"),
               _li("070847811169", 2, "5.00", "10.00")],
    )


def test_mixed_batch_partial_success():
    batch_id = "B-1_08-29-2026"
    fname = batch_filename(batch_id)
    result = assemble_batch([good_bimbo(), bad_coca(), good_coca()], batch_id, fname)

    # Good ones in the batch, bad one in review.
    refs_in = {inv.invoice_ref for inv in result.in_batch}
    assert refs_in == {"BIMBO-GOOD", "COCA-GOOD"}
    assert len(result.review) == 1
    assert result.review[0].invoice.invoice_ref == "COCA-BAD"
    assert 4 in {f.gate for f in result.review[0].result.failures}

    # Naming.
    assert result.batch_id == "B-1_08-29-2026"
    assert result.filename == "B-1_08-29-2026.csv"
    assert result.has_output

    # CSV is vendor-grouped and excludes the bad invoice.
    lines = result.csv_text.splitlines()
    assert lines[0] == "0000,MI,147"
    assert lines.count("0000,MI,147") == 1
    assert lines.count("0000,MI,103") == 1
    assert "COCA-BAD" not in result.csv_text
    assert "BIMBO-GOOD" in result.csv_text
    assert "COCA-GOOD" in result.csv_text


def test_manifest_lists_in_batch_and_review():
    result = assemble_batch([good_bimbo(), bad_coca()], "B-1_08-29-2026",
                            "B-1_08-29-2026.csv")
    man = result.manifest_text()
    assert "IN-BATCH" in man and "BIMBO-GOOD" in man
    assert "REVIEW" in man and "COCA-BAD" in man
    assert "failed_gates=[4]" in man


def test_all_bad_writes_no_output():
    result = assemble_batch([bad_coca()], "B-1_08-29-2026", "B-1_08-29-2026.csv")
    assert not result.has_output
    assert result.csv_text == ""
    assert len(result.review) == 1


def test_counter_drives_naming(tmp_path):
    # End-to-end naming: counter id -> filename, first run of the day is B-1.
    p = tmp_path / "counter.json"
    bid = next_id("B", "08-29-2026", p)
    result = assemble_batch([good_bimbo()], bid, batch_filename(bid))
    assert result.filename == "B-1_08-29-2026.csv"
