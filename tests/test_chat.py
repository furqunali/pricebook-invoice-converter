"""Chat-agent intent (Part B) + owner grow-via-chat (Part C).

All tests force the deterministic keyword classifier (PDI_CHAT_FORCE_FALLBACK) so
they never shell out to the subscription CLI, and run against a TEMP settings base
so they never touch the real config files or the shared drive.
"""

import shutil

import pytest
import yaml

from pdi_invoice_converter import rules_mgmt
from pdi_invoice_converter.chat import actions as A
from pdi_invoice_converter.chat import agent as AG
from pdi_invoice_converter.chat import llm
from pdi_invoice_converter.chat.identity import Identity
from pdi_invoice_converter.config import ROOT, Settings

OWNER = Identity(username="owner", name="Owner", role="owner", known=True)
USER = Identity(username="ali", name="Ali", role="user", known=True)
VIEWER = Identity(username="director", name="Director", role="viewer", known=True)


@pytest.fixture(autouse=True)
def _force_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("PDI_CHAT_FORCE_FALLBACK", "1")
    monkeypatch.setenv("PDI_CHAT_LOG_DIR", str(tmp_path / "logs" / "chat"))


def _settings(tmp_path) -> Settings:
    base = tmp_path
    inv = base / "invoices"
    for d in ("1-incoming", "2-converted", "3-review", "3-review/reprocess",
              "4-archive", "5-pdi-dropzone"):
        (inv / d).mkdir(parents=True, exist_ok=True)
    (base / "logs").mkdir(exist_ok=True)
    (base / "reports").mkdir(exist_ok=True)
    cfg = base / "config"
    cfg.mkdir(exist_ok=True)
    shutil.copy(ROOT / "config" / "vendor_ids.csv", cfg / "vendor_ids.csv")
    shutil.copy(ROOT / "config" / "site_ids.csv", cfg / "site_ids.csv")
    prompt = base / "prompts" / "extraction_prompt.md"
    prompt.parent.mkdir(exist_ok=True)
    prompt.write_text("BASE PROMPT\n", encoding="utf-8")
    data = {
        "paths": {
            "incoming_dir": str(inv / "1-incoming"), "converted_dir": str(inv / "2-converted"),
            "review_dir": str(inv / "3-review"), "reprocess_dir": str(inv / "3-review" / "reprocess"),
            "archive_dir": str(inv / "4-archive"), "dropzone_dir": str(inv / "5-pdi-dropzone"),
            "log_dir": str(base / "logs"), "reports_dir": str(base / "reports"),
        },
        "lookups": {"vendor_ids": str(cfg / "vendor_ids.csv"), "site_ids": str(cfg / "site_ids.csv")},
        "prompts": {"extraction_prompt": str(prompt)},
        "validation": {"money_tolerance": "0.01"},
    }
    p = cfg / "settings.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return Settings.load(p)


# --------------------------------------------------------------------------- #
# Part B — intent classification
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("msg,expected", [
    ("aaj ka status kya hai", "status"),
    ("review mein kya hai", "list_review"),
    ("bimbo review mein kyun hai", "review_reason"),
    ("report kahan hai path do", "where_is_file"),
    ("is hafte ki report banao", "draft_report"),
    ("naya batch chalao", "run_batch"),
    ("reprocess dobara chalao", "review_run"),
    ("madad chahiye", "help"),
])
def test_intent_mapping(msg, expected):
    prop = llm.propose(USER, msg)
    assert prop.action == expected, f"{msg!r} -> {prop.action}"


def test_report_path_is_not_a_draft():
    prop = llm.propose(USER, "report kahan hai path do")
    assert prop.action == "where_is_file"
    assert prop.action != "draft_report"


def test_unclear_message_asks_clarifying_not_report():
    prop = llm.propose(USER, "arre yaar zara batao")
    assert prop.action is None          # a clarifying question, no action
    assert not prop.refused
    assert "samajh" in prop.reply.lower()  # it asks, not drafts


def test_forbidden_change_format_is_refused():
    prop = llm.propose(OWNER, "format change kar do")
    assert prop.refused is True
    assert prop.action is None


def test_saved_report_reply_has_full_path_and_where_is_file_finds_it(tmp_path):
    s = _settings(tmp_path)
    res = A.run_action("draft_report", s, {}, OWNER)
    assert res.ok
    saved = res.details["path"]
    assert saved in res.text                       # FULL path is in the reply (Part B #2)
    assert saved.endswith(".txt")
    # "report kahan hai" now returns that same path, not a new draft (Part B #3)
    where = A.run_action("where_is_file", s, {}, OWNER)
    assert saved in where.text


# --------------------------------------------------------------------------- #
# Part C — owner grow-via-chat
# --------------------------------------------------------------------------- #

def test_add_vendor_owner_two_turn_confirm_appends_line(tmp_path):
    s = _settings(tmp_path)
    pending = {}
    r1 = AG.handle(OWNER, "add_vendor test co id 999", s, pending)
    assert r1.pending and r1.action == "add_vendor"
    r2 = AG.handle(OWNER, "Haan", s, pending)
    assert r2.status_color == "green"
    assert "test co,999" in r2.reply                # the exact appended line is shown
    assert "test co,999" in s.vendor_ids_file.read_text(encoding="utf-8")


def test_add_vendor_non_owner_is_refused_and_file_unchanged(tmp_path):
    s = _settings(tmp_path)
    before = s.vendor_ids_file.read_text(encoding="utf-8")
    r = AG.handle(USER, "add_vendor test co id 999", s, {})
    assert r.status_color == "red"
    assert not r.pending
    assert s.vendor_ids_file.read_text(encoding="utf-8") == before


def test_add_site_owner(tmp_path):
    s = _settings(tmp_path)
    res = A.run_action("add_site", s, {"name": "Brookside", "id": "0099"}, OWNER)
    assert res.ok and "Brookside,0099" in res.text
    assert "Brookside,0099" in s.site_ids_file.read_text(encoding="utf-8")


def test_add_vendor_rule_is_draft_and_stripped_until_live(tmp_path):
    s = _settings(tmp_path)
    params = {"vendor": "Riggins", "item_col": "Code", "qty_col": "Qty",
              "price_col": "Net", "notes": "test vendor"}
    res = A.run_action("add_vendor_rule", s, params, OWNER)
    assert res.ok
    prompt_text = s._d["prompts"]["extraction_prompt"]
    from pathlib import Path
    text = Path(prompt_text).read_text(encoding="utf-8")
    assert 'vendor="Riggins" status="DRAFT"' in text
    # A DRAFT rule must NOT reach the model: strip_draft_blocks removes it.
    assert "Riggins" not in rules_mgmt.strip_draft_blocks(text)
    # go live -> now it survives stripping (used in real batches).
    live = A.run_action("go_live_rule", s, {"vendor": "Riggins"}, OWNER)
    assert live.ok
    text2 = Path(prompt_text).read_text(encoding="utf-8")
    assert "Riggins" in rules_mgmt.strip_draft_blocks(text2)


def test_cannot_edit_existing_live_rule_from_chat(tmp_path):
    s = _settings(tmp_path)
    p = {"vendor": "Riggins", "item_col": "Code", "qty_col": "Qty", "price_col": "Net"}
    A.run_action("add_vendor_rule", s, p, OWNER)
    A.run_action("go_live_rule", s, {"vendor": "Riggins"}, OWNER)
    # Re-adding (editing) a LIVE rule from chat is refused (red).
    again = A.run_action("add_vendor_rule", s, p, OWNER)
    assert not again.ok and again.status_color == "red"


def test_list_pending_rules_owner_only(tmp_path):
    s = _settings(tmp_path)
    A.run_action("add_vendor_rule", s,
                 {"vendor": "Riggins", "item_col": "Code", "qty_col": "Qty", "price_col": "Net"},
                 OWNER)
    listed = A.run_action("list_pending_rules", s, {}, OWNER)
    assert "Riggins" in listed.text and "DRAFT" in listed.text
    # A non-owner cannot even list them.
    refused = A.run_action("list_pending_rules", s, {}, USER)
    assert not refused.ok and refused.status_color == "red"
