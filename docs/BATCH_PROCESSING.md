# Batch processing — 2x daily, review re-runs

## Schedule
Windows Task Scheduler on the office server runs the converter **twice a day**
(e.g. 11:45 -> `B-1`, 17:45 -> `B-2`). Times configurable. The server is
always-on, so runs never depend on a member's PC.

## Batch numbering (system date)
- Daily runs: `B-1_MM-DD-YYYY` (first run of the day), `B-2_MM-DD-YYYY` (second).
  The `B` counter resets each day; next day starts at `B-1` again with the new
  date. Example: `B-1_08-28-2026.csv`, `B-2_08-28-2026.csv`.
- Review re-runs: `R-1_MM-DD-YYYY`, `R-2_...` (also reset daily).
- Date = the server's system date at run time.
- Counters persist in `config\batch_counter.json` ({date, b, r}); on a new date
  they reset before incrementing.

## Daily run (`invoice2pdi batch`)
1. Bump the `B` counter -> batch id `B-<b>_<date>`.
2. Read every PDF in `invoices\1-incoming\`.
3. Convert + validate each (per CONVERSION_RULES §8).
4. **Passing** invoices -> assembled into ONE combined CSV, grouped by vendor
   (`0000,MI,<vid>` block per vendor), written to `invoices\5-pdi-dropzone\` and
   copied to `invoices\2-converted\`. Their PDFs move to
   `invoices\4-archive\B-<b>_<date>\`.
5. **Failing** invoices -> moved to `invoices\3-review\` with
   `<invoice>.reason.txt` (which gate failed + numbers) and `.extracted.json`.
6. Write `logs\B-<b>_<date>.manifest.txt`: per invoice — vendor, site, invoice #,
   net total, IN-BATCH or REVIEW + reason.
7. If nothing passed, write no dropzone file; just log.

Partial batches are normal and desired: one bad invoice never holds up the good
ones.

## Review re-run (`invoice2pdi review-run`)
When a reviewer (primary; backup) has handled items:
- **Fix:** correct the cause (better scan; add a site/vendor to the CSV) and move
  the PDF to `invoices\3-review\reprocess\`.
- **Approve/override:** if the invoice's own numbers are genuinely wrong (vendor
  error) but verified, drop `<invoice>.override.json` (authoritative net total /
  counts) beside the PDF in `reprocess\`.

Then:
1. Bump the `R` counter -> `R-<r>_<date>`.
2. Process everything in `reprocess\`; re-validate (an override satisfies the
   failed gate and is flagged as manually approved).
3. Passing -> combined `R-<r>_<date>.csv` to dropzone (+ `2-converted\`); PDFs to
   `4-archive\R-<r>_<date>\`.
4. Still failing -> back to `3-review\` with an updated reason.
5. Write `logs\R-<r>_<date>.manifest.txt`, marking manual approvals.

The review-run can be triggered by the chat agent after a reviewer confirms, or
run on its own small schedule.

## Combined file = vendor-grouped
Within any batch/review file, invoices are grouped by vendor:
```
0000,MI,147
1200,...bimbo invoice A...
1202,...
1200,...bimbo invoice B...
0000,MI,103
1200,...coca-cola invoice...
1202,...
```
One `0000` per vendor, no blank lines, invoices in upload order within a vendor.

## CLI
- `invoice2pdi batch` — Task Scheduler calls this (produces `B-n`).
- `invoice2pdi review-run` — produces `R-n` from approved items.
- `invoice2pdi convert PATH [--site ID] [--vendor ID]` — one file, manual/testing.
