# Architecture map

## One-paragraph summary
Vendors' scanned PDFs land in a data intake folder. Twice a day, the
converter (running on the always-on server, from code that lives only on
the owner's workstation) reads each PDF with a Claude vision model, validates it
against the invoice's own totals, and assembles the passing invoices into one
combined, vendor-grouped PDI import file. PDI's Focal Point scheduler imports that
file. Anything that fails validation waits in a review folder; a reviewer
fixes/approves it and it re-runs. A chat agent sits on top to help the team, and a
weekly job produces reconciliation and reports.

## Data-flow map

```
                         VENDORS (Acme Beverage, Sample Snacks, Demo Dairy, ... many)
                                   |  scanned PDF invoices
                                   v
   DATA FOLDER (C:\InvoiceConverterData\)
   +-----------------------------------------------------------------------+
   |  invoices\1-incoming\        <- team drops all vendors' PDFs (mixed)   |
   +-----------------------------------------------------------------------+
                                   |
                                   |  2x daily (Windows Task Scheduler on the server)
                                   v
   CONVERTER ENGINE  (runs on the server; CODE lives on the owner's workstation)
   +-----------------------------------------------------------------------+
   |  pdf_prep  ->  vision extract  ->  model  ->  sites/vendors  ->        |
   |  VALIDATE (5 gates)  ->  writer (PDI format)                           |
   +-----------------------------------------------------------------------+
             |  pass                                   |  fail
             v                                         v
   invoices\5-pdi-dropzone\                    invoices\3-review\
   B-1_MM-DD-YYYY.csv  (vendor-grouped)        <bad invoice> + reason.txt
   (+ copy to 2-converted\, PDFs -> 4-archive) |
             |                                  |  reviewer
             v                                  |  fix or approve -> reprocess\
   PDI  (Focal Point "PDI Enterprise Queue      v
   Service" scheduled import, 2x daily)   review-run -> R-1_MM-DD-YYYY.csv
             |                                        -> dropzone -> PDI
             v
   PDI posts item sales  ---> PDI EXPORT (posted data)
                                   |
             +---------------------+-----------------------+
             v                                             v
   WEEKLY RECONCILIATION (auto)                   POWER BI
   converter output  vs  PDI-posted  vs           reads PDI Export
   vendor statements  + store-wise report          -> dashboards
   -> PDF + Excel (professional) in the data folder

   CHAT SUPPORT AGENT (on the server, 24/7)
   +-----------------------------------------------------------------------+
   |  members connect -> agent auto-detects Windows username -> per-user   |
   |  chat log in the data folder. Explains review items, answers status,  |
   |  drafts reports. Acts (re-run / approve) ONLY after confirmation.     |
   |  Cannot change code, format, or logic.                                |
   +-----------------------------------------------------------------------+
```

## Components
| Component | Runs where | Purpose |
|-----------|-----------|---------|
| Converter engine | server (code from workstation) | PDF -> validated PDI CSV |
| Batch scheduler | Windows Task Scheduler on server | 2x daily `B-n`; review `R-n` |
| PDI import | Focal Point (PDI Enterprise Queue Service) | imports CSV from dropzone |
| Chat agent | server, 24/7 | team help; confirm-then-act |
| Reconciliation | weekly scheduled job | 3-way tie-out + reports |
| Power BI | reads PDI Export | dashboards |

## Where code vs data lives (the protection boundary)
- **Code / logic / prompts / config / this documentation:** the owner's private
  workstation copy — only the owner writes here.
- **All moving data:** the data folder `C:\InvoiceConverterData\` — team-facing,
  role-based permissions.
- The engine runs on the server but executes **only** the code from the owner's
  controlled copy. Members can use the system and read data; they cannot alter how
  it works.

## Trust boundary in one line
Members + agent can READ data and REQUEST actions. Only validated data reaches
PDI. Only the owner changes code. Every action is logged.
