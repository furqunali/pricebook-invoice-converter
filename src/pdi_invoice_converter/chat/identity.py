"""Who is talking — Windows-username auto-detect + a name registry.

No registration: the first time a username appears the agent asks for the
person's name and stores it against ``%USERNAME%``; afterwards it auto-detects
("Hi there"). This is why the agent runs as a small service near the members'
machines / on the server, not a plain browser chat (a browser cannot read the
computer's user).
"""

from __future__ import annotations

import getpass
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from ..config import CONFIG_DIR, Settings
from .paths_chat import chat_root

_ROLES_FILE = CONFIG_DIR / "roles.yaml"
_VALID_ROLES = {"owner", "reviewer", "user", "viewer"}


def windows_username() -> str:
    """The current Windows user (%USERNAME%), lowercased. Falls back to getpass."""
    return (os.environ.get("USERNAME") or getpass.getuser() or "unknown").strip().lower()


@dataclass
class Identity:
    username: str
    name: str            # display name (may equal username until registered)
    role: str            # owner | reviewer | user | viewer
    known: bool          # True once a display name has been registered

    @property
    def is_reviewer(self) -> bool:
        return self.role in ("reviewer", "owner")

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def can_act(self) -> bool:
        """Viewers are strictly read-only."""
        return self.role != "viewer"


def _load_roles() -> tuple[dict, str]:
    if not _ROLES_FILE.exists():
        return {}, "user"
    with open(_ROLES_FILE, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    users = {k.lower(): v for k, v in (data.get("users") or {}).items()}
    default = data.get("default_role", "user")
    return users, default


def _registry_path(settings: Optional[Settings]) -> Path:
    return chat_root(settings) / "_registry.json"


def _load_registry(settings: Optional[Settings]) -> dict:
    p = _registry_path(settings)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def resolve(username: Optional[str] = None,
            settings: Optional[Settings] = None) -> Identity:
    """Resolve the caller's identity: role from roles.yaml, display name from the
    registry (or the roles file), ``known`` False until a name is registered."""
    username = (username or windows_username()).lower()
    roles, default_role = _load_roles()
    registry = _load_registry(settings)

    entry = roles.get(username, {})
    role = entry.get("role", default_role)
    if role not in _VALID_ROLES:
        role = default_role

    # Registered name wins; else the roles.yaml name; else not-yet-known.
    reg_name = registry.get(username)
    known = bool(reg_name)
    name = reg_name or entry.get("name") or username.capitalize()
    return Identity(username=username, name=name, role=role, known=known)


def register_name(name: str, username: Optional[str] = None,
                  settings: Optional[Settings] = None) -> Identity:
    """Store the person's display name against their Windows username."""
    username = (username or windows_username()).lower()
    p = _registry_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    reg = _load_registry(settings)
    reg[username] = name.strip()
    p.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolve(username, settings)
