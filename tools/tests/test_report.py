from pathlib import Path

from tools.report import REPORT_SECTIONS, report_problems

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_sections_are_the_six_headings():
    assert REPORT_SECTIONS == (
        "## Root cause",
        "## Knock-on effects",
        "## Separate issues",
        "## Fixes",
        "## What was checked",
        "## Helper details",
    )


def test_good_report_passes():
    assert report_problems(read("report-good.md")) == []


def test_clean_report_passes():
    assert report_problems(read("report-clean.md")) == []


def test_missing_undo_fails():
    problems = report_problems(read("report-missing-undo.md"))
    assert any("missing # Undo" in p for p in problems)


def test_wrong_order_fails():
    text = read("report-good.md")
    text = text.replace("## Root cause", "## @@").replace("## Knock-on effects", "## Root cause")
    text = text.replace("## @@", "## Knock-on effects")
    assert any("order" in p for p in report_problems(text))


def test_missing_heading_fails():
    text = read("report-good.md").replace("## Helper details", "## Details")
    assert report_problems(text)


def test_extra_h2_fails():
    text = read("report-good.md") + "\n## Bonus\n\nx\n"
    assert report_problems(text)


def test_claims_fix_ran_fails():
    text = read("report-good.md").replace("Add the missing key:", "I applied the patch.")
    assert any("ran" in p or "applied" in p for p in report_problems(text))


def test_claim_inside_code_block_is_ignored():
    text = read("report-good.md").replace(
        "kubectl -n my-namespace patch configmap my-config --type=merge",
        "echo 'I ran it'; kubectl -n my-namespace patch configmap my-config --type=merge",
    )
    assert report_problems(text) == []


def test_headings_inside_code_blocks_are_ignored():
    text = read("report-good.md").replace(
        "kubectl -n my-namespace patch configmap my-config --type=merge",
        "## Fixes\n    kubectl get pods",
    )
    assert report_problems(text) == []


def test_tilde_fence_needs_undo():
    text = read("report-good.md").replace("```bash", "~~~bash").replace("\n```\n", "\n~~~\n")
    assert report_problems(text) == []
    text = text.replace("# Undo:", "# Note:")
    assert any("missing # Undo" in p for p in report_problems(text))
