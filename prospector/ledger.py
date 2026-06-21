"""
ledger.py — per-category dedup ledger (CSV).

  - One file per category: <ledger_dir>/ledger_<category>.csv
  - Columns: place_id, domain, date_first_seen
  - Loaded once into in-memory sets at run start (microsecond lookups).
  - Checked at DISCOVERY, before any paid enrichment -> duplicates cost nothing.
  - Global within a category; different categories have separate files.
  - No file -> nothing seen -> everything searchable; file auto-created on save.
  - CSV (not SQLite) for portability: copy to a new device and resume.

A business is "seen" if EITHER its place_id OR its domain is already recorded.
"""
import csv
import os
import re
from datetime import date


def _safe(cat):
    return re.sub(r'[^a-z0-9]+', '-', (cat or "").lower()).strip('-') or "uncategorised"


def _domain(url):
    return re.sub(r'^https?://', '', url or "").split('/')[0].lower().replace("www.", "")


class Ledger:
    def __init__(self, category, ledger_dir):
        self.category = category
        self.path = os.path.join(ledger_dir, f"ledger_{_safe(category)}.csv")
        self.dir = ledger_dir
        self._pids = set()
        self._domains = set()
        self._new_rows = []          # buffered, flushed on save()
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return                    # no file -> nothing seen
        try:
            with open(self.path, "r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    pid = (row.get("place_id") or "").strip()
                    dom = (row.get("domain") or "").strip().lower()
                    if pid:
                        self._pids.add(pid)
                    if dom:
                        self._domains.add(dom)
        except OSError:
            pass

    def seen(self, rec):
        """True if this business was already processed (by place_id OR domain)."""
        pid = (rec.get("place_id") or "").strip()
        dom = _domain(rec.get("website", ""))
        if pid and pid in self._pids:
            return True
        if dom and dom in self._domains:
            return True
        return False

    def mark(self, rec):
        """Record a business as seen (buffered; written on save())."""
        pid = (rec.get("place_id") or "").strip()
        dom = _domain(rec.get("website", ""))
        # avoid double-recording within the same run
        is_new = False
        if pid and pid not in self._pids:
            self._pids.add(pid); is_new = True
        if dom and dom not in self._domains:
            self._domains.add(dom); is_new = True
        if is_new or (not pid and not dom):
            self._new_rows.append({
                "place_id": pid, "domain": dom,
                "date_first_seen": date.today().isoformat()})

    def save(self):
        """Append buffered rows; create file + header if missing. Atomic-ish append."""
        if not self._new_rows:
            return
        os.makedirs(self.dir, exist_ok=True)
        write_header = not os.path.exists(self.path)
        try:
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["place_id", "domain", "date_first_seen"])
                if write_header:
                    w.writeheader()
                for row in self._new_rows:
                    w.writerow(row)
            self._new_rows = []
        except OSError:
            pass

    @property
    def count(self):
        return len(self._pids | self._domains)
