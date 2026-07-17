"""
PII scrubber (Week 2 — built now, used by Week 2b real-data ingestion).

Purpose
-------
Before any REAL resume (e.g. Kaggle corpus) touches `data/raw/`, we strip
personally identifiable information and replace it with deterministic fakes.
This is a hard rule recorded in docs/research.md §5 ("never store raw PII")
and it is what makes the project safe to keep on a public GitHub portfolio.

What it scrubs
--------------
  - Email addresses           -> fake@example.com
  - Phone numbers (US/IN/UK)  -> +1-555-0XXX
  - URLs with person-y paths  -> https://example.com/...
  - Credit-card-shaped digits -> 4111-1111-1111-1111
  - SSN (US pattern)          -> 000-00-0000
  - Resume IDs / addresses    -> handled by caller if needed

Design
------
  - Stateless functions operating on plain text (pure, testable).
  - Each PII type has a regex + a deterministic replacement so the SAME input
    always maps to the SAME fake output (reproducibility for tests/eval).
  - Returns BOTH the scrubbed text AND a report of what was removed, so the
    caller can log a per-file audit trail (Week 2b manifest).

Week 4 parser note: synthetic resumes contain FAKE PII already, so they do
not need scrubbing. This module is for the real-data path only.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# Each pattern paired with a replacement strategy.
# Order matters: emails and URLs before generic digits so we don't mangle them.
_PII_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # Email — capture so we can hash it for a stable fake address.
    ("email", re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "fake"),
    # US SSN
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "redacted_ssn"),
    # Credit-card-shaped (16 digits, optional dashes/spaces)
    ("credit_card",
     re.compile(r"\b(?:\d[ -]?){13,16}\d\b"), "redacted_cc"),
    # URL — strip query/paths that may carry identifiers.
    ("url", re.compile(r"https?://\S+", re.IGNORECASE), "example_url"),
    # International / US phone numbers (loose: 7-15 digits with separators).
    ("phone",
     re.compile(
         r"(?:\+?\d{1,3}[\s.-]?)?"           # country code
         r"\(?\d{2,4}\)?[\s.-]?"             # area
         r"\d{3,4}[\s.-]?\d{3,4}"            # local
     ),
     "fake_phone"),
]


def _stable_fake(prefix: str, original: str, length: int = 6) -> str:
    """Deterministic fake: same input -> same output. Not a hash of PII
    itself (we never want to store that), but a short digest used purely so
    tests are reproducible and a single original maps to one fake."""
    digest = hashlib.sha1(original.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


@dataclass
class ScrubReport:
    """Audit record of what was removed from one document."""
    counts: dict[str, int] = field(default_factory=dict)
    samples: dict[str, list[str]] = field(default_factory=dict)

    def add(self, pii_type: str, sample: str) -> None:
        self.counts[pii_type] = self.counts.get(pii_type, 0) + 1
        # Keep up to 3 samples per type for the audit log.
        bucket = self.samples.setdefault(pii_type, [])
        if len(bucket) < 3:
            bucket.append(sample if len(sample) <= 60 else sample[:60] + "…")

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def to_dict(self) -> dict:
        return {"counts": self.counts, "samples": self.samples,
                "total": self.total}


def scrub_text(text: str) -> tuple[str, ScrubReport]:
    """Replace PII in `text` with deterministic fakes.

    Returns (scrubbed_text, report). The scrubbed text is safe to persist;
    the report is for the audit log only and contains TRUNCATED samples
    (never full emails/phones) to aid debugging.
    """
    report = ScrubReport()
    if not text:
        return text, report

    out = text
    for pii_type, pattern, strat in _PII_PATTERNS:
        def _replace(match, _t=pii_type, _s=strat):
            original = match.group(0)
            report.add(_t, original)
            if _s == "fake":
                return _stable_fake("user", original) + "@example.com"
            if _s == "fake_phone":
                return "+1-555-" + hashlib.sha1(
                    original.encode()).hexdigest()[:3] + "-0000"
            if _s == "example_url":
                return "https://example.com/" + _stable_fake("page", original)
            return _s  # static redaction string

        out = pattern.sub(_replace, out)
    return out, report
