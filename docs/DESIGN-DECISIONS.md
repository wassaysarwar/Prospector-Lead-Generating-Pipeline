# Design decisions

The choices that shaped the system — and the reasoning behind them. (These are
the trade-offs I'd defend in a code review.)

### 1. Never fabricate — blank beats wrong
Every output field is a verifiable fact. If the owner's name can't be confirmed,
it stays blank rather than guessed; "problems" are only ever checkable facts, never
unknowable claims (ROAS, ad-creative quality, targeting). **Why:** the output feeds
a sales conversation — one made-up detail caught on a call destroys credibility and
the deal. Correctness is the product.

### 2. Verify input before spending a cent
Niche and location are validated (typo → suggestion, unknown → rejected) *before*
any paid API call. **Why:** a copy-paste error should never cost money.

### 3. Hard budget cap, tracked per key
Spend is tracked per API key per month and stops gracefully before a configurable
cap. **Why:** an unattended/large run must be incapable of an unbounded bill.
(`cost.py` — included here.)

### 4. Idempotent by design — a dedup ledger
A per-niche ledger records every business processed and is checked at discovery,
*before* any paid enrichment. **Why:** re-runs scale coverage instead of re-paying
for the same leads; the system has permanent memory and is safe to run repeatedly.
(`ledger.py` — included here.)

### 5. Resilient to flaky networks
Transient API errors are retried with exponential backoff; a long run checkpoints
its progress and resumes after a crash instead of restarting. **Why:** one network
hiccup shouldn't lose a lead or a multi-hour run. (`reliability.py` — included here.)

### 6. Concurrency tuned to the slowest API, not the CPU
The work is I/O-bound, so it runs on a thread pool — but the pool size is bounded by
the strictest upstream rate limit, not the core count. **Why:** more threads past
that point just trigger throttling; the real ceiling is the slowest dependency.
Net effect: ~25× the throughput of the original sequential version.

### 7. Output that survives real-world use
Results are written to Excel with phone/email columns forced to text (no
`4.4E+11` corruption), and filenames never overwrite a previous run (collision-safe
`_1`, `_2`, …). **Why:** the deliverable is opened in Excel by non-technical users;
small ergonomics prevent silent data loss.

### 8. Testable without the network
Every external call is injected, so the full suite runs offline with mocked
responses. **Why:** fast, deterministic CI and confidence to refactor.
