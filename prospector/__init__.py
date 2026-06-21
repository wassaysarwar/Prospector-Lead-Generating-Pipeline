"""
Prospector — selected infrastructure modules (public showcase).

This package, in the public repository, contains only the non-proprietary
infrastructure layer of the pipeline: per-key API cost control, the dedup
ledger, and the reliability (retry + checkpoint) layer. The discovery,
enrichment, and audit modules are proprietary and kept private.
"""

__version__ = "2.0.0"
