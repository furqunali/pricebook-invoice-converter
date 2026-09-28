"""Daily-reset counters: B-1 then B-2 same day; new date resets to B-1; the R
counter is independent."""

from pdi_invoice_converter.counter import batch_filename, next_id


def test_b_counter_increments_same_day(tmp_path):
    p = tmp_path / "counter.json"
    assert next_id("B", "08-28-2026", p) == "B-1_08-28-2026"
    assert next_id("B", "08-28-2026", p) == "B-2_08-28-2026"
    assert next_id("B", "08-28-2026", p) == "B-3_08-28-2026"


def test_new_date_resets_to_1(tmp_path):
    p = tmp_path / "counter.json"
    next_id("B", "08-28-2026", p)
    next_id("B", "08-28-2026", p)
    assert next_id("B", "08-29-2026", p) == "B-1_08-29-2026"


def test_r_counter_independent_but_shares_daily_reset(tmp_path):
    p = tmp_path / "counter.json"
    assert next_id("B", "08-28-2026", p) == "B-1_08-28-2026"
    assert next_id("R", "08-28-2026", p) == "R-1_08-28-2026"
    assert next_id("R", "08-28-2026", p) == "R-2_08-28-2026"
    # B is unaffected by R bumps within the same day.
    assert next_id("B", "08-28-2026", p) == "B-2_08-28-2026"
    # New date resets BOTH.
    assert next_id("R", "08-29-2026", p) == "R-1_08-29-2026"
    assert next_id("B", "08-29-2026", p) == "B-1_08-29-2026"


def test_batch_filename():
    assert batch_filename("B-1_08-28-2026") == "B-1_08-28-2026.csv"
    assert batch_filename("R-2_08-29-2026", "csv") == "R-2_08-29-2026.csv"


def test_invalid_kind_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        next_id("X", "08-28-2026", tmp_path / "c.json")
