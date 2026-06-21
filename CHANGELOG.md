# Changelog

## v2 — production hardening
Re-architected from a single-pass finder into a concurrent, cost-capped, resumable
pipeline:
- Multi-source discovery; decision-maker + verified contact; 3-tier marketing audit.
- Per-key budget cap with graceful stop; per-niche dedup ledger; retry/backoff +
  checkpoint resume.
- Concurrency + bulk verification (~25× faster than the sequential version).
- Excel output with text-safe phone columns; collision-safe filenames.
- Hardened correctness: name-matched directors (no wrong-owner errors), verifiable
  facts only.

## v1 — initial
Single-source discovery, director lookup, work-email derivation + verification,
3-tier audit, CSV output.
