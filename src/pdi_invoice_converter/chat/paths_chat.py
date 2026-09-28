"""Where chat data lives: ``logs\\chat\\`` on the shared drive.

Per-user chat logs and the name registry sit under the engine's log dir so the
director can review them alongside the batch/review manifests. A ``PDI_CHAT_LOG_DIR``
env var overrides the base (handy for local testing off the shared drive).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..config import Settings


def chat_root(settings: Optional[Settings] = None) -> Path:
    override = os.environ.get("PDI_CHAT_LOG_DIR")
    if override:
        return Path(override)
    settings = settings or Settings.load()
    log_dir = (settings._d.get("paths") or {}).get("log_dir")
    base = Path(log_dir) if log_dir else (Path.cwd() / "logs")
    return base / "chat"


def user_dir(username: str, settings: Optional[Settings] = None) -> Path:
    return chat_root(settings) / username.lower()
