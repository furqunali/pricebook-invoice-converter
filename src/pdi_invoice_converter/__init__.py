"""PDI Invoice Converter — offline core (Phase 1).

Converts multi-vendor supplier invoices into PDI import files (0000/1200/1202
records), validates them against the invoice's own totals, and assembles the
passing invoices into one vendor-grouped batch file.

Phase 1 = offline core (no API): model, vendors, sites, writer, validate,
counter, and batch assembly. See docs/CONVERSION_RULES.md (source of truth).
"""

__version__ = "0.1.0"
