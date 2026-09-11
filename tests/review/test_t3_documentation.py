"""Sol's T3 round-2 F1 BLOCKER: the README must never present simulator numbers as live.

The original defect: "The figures above come from live OpenAI responses." opened "Why the
numbers are real". True when only the 2026-08-07 live block sat above it; false the moment
T3.2 inserted the Stage 1 vs Stage 2 simulator table in between. Nobody wrote a lie — an
insertion made a true sentence false because it located its subject by document order.

Sol's original assertion pinned that literal sentence and checked it preceded the simulator
heading. That caught the defect, but it could not tell "fixed" from "removed" — deleting the
sentence raised ValueError instead of passing — and it still allowed the positional wording
that caused the defect. The orchestrator directed the rewrite (2026-09-10): the intent
survives unchanged, the assertion now pins the invariant behind it. Every live-provenance
claim in README.md must name what it covers (the headline, 42.9%, the 2026-08-07 run, a
results/ file, or "simulator" as the contrast) and must not locate it by position on the
page. The simulator table must be labelled simulator, by name, where it appears.

Verified against the pre-fix README (`git show 9edd325^:README.md`): `live_claim_defects`
reports the unqualified "figures above" paragraph, so the original defect still fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"

# A paragraph asserts live provenance if it says data came from a real model. "live in" is
# the verb ("tiers live in one module"), not a provenance claim.
LIVE_CLAIM = re.compile(r"real (?:OpenAI|API)|\blive\b(?! in\b)", re.I)
# Locating the subject by page position is the failure mode; it is banned outright.
POSITIONAL = re.compile(
    r"\b(?:figures|numbers|table|results)\s+(?:above|below|here)\b"
    r"|\bthe figures\b|\bthese (?:numbers|figures)\b|\bthis provider\b|\b(?:above|below)\b",
    re.I,
)
# What a provenance claim must name instead.
NAMED_SUBJECT = re.compile(
    r"42\.9|2026-08-07|\bheadline\b|\bsimulator\b|results/[\w.-]+\.json|gpt-5\.6-terra", re.I
)


def paragraphs(readme: str) -> list[str]:
    prose = re.sub(r"```.*?```", "", readme, flags=re.S)
    kept = [ln for ln in prose.splitlines() if not ln.lstrip().startswith(("#", "|"))]
    return [p.strip() for p in re.split(r"\n\s*\n", "\n".join(kept)) if p.strip()]


def live_claim_defects(readme: str) -> list[str]:
    """Live-provenance paragraphs that point at a position or fail to name their subject."""
    defects = []
    for para in paragraphs(readme):
        if not LIVE_CLAIM.search(para):
            continue
        if POSITIONAL.search(para):
            defects.append(f"positional: {para[:90]!r}")
        elif not NAMED_SUBJECT.search(para):
            defects.append(f"unnamed subject: {para[:90]!r}")
    return defects


def test_readme_live_claims_name_their_subject_and_never_a_position() -> None:
    assert live_claim_defects(README.read_text(encoding="utf-8")) == []


def test_readme_simulator_table_is_labelled_simulator_by_name() -> None:
    readme = README.read_text(encoding="utf-8")
    heading = re.search(r"^### What the provenance delimiter did.*$", readme, re.M)
    assert heading and "simulator" in heading.group(0)
    section = readme[heading.end() : readme.index("\n## ", heading.end())]
    assert "results/2026-09-10-simulator.json" in section
    assert "results/2026-09-10-simulator-stage2.json" in section
    assert "42.9" in readme
