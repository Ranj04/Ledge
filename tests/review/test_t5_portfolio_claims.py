from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_readme_offline_runtime_claim_has_no_remote_browser_assets() -> None:
    """An offline app must not make the browser fetch assets from the network."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "no network once the tokenizer table is cached" in " ".join(readme.split())

    externally_loaded = []
    for path in (ROOT / "web").rglob("*"):
        if not path.is_file() or path.suffix not in {".html", ".css", ".js", ".jsx", ".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "fonts.googleapis.com" in text or "fonts.gstatic.com" in text:
            externally_loaded.append(str(path.relative_to(ROOT)))

    assert externally_loaded == [], (
        "README promises an offline runtime after caching the tokenizer, but the browser "
        f"still loads Google Fonts from the network in: {externally_loaded}"
    )
