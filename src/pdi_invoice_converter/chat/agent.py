"""Agent orchestration: identity -> propose -> confirm -> act -> log.

Enforces the doc's interaction pattern: the agent explains and PROPOSES; a
side-effecting action runs only after the user says Haan. Read-only lookups are
answered directly. Every question, proposal, confirmation, action, and refusal
is written to the per-user audit log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..config import Settings
from . import actions as A
from . import chatlog, llm
from .identity import Identity

_CONFIRM = {"haan", "han", "haanji", "haan ji", "haanji.", "yes", "y", "ok", "okay",
            "theek", "thik", "theek hai", "karo", "karein", "kar do", "sahi", "bilkul"}
_DENY = {"nahi", "nahin", "no", "n", "cancel", "rehne do", "mat karo", "chhodo", "chhod do"}


@dataclass
class AgentResponse:
    reply: str
    status_color: str = "blue"
    pending: bool = False               # True when awaiting Haan/Nahi
    action: Optional[str] = None
    source: str = "cli"                 # which NL path answered ("cli"/"fallback")
    details: dict = field(default_factory=dict)


def _is_confirm(msg: str) -> bool:
    return msg.strip().lower().rstrip(".!") in _CONFIRM


def _is_deny(msg: str) -> bool:
    return msg.strip().lower().rstrip(".!") in _DENY


def _context(settings: Settings) -> str:
    """A little live context so the model's suggestions are grounded."""
    try:
        rv = A.action_list_review(settings, {})
        return rv.text
    except Exception:
        return "(context unavailable)"


def handle(identity: Identity, message: str, settings: Settings,
           pending: dict) -> AgentResponse:
    """Process one user turn. ``pending`` is a per-username dict the caller keeps
    across turns: {username: {"action": str, "params": dict, "summary": str}}."""
    uname = identity.username
    chatlog.log_event(uname, "question", {"text": message}, settings)

    # 1) Resolve an outstanding confirmation first.
    prior = pending.get(uname)
    if prior:
        if _is_confirm(message):
            chatlog.log_event(uname, "confirm", {"action": prior["action"],
                                                 "params": prior["params"]}, settings)
            res = A.run_action(prior["action"], settings, prior["params"], identity)
            pending.pop(uname, None)
            chatlog.log_event(uname, "action",
                              {"action": prior["action"], "ok": res.ok,
                               "result": res.text, "details": res.details}, settings)
            return AgentResponse(res.text, res.status_color, action=prior["action"],
                                 details=res.details or {})
        if _is_deny(message):
            pending.pop(uname, None)
            chatlog.log_event(uname, "confirm", {"action": prior["action"],
                                                 "confirmed": False}, settings)
            return AgentResponse("Theek hai, cancel kar diya. Aur kuch?", "blue")
        # Neither yes nor no -> drop the stale proposal and treat as a fresh query.
        pending.pop(uname, None)

    # 2) Ask the NL layer (subscription CLI) for a reply + optional action.
    prop = llm.propose(identity, message, _context(settings))

    if prop.refused:
        chatlog.log_event(uname, "refusal", {"text": message}, settings)
        return AgentResponse(prop.reply, "red", source=prop.source)

    if not prop.action:
        chatlog.log_event(uname, "answer", {"text": prop.reply}, settings)
        return AgentResponse(prop.reply, "blue", source=prop.source)

    needs_confirm, reviewer_only, _read_only, owner_only = A.ACTIONS[prop.action]

    # Owner gate first: the grow-via-chat actions are owner-only; a non-owner can
    # never reach them (they are not even offered a confirmation).
    if owner_only and not identity.is_owner:
        msg = ("Yeh sirf owner (Furqan) kar sakte hain — vendor/site/rule add karna "
               "ya rule ko live karna. Aap yeh nahi kar sakte.")
        chatlog.log_event(uname, "refusal", {"text": message, "blocked": prop.action}, settings)
        return AgentResponse(msg, "red", source=prop.source)

    # Role gate up front so a User isn't asked to confirm something they can't do.
    if reviewer_only and not identity.is_reviewer:
        msg = ("Yeh kaam sirf Reviewer (Farhan/Hamza) kar sakte hain. Aap request "
               "kar sakte hain — main unhe bata sakta hoon, lekin approve aap nahi kar sakte.")
        chatlog.log_event(uname, "answer", {"text": msg, "blocked": prop.action}, settings)
        return AgentResponse(msg, "amber", source=prop.source)

    if not needs_confirm:
        # Read-only lookup: just answer.
        res = A.run_action(prop.action, settings, prop.params, identity)
        chatlog.log_event(uname, "action",
                          {"action": prop.action, "ok": res.ok, "read_only": True}, settings)
        head = (prop.reply + "\n\n") if prop.source == "cli" else ""
        return AgentResponse(head + res.text, res.status_color,
                             action=prop.action, source=prop.source, details=res.details or {})

    # Side-effecting: propose + wait for Haan.
    pending[uname] = {"action": prop.action, "params": prop.params, "summary": prop.reply}
    chatlog.log_event(uname, "proposal",
                      {"action": prop.action, "params": prop.params}, settings)
    ask = prop.reply.rstrip()
    if "haan" not in ask.lower() and "confirm" not in ask.lower():
        ask += "\n\nChaloon? (Haan / Nahi)"
    return AgentResponse(ask, "blue", pending=True, action=prop.action, source=prop.source)
