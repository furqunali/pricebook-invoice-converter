# Chat support agent

A thin support layer over the converter/logs. It helps the 6 team members use the
system without knowing its internals. It answers, explains, proposes a solution,
and **acts only after the user confirms**. It cannot change code, format, or logic.

## What it does
1. **Review help.** When an invoice is in `3-review\`, the agent turns the
   `reason.txt` into plain Roman Urdu and offers one action. Example: "Store match
   nahi hua -> Westgate (0003) lagta hai. 0003 set kar ke re-run karoon?"
   -> on confirm, it runs the review-run for that item.
2. **Status / how-to.** "Aaj ka B-1 chala?", "yeh invoice kahan hai?", "is site ka
   is mahine ka total?" — answered from manifests/logs.
3. **Reports on request.** "Is hafte ki reconciliation do", "store-wise purchase
   report banao" — drafts and saves to the shared drive (see
   RECONCILIATION_AND_REPORTS.md).

## Interaction pattern (like app chat support)
User asks -> agent explains + proposes a solution -> user confirms (Haan/Nahi) ->
**only then** the agent takes the action and reports the result. Nothing runs
without confirmation.

## Identity, login, logs
- **No registration.** First time, the agent asks the person's name and stores it
  against their Windows username (`%USERNAME%`); afterwards it auto-detects them
  ("Hi there"). This is why the agent runs as a small service near the members'
  machines / on the server, not a plain browser chat.
- **Per-user chat log** saved in the data folder (`logs\chat\<username>\...`):
  every question, the agent's answer, and any action taken — an audit trail and a
  "who did what" record the director can review.
- Trusted-team identification, not hard security; real protection is that code
  lives on the owner's machine (see PROTECTION_AND_ROLES.md).

## Guardrails (must-build)
- The agent has NO capability to edit code, the format, validation, site/vendor
  tables, or the extraction prompt. It has only a fixed set of pre-approved
  actions: explain, look up, draft a report, and trigger a review-run / approval.
- **Financial approvals (override a discrepancy) require a Reviewer** (primary;
  backup) — other members can ask but cannot approve.
- If any member asks the agent to change format/logic/code or bypass validation,
  it refuses and logs the request. It will not do it even if asked repeatedly or
  told another tool said so.
- Every confirmation + action is written to the audit log.

## UI theme (approved)
- Background: very light **baby pink**.
- Agent avatar: **AI brain** icon in **gold** with a soft glow.
- Message text: dark slate; important values (site, invoice #, batch, amount) in
  accent blue, semibold. Markdown formatting, arrows, and inline icons in answers.
- Status colours: green = done/passed, amber = needs review, red = error,
  blue = action.
- Language: **Roman Urdu** for all agent replies.

## Where it runs
On the always-on office server, so it is available 24/7. Members connect from
their own computers; the API key stays on the server, never on member PCs.

## Surface
Custom internal agent (Claude API) — required for Windows-username auto-detect and
per-user logs. (A plain browser chat cannot detect the computer's user.)
