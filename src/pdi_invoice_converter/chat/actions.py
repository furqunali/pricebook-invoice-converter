"""The FIXED, pre-approved action set — the only things the agent can ever do.

There is deliberately NO action that edits code, output format, validation, the
site/vendor tables, or the extraction prompt (docs/PROTECTION_AND_ROLES.md #3).
The model may *propose* one of these by name; execution happens here, in Python,
after a confirmation and a role check. Anything outside this dict cannot run.

Read-only actions (answers): status, list_review, help.
Side-effecting actions (confirm-then-act): draft_report, review_run,
approve_override — the last two are Reviewer/Owner only.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .. import rules_mgmt
from ..config import ROOT, Settings
from ..paths import Paths
from .identity import Identity
from .paths_chat import chat_root

def _prompt_file(settings: Settings) -> Path:
    """The extraction prompt to grow DRAFT rules into. From settings if given
    (keeps tests/other bases off the real prompt), else the project prompt."""
    raw = (settings._d.get("prompts") or {}).get("extraction_prompt")
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else ROOT / p
    return ROOT / "prompts" / "extraction_prompt.md"

# name -> (needs_confirm, reviewer_only, read_only, owner_only)
ACTIONS = {
    "status":              (False, False, True,  False),
    "list_review":         (False, False, True,  False),
    "review_reason":       (False, False, True,  False),
    "help":                (False, False, True,  False),
    "where_is_file":       (False, False, True,  False),
    "draft_report":        (True,  False, False, False),
    "run_batch":           (True,  False, False, False),
    "review_run":          (True,  True,  False, False),
    "approve_override":    (True,  True,  False, False),
    # Owner-only "grow via chat" (Part C) — non-owners can never reach these.
    "add_vendor":          (True,  False, False, True),
    "add_site":            (True,  False, False, True),
    "add_vendor_rule":     (True,  False, False, True),
    "go_live_rule":        (True,  False, False, True),
    "list_pending_rules":  (False, False, True,  True),
}


@dataclass
class ActionResult:
    ok: bool
    text: str                 # Roman-Urdu-friendly summary of what happened
    status_color: str = "blue"  # green done | amber review | red error | blue info
    details: Optional[dict] = None


def _paths(settings: Settings) -> Paths:
    return Paths.from_settings(settings)


def _last_report_file(settings: Settings) -> Path:
    return chat_root(settings) / "_last_report.json"


def _record_last_report(settings: Settings, username: str, path: Path) -> None:
    """Remember the last report a user saved, so 'report kahan hai' can answer it."""
    f = _last_report_file(settings)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        data[username.lower()] = str(path)
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _get_last_report(settings: Settings, username: str) -> Optional[str]:
    f = _last_report_file(settings)
    try:
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8")).get(username.lower())
    except (OSError, ValueError):
        pass
    return None


# --------------------------------------------------------------------------- #
# Read-only lookups
# --------------------------------------------------------------------------- #

def action_status(settings: Settings, params: dict, **_) -> ActionResult:
    """Report recent batch/review runs from the manifests in the log dir."""
    logs = _paths(settings).logs
    manifests = sorted(logs.glob("*.manifest.txt")) if logs.exists() else []
    if not manifests:
        return ActionResult(True, "Abhi tak koi batch/review manifest nahi mila.", "amber")
    wanted = (params or {}).get("batch_id")
    if wanted:
        hit = [m for m in manifests if wanted in m.name]
        chosen = hit[-1] if hit else None
        if chosen is None:
            return ActionResult(True, f"'{wanted}' ka manifest nahi mila.", "amber")
        return ActionResult(True, chosen.read_text(encoding="utf-8"), "blue",
                            {"manifest": chosen.name})
    latest = manifests[-1]
    return ActionResult(True, latest.read_text(encoding="utf-8"), "blue",
                        {"manifest": latest.name, "count": len(manifests)})


def action_list_review(settings: Settings, params: dict, **_) -> ActionResult:
    """List invoices currently sitting in 3-review with their reasons."""
    review = _paths(settings).review
    if not review.exists():
        return ActionResult(True, "Review folder abhi mojood nahi.", "amber")
    pdfs = [p for p in sorted(review.iterdir())
            if p.is_file() and p.suffix.lower() != ".txt"
            and not p.name.endswith(".json")]
    if not pdfs:
        return ActionResult(True, "Review mein koi invoice nahi — sab clear hai.", "green")
    lines = [f"Review mein {len(pdfs)} invoice(s):"]
    for p in pdfs:
        reason = p.with_suffix(p.suffix + ".reason.txt")
        first = ""
        if reason.exists():
            body = [ln for ln in reason.read_text(encoding="utf-8").splitlines() if ln.strip()]
            gate = [ln for ln in body if ln.strip().startswith("[gate")]
            if gate:
                first = gate[0].strip()
            elif len(body) > 1:
                first = body[1].strip()
            elif body:
                first = body[0].strip()[:90]
        lines.append(f"- {p.name} — {first}")
    return ActionResult(True, "\n".join(lines), "amber",
                        {"files": [p.name for p in pdfs]})


def _match_review_file(review: Path, params: dict) -> tuple[Optional[Path], list[Path]]:
    """Find the ONE review invoice the user means, from a filename or a free-text
    query (e.g. "why is Bimbo in review" -> matches 05 - Bimbo.pdf)."""
    pdfs = [p for p in sorted(review.iterdir())
            if p.is_file() and p.suffix.lower() != ".txt"
            and not p.name.endswith(".json")] if review.exists() else []
    q = str((params or {}).get("filename") or (params or {}).get("query") or "").lower()
    if not q:
        return None, pdfs
    exact = [p for p in pdfs if p.name.lower() == q or p.stem.lower() == q]
    if exact:
        return exact[0], pdfs
    # token overlap: any word (len>2) of a filename appearing in the query
    for p in pdfs:
        words = [w for w in p.stem.lower().replace("-", " ").split() if len(w) > 2]
        if any(w in q for w in words):
            return p, pdfs
    return None, pdfs


def action_review_reason(settings: Settings, params: dict, **_) -> ActionResult:
    """Explain ONE invoice's review reason (not the whole list)."""
    review = _paths(settings).review
    match, pdfs = _match_review_file(review, params)
    if match is None:
        if not pdfs:
            return ActionResult(True, "Review mein koi invoice nahi — sab clear hai.", "green")
        names = ", ".join(p.name for p in pdfs)
        return ActionResult(True, f"Kaunsi invoice? Review mein yeh hain: {names}", "amber")
    reason = match.with_suffix(match.suffix + ".reason.txt")
    body = reason.read_text(encoding="utf-8").strip() if reason.exists() else "(reason file nahi mila)"
    return ActionResult(True, f"{match.name} review mein kyun hai:\n{body}", "amber",
                        {"file": match.name})


def action_help(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    txt = (
        "Main aapki in cheezon mein madad kar sakta hoon:\n"
        "- Status: 'aaj ka batch chala?', 'yeh invoice kahan hai?'\n"
        "- Review: 'review mein kya hai?', reason ko samjhana\n"
        "- Report: 'is hafte ki report banao' (draft, aap confirm karein)\n"
        "- Review-run / approval (sirf Reviewer): fix ke baad dobara chalana\n"
        "Main code/format/logic kabhi nahi badal sakta."
    )
    return ActionResult(True, txt, "blue")


# --------------------------------------------------------------------------- #
# Side-effecting actions (only reached after confirm + role check)
# --------------------------------------------------------------------------- #

def action_draft_report(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    """Draft a simple status report from the manifests and save it to reports/.
    (A real reconciliation lives in RECONCILIATION_AND_REPORTS.md; this is the
    on-request status draft.)"""
    paths = _paths(settings)
    paths.reports.mkdir(parents=True, exist_ok=True)
    manifests = sorted(paths.logs.glob("*.manifest.txt")) if paths.logs.exists() else []
    title = (params or {}).get("title", "status-report")
    safe = "".join(c for c in title if c.isalnum() or c in "-_").lower() or "report"
    out = paths.reports / f"{safe}.txt"
    body = [f"REPORT: {title}", f"by: {identity.name} ({identity.username})", ""]
    if not manifests:
        body.append("(koi manifest nahi mila)")
    else:
        for m in manifests[-10:]:
            body.append(f"== {m.name} ==")
            body.append(m.read_text(encoding="utf-8"))
            body.append("")
    out.write_text("\n".join(body), encoding="utf-8")
    _record_last_report(settings, identity.username, out)
    # Reply with the FULL saved path (Part B #2), not just the file name.
    return ActionResult(True, f"Report draft save ho gayi. Poora path:\n{out}", "green",
                        {"report": str(out), "path": str(out)})


def action_where_is_file(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    """'report kahan hai / path do' -> the FULL path of the last saved report
    (Part B #3). Does NOT draft a new one. Falls back to the newest file in
    reports/ if this user has not saved one this session."""
    last = _get_last_report(settings, identity.username)
    if last and Path(last).exists():
        return ActionResult(True, f"Aapki aakhri report yahan save hui thi:\n{last}",
                            "blue", {"path": last})
    reports = _paths(settings).reports
    files = sorted((p for p in reports.glob("*") if p.is_file()),
                   key=lambda p: p.stat().st_mtime) if reports.exists() else []
    if not files:
        return ActionResult(True, "Abhi tak koi report save nahi hui. 'report banao' "
                            "kahein to bana ke poora path de doonga.", "amber")
    p = files[-1]
    return ActionResult(True, f"Sab se recent report yahan hai:\n{p}", "blue", {"path": str(p)})


def action_run_batch(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    """Run a batch (B-n) over 1-incoming now (confirm-then-act; not for viewers)."""
    from ..batch import run_batch  # lazy: keeps import light + avoids cycles
    run = run_batch(settings=settings)
    passed, review = len(run.in_batch), len(run.review)
    color = "green" if passed and not review else ("amber" if review else "blue")
    msg = f"Batch {run.batch_id} mukammal: {passed} pass, {review} review mein."
    if run.dropzone_file:
        msg += f"\nDropzone file ka poora path:\n{run.dropzone_file}"
    return ActionResult(True, msg, color,
                        {"batch_id": run.batch_id, "passed": passed, "review": review,
                         "path": str(run.dropzone_file) if run.dropzone_file else None})


def action_review_run(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    """Trigger an R-n review-run over 3-review/reprocess/ (Reviewer/Owner only)."""
    from ..review import run_review  # lazy: keeps import light + avoids cycles
    run = run_review(settings=settings)
    passed, review = len(run.in_batch), len(run.review)
    color = "green" if passed and not review else ("amber" if review else "blue")
    msg = (f"Review-run {run.batch_id} mukammal: {passed} pass, {review} abhi bhi review mein.")
    if run.dropzone_file:
        msg += f"\nDropzone file ka poora path:\n{run.dropzone_file}"
    return ActionResult(True, msg, color,
                        {"batch_id": run.batch_id, "passed": passed, "review": review,
                         "path": str(run.dropzone_file) if run.dropzone_file else None})


def action_approve_override(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    """Reviewer override: stage a review invoice into reprocess/ with an
    override sidecar (corrected figures and/or approve:true), then review-run.
    Records the Reviewer's name + reason (docs/PROTECTION_AND_ROLES.md, Audit)."""
    paths = _paths(settings)
    filename = (params or {}).get("filename")
    if not filename:
        return ActionResult(False, "Kis invoice ko approve karna hai? File ka naam batayein.", "red")

    src = paths.review / filename
    if not src.exists():
        return ActionResult(False, f"'{filename}' review folder mein nahi mila.", "red")

    override = {
        "note": (params or {}).get("reason", "reviewer override"),
        "approved_by": identity.name,
    }
    for k in ("net_total", "tax", "stated_qty_count", "stated_totes",
              "gross", "discounts", "fees"):
        if k in (params or {}):
            override[k] = params[k]
    if (params or {}).get("approve", True) and not any(
            k in override for k in ("net_total", "stated_qty_count")):
        override["approve"] = True  # force-include a verified vendor-error invoice

    paths.reprocess.mkdir(parents=True, exist_ok=True)
    dest = paths.reprocess / filename
    shutil.move(str(src), str(dest))
    reason_txt = src.with_suffix(src.suffix + ".reason.txt")
    if reason_txt.exists():
        shutil.move(str(reason_txt), str(dest.with_suffix(dest.suffix + ".reason.txt")))
    dest.with_suffix(dest.suffix + ".override.json").write_text(
        json.dumps(override, indent=2, ensure_ascii=False), encoding="utf-8")

    res = action_review_run(settings, {}, identity)
    return ActionResult(res.ok,
                        f"Override laga diya ({identity.name}). " + res.text,
                        res.status_color, res.details)


# --------------------------------------------------------------------------- #
# Owner-only "grow via chat" (Part C). Every one is confirm-then-act and logged.
# None of these edit code, the writer, the gates, the output format, or a LIVE
# vendor rule — only add a new id or a new DRAFT rule.
# --------------------------------------------------------------------------- #

def action_add_vendor(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    name = str((params or {}).get("name", "")).strip()
    vid = str((params or {}).get("id", "")).strip()
    if not name or not vid:
        return ActionResult(False, "Vendor ka naam aur id dono chahiye. Misaal: "
                            "'ABC Foods ka vendor id 4200 add karo'.", "red")
    try:
        line = rules_mgmt.append_vendor(settings.vendor_ids_file, name, vid)
    except ValueError as exc:
        return ActionResult(False, f"Nahi ho saka: {exc}", "amber")
    return ActionResult(True, f"Vendor add kar diya. Yeh line likhi gayi:\n{line}\n"
                        f"(File: {settings.vendor_ids_file}). Ab se foran laagoo.",
                        "green", {"line": line, "path": str(settings.vendor_ids_file)})


def action_add_site(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    name = str((params or {}).get("name", "")).strip()
    sid = str((params or {}).get("id", "")).strip()
    city = str((params or {}).get("city", "")).strip()
    address = str((params or {}).get("address", "")).strip()
    if not name or not sid:
        return ActionResult(False, "Site ka naam aur id dono chahiye. Misaal: "
                            "'Riverside ka site id 0099 add karo'.", "red")
    try:
        line = rules_mgmt.append_site(settings.site_ids_file, name, sid, city, address)
    except ValueError as exc:
        return ActionResult(False, f"Nahi ho saka: {exc}", "amber")
    return ActionResult(True, f"Site add kar diya. Yeh line likhi gayi:\n{line}\n"
                        f"(File: {settings.site_ids_file}). Ab se foran laagoo.",
                        "green", {"line": line, "path": str(settings.site_ids_file)})


def action_add_vendor_rule(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    vendor = str((params or {}).get("vendor", "")).strip()
    item_col = str((params or {}).get("item_col", "")).strip()
    qty_col = str((params or {}).get("qty_col", "")).strip()
    price_col = str((params or {}).get("price_col", "")).strip()
    notes = str((params or {}).get("notes", "")).strip()
    if not (vendor and item_col and qty_col and price_col):
        return ActionResult(False, "Rule ke liye vendor, item#, qty aur price columns "
                            "chahiye. Misaal: 'for Riggins, item# = Code, qty = Qty, "
                            "price = Net'.", "red")
    try:
        block = rules_mgmt.append_draft_rule(_prompt_file(settings), vendor, item_col,
                                             qty_col, price_col, notes)
    except PermissionError as exc:
        return ActionResult(False, f"Nahi ho saka: {exc}", "red")
    return ActionResult(
        True,
        f"'{vendor}' ka rule DRAFT ke tor par add kar diya (abhi LIVE nahi — real "
        f"batches par asar nahi karega).\n{block}\n"
        f"Test-before-live: ek asli {vendor} invoice 'invoice2pdi convert' se chala "
        f"kar dekhein — gates pass hon AUR item#/prices sahi lagein — phir "
        f"'go live {vendor}' kahein.",
        "amber", {"vendor": vendor, "status": "DRAFT"})


def action_go_live_rule(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    vendor = str((params or {}).get("vendor", "")).strip()
    if not vendor:
        return ActionResult(False, "Kis vendor ka rule LIVE karna hai?", "red")
    ok = rules_mgmt.set_status(_prompt_file(settings), vendor, "LIVE")
    if not ok:
        return ActionResult(False, f"'{vendor}' ka koi chat-added rule nahi mila.", "amber")
    return ActionResult(True, f"'{vendor}' ka rule ab LIVE hai — agle batch se istemal hoga.",
                        "green", {"vendor": vendor, "status": "LIVE"})


def action_list_pending_rules(settings: Settings, params: dict, identity: Identity, **_) -> ActionResult:
    text = _prompt_file(settings).read_text(encoding="utf-8")
    blocks = rules_mgmt.list_blocks(text)
    if not blocks:
        return ActionResult(True, "Koi chat-added rule nahi hai (na draft na live).", "blue")
    lines = ["Chat-added vendor rules:"]
    for b in blocks:
        lines.append(f"- {b['vendor']}: STATUS {b['status']}")
    drafts = [b['vendor'] for b in blocks if b['status'] != "LIVE"]
    if drafts:
        lines.append(f"Draft/pending (LIVE nahi): {', '.join(drafts)}")
    return ActionResult(True, "\n".join(lines), "blue", {"blocks": blocks})


_DISPATCH = {
    "status": action_status,
    "list_review": action_list_review,
    "review_reason": action_review_reason,
    "help": action_help,
    "where_is_file": action_where_is_file,
    "draft_report": action_draft_report,
    "run_batch": action_run_batch,
    "review_run": action_review_run,
    "approve_override": action_approve_override,
    "add_vendor": action_add_vendor,
    "add_site": action_add_site,
    "add_vendor_rule": action_add_vendor_rule,
    "go_live_rule": action_go_live_rule,
    "list_pending_rules": action_list_pending_rules,
}


def run_action(name: str, settings: Settings, params: dict,
               identity: Identity) -> ActionResult:
    """Execute a fixed action after the caller has confirmed and passed role
    checks. Rejects anything not in the fixed set (defence in depth)."""
    if name not in ACTIONS:
        return ActionResult(False, "Yeh kaam meri ijazat-shuda list mein nahi hai.", "red")
    _needs_confirm, reviewer_only, read_only, owner_only = ACTIONS[name]
    if owner_only and not identity.is_owner:
        return ActionResult(False,
                            "Yeh sirf owner (Furqan) kar sakte hain. Aap yeh nahi kar sakte.",
                            "red")
    if reviewer_only and not identity.is_reviewer:
        return ActionResult(False,
                            "Yeh sirf Reviewer (Farhan/Hamza) kar sakte hain. "
                            "Aap request kar sakte hain, approve nahi.", "red")
    if not read_only and not identity.can_act:
        return ActionResult(False, "Aap ke paas sirf read (viewer) ijazat hai.", "red")
    return _DISPATCH[name](settings=settings, params=params or {}, identity=identity)
