"""
Tests for the infrastructure layer included in this public repo: the per-key
cost tracker, the dedup ledger, and the reliability (retry/checkpoint) layer.
Network is never touched. Run with: python -m pytest tests/ -q
"""
import os
import csv
import json
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import cost, ledger, reliability


# ============================ COST TRACKER ============================
class TestCostTracker:
    def _fresh(self, tmp, key="KEYA", cap=198.0):
        return cost.CostTracker(key, cap=cap, buffer_stop=cap - 3,
                                state_path=os.path.join(tmp, "cost.json"))

    def test_starts_zero(self, tmp_path):
        ct = self._fresh(str(tmp_path))
        assert ct.google_spent == 0.0
        assert ct.remaining() == 198.0

    def test_charge_accumulates(self, tmp_path):
        ct = self._fresh(str(tmp_path))
        ct.charge("places_text_search", n=10)
        assert ct.google_spent == pytest.approx(0.32, abs=1e-6)

    def test_can_spend_blocks_at_buffer(self, tmp_path):
        ct = self._fresh(str(tmp_path), cap=10.0)   # buffer 7
        ct.google_spent = 6.99
        assert ct.can_spend("places_text_search") is False
        ct.google_spent = 6.90
        assert ct.can_spend("places_text_search") is True

    def test_buffer_never_exceeded_logic(self, tmp_path):
        ct = self._fresh(str(tmp_path), cap=10.0)   # buffer 7
        ct.google_spent = 7.0
        assert ct.can_spend("place_details") is False

    def test_persist_and_reload_same_key(self, tmp_path):
        p = str(tmp_path)
        ct = self._fresh(p)
        ct.charge("place_details", n=100)
        ct.save()
        ct2 = cost.CostTracker("KEYA", state_path=os.path.join(p, "cost.json"))
        assert ct2.google_spent == pytest.approx(1.7, abs=1e-6)

    def test_different_keys_isolated(self, tmp_path):
        p = os.path.join(str(tmp_path), "cost.json")
        a = cost.CostTracker("KEYA", state_path=p); a.charge("place_details", 100); a.save()
        b = cost.CostTracker("KEYB", state_path=p)
        assert b.google_spent == 0.0

    def test_reset_usage(self, tmp_path):
        ct = self._fresh(str(tmp_path))
        ct.charge("place_details", 100)
        ct.reset_usage()
        assert ct.google_spent == 0.0

    def test_update_cap_keeps_buffer_gap(self, tmp_path):
        ct = self._fresh(str(tmp_path))
        ct.update_cap(300)
        assert ct.cap == 300
        assert ct.buffer_stop == 297

    def test_verify_tracked_only(self, tmp_path):
        ct = self._fresh(str(tmp_path))
        ct.charge_verify(50)
        assert ct.verify_emails == 50
        assert ct.verify_spent == pytest.approx(0.05, abs=1e-6)
        assert ct.google_spent == 0.0

    def test_estimate_range(self, tmp_path):
        ct = self._fresh(str(tmp_path))
        est = ct.estimate_run(10, 100, 400)
        assert est["google_low"] < est["google_point"] < est["google_high"]
        assert est["verify"] == pytest.approx(0.4, abs=1e-6)

    def test_atomic_save_no_corruption(self, tmp_path):
        p = os.path.join(str(tmp_path), "cost.json")
        ct = cost.CostTracker("KEYA", state_path=p); ct.charge("place_details", 10); ct.save()
        with open(p) as f:
            json.load(f)


# ============================ LEDGER ============================
class TestLedger:
    def test_no_file_nothing_seen(self, tmp_path):
        lg = ledger.Ledger("roofing", str(tmp_path))
        assert lg.seen({"place_id": "p1", "website": "https://x.co"}) is False

    def test_mark_then_seen(self, tmp_path):
        lg = ledger.Ledger("roofing", str(tmp_path))
        rec = {"place_id": "p1", "website": "https://x.co"}
        lg.mark(rec)
        assert lg.seen(rec) is True

    def test_seen_by_domain_alone(self, tmp_path):
        lg = ledger.Ledger("roofing", str(tmp_path))
        lg.mark({"place_id": "", "website": "https://x.co"})
        assert lg.seen({"place_id": "pNEW", "website": "https://x.co"}) is True

    def test_seen_by_pid_alone(self, tmp_path):
        lg = ledger.Ledger("roofing", str(tmp_path))
        lg.mark({"place_id": "p1", "website": ""})
        assert lg.seen({"place_id": "p1", "website": "https://other.co"}) is True

    def test_persist_across_instances(self, tmp_path):
        d = str(tmp_path)
        lg = ledger.Ledger("roofing", d)
        lg.mark({"place_id": "p1", "website": "https://x.co"})
        lg.save()
        lg2 = ledger.Ledger("roofing", d)
        assert lg2.seen({"place_id": "p1", "website": ""}) is True

    def test_categories_isolated(self, tmp_path):
        d = str(tmp_path)
        roof = ledger.Ledger("roofing", d)
        roof.mark({"place_id": "p1", "website": "https://x.co"}); roof.save()
        solar = ledger.Ledger("solar", d)
        assert solar.seen({"place_id": "p1", "website": "https://x.co"}) is False

    def test_file_has_header_and_rows(self, tmp_path):
        d = str(tmp_path)
        lg = ledger.Ledger("roofing", d)
        lg.mark({"place_id": "p1", "website": "https://x.co"}); lg.save()
        with open(lg.path) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["place_id"] == "p1"
        assert rows[0]["domain"] == "x.co"
        assert "date_first_seen" in rows[0]


# ============================ RETRY / BACKOFF ============================
class TestRetry:
    def test_success_first_try(self):
        assert reliability.retry_call(lambda: 42) == 42

    def test_retries_transient_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError("temp")
            return "ok"
        assert reliability.retry_call(flaky, base_delay=0, attempts=5) == "ok"
        assert calls["n"] == 3

    def test_returns_default_after_exhaustion(self):
        def always_fail():
            raise ConnectionError("down")
        assert reliability.retry_call(always_fail, base_delay=0, attempts=2, default="DEF") == "DEF"

    def test_non_transient_raises(self):
        def bad():
            raise ValueError("permanent")
        with pytest.raises(ValueError):
            reliability.retry_call(bad, attempts=3)


# ============================ CHECKPOINT ============================
class TestCheckpoint:
    def test_mark_and_resume(self, tmp_path):
        cp = reliability.Checkpoint("run1", str(tmp_path))
        cp.mark_done("b1"); cp.save()
        cp2 = reliability.Checkpoint("run1", str(tmp_path))
        assert cp2.is_done("b1") is True
        assert cp2.is_done("b2") is False

    def test_clear(self, tmp_path):
        cp = reliability.Checkpoint("run1", str(tmp_path))
        cp.mark_done("b1"); cp.save(); cp.clear()
        cp2 = reliability.Checkpoint("run1", str(tmp_path))
        assert cp2.is_done("b1") is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
