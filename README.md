# Pricebook Invoice Converter

Turn scanned or photographed **supplier invoices** (PDF / JPG / PNG) into a
back-office **Pricebook import file** (`.txt`) using a vision-capable LLM — entirely
in the browser, with a deterministic output builder you can trust.

> **Live demo:** https://pricebook-invoice-converter.vercel.app
>
> This public demo ships with **fictional sample vendors and stores** so it can be
> shared safely. It is fully functional — bring your own API key and your own
> lookup tables to use it for real.

---

## What it does

Back-office teams often re-key vendor invoices into their point-of-sale / pricebook
system by hand — slow and error-prone. This tool reads each invoice with a vision
LLM and produces the exact fixed-format `.txt` the import expects:

```
0000,MI,<VENDOR_ID>
1200,<DATE>,<SITE_ID>,<INVOICE_REF>,I,,<TOTAL>,, ... ,
1202,<ITEM#>,,<QTY>,<PRICE>,,,,
```

The **model only returns structured JSON** — the `.txt` is assembled locally by the
app, so formatting is never left to the model. Every invoice is validated
(line items must sum to the invoice total) before you download.

## Key features

- **Bring-your-own-key**, any of three providers — Anthropic Claude, Google Gemini,
  or any OpenAI-compatible endpoint (OpenAI / OpenRouter / Groq / DeepSeek / xAI /
  local). Paste a key, it auto-detects the provider, lists the models that key can
  use, picks a working one, and pings it.
- **Real PDF + image ingestion.** PDFs go straight to Claude/Gemini; for
  OpenAI-compatible providers, pages are rasterized client-side with pdf.js.
- **Deterministic output builder** — the `.txt` is built in code from the parsed
  JSON, not by the model.
- **Automatic validation** — flags any invoice whose items don't reconcile to the
  net total (±$0.02), with OK / REVIEW / CHECK badges.
- **Resilient conversion engine** — retries with backoff, auto-fallback to a lighter
  model when one is busy, token-budget escalation for long invoices, and JSON
  salvage from truncated responses.
- **Prompt caching** on the big rules block (Claude), with a live token-usage panel.
- **Editable results** — fix any field, add/remove line items, bulk item-number
  clean-up (strip/pad leading zeros) with undo, all with live re-validation.
- **Assistant chat** grounded on your lookup tables + the current invoice.
- **Vendor-specific extraction rules** — the engine supports per-vendor item-number,
  quantity, price and total conventions (UPC trimming, catch-weight, coupons,
  gratis units, multi-page merges, etc.). The public demo includes three
  representative sample rules to show the pattern.

## Use it

1. Open the live demo (or `index.html` locally — no build step, no server).
2. Paste your API key in the **Connection** box and click **Connect**.
3. Drop one or more invoice files in.
4. Click **Convert**, review/fix the results, then **Download** the `.txt`.

### Make it yours

Edit two lookup tables inside `index.html` (search for `RULES_TEXT`):

- **VENDOR ID LOOKUP** — your suppliers → your vendor codes.
- **SITE ID LOOKUP** — your stores → your site IDs (name and/or ship-to address).

Add per-vendor rules under **ITEM LINES** for any supplier whose invoice layout
needs special handling.

## Tech

Single self-contained HTML file. Vanilla JS, no framework, no build step.
[pdf.js](https://mozilla.github.io/pdf.js/) is lazy-loaded from a CDN only when a
PDF must be rasterized. API calls go directly from the browser to the LLM provider
you choose; **no key is ever stored or transmitted anywhere except to that
provider.** Keys are kept only in your browser's `localStorage`.

## Privacy & security

- **No API key ships in this repo.** Each user supplies their own.
- The public demo contains **no real business data** — vendors, stores and
  addresses are fictional samples.
- For real use, keep your configured copy (with your real vendor/store tables and,
  optionally, a shared team key) **private** — do not publish it. On a shared host
  without access control, treat anything you deploy as public.

## Deploy

Static site — deploys as-is to Vercel, Netlify, GitHub Pages, or any static host.
No environment variables, no server functions required.

## License

See [LICENSE](LICENSE). Provided for review and evaluation.
