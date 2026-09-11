from pathlib import Path


def test_readme_does_not_describe_simulator_table_as_live() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    simulator_heading = readme.index("### What the provenance delimiter did")
    live_claim = readme.index("The figures above come from live OpenAI responses.")
    assert live_claim < simulator_heading, (
        "The unqualified 'figures above' live claim follows the simulator results table "
        "and therefore falsely labels those committed simulator figures as live."
    )
