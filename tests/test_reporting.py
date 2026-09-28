"""Phase 5 (Part 1) reporting engine: parsing, aggregation, reconciliation stub,
and that PDF + Excel + Power BI outputs are written and reconcile to the totals.
"""

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from pdi_invoice_converter import reporting as R
from pdi_invoice_converter.config import ROOT, Settings

CSV1 = (
    "0000,MI,1101\n"
    "1200,20260901,0003,INV-TJ1,I,,45.98,,,,,,,,,,,,,,,,,,,,,,,,,,,\n"
    "1202,002986,,1.0000,22.99,,,,\n1202,002985,,1.0000,22.99,,,,\n"
    "0000,MI,103\n"
    "1200,20260901,0008,INV-CC1,I,,120.40,,,,,,,,,,,,,,,,,,,,,,,,,,,\n"
    "1202,858176002157,,2.0000,20.40,,,,\n1202,070847811169,,1.0000,79.60,,,,\n"
)
CSV2 = (
    "0000,MI,147\n"
    "1200,20260901,0008,INV-BB1,I,,451.61,,,,,,,,,,,,,,,,,,,,,,,,,,,\n"
    "1202,008788,,10.0000,2.41,,,,\n1202,008788,,-6.0000,2.41,,,,\n"
)
MANIFEST = (
    "BATCH MANIFEST B-1_09-01-2026\nfile: B-1_09-01-2026.csv\n\n"
    "IN-BATCH  a.pdf  vendor=1101  site=0003  inv=INV-TJ1  net=45.98\n"
    "REVIEW    z.pdf  failed_gates=[4]  reason: money tie-out off by 3.00\n\n"
    "totals: in_batch=2  review=1\n"
)


def test_parse_pdi_csv_totals_and_returns():
    invs = R.parse_pdi_csv(CSV1, batch_id="B-1")
    assert [i.invoice_ref for i in invs] == ["INV-TJ1", "INV-CC1"]
    assert invs[0].vendor_id == "1101" and invs[0].site_id == "0003"
    assert invs[1].total == Decimal("120.40")
    bb = R.parse_pdi_csv(CSV2)[0]
    assert bb.returns == Decimal("-6.0000") * Decimal("2.41")   # negative-qty line


def test_parse_manifest():
    m = R.parse_manifest(MANIFEST)
    assert m.kind == "BATCH" and m.in_batch == 2 and m.review == 1
    assert m.review_entries and m.review_entries[0][0] == "z.pdf"
    assert "money tie-out" in m.review_entries[0][1]


def _settings(tmp_path) -> Settings:
    data = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}
    data.setdefault("lookups", {})["vendor_ids"] = str(ROOT / "config" / "vendor_ids.csv")
    data["lookups"]["site_ids"] = str(ROOT / "config" / "site_ids.csv")
    data.setdefault("paths", {})["pdi_export_dir"] = ""          # stub empty
    data["paths"]["vendor_statements_dir"] = ""
    p = tmp_path / "settings.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return Settings.load(p)


def _dirs(tmp_path):
    conv, logs, out = tmp_path / "converted", tmp_path / "logs", tmp_path / "reports"
    conv.mkdir(); logs.mkdir()
    (conv / "B-1.csv").write_text(CSV1, encoding="utf-8")
    (conv / "B-2.csv").write_text(CSV2, encoding="utf-8")
    (logs / "B-1.manifest.txt").write_text(MANIFEST, encoding="utf-8")
    return conv, logs, out


def test_aggregates_and_reconciliation_stub(tmp_path):
    s = _settings(tmp_path)
    conv, logs, _ = _dirs(tmp_path)
    agg = R.build_aggregates(conv, logs, s, "2026-09")
    assert len(agg.invoices) == 3
    assert agg.total_purchases() == Decimal("45.98") + Decimal("120.40") + Decimal("451.61")
    # site 0008 has two invoices (CC1 + BB1); names resolve from site_ids.csv
    site08 = [r for r in agg.by_site() if r["site_id"] == "0008"][0]
    assert site08["count"] == 2 and site08["site"] == "Maple"
    assert 0.0 < agg.review_rate() < 1.0                # 1 review of 3
    rows, status = R.reconciliation_rows(agg, s)
    assert status.startswith("PENDING")                 # stubs not wired
    assert all(r["pdi_posted"] is None for r in rows)


def test_build_reports_writes_all_outputs(tmp_path):
    pytest.importorskip("openpyxl")
    pytest.importorskip("reportlab")
    from pdi_invoice_converter.report_render import build_reports
    s = _settings(tmp_path)
    conv, logs, out = _dirs(tmp_path)
    r = build_reports(settings=s, converted_dir=conv, logs_dir=logs, out_dir=out,
                      period="2026-09")
    assert r["invoices"] == 3
    assert Path(r["excel"]).exists() and Path(r["excel"]).stat().st_size > 0
    assert Path(r["pdf"]).exists() and Path(r["pdf"]).stat().st_size > 0
    fact = out / "powerbi" / "purchase_fact.csv"
    assert fact.exists()
    body = fact.read_text(encoding="utf-8").splitlines()
    assert body[0].startswith("date,batch_id,vendor_id")
    assert len(body) == 1 + 3                            # header + 3 invoices
