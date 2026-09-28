"""Phase 3 filesystem runners: batch (B-n) and review-run (R-n).

Uses a stub converter so the runner's orchestration — file discovery, counter
naming, vendor-grouped assembly, archiving, review routing, manifests, override
handling — is exercised without the vision API or the shared drive.
"""

import json

import pytest

from pdi_invoice_converter.batch import run_batch
from pdi_invoice_converter.paths import Paths
from pdi_invoice_converter.pipeline import convert_extracted
from pdi_invoice_converter.review import run_review

STORE_ADDR = "1000 Mock St, Demo City TX 70010"


def _li(item_no, qty, price, ext):
    return {"item_no": item_no, "qty": qty, "price": price, "extended": ext,
            "is_tote": False, "counts_qty": True}


def good_bimbo():
    return {
        "vendor_name": "SAMPLE SNACKS LLC", "store_name": None, "store_address": STORE_ADDR,
        "invoice_date": "20260728", "invoice_ref": "SNACK1", "net_total": "23.00",
        "tax": None, "stated_qty_count": "9", "stated_totes": None,
        "gross": None, "discounts": None, "fees": None,
        "line_items": [_li("008788", "10", "2.00", "20.00"),
                       _li("008771", "5", "3.00", "15.00"),
                       _li("008788", "-6", "2.00", "-12.00")],
    }


def good_coca():
    return {
        "vendor_name": "DEMO DAIRY DISTRIBUTORS", "store_name": None,
        "store_address": STORE_ADDR, "invoice_date": "20260827", "invoice_ref": "DAIRY1",
        "net_total": "35.00", "tax": None, "stated_qty_count": "5", "stated_totes": None,
        "gross": None, "discounts": None, "fees": None,
        "line_items": [_li("858176002157", "2", "10.00", "20.00"),
                       _li("070847811169", "3", "5.00", "15.00")],
    }


def bad_coca():
    # Lines sum to 40.00 but net says 35.00 -> money gate fails -> review.
    d = good_coca()
    d["invoice_ref"] = "DAIRYBAD"
    d["line_items"] = [_li("858176002157", "3", "10.00", "30.00"),
                       _li("070847811169", "2", "5.00", "10.00")]
    return d


_MAP = {"bimbo": good_bimbo, "coca": good_coca, "badcoca": bad_coca}


def stub_convert(path):
    return convert_extracted(_MAP[path.stem.lower()](), source=str(path))


def _touch(directory, name):
    f = directory / name
    f.write_bytes(b"%PDF-1.4 stub")
    return f


def _make_paths(tmp_path):
    paths = Paths.for_base(tmp_path)
    paths.ensure()
    return paths, tmp_path / "counter.json"


def test_batch_partial_success_full_flow(tmp_path):
    paths, counter = _make_paths(tmp_path)
    _touch(paths.incoming, "bimbo.pdf")
    _touch(paths.incoming, "coca.pdf")
    _touch(paths.incoming, "badcoca.pdf")

    res = run_batch(convert_fn=stub_convert, paths=paths,
                    run_date="08-29-2026", counter_path=counter)

    # Naming + counter.
    assert res.batch_id == "B-1_08-29-2026"
    assert res.filename == "B-1_08-29-2026.csv"

    # Dropzone file: vendor-grouped, good ones only, copied to converted/.
    assert res.has_output
    csv_text = res.dropzone_file.read_text()
    assert csv_text.splitlines()[0] == "0000,MI,147"
    assert csv_text.count("0000,MI,147") == 1 and csv_text.count("0000,MI,103") == 1
    assert "SNACK1" in csv_text and "DAIRY1" in csv_text and "DAIRYBAD" not in csv_text
    assert (paths.converted / res.filename).read_text() == csv_text

    # Passing PDFs archived; failing routed to review with sidecars.
    assert (paths.archive / res.batch_id / "bimbo.pdf").exists()
    assert (paths.archive / res.batch_id / "coca.pdf").exists()
    assert (paths.review / "badcoca.pdf").exists()
    assert (paths.review / "badcoca.pdf.reason.txt").exists()
    assert (paths.review / "badcoca.pdf.extracted.json").exists()

    # Incoming drained.
    assert list(paths.incoming.iterdir()) == []

    # Manifest.
    manifest = res.manifest_file.read_text()
    assert manifest.count("IN-BATCH") == 2
    assert "REVIEW" in manifest and "badcoca.pdf" in manifest
    assert "in_batch=2  review=1" in manifest


def test_batch_second_run_same_day_is_b2(tmp_path):
    paths, counter = _make_paths(tmp_path)
    _touch(paths.incoming, "bimbo.pdf")
    run_batch(convert_fn=stub_convert, paths=paths, run_date="08-29-2026", counter_path=counter)
    _touch(paths.incoming, "coca.pdf")
    res2 = run_batch(convert_fn=stub_convert, paths=paths, run_date="08-29-2026", counter_path=counter)
    assert res2.batch_id == "B-2_08-29-2026"


def test_batch_nothing_passes_writes_no_dropzone(tmp_path):
    paths, counter = _make_paths(tmp_path)
    _touch(paths.incoming, "badcoca.pdf")
    res = run_batch(convert_fn=stub_convert, paths=paths,
                    run_date="08-29-2026", counter_path=counter)
    assert not res.has_output
    assert list(paths.dropzone.iterdir()) == []
    assert res.manifest_file.exists()          # still logs
    assert (paths.review / "badcoca.pdf").exists()


def test_review_override_corrects_and_approves(tmp_path):
    paths, counter = _make_paths(tmp_path)
    # A failing invoice a reviewer verified: the TRUE net is 40.00 (vendor misprinted).
    _touch(paths.reprocess, "badcoca.pdf")
    (paths.reprocess / "badcoca.pdf.override.json").write_text(
        json.dumps({"net_total": "40.00", "note": "vendor total misprinted"}))

    res = run_review(convert_fn=stub_convert, paths=paths,
                     run_date="08-29-2026", counter_path=counter)

    assert res.batch_id == "R-1_08-29-2026"
    assert res.has_output
    assert len(res.in_batch) == 1
    assert res.in_batch[0][1].manual_approval is True
    assert "DAIRYBAD" in res.dropzone_file.read_text()
    assert "MANUALLY APPROVED" in res.manifest_file.read_text()


def test_review_force_approve_despite_failing_gates(tmp_path):
    paths, counter = _make_paths(tmp_path)
    _touch(paths.reprocess, "badcoca.pdf")
    (paths.reprocess / "badcoca.pdf.override.json").write_text(
        json.dumps({"approve": True, "note": "accepted as-is"}))

    res = run_review(convert_fn=stub_convert, paths=paths,
                     run_date="08-29-2026", counter_path=counter)
    assert res.has_output
    assert len(res.in_batch) == 1
    assert res.in_batch[0][1].manual_approval is True


def test_review_without_override_still_fails(tmp_path):
    paths, counter = _make_paths(tmp_path)
    _touch(paths.reprocess, "badcoca.pdf")
    res = run_review(convert_fn=stub_convert, paths=paths,
                     run_date="08-29-2026", counter_path=counter)
    assert not res.has_output
    assert len(res.review) == 1
