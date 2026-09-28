# SLP Invoice Converter — Multi-Vendor Pricebook Automation

A production-style system that turns scanned/photographed **multi-vendor supplier
invoices** into a back-office **Pricebook import file**, with batch processing, a
support chat agent, validation gates, reconciliation reports, and a full test suite.

> **Live browser demo:** https://pricebook-invoice-converter.vercel.app
> _(a lightweight, self-contained HTML version of the converter — bring your own
> API key; ships with fictional sample data)_
>
> This repository is published for **review** and ships **fictional sample data**
> (sample vendors, stores, addresses). No real business data, no API keys.

---

## Two things in this repo

1. **The production system** (`src/`, `config/`, `docs/`, `prompts/`, `tests/`) — a
   Python package (`pdi_invoice_converter`) that runs on an always-on office server:
   batch conversion twice daily, a review workflow, a chat support agent, and weekly
   reconciliation/reporting. This is the real architecture.
2. **A live browser demo** (`index.html`, hosted on Vercel/Hugging Face) — a
   self-contained, no-install version of the converter you can try in the browser.

## What the system does

- **Extraction** — reads scanned multi-vendor invoices (PDF/image) with a vision LLM
  and returns structured data; the output file is then assembled deterministically in
  code (the model never formats the final file).
- **Vendor rules** — per-vendor item-number / quantity / price / total conventions
  (UPC handling, catch-weight, coupons, gratis units, multi-page merges, returns…).
- **Validation gates** — every invoice must reconcile (line items vs. net total)
  before it is accepted; failures route to a review queue.
- **Batch processing** — one combined, vendor-grouped file per run (2×/day), review
  re-runs, and partial batches, with daily counters.
- **Chat support agent** — a grounded assistant that explains review items and acts
  only after confirmation (per-user chat log).
- **Reconciliation & reports** — converter vs. posted vs. vendor statements, store
  purchase reports, professional PDF/Excel output.
- **Roles & protection** — code stays private to the owner; the team uses the system
  and its data, but cannot change the logic.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the data flow and module map,
and [`docs/CONVERSION_RULES.md`](docs/CONVERSION_RULES.md) for the output format and
every vendor rule.

## Run it locally

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -e .
pip install -r requirements.txt
# configure config/settings.yaml (paths + provider); set your API key via env var:
#   setx GEMINI_API_KEY "..."   (or ANTHROPIC_API_KEY)
python -m pytest -q          # run the test suite (offline; no API needed)
```

Then use the CLI entry point (see `pyproject.toml` `[project.scripts]`) or the batch
runners in `setup/`.

## Configuration

- `config/settings.yaml` — provider, models, paths, batch/validation settings.
  **API keys are never stored here** — they come from environment variables.
- `config/vendor_ids.csv`, `config/site_ids.csv` — your vendor and store lookups
  (this public repo ships **fictional samples**; replace with your own).

## Security & privacy

- **No API keys in the repo** — the code reads them from env vars only.
- **No real business data** — vendors, stores, addresses, and any sample figures are
  fictional. Real lookups/invoices are kept private and off the public repo.
- Real invoices are never committed; point the converter at your own files locally.

## Tests

`python -m pytest -q` — offline unit tests covering the writer/format, vendor rules,
validation, batch naming/counters, sites, reporting, and the chat actions.

## License

See [LICENSE](LICENSE). Provided for review and evaluation.
