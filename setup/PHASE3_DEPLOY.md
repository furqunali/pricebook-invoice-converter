# Phase 3 deployment — batch + review on the server

The runners read **every path from `config/settings.yaml`** — nothing is
hardcoded. The base path there is a sample placeholder; point it at your own data
folder before scheduling.

## One-time server setup
1. **Confirm the data folder path.** Edit `config/settings.yaml` → `paths:` so
   they point at your location, then run `setup\create_folders.bat` (also edit its
   `BASE`). The folders must match: `1-incoming, 2-converted, 3-review,
   3-review\reprocess, 4-archive, 5-pdi-dropzone, logs, reports`.
2. **Install deps** (in a venv at `.venv\` is cleanest):
   `pip install -e .[extract]`  (adds anthropic, pypdfium2, numpy, Pillow).
3. **Set the API key** as a **machine** environment variable:
   `setx ANTHROPIC_API_KEY "sk-ant-..." /M`  (then reopen the shell).
4. **Verify the model ids** in `config/settings.yaml` (`extract_model`,
   `escalate_model`) against the current Anthropic docs.

## REQUIRED preflight — one real invoice through the ACTUAL API
Before scheduling anything, convert one real invoice live and confirm it ties out:

```
invoice2pdi convert "C:\InvoiceConverterData\invoices\1-incoming\05 - sample.pdf"
```

Expect the PDI records on stdout (a `0000/1200/1202` block). A non-zero exit or a
`REVIEW` message means it did **not** reconcile — fix before going live. Do this
for at least one PDF, one PNG and one JPEG.

## Schedule (2x daily) + review re-run
Run **as administrator**: `setup\schedule_tasks.cmd`
- Batch AM 11:45 → `B-1`, Batch PM 17:45 → `B-2` (both call `invoice2pdi batch`).
- Review 18:15 → `R-n` (`invoice2pdi review-run`); can also be triggered on demand.

`run_batch.cmd` / `run_review.cmd` abort with a clear error if
`ANTHROPIC_API_KEY` is missing, so a mis-set key never produces silent bad output.

## Daily flow (what the team does)
- Drop mixed-vendor PDFs into `invoices\1-incoming\`.
- After a run: passing invoices are in one vendor-grouped `B-n_MM-DD-YYYY.csv` in
  `5-pdi-dropzone\` (PDI imports it); failures wait in `3-review\` with a
  `.reason.txt`. A reviewer fixes/approves into `3-review\reprocess\` (optionally
  with a `<file>.override.json`) and the review re-run emits `R-n`.
- Every run writes `logs\<batch>.manifest.txt`.
```
