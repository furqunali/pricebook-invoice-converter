"""Owner-managed lookups & DRAFT vendor rules (the safe half of "grow via chat").

The chat agent may, for the OWNER only, append a new vendor id, a new site id, or
a NEW DRAFT vendor rule. It may NEVER edit code, the writer, the validation gates,
the output format, or an EXISTING (LIVE) vendor rule — those stay CLI-only.

Safety model for vendor rules:
  * A rule added from chat is written to the extraction prompt as a delimited block
    tagged ``STATUS: DRAFT``.
  * ``strip_draft_blocks`` removes every DRAFT block before the prompt is sent to
    the vision model, so a DRAFT rule NEVER affects a real batch.
  * Only ``set_status(..., "LIVE")`` — reached by the owner's "go live <vendor>"
    after a passing test-before-live — makes the rule take effect.

This module is import-light and has no chat dependency, so both the core
extractor and the chat actions can use it.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Optional

# Per-rule delimiters embedded in prompts/extraction_prompt.md.
_START_RE = re.compile(
    r'<!--\s*CHATRULE:START\s+vendor="(?P<vendor>[^"]*)"\s+status="(?P<status>[^"]*)"\s*-->')
_BLOCK_RE = re.compile(
    r'<!--\s*CHATRULE:START\s+vendor="(?P<vendor>[^"]*)"\s+status="(?P<status>[^"]*)"\s*-->'
    r'.*?<!--\s*CHATRULE:END\s*-->\n?',
    re.DOTALL)


# --------------------------------------------------------------------------- #
# Vendor rule blocks in the extraction prompt
# --------------------------------------------------------------------------- #

def list_blocks(prompt_text: str) -> list[dict]:
    """Every chat-added vendor rule block: {vendor, status, text}."""
    out = []
    for m in _BLOCK_RE.finditer(prompt_text):
        out.append({"vendor": m.group("vendor"), "status": m.group("status").upper(),
                    "text": m.group(0)})
    return out


def find_block(prompt_text: str, vendor: str) -> Optional[dict]:
    v = vendor.strip().lower()
    for b in list_blocks(prompt_text):
        if b["vendor"].strip().lower() == v:
            return b
    return None


def strip_draft_blocks(prompt_text: str) -> str:
    """Remove every DRAFT block so drafts never reach the model. LIVE blocks stay."""
    def _drop(m: re.Match) -> str:
        return "" if m.group("status").strip().upper() != "LIVE" else m.group(0)
    return _BLOCK_RE.sub(_drop, prompt_text)


def _render_block(vendor: str, item_col: str, qty_col: str, price_col: str,
                  notes: str, status: str) -> str:
    return (
        f'<!-- CHATRULE:START vendor="{vendor}" status="{status}" -->\n'
        f'  * {vendor} (chat-added rule)  STATUS: {status}\n'
        f'      item# = {item_col}\n'
        f'      qty   = {qty_col}\n'
        f'      price = {price_col}\n'
        f'      notes: {notes or "(none)"}\n'
        f'<!-- CHATRULE:END -->\n'
    )


def append_draft_rule(prompt_path: Path, vendor: str, item_col: str, qty_col: str,
                      price_col: str, notes: str = "") -> str:
    """Append a NEW DRAFT vendor rule block. Refuses to touch a LIVE block (that is
    editing an existing rule -> CLI-only). A previous DRAFT for the same vendor is
    replaced. Returns the block text that is now in the file."""
    text = prompt_path.read_text(encoding="utf-8")
    existing = find_block(text, vendor)
    if existing and existing["status"] == "LIVE":
        raise PermissionError(
            f"'{vendor}' already has a LIVE rule. Editing an existing rule is CLI-only "
            f"(Furqan). Chat can only add a new draft.")
    block = _render_block(vendor, item_col, qty_col, price_col, notes, "DRAFT")
    if existing:  # replace the old draft in place
        text = text.replace(existing["text"], block)
    else:
        text = text.rstrip("\n") + "\n\n" + block
    prompt_path.write_text(text, encoding="utf-8", newline="\n")
    return block


def set_status(prompt_path: Path, vendor: str, status: str) -> bool:
    """Flip a vendor's chat-rule block to DRAFT/LIVE. Returns False if no such block."""
    status = status.strip().upper()
    text = prompt_path.read_text(encoding="utf-8")
    b = find_block(text, vendor)
    if not b:
        return False
    new_block = b["text"]
    # status appears twice: in the START comment and in the "STATUS: X" line.
    new_block = _START_RE.sub(
        lambda m: m.group(0).replace(f'status="{m.group("status")}"', f'status="{status}"'),
        new_block)
    new_block = re.sub(r'STATUS:\s*\w+', f'STATUS: {status}', new_block)
    prompt_path.write_text(text.replace(b["text"], new_block), encoding="utf-8", newline="\n")
    return True


# --------------------------------------------------------------------------- #
# CSV lookups (vendor_ids.csv / site_ids.csv)
# --------------------------------------------------------------------------- #

def _csv_row(fields: list[str]) -> str:
    """One CSV row, quoted exactly like the existing files (QUOTE_MINIMAL, LF)."""
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerow(fields)
    return buf.getvalue().rstrip("\n")


def _read_names(csv_path: Path, col: int = 0) -> set[str]:
    if not csv_path.exists():
        return set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return {r[col].strip().lower() for r in rows[1:] if r}


def _append_line(csv_path: Path, line: str) -> None:
    existing = csv_path.read_text(encoding="utf-8") if csv_path.exists() else ""
    sep = "" if (not existing or existing.endswith("\n")) else "\n"
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        f.write(sep + line + "\n")


def append_vendor(csv_path: Path, name: str, vendor_id: str) -> str:
    """Append a vendor -> id row to vendor_ids.csv. Returns the exact line added.
    Raises ValueError if the name already exists."""
    name = name.strip()
    vendor_id = str(vendor_id).strip()
    if name.lower() in _read_names(csv_path, 0):
        raise ValueError(f"'{name}' already exists in the vendor table.")
    line = _csv_row([name, vendor_id])
    _append_line(csv_path, line)
    return line


def append_site(csv_path: Path, match_word: str, site_id: str,
                city: str = "", address: str = "") -> str:
    """Append a site row to site_ids.csv. Returns the exact line added.
    Raises ValueError if the match word already exists."""
    match_word = match_word.strip()
    site_id = str(site_id).strip()
    if match_word.lower() in _read_names(csv_path, 0):
        raise ValueError(f"'{match_word}' already exists in the site table.")
    line = _csv_row([match_word, site_id, city.strip(), address.strip()])
    _append_line(csv_path, line)
    return line
