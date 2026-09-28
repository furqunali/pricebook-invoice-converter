"""Site matching: name and address matches, collision handling (Summit/Campus,
North Point/Depot), ambiguous -> flagged."""

from pdi_invoice_converter.sites import SiteLookup


def lut() -> SiteLookup:
    return SiteLookup.load()


def test_match_by_name():
    s = lut()
    assert s.match(name="Westgate").site_id == "0003"
    assert s.match(name="Grove Truck Stop").site_id == "0010"
    assert s.match(name="MAPLE SHELL").site_id == "0008"


def test_address_only_match():
    s = lut()
    m = s.match(address="1000 Mock St, Demo City TX 70010")
    assert m.site_id == "0010"
    assert m.matched


def test_two_stores_on_one_street_distinguished_by_street_number():
    s = lut()
    assert s.match(address="110 Example Blvd, Anytown TX 70011").site_id == "0011"
    assert s.match(address="100 Example Blvd, Anytown TX 70001").site_id == "0001"


def test_summit_campus_same_address_is_ambiguous():
    s = lut()
    m = s.match(address="500 Sample St, Demo City TX 70005")
    assert not m.matched
    assert m.ambiguous
    assert m.site_id is None
    assert m.reason


def test_name_disambiguates_shared_address():
    s = lut()
    # With a name printed, the shared address is no longer ambiguous.
    assert s.match(name="Campus",
                   address="500 Sample St, Demo City TX 70005").site_id == "0012"
    assert s.match(name="Summit",
                   address="500 Sample St, Demo City TX 70005").site_id == "0005"


def test_unknown_site_is_flagged_not_guessed():
    s = lut()
    m = s.match(name="Nonexistent Store", address="999 Nowhere Rd, Mars TX 00000")
    assert not m.matched
    assert m.site_id is None
