# Protection and roles

## The protection model (structure, not promises)
1. **Code lives only on the owner's private workstation** and runs on the server
   from that controlled copy. The data folder holds DATA only — never the code,
   format logic, validation, or the extraction prompt.
2. **Members cannot reach the code.** In the data folder they can use the system
   and its data; the logic that decides format/validation is not there to edit.
3. **The agent cannot change logic.** It has only fixed, pre-approved actions
   (explain, look up, draft report, trigger review-run/approval). No capability to
   write code or edit format/validation/tables.
4. **Only the owner modifies** code, format, logic, site/vendor tables, or the
   extraction prompt — on that machine.

Honest limit: a member could ask their own private LLM to write different code,
but it cannot touch production, because they have no write access to the code the
server runs. Their private experiment can never deploy.

## Roles
| Role | Who | Can do |
|------|-----|--------|
| Owner / Admin | Owner | Everything: code, format, logic, site/vendor tables. Only the owner. |
| Reviewer | Reviewer One (primary), Reviewer Two (backup) | Fix/approve review invoices, approve overrides, trigger `R-n`. No code. |
| User | team members | Drop invoices, ask the agent, request reports/status. Read-only otherwise. |
| Viewer | Director | Read reports/dashboards. |

## Data-folder permissions (ask IT)
- `invoices\1-incoming\` — Users write (drop PDFs).
- `invoices\2-converted\`, `5-pdi-dropzone\` — engine writes; PDI reads.
- `invoices\3-review\` (+ `reprocess\`) — Reviewers write; Users read.
- `invoices\4-archive\`, `logs\`, reports folder — engine writes; team reads.
- `Sample Past Invoices\`, `multi_vendor_invoices_prompt\` (if copied to the data
  folder) — **read-only** for the team. The MASTER of the prompt/logic stays on the
  owner's workstation; a shared copy is reference only.
- The API key lives on the server only — never in the shared data folder or a
  member PC.

## Audit
- Every agent action (who confirmed, what ran, when) -> `logs\chat\<user>\` and the
  batch/review manifests.
- Override approvals record the Reviewer's name and the reason.
- The director can review per-user chat logs and manifests any time.
