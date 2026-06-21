"""
reliability.py — retry/backoff + crash-resume checkpointing.

retry_call(): wraps a network call; retries transient failures (timeouts, 5xx,
connection errors, 429) with exponential backoff. Permanent failures (4xx other
than 429) are NOT retried. Returns the call result or a caller-supplied default
after exhausting attempts (so one flaky lead never aborts a whole run).

Checkpoint: a tiny JSON of which discovered businesses have been processed in the
CURRENT run, so a crash mid-run resumes instead of restarting. Keyed by a run-id
(niche+location+date) so different runs don't collide. The dedup ledger handles
cross-run memory; this handles WITHIN-run resume.
"""
import json
import os
import time
import random

try:
    import requests
    _REQ_EXC = (requests.exceptions.RequestException,)
except Exception:                      # requests always present, but be safe
    _REQ_EXC = ()


TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def is_transient(exc=None, status=None):
    if status is not None and status in TRANSIENT_STATUS:
        return True
    if exc is not None:
        if _REQ_EXC and isinstance(exc, _REQ_EXC):
            return True
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return True
    return False


def retry_call(fn, *args, attempts=4, base_delay=0.6, max_delay=8.0,
               default=None, status_of=None, log=lambda *a: None, **kwargs):
    """
    Call fn(*args, **kwargs) with retry on transient errors.

    status_of: optional fn(result)->int to inspect an HTTP status code in a
               returned object (so we can retry on a 503 that didn't raise).
    default:   returned if all attempts fail (keeps the run alive).
    """
    delay = base_delay
    last_exc = None
    for i in range(1, attempts + 1):
        try:
            result = fn(*args, **kwargs)
            if status_of is not None:
                code = status_of(result)
                if code is not None and code in TRANSIENT_STATUS and i < attempts:
                    log(f"      transient HTTP {code}, retry {i}/{attempts-1}")
                    time.sleep(min(delay, max_delay) + random.uniform(0, 0.3))
                    delay *= 2
                    continue
            return result
        except Exception as e:          # noqa: BLE001 — we classify below
            last_exc = e
            if not is_transient(exc=e) or i >= attempts:
                if i >= attempts:
                    log(f"      gave up after {attempts} attempts ({e})")
                    return default
                # non-transient: don't retry
                raise
            log(f"      transient error, retry {i}/{attempts-1} ({e})")
            time.sleep(min(delay, max_delay) + random.uniform(0, 0.3))
            delay *= 2
    if last_exc:
        return default
    return default


class Checkpoint:
    """Within-run resume: remembers processed business ids for one run-id."""

    def __init__(self, run_id, ckpt_dir):
        import re
        safe = re.sub(r'[^a-z0-9]+', '-', run_id.lower()).strip('-')
        self.path = os.path.join(ckpt_dir, f".ckpt_{safe}.json")
        self.dir = ckpt_dir
        self._done = set()
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._done = set(json.load(f).get("done", []))
        except (json.JSONDecodeError, OSError):
            self._done = set()

    def is_done(self, business_id):
        return business_id in self._done

    def mark_done(self, business_id):
        self._done.add(business_id)

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"done": sorted(self._done)}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def clear(self):
        self._done = set()
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass
