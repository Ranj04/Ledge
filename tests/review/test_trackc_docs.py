"""Track C round-1 review tests (Fable reviewing Sol).

Track C moved seven root documents into docs/history/, deleted the Sales tab,
and published a measurement artifact for strangers. These pin the three
things a stranger would trip over that the build prompt stated in prose but
nothing asserts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# The seven documents C3 moved. A bare `X.md` in a root document now points
# at nothing.
MOVED = {"AGENTS", "DEMO", "EVENT_DAY", "FINISH", "HANDOFF", "MORNING_STATUS", "PIVOT"}


def _bare_doc_pointers(text: str) -> list[tuple[int, str]]:
    """(line_no, name) for every backticked bare `NAME.md` naming a moved doc."""
    hits = []
    for no, line in enumerate(text.splitlines(), 1):
        for name in re.findall(r"`([A-Z_]+)\.md`", line):
            if name in MOVED:
                hits.append((no, name))
    return hits


@pytest.mark.parametrize("doc", ["README.md", "CLAUDE.md"])
def test_root_docs_do_not_point_at_moved_files_by_their_old_root_path(doc: str) -> None:
    """README.md's 'Going live' and 'Documents' sections and CLAUDE.md's
    'Living documents' table still say `EVENT_DAY.md`, `DEMO.md`, `HANDOFF.md`
    as if they sat at root. A stranger runs `cat EVENT_DAY.md` and gets
    'No such file'; an agent following CLAUDE.md recreates the root file the
    track just removed. `AGENTS.md` is exempt: a pointer stub exists at root.
    """
    text = (ROOT / doc).read_text(encoding="utf-8")
    stale = [(no, n) for no, n in _bare_doc_pointers(text) if n != "AGENTS"]
    stale = [(no, n) for no, n in stale if not (ROOT / f"{n}.md").exists()]
    assert not stale, f"{doc} still points at moved docs by their old root path: {stale}"


def test_results_readme_carries_no_machine_specific_path() -> None:
    """results/README.md is the provenance note a stranger reads. It must not
    embed one contributor's home directory; the command it documents has to
    run on somebody else's clone.
    """
    text = (ROOT / "results" / "README.md").read_text(encoding="utf-8")
    leaks = re.findall(r"[A-Za-z]:/Users/[^/\s]+|/Users/[^/\s]+|/home/[^/\s]+", text)
    assert not leaks, f"results/README.md embeds an absolute home path: {leaks}"


def test_no_orphaned_sales_css_after_salesview_deletion() -> None:
    """web/src/SalesView.tsx is gone, so every `.sales-*` (and the
    `.seeded-flag` / `.seeded-tag` pair it alone used) selector in styles.css
    is dead weight shipped to every viewer of dist/.
    """
    css = (ROOT / "web" / "src" / "styles.css").read_text(encoding="utf-8")
    tsx = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "web" / "src").glob("*.tsx"))
    selectors = set(re.findall(r"\.((?:sales|seeded)-[a-z0-9-]+)", css))
    orphaned = sorted(s for s in selectors if s not in tsx)
    assert not orphaned, f"{len(orphaned)} CSS classes have no TSX user: {orphaned[:8]}..."
