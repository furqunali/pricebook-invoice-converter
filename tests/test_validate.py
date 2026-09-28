"""Validation gates: synthetic clean invoices pass; mutating one qty fails the
matching gate; per-vendor quantity labels appear in diagnostics."""

from decimal import Decimal

from pdi_invoice_converter.model import Invoice, LineItem
from pdi_invoice_converter.validate import validate


def _li(item_no, qty, price, ext=None, counts_qty=True):
    return LineItem(
        item_no=item_no, qty=Decimal(str(qty)), price=Decimal(str(price)),
        extended=None if ext is None else Decimal(str(ext)), counts_qty=counts_qty,
    )


def clean_bimbo() -> Invoice:
    # qty*price sums EXACTLY to net total; includes a negative-qty return line.
    return Invoice(
        vendor_id="147", vendor_name="BIMBO BAKERIES USA",
        site_id="0062", date="20260728", invoice_ref="B-CLEAN",
        total=Decimal("23.00"), stated_qty_count=Decimal("9"),
        items=[
            _li("008788", 10, "2.00", ext="20.00"),
            _li("008771", 5, "3.00", ext="15.00"),
            _li("008788", -6, "2.00", ext="-12.00"),
        ],
    )


def clean_coca_cola() -> Invoice:
    return Invoice(
        vendor_id="103", vendor_name="COCA-COLA SOUTHWEST BEVERAGES LLC",
        site_id="0062", date="20260827", invoice_ref="C-CLEAN",
        total=Decimal("35.00"), stated_qty_count=Decimal("5"),
        items=[
            _li("858176002157", 2, "10.00", ext="20.00"),
            _li("070847811169", 3, "5.00", ext="15.00"),
        ],
    )


def clean_texas_jasmine() -> Invoice:
    # Has a tax line: sum(items)=25.00 + tax 2.00 == net 27.00.
    return Invoice(
        vendor_id="1101", vendor_name="TEXAS JASMINE",
        site_id="0016", date="20260813", invoice_ref="T-CLEAN",
        total=Decimal("27.00"), tax=Decimal("2.00"), stated_qty_count=Decimal("3"),
        gross=Decimal("25.00"),  # gross (pre-tax) 25 + tax 2 == net 27
        items=[
            _li("002986", 2, "10.00", ext="20.00"),
            _li("002985", 1, "5.00", ext="5.00"),
        ],
    )


def test_clean_invoices_pass_all_gates():
    for inv in (clean_bimbo(), clean_coca_cola(), clean_texas_jasmine()):
        res = validate(inv)
        assert res.passed, res.reason_text()
        assert res.failures == []


def test_mutating_one_qty_fails_the_money_gate():
    good = clean_bimbo()
    # Bump one line's qty: line math (gate 1), qty count (gate 2) and money (gate 4)
    # all break — proving the mutation is caught.
    bad_items = list(good.items)
    bad_items[0] = bad_items[0].model_copy(update={"qty": Decimal("11")})
    bad = good.model_copy(update={"items": tuple(bad_items)})

    res = validate(bad)
    assert not res.passed
    failed_gates = {f.gate for f in res.failures}
    assert 4 in failed_gates            # universal money tie-out
    assert 1 in failed_gates            # per-line ext no longer matches
    assert 2 in failed_gates            # qty count no longer matches


def test_gate2_uses_vendor_specific_labels():
    labels = {
        "147": "TICKET TOTAL",
        "103": "NET PRODUCT QTY",
        "1101": "Total Item Count",
    }
    builders = {"147": clean_bimbo, "103": clean_coca_cola, "1101": clean_texas_jasmine}
    for vid, build in builders.items():
        inv = build()
        # State a wrong count so gate 2 fails and we can read its label.
        bad = inv.model_copy(update={"stated_qty_count": inv.stated_qty_count + 1})
        res = validate(bad)
        g2 = [f for f in res.failures if f.gate == 2]
        assert g2, f"gate 2 should fail for {vid}"
        assert labels[vid] in g2[0].detail


def test_money_tolerance_one_cent_ok_two_cents_fails():
    base = clean_coca_cola()
    within = base.model_copy(update={"total": Decimal("35.01")})   # 1 cent off
    beyond = base.model_copy(update={"total": Decimal("35.02")})   # 2 cents off
    assert validate(within).passed
    assert not validate(beyond).passed


def test_gross_tie_out_gate5():
    base = clean_texas_jasmine()
    good = base.model_copy(update={"gross": Decimal("30.00"), "discounts": Decimal("5.00")})
    # gross 30 - disc 5 + fees 0 + tax 2 == 27 net -> passes
    assert validate(good).passed
    bad = base.model_copy(update={"gross": Decimal("30.00"), "discounts": Decimal("9.00")})
    res = validate(bad)
    assert not res.passed
    assert 5 in {f.gate for f in res.failures}


def test_totes_gate3():
    base = clean_coca_cola()
    items = list(base.items)
    # Add two tote lines that don't count toward qty; state totes = 2.
    items.append(LineItem(item_no="TOTE", qty=Decimal("2"), price=Decimal("0"),
                          is_tote=True, counts_qty=False))
    good = base.model_copy(update={"items": tuple(items), "stated_totes": Decimal("2")})
    assert validate(good).passed
    bad = good.model_copy(update={"stated_totes": Decimal("3")})
    res = validate(bad)
    assert not res.passed
    assert 3 in {f.gate for f in res.failures}
