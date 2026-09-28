"""Site (store) lookup — match the delivery store to a 4-digit Site ID.

Match by store NAME when printed, otherwise by ADDRESS. Two documented
collisions are handled explicitly and never guessed:
  - Summit (0005) and Campus (0012) share ONE address. Address-only ->
    ambiguous -> flagged. A name disambiguates them.
  - North Point (0001, 100 Example Blvd) vs Depot (0011, 110 Example Blvd) differ
    only by street number -> the address match keys on the street number.

Site IDs are strings; leading zeros are preserved.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import Settings


@dataclass(frozen=True)
class SiteRow:
    match_word: str
    site_id: str
    city: str
    address: str


@dataclass(frozen=True)
class SiteMatch:
    site_id: Optional[str]
    city: Optional[str]
    matched: bool
    ambiguous: bool = False
    reason: str = ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


def _street_number(s: str) -> Optional[str]:
    m = re.search(r"\d+", s or "")
    return m.group(0) if m else None


def _addr_tokens(s: str) -> set[str]:
    # Alpha tokens of the address, minus generic road words that don't distinguish.
    stop = {"frwy", "fwy", "freeway", "st", "street", "blvd", "pkwy", "parkway",
            "hwy", "us", "n", "s", "e", "w", "north", "south", "east", "west",
            "tx", "houston", "fm", "i"}
    return {t for t in _norm(s).split() if not t.isdigit() and t not in stop}


class SiteLookup:
    def __init__(self, rows: list[SiteRow]):
        self._rows = rows

    @classmethod
    def load(cls, path: Path | None = None) -> "SiteLookup":
        p = Path(path) if path else Settings.load().site_ids_file
        rows: list[SiteRow] = []
        with open(p, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                rows.append(SiteRow(
                    match_word=r["match_word"].strip(),
                    site_id=r["site_id"].strip(),
                    city=r["city"].strip(),
                    address=r["address"].strip(),
                ))
        return cls(rows)

    def match(self, name: Optional[str] = None,
              address: Optional[str] = None) -> SiteMatch:
        # 1) Prefer a name match when a store name is printed.
        if name and name.strip():
            nm = self.match_by_name(name)
            if nm.matched or nm.ambiguous:
                return nm
        # 2) Fall back to the delivery/ship-to address.
        if address and address.strip():
            return self.match_by_address(address)
        if name and name.strip():
            return SiteMatch(None, None, False, reason=f"no site matched name '{name}'")
        return SiteMatch(None, None, False, reason="no store name or address to match")

    def match_by_name(self, name: str) -> SiteMatch:
        low = name.lower()
        hits = [r for r in self._rows if r.match_word.lower() in low]
        if len(hits) == 1:
            r = hits[0]
            return SiteMatch(r.site_id, r.city, True)
        if len(hits) > 1:
            names = ", ".join(sorted(f"{h.match_word} ({h.site_id})" for h in hits))
            return SiteMatch(None, None, False, ambiguous=True,
                             reason=f"ambiguous store name '{name}': {names}")
        return SiteMatch(None, None, False, reason=f"no site matched name '{name}'")

    def match_by_address(self, address: str) -> SiteMatch:
        q_num = _street_number(address)
        q_tokens = _addr_tokens(address)

        # Key on street number first (this is what separates 3503 vs 3505).
        if q_num is not None:
            candidates = [r for r in self._rows if _street_number(r.address) == q_num]
        else:
            candidates = list(self._rows)

        if not candidates:
            return SiteMatch(None, None, False,
                             reason=f"no site matched address '{address}'")

        if len(candidates) == 1:
            r = candidates[0]
            return SiteMatch(r.site_id, r.city, True)

        # Same street number on several stores -> try to narrow by street-name tokens.
        narrowed = [r for r in candidates if _addr_tokens(r.address) & q_tokens] or candidates
        distinct_ids = {r.site_id for r in narrowed}
        if len(distinct_ids) == 1:
            r = narrowed[0]
            return SiteMatch(r.site_id, r.city, True)

        names = ", ".join(sorted(f"{r.match_word} ({r.site_id})" for r in narrowed))
        return SiteMatch(
            None, None, False, ambiguous=True,
            reason=(f"ambiguous address '{address}' matches multiple stores "
                    f"(same address): {names} — need the store name"),
        )
