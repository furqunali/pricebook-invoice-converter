# Reconciliation and reports

## Weekly reconciliation (auto)
A scheduled job runs **weekly** (suggest Monday morning, so the prior week is
complete) and produces a 3-way reconciliation:
1. **Converter output** (what we sent) — from `2-converted\` / manifests.
2. **PDI-posted** — from the **PDI Export** (posted item sales).
3. **Vendor statements** — the vendor's own totals.

It flags differences: invoices we converted but PDI did not post, amount or qty
mismatches, and anything in review that never cleared. Output is saved to the
shared drive as professional **PDF + Excel** (see theme below).

## Store-wise purchase report
Same cadence (or on demand): purchases by site (0016, 0028, ...) and by vendor,
with totals — so each store's buying is visible. PDF + Excel.

## Monthly
The weekly outputs roll up into a monthly reconciliation + purchase summary for
submission. Same 3-way basis.

## Report theme (professional)
- Clean, corporate colour theme; consistent header/footer with title, period,
  site/vendor, and generation date.
- Excel: proper headers, frozen top row, number formats, subtotal/total rows,
  one sheet per view (reconciliation, store-wise, exceptions).
- PDF: cover line + summary table + exceptions section; readable, printable.
- Numbers always reconcile to the same totals the converter validated against.

## Power BI
- New, built on the **PDI Export** (final posted data).
- The reconciliation job also writes a clean, refreshable dataset (CSV/Excel on
  the shared drive) that Power BI reads; the agent can draft the DAX measures.
- Dashboards: purchases by site/vendor/period, returns and discounts, review rate,
  converted-vs-posted trend. Live refresh from the shared-drive dataset.

## Inputs to confirm (when building this phase)
- **PDI Export**: which format (CSV/Excel) and which shared-drive folder it lands
  in, and on what cadence.
- **Vendor statements**: format (PDF/Excel/email) and where they are collected.

## Who can run
Any member can request a report via the agent (read-only). Scheduled runs are
automatic. Overriding a reconciliation difference (accepting a mismatch) is a
Reviewer action, logged.
