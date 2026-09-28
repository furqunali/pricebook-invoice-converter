"""Phase 4 — chat support agent.

A thin, trusted-team support layer over the converter/logs (docs/CHAT_AGENT.md).
It explains, looks up, drafts reports, and triggers a review-run/approval — and
ONLY after the user confirms. It has NO capability to edit code, format, logic,
validation, or the site/vendor tables (docs/PROTECTION_AND_ROLES.md): the set of
actions is fixed in ``actions.py`` and enforced in Python, never by the model.

The natural-language layer runs on the Claude Code subscription (headless
``claude -p``), not the paid API and not Gemini — see ``llm.py``.
"""
