from pathlib import Path


def test_d33_amendment_preserves_and_repairs_its_sql_citation() -> None:
    decisions = Path("DECISIONS.md").read_text(encoding="utf-8")
    sql_lines = Path("sql/README.md").read_text(encoding="utf-8").splitlines()

    assert "#### D33 — amended 2026-09-10" in decisions
    assert "sentence now sits at\n`sql/README.md:6`" in decisions
    assert "lag 45 minutes" in sql_lines[5]


def test_sensitive_python_files_only_received_pointer_text_changes() -> None:
    patch = Path(".review/t1/1/diff.patch").read_text(encoding="utf-8")

    contracts = patch.split("diff --git a/app/contracts.py", 1)[1].split("diff --git", 1)[0]
    conftest = patch.split("diff --git a/conftest.py", 1)[1].split("diff --git", 1)[0]
    changed_contracts = [line for line in contracts.splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---"))]
    changed_conftest = [line for line in conftest.splitlines() if line[:1] in "+-" and not line.startswith(("+++", "---"))]

    assert changed_contracts == [
        "-change is needed, write it to HANDOFF.md rather than editing silently.",
        "+change is needed, write it to `.sol/requests/` rather than editing silently",
        "+(earlier ones are in docs/history/HANDOFF.md).",
    ]
    assert changed_conftest == [
        "-event flips the real switches in `.env` exactly as `EVENT_DAY.md` describes.",
        "+event flips the real switches in `.env` exactly as `docs/history/EVENT_DAY.md` describes.",
    ]
