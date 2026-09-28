"""Vendor matching: known sellers resolve to the right id; unknown -> flagged."""

from pdi_invoice_converter.vendors import VendorLookup


def lut() -> VendorLookup:
    return VendorLookup.load()


def test_known_vendors_resolve():
    v = lut()
    assert v.match("Acme Beverage Co").vendor_id == "201"
    assert v.match("SAMPLE SNACKS LLC").vendor_id == "147"
    assert v.match("Orchard Fruit Co").vendor_id == "1101"


def test_match_ignores_suffixes_and_case():
    v = lut()
    assert v.match("sample snacks").vendor_id == "147"
    assert v.match("MOCK MAINTENANCE SERVICES CO").vendor_id == "208"


def test_printed_letterheads_resolve_via_fuzzy_matching():
    # Names as printed on the letterhead differ slightly from the table.
    v = lut()
    assert v.match("ORCHARDS FRUIT COMPANY").vendor_id == "1101"   # ORCHARD (prefix)
    assert v.match("EXAMPLES ENERGY DRINKS INC").vendor_id == "104"  # EXAMPLE (prefix)
    assert v.match("SAMPLE SNACKS LLC, INC.").vendor_id == "147"


def test_rare_token_beats_common_geographic_token():
    # "ACME ANYTOWN" must NOT map to "ANYTOWN DISTRIBUTING CO" (105) just because
    # ANYTOWN fully covers that row; ACME is the identifying token.
    v = lut()
    assert v.match("ACME ANYTOWN, INC.").vendor_id == "201"
    # A vendor whose whole name is a common word still resolves via exact match.
    assert v.match("ANYTOWN DISTRIBUTING CO. INC.").vendor_id == "105"


def test_common_word_only_match_is_flagged():
    # A stray shared word must not anchor a confident match.
    v = lut()
    m = v.match("Foobar Anytown Gadgets")   # only "ANYTOWN" overlaps anything
    assert not m.matched


def test_unknown_vendor_is_flagged_not_guessed():
    v = lut()
    m = v.match("Totally Unknown Gizmo Brand")
    assert not m.matched
    assert m.vendor_id is None
    assert m.reason


def test_empty_name_is_flagged():
    m = lut().match("")
    assert not m.matched
