"""
cost.py — per-key Google API cost tracking + hard budget cap.

Design (matches spec):
  - Google spend is tracked PER KEY (you rotate multiple accounts) in a small
    JSON file, partitioned by key-fingerprint + calendar month.
  - A cap (default $198) with a hard stop buffer (~$195) is enforced BEFORE each
    paid Google call via CostTracker.can_spend().
  - Verification is tracked only (no cap).
  - All prices are OUR calculation from published per-call rates, NOT a live read
    of Google's bill. The buffer absorbs drift. Reliable only if Prospector is
    the sole user of a key.

Nothing here makes network calls. Pure accounting + persistence.
"""
import hashlib
import json
import os
import threading
from datetime import date

# ---------------------------------------------------------------------------
# Published per-call prices (USD). Conservative/rounded UP so we never
# *under*-count and blow the real cap. Source: Google Places (New) pricing.
# These are the SKUs Prospector actually calls.
# ---------------------------------------------------------------------------
PRICES = {
    "places_text_search": 0.032,   # Text Search (New), per request (Pro tier rounded up)
    "place_details":       0.017,   # per details request
    "pagespeed":           0.0,     # PageSpeed Insights API is free
}
VERIFY_PER_EMAIL = 0.001

DEFAULT_CAP = 198.0
DEFAULT_BUFFER_STOP = 195.0        # hard stop before the cap

STATE_PATH = os.environ.get(
    "PROSPECTOR_COST_STATE",
    os.path.join(os.path.expanduser("~"), ".prospector_cost.json"))


def _key_fingerprint(api_key):
    """Short, non-reversible id for a key so we never store the raw secret."""
    if not api_key:
        return "no-key"
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def _month_tag(d=None):
    d = d or date.today()
    return f"{d.year:04d}-{d.month:02d}"


def _load_state(path=STATE_PATH):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state, path=STATE_PATH):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)          # atomic write — never corrupts on crash
    except OSError:
        pass


class CostTracker:
    """
    Per-key, per-month Google spend tracker with a hard cap.

    Usage:
        ct = CostTracker(google_key)
        ct.estimate_run(n_text_searches, n_details, n_emails)  -> dict
        if ct.can_spend("places_text_search"): ...; ct.charge("places_text_search")
        ct.charge_verify(n)
        ct.save()
    """

    def __init__(self, google_key, cap=DEFAULT_CAP, buffer_stop=DEFAULT_BUFFER_STOP,
                 state_path=STATE_PATH):
        self.fp = _key_fingerprint(google_key)
        self.month = _month_tag()
        self.cap = float(cap)
        self.buffer_stop = float(buffer_stop)
        self.state_path = state_path
        self._state = _load_state(state_path)
        rec = self._state.get(self.fp, {})
        # spend carried for THIS key + THIS month only
        self.google_spent = float(rec.get("months", {}).get(self.month, 0.0))
        # session-local verify counters (also persisted under the key)
        self.verify_emails = int(rec.get("verify_emails", 0))
        self.verify_spent = float(rec.get("verify_spent", 0.0))
        self._session_google = 0.0
        self._session_verify_emails = 0
        self._lock = threading.Lock()   # counters are touched by concurrent lead workers

    # ---- pricing helpers ----
    @staticmethod
    def price(kind):
        return PRICES.get(kind, 0.0)

    def remaining(self):
        return max(0.0, self.cap - self.google_spent)

    def buffer_remaining(self):
        return max(0.0, self.buffer_stop - self.google_spent)

    def can_spend(self, kind, n=1):
        """True if charging n×kind keeps us at/under the buffer stop."""
        cost = self.price(kind) * n
        return (self.google_spent + cost) <= self.buffer_stop

    def charge(self, kind, n=1):
        cost = self.price(kind) * n
        with self._lock:
            self.google_spent += cost
            self._session_google += cost
        return cost

    def charge_verify(self, n=1):
        c = VERIFY_PER_EMAIL * n
        with self._lock:
            self.verify_emails += n
            self._session_verify_emails += n
            self.verify_spent += c
        return c

    # ---- estimate ----
    def estimate_run(self, n_text_searches, n_details, n_emails):
        g = (self.price("places_text_search") * n_text_searches
             + self.price("place_details") * n_details)
        r = VERIFY_PER_EMAIL * n_emails
        return {
            "google_low": round(g * 0.7, 2), "google_high": round(g * 1.3, 2),
            "verify": round(r, 4), "google_point": round(g, 2),
            "would_exceed": (self.google_spent + g) > self.buffer_stop,
        }

    # ---- cap management (pre-run menu actions) ----
    def update_cap(self, new_cap, new_buffer=None):
        self.cap = float(new_cap)
        if new_buffer is not None:
            self.buffer_stop = float(new_buffer)
        else:
            # keep the same ~$3 safety gap proportion
            self.buffer_stop = max(0.0, self.cap - (DEFAULT_CAP - DEFAULT_BUFFER_STOP))

    def reset_usage(self):
        """Zero this key's spend for the current month (new key / new month / top-up)."""
        self.google_spent = 0.0
        self._session_google = 0.0

    # ---- persistence ----
    def save(self):
        rec = self._state.get(self.fp, {})
        months = rec.get("months", {})
        months[self.month] = round(self.google_spent, 4)
        rec["months"] = months
        rec["verify_emails"] = self.verify_emails
        rec["verify_spent"] = round(self.verify_spent, 4)
        rec["cap"] = self.cap
        self._state[self.fp] = rec
        _save_state(self._state, self.state_path)

    # ---- reporting ----
    def session_summary(self):
        return {
            "google_this_run": round(self._session_google, 4),
            "verify_emails_this_run": self._session_verify_emails,
            "verify_this_run": round(self._session_verify_emails * VERIFY_PER_EMAIL, 4),
            "google_month_to_date": round(self.google_spent, 4),
            "cap": self.cap, "buffer_stop": self.buffer_stop,
            "remaining_to_buffer": round(self.buffer_remaining(), 4),
        }


class BudgetExceeded(Exception):
    """Raised internally to trigger a graceful stop when the buffer is hit."""
    pass
