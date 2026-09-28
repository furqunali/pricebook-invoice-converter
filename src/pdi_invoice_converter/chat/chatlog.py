"""Per-user audit trail: every question, the agent's answer, and any action taken.

Saved on the shared drive at ``logs\\chat\\<username>\\chat-YYYYMMDD.jsonl`` — an
append-only "who did what" record the director can review at any time. Refusals
and confirmations are logged too (docs/PROTECTION_AND_ROLES.md, Audit).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from ..config import Settings
from .paths_chat import user_dir


def _stamp() -> str:
    # UTC ISO timestamp; deterministic format, timezone-aware.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_event(username: str, kind: str, payload: dict,
              settings: Optional[Settings] = None) -> None:
    """Append one audit event. ``kind`` is one of:
    question | answer | proposal | confirm | action | refusal | error.
    Never raises into the caller — an audit failure must not break the chat."""
    try:
        d = user_dir(username, settings)
        d.mkdir(parents=True, exist_ok=True)
        day = _stamp()[:10].replace("-", "")
        line = {"ts": _stamp(), "user": username.lower(), "kind": kind, **payload}
        with open(d / f"chat-{day}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass
