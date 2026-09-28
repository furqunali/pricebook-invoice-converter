# Conversion rules — output format + per-vendor logic + validation

Authoritative for the output. If code disagrees, this file wins. The full
extraction instruction the model uses is `prompts/extraction_prompt.md`; this
file is the human-readable summary + the validation gates that make it safe.

## 1. File shape
Plain text, comma-separated, one record per line, UTF-8, `\n`, no blank lines,
no spaces. Extension per the PDI File Retrieval profile (confirm `.csv`).

Record types: `0000` vendor-block header; `1200` invoice header; `1202` line item.

## 2. Grouped BY VENDOR
The file is grouped by vendor. For each vendor that appears:
```
0000,MI,<VENDOR_ID>
1200,...invoice 1 header...
1202,...invoice 1 items...
1200,...invoice 2 header...
1202,...invoice 2 items...
0000,MI,<NEXT_VENDOR_ID>
...
```
- `0000,MI,<VENDOR_ID>` appears ONCE per vendor, right before that vendor's first
  invoice. Do not repeat it between same-vendor invoices. New vendor -> new `0000`.
- VENDOR_ID from `config/vendor_ids.csv` (match the SELLER/letterhead name, not the
  store). No confident match -> route to review (never guess).
- Orchard Fruit Co = 1101, Sample Snacks = 147, Demo Dairy = 103.

## 3. Invoice header (`1200`)
```
1200,<DATE>,<SITE_ID>,<INVOICE_REF>,I,,<TOTAL>,,,,,,,,,,,,,,,,,,,,,,,,,,,
```
- DATE = invoice date `YYYYMMDD`.
- SITE_ID = 4-digit store from `config/site_ids.csv`, matched by store NAME or, if
  only an address is printed, by ADDRESS. Watch the two collisions: Summit 0005
  vs Campus 0012 (same address -> if no name, review); Depot 0011
  (110) vs North Point 0001 (100) (check street number).
- INVOICE_REF = invoice number as printed.
- TOTAL = the invoice's net total, 2 decimals (see 6). Then exactly 27 commas.

## 4. Line item (`1202`)
```
1202,<ITEM#>,,<QTY>,<PRICE>,,,,
```
9 fields / 8 commas. ITEM# exactly as printed (keep digit count). QTY = shipped,
4 decimals; 0-shipped -> `0.0000`; returns -> NEGATIVE qty. PRICE 4 decimals.

## 5. Per-vendor field mapping (confirmed)
| Vendor | ITEM# | QTY | PRICE | Net total | Tax |
|--------|-------|-----|-------|-----------|-----|
| Orchard Fruit Co (1101) | Item # column | Qty Shipped | Price, or Net Price if discounted | "Net Total" | yes (line present) |
| Sample Snacks (147) | ITEM No column | QTY (+deliveries / -returns) | WHOLESALE Price | CASH DUE / TICKET TOTAL | none |
| Demo Dairy (103) | UPC (12-digit, 2nd line) | Cases | per-unit NET | AMOUNT DUE | none |
| Other vendors | Item # column (fallback UPC) | shipped | Price / Net | net/amount due | only if shown |

## 6. Which number is the net total
Use the amount labelled "Net Total" if present. Otherwise the single-invoice final
amount due (Sample Snacks: CASH DUE; Demo Dairy: AMOUNT DUE). NEVER Gross Sale, Total
Discount, Balance, or Current A/R.

## 7. Special cases
- **Returns:** same ITEM#, negative qty, positive price. (`1202,008788,,-6.0000,2.4100,,,,`)
- **Discounted single item (Orchard Fruit Co):** use the Net Price.
- **Per-unit NET column (Demo Dairy):** NET is the per-unit price; use Cases as qty,
  NET as price (do NOT multiply). Skip category headers, pack subtotals, and the
  DELIVERY RECAP.
- **Invoice-wide discount:** its own line `1202,<VIN or DISCOUNT>,,1.0000,-<amt>,,,,`.
- **Other charges (fuel/shipping/handling with no item#):** `1202,<NAME_CAPS>,,1.0000,<amt>,,,,`.
- **Delivery Fee / Totes:** normal lines with their own item# and qty.
- **Sales tax:** only if the invoice shows a TAX value ->
  `1202,SALES TAX,,1.0000,<tax>,,,,`. Shown as 0.00 -> include as `1.0000,0.0000`.
  No tax field at all -> no tax line.
- **Zero-shipped:** include as `0.0000,0.0000`.

## 8. VALIDATION GATES (mandatory)
Per invoice, ALL must pass before it enters a batch; any failure -> that invoice
to `3-review\` with a diagnostic (the rest of the batch continues).

1. **Per-line math** (where the invoice prints an extended/amount): `round(ext,2)
   == round(qty*price,2)`.
2. **Quantity count** matches the invoice's own net-qty total
   (Orchard Fruit Co "Total Item Count"; Sample Snacks "TICKET TOTAL" qty = deliveries+returns;
   Demo Dairy "NET PRODUCT QTY").
3. **Totes count** (if the invoice has one) matches its stated totes count.
4. **Universal money tie-out:** `sum(price*qty over all 1202 item lines) + tax ==
   net total`. This one holds for EVERY vendor and is the main multi-vendor safety
   net.
5. **Gross tie-out (when the invoice states gross + adjustments):**
   `gross - discounts (+ fees + tax) == net total`.

Sample reference values:
- Orchard Fruit Co 00841982: qty 354, net 7379.00.
- Sample Snacks 84071790010652: net qty 243 (296 del - 53 ret), net 451.61.
- Demo Dairy 53989641004: net product qty 281, net 4445.59 (10735.19 - 6289.60).

## 9. Batch assembly (see BATCH_PROCESSING.md)
A batch run assembles all PASSING invoices into one file, grouped by vendor:
`0000,MI,147` + Sample Snacks invoices, `0000,MI,103` + Demo Dairy invoices, etc. One file
per run, named `B-n_MM-DD-YYYY.csv` (or `R-n` for review re-runs).

## 10. Global formatting
4 decimals for qty and price; 2 decimals for net total. No spaces, no blank lines.
Item# digit-count preserved. Never skip a line.
