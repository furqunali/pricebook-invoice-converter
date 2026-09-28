"""Natural-language layer — runs on the Claude Code SUBSCRIPTION, not the paid API
and not Gemini.

We shell out to the headless CLI (``claude -p ... --output-format json``), which
uses the operator's existing Claude Code login. No ANTHROPIC_API_KEY, no Gemini
key. The model's only job is to (a) write a Roman-Urdu reply and (b) OPTIONALLY
name ONE action from the fixed set — it never executes anything (see actions.py).

If the CLI is unavailable/slow, a deterministic keyword fallback keeps the agent
usable and gives the tests a no-network path.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from .actions import ACTIONS
from .identity import Identity

log = logging.getLogger(__name__)

_CLI_TIMEOUT = 60

# Set PDI_CHAT_FORCE_FALLBACK=1 to skip the subscription CLI and use the
# deterministic keyword classifier only (tests + reproducible demos).
def _force_fallback() -> bool:
    return os.environ.get("PDI_CHAT_FORCE_FALLBACK", "").strip().lower() in ("1", "true", "yes")

# Words that mean "change the system itself" -> always refuse (never an action).
# Matched as substrings, both word orders where it matters ("change format" AND
# "format change"), so a request to alter code/format/logic is never run.
_FORBIDDEN = (
    "change the code", "edit code", "modify code", "code badlo", "code change",
    "change code", "format badlo", "change format", "format change", "format badal",
    "logic badlo", "change logic", "logic change", "validation", "gate hata",
    "gate badlo", "bypass", "prompt badlo", "prompt change", "edit the prompt",
    "vendor table", "site table", "disable check", "check hata", "writer badlo",
)


@dataclass
class Proposal:
    reply: str                                  # Roman Urdu text for the user
    action: Optional[str] = None                # a key of actions.ACTIONS, or None
    params: dict = field(default_factory=dict)
    refused: bool = False
    source: str = "cli"                         # "cli" | "fallback"


def _system_prompt(identity: Identity, context: str) -> str:
    return f"""Aap "PDI Invoice Assistant" hain — ek invoice-converter support agent. SIRF Roman Urdu mein jawab dein (English technical terms theek hain). Lehja narm aur madadgar ho.

Aap ke baare mein ahem baatein:
- Aap SIRF samjha sakte hain, dekh sakte hain, report draft kar sakte hain, aur review-run/approval trigger kar sakte hain.
- Aap kabhi bhi code, output format, validation/gates, site/vendor tables, ya extraction prompt NAHI badal sakte. Agar koi yeh maange to politely inkaar karein aur "refused": true karein.
- Koi bhi action tab tak na chalayein jab tak user confirm na kare. Aap sirf action tajweez (propose) karte hain.
- Financial override/approval SIRF Reviewer (Farhan primary, Hamza backup) kar sakte hain.

User: {identity.name} ({identity.username}), role = {identity.role}.

Maujooda context:
{context}

Intent classification ZARURI hai: har message ko neeche diye actions mein se EK se
map karein, ya agar clear na ho to action null rakh kar ek CHHOTA sawal poochein.
Kabhi bhi shak ki soorat mein by-default report draft na karein.

Fixed actions (in mein se zyada se zyada EK propose karein, warna null):
- status: batch/review ki halat (read-only)
- list_review: review folder ki poori list + reasons (read-only)
- review_reason: SIRF ek invoice review mein kyun hai — us ka reason. params: {{"query": "<user ka message>"}} ya {{"filename": "..."}} (read-only)
- where_is_file: "report kahan hai / path do" — aakhri save-shuda report ka POORA path (read-only). Naya draft NAHI.
- help: madad/tareeqa (read-only)
- draft_report: report draft + save (confirm chahiye). Save ke baad poora path batayein.
- run_batch: 1-incoming par abhi batch chalana -> B-n (confirm chahiye)
- review_run: reprocess ko dobara chalana -> R-n (Reviewer only, confirm chahiye)
- approve_override: review invoice ko approve/override kar ke chalana (Reviewer only, confirm chahiye). params: {{"filename": "...", "reason": "..."}}
- add_vendor: (SIRF owner) vendor id add. params: {{"name": "...", "id": "..."}}
- add_site: (SIRF owner) site id add. params: {{"name": "...", "id": "...", "city": "...", "address": "..."}}
- add_vendor_rule: (SIRF owner) naya DRAFT vendor rule. params: {{"vendor": "...", "item_col": "...", "qty_col": "...", "price_col": "...", "notes": "..."}}
- go_live_rule: (SIRF owner) draft rule ko LIVE karna. params: {{"vendor": "..."}}
- list_pending_rules: (SIRF owner) kaunse rules draft/pending hain (read-only)

Yaad rahe: aap kabhi code, output format, gates/validation, ya kisi MAUJOODA (LIVE)
vendor rule ko NAHI badal sakte — woh sirf Furqan CLI se karte hain; aisi farmaish
par politely inkaar karein aur "refused": true.

SIRF ek JSON object return karein (koi markdown nahi, koi extra text nahi):
{{"reply": "<Roman Urdu jawab>", "action": <null ya action ka naam>, "params": <object>, "refused": <true/false>}}"""


def _resolve_cli() -> Optional[str]:
    for cand in ("claude", "claude.cmd", "claude.exe"):
        path = shutil.which(cand)
        if path:
            return path
    return None


def _extract_json_object(text: str) -> Optional[dict]:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(t[start:end + 1])
    except ValueError:
        return None


def _via_cli(identity: Identity, message: str, context: str) -> Optional[Proposal]:
    cli = _resolve_cli()
    if not cli:
        return None
    prompt = _system_prompt(identity, context) + f"\n\nUser ka message:\n{message}"
    try:
        proc = subprocess.run(
            [cli, "-p", "--output-format", "json"],
            input=prompt, capture_output=True, text=True,
            timeout=_CLI_TIMEOUT, encoding="utf-8",
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    # --output-format json wraps the run; the model text is in "result".
    try:
        outer = json.loads(proc.stdout)
        result_text = outer.get("result", proc.stdout) if isinstance(outer, dict) else proc.stdout
    except ValueError:
        result_text = proc.stdout
    obj = _extract_json_object(result_text)
    if obj is None or "reply" not in obj:
        return None
    action = obj.get("action")
    if action not in ACTIONS:
        action = None
    return Proposal(reply=str(obj["reply"]), action=action,
                    params=obj.get("params") or {},
                    refused=bool(obj.get("refused", False)), source="cli")


# --- owner "grow via chat" command parsing (deterministic) ------------------ #
_RE_ADD_VENDOR = (
    re.compile(r'add[_ ]vendor\s+(?P<name>.+?)\s+id\s+(?P<id>\S+)', re.I),
    re.compile(r'(?P<name>.+?)\s+ka\s+vendor\s+id\s+(?P<id>\S+)', re.I),
)
_RE_ADD_SITE = (
    re.compile(r'add[_ ]site\s+(?P<name>.+?)\s+id\s+(?P<id>\S+)', re.I),
    re.compile(r'(?P<name>.+?)\s+ka\s+site\s+id\s+(?P<id>\S+)', re.I),
)
_RE_RULE = re.compile(
    r'for\s+(?P<vendor>.+?)[,\s]+item#?\s*=\s*(?P<item>.+?)[,\s]+qty\s*=\s*'
    r'(?P<qty>.+?)[,\s]+price\s*=\s*(?P<price>[^,]+?)(?:[,\s]+(?P<notes>.+))?$', re.I)
_RE_GO_LIVE = re.compile(r'go[_ ]live\s+(?P<vendor>.+?)\s*$', re.I)


def _parse_grow(message: str) -> Optional[Proposal]:
    """Owner-only grow commands. Returns a Proposal (role enforced downstream) or
    None. Checked BEFORE the forbidden filter so an owner's add-vendor is not
    mistaken for 'change the vendor table'."""
    m = message.strip()
    ml = m.lower()

    r = _RE_RULE.search(m)
    if r:
        return Proposal(
            reply=f"'{r.group('vendor').strip()}' ka naya DRAFT rule add karoon? "
                  f"(LIVE nahi hoga jab tak aap test ke baad 'go live' na kahein). Haan/Nahi.",
            action="add_vendor_rule",
            params={"vendor": r.group("vendor").strip(), "item_col": r.group("item").strip(),
                    "qty_col": r.group("qty").strip(), "price_col": r.group("price").strip(),
                    "notes": (r.group("notes") or "").strip()},
            source="fallback")

    g = _RE_GO_LIVE.search(m)
    if g:
        return Proposal(reply=f"'{g.group('vendor').strip()}' ka rule LIVE kar doon? "
                        "(Sirf tab jab test-before-live pass ho chuka ho). Haan/Nahi.",
                        action="go_live_rule", params={"vendor": g.group("vendor").strip()},
                        source="fallback")

    if any(w in ml for w in ("draft rule", "pending rule", "kaunse rule", "kaun se rule",
                             "rules draft", "draft/pending", "pending/draft")):
        return Proposal(reply="Chat-added rules dekhta hoon...", action="list_pending_rules",
                        source="fallback")

    for rx in _RE_ADD_VENDOR:
        mv = rx.search(m)
        if mv and "rule" not in ml and "site" not in ml:
            return Proposal(reply=f"Vendor '{mv.group('name').strip()}' id "
                            f"{mv.group('id').strip()} add karoon? Haan/Nahi.",
                            action="add_vendor",
                            params={"name": mv.group("name").strip(), "id": mv.group("id").strip()},
                            source="fallback")
    for rx in _RE_ADD_SITE:
        ms = rx.search(m)
        if ms and "rule" not in ml:
            return Proposal(reply=f"Site '{ms.group('name').strip()}' id "
                            f"{ms.group('id').strip()} add karoon? Haan/Nahi.",
                            action="add_site",
                            params={"name": ms.group("name").strip(), "id": ms.group("id").strip()},
                            source="fallback")
    return None


def _fallback(identity: Identity, message: str) -> Proposal:
    """Deterministic keyword intent — no network. Roman Urdu replies. Unclear
    messages ask a short clarifying question; they do NOT default to a report."""
    m = message.lower()

    # 0) Owner grow commands first (so they aren't caught by the forbidden filter).
    grow = _parse_grow(message)
    if grow is not None:
        return grow

    if any(w in m for w in _FORBIDDEN):
        return Proposal(
            reply=("Maazrat — main code, format, logic, validation ya kisi MAUJOODA "
                   "(live) vendor rule ko nahi badal sakta. Yeh sirf Furqan CLI se "
                   "karte hain. Aap ka request log kar diya gaya hai."),
            refused=True, source="fallback")

    # 1) "report kahan hai / path do" -> last saved report PATH (never a new draft).
    loc = any(w in m for w in ("kahan", "kaha", "kidhar", "path", "location", "where"))
    if loc and any(w in m for w in ("report", "file", "csv")):
        return Proposal(reply="Aakhri report ka path nikaalta hoon...",
                        action="where_is_file", source="fallback")

    # 2) Side-effecting intents (specific before generic).
    if any(w in m for w in ("approve", "override", "manzoor", "manzur")):
        return Proposal(reply="Kaunsi invoice approve karni hai? (Reviewer only). Confirm par chalaoon.",
                        action="approve_override", source="fallback")
    if any(w in m for w in ("naya batch", "new batch", "run batch", "batch chalao",
                            "batch chala do", "batch karo", "process inbox", "incoming chalao")):
        return Proposal(reply="Abhi ek naya batch (B-n) chalaoon? Confirm karein (Haan/Nahi).",
                        action="run_batch", source="fallback")
    if any(w in m for w in ("re-run", "rerun", "review-run", "review run", "reprocess",
                            "dobara chalao", "dobara chala", "review dobara")):
        return Proposal(reply="Reprocess ko dobara chalaoon (R-n)? Confirm karein (Haan/Nahi).",
                        action="review_run", source="fallback")
    # report DRAFT only on an explicit "make/draft a report" verb — NOT bare "report",
    # so "report kahan hai" (handled above) never triggers a draft.
    if any(w in m for w in ("report banao", "report bana", "report draft", "draft report",
                            "reconcile", "reconcil")) or \
       ("report" in m and any(w in m for w in ("banao", "bana", "draft", "chahiye"))):
        return Proposal(reply="Report draft karoon? Confirm karein (Haan/Nahi).",
                        action="draft_report", source="fallback")

    # 3) Read-only lookups.
    if any(w in m for w in ("why", "kyun", "kyu", "kyon", "wajah")) and "review" in m:
        return Proposal(reply="Us invoice ka reason dekhta hoon...",
                        action="review_reason", params={"query": message}, source="fallback")
    if loc and "invoice" in m:
        return Proposal(reply="Us invoice ka reason/mauqa dekhta hoon...",
                        action="review_reason", params={"query": message}, source="fallback")
    if any(w in m for w in ("review mein", "review me", "reason", "kya hai review", "list review")):
        return Proposal(reply="Review folder dekh raha hoon...", action="list_review", source="fallback")
    if any(w in m for w in ("status", "batch", "manifest", "chala?", "chala ", "halat",
                            "b-1", "b-2", "aaj ka")):
        return Proposal(reply="Aaj ki halat dekhta hoon...", action="status", source="fallback")
    if any(w in m for w in ("madad", "help", "kaise", "kya kar sakte", "kya kar")):
        return Proposal(reply="Main madad ke liye hazir hoon.", action="help", source="fallback")

    # 4) Unclear -> a short clarifying question. NOT a report by default.
    return Proposal(
        reply=("Maaf kijiye, poori tarah samajh nahi aaya. Aap in mein se kya chahte hain: "
               "status, review list, kisi invoice ka reason, report ka path, report banana, "
               "ya batch chalana?"),
        action=None, source="fallback")


def propose(identity: Identity, message: str, context: str = "") -> Proposal:
    """Ask the model (subscription CLI) for a reply + optional action; fall back
    to the deterministic keyword classifier if the CLI can't be reached. Logs which
    path answered so a silent fall-back to keyword-only is visible in the logs."""
    if not _force_fallback():
        prop = _via_cli(identity, message, context)
        if prop is not None:
            log.info("intent via subscription CLI: action=%s", prop.action)
            return prop
        log.warning("subscription CLI unavailable -> deterministic keyword fallback")
    return _fallback(identity, message)
