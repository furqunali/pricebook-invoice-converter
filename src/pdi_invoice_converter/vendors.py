"""Vendor lookup — match the SELLER/letterhead name to a Vendor ID.

Matches on the distinctive word(s) of the name, ignoring corporate suffixes
(LLC, INC, CO, COMPANY, DISTRIBUTING, ...). No confident, unambiguous match ->
flagged (never guess); the caller routes the invoice to review.

Vendor IDs are strings and are preserved exactly (leading zeros kept).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import Settings

# Tokens that carry no distinguishing signal — dropped before matching.
_STOPWORDS = {
    "LLC", "INC", "CO", "COMPANY", "CORP", "CORPORATION", "LP", "LTD", "L", "P",
    "USA", "DBA", "THE", "OF", "AND", "DISTRIBUTING", "DIST", "DISTRIBUTION",
    "DISTRIBUTORS", "DISTRIBUTOR", "ENTERPRISES", "ENTERPRISE", "GROUP",
    "SUPPLY", "SUPPLIES", "SERVICE", "SERVICES", "TX", "SOUTH", "SOUTHWEST",
    # Generic commercial words — too common to anchor a match on their own.
    "VENDOR", "STORE", "WHOLESALE",
}


def _tokens(name: str) -> list[str]:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", name.upper())
    return [t for t in cleaned.split() if t and t not in _STOPWORDS]


def _tok_match(a: str, b: str) -> bool:
    """Two name tokens match if equal, or (for tokens >=5 chars) one is a prefix
    of the other — so a letterhead 'PEPSICO' matches the table's 'PEPSI', and
    'MARTINS' matches 'MARTIN', without letting short common fragments over-match."""
    if a == b:
        return True
    return len(a) >= 5 and len(b) >= 5 and (a.startswith(b) or b.startswith(a))


@dataclass(frozen=True)
class VendorMatch:
    vendor_id: Optional[str]
    vendor_name: Optional[str]
    matched: bool
    reason: str = ""


class VendorLookup:
    def __init__(self, rows: list[tuple[str, str]]):
        # rows: list of (vendor_name, vendor_id)
        self._rows = rows
        self._token_sets = [(name, vid, set(_tokens(name))) for name, vid in rows]
        # Document frequency per token -> rarity weight. A token shared by many
        # vendors (HOUSTON, TEXAS, BEVERAGE) carries little identifying signal; a
        # unique brand token (SYSCO, BIMBO, PEPSI) carries a lot. Weighting by
        # 1/df stops "SYSCO HOUSTON INC" from matching "HOUSTON DISTRIBUTING".
        self._df: dict[str, int] = {}
        for _name, _vid, tset in self._token_sets:
            for t in tset:
                self._df[t] = self._df.get(t, 0) + 1

    def _weight(self, token: str) -> float:
        return 1.0 / self._df.get(token, 1)

    @classmethod
    def load(cls, path: Path | None = None) -> "VendorLookup":
        p = Path(path) if path else Settings.load().vendor_ids_file
        rows: list[tuple[str, str]] = []
        with open(p, "r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)  # skip header row
            for r in reader:
                if len(r) >= 2 and r[0].strip():
                    rows.append((r[0].strip(), r[1].strip()))
        return cls(rows)

    def match(self, seller_name: str) -> VendorMatch:
        if not seller_name or not seller_name.strip():
            return VendorMatch(None, None, False, "empty seller name")

        query = set(_tokens(seller_name))
        if not query:
            return VendorMatch(None, None, False,
                               f"no distinctive words in '{seller_name}'")

        # Exact token-set match wins outright (handles vendors whose whole name is
        # common words, e.g. "HOUSTON DISTRIBUTING CO" -> {HOUSTON}).
        exact = [(name, vid) for name, vid, tset in self._token_sets if tset == query]
        if len({vid for _n, vid in exact}) == 1:
            return VendorMatch(exact[0][1], exact[0][0], True)

        # Score each vendor by the RARITY-WEIGHTED strength of its matched tokens
        # (primary), then by weighted coverage of the vendor's own tokens
        # (secondary tie-break). Matching a unique brand token beats fully
        # covering a vendor whose only token is a common word.
        scored: list[tuple[float, float, str, str]] = []
        for name, vid, tset in self._token_sets:
            if not tset:
                continue
            matched = [rt for rt in tset if any(_tok_match(qt, rt) for qt in query)]
            if not matched:
                continue
            matched_weight = sum(self._weight(rt) for rt in matched)
            coverage = matched_weight / sum(self._weight(rt) for rt in tset)
            scored.append((matched_weight, coverage, name, vid))

        if not scored:
            return VendorMatch(None, None, False,
                               f"no vendor matched '{seller_name}'")

        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        best = scored[0]

        # No sufficiently distinctive token matched (only common words) -> don't
        # guess; route to review. A weight of 1.0 == one fully-unique brand token.
        if best[0] < 1.0:
            return VendorMatch(
                None, None, False,
                f"no confident vendor match for '{seller_name}' (only common words matched)")

        # Ambiguous if a different vendor ties the top (weight, coverage).
        eps = 1e-9
        ties = [s for s in scored
                if abs(s[0] - best[0]) < eps and abs(s[1] - best[1]) < eps and s[3] != best[3]]
        if ties:
            names = ", ".join(sorted({best[2], *(t[2] for t in ties)}))
            return VendorMatch(None, None, False,
                               f"ambiguous vendor match for '{seller_name}': {names}")

        return VendorMatch(best[3], best[2], True)
