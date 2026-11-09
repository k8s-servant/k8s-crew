from pathlib import Path

import pytest

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


def with_fixes(body: str) -> str:
    """The clean report with its ## Fixes section replaced by ``body``."""
    clean = (FIXTURES / "report-clean.md").read_text()
    return clean.replace("No fixes needed.\n", body)


@pytest.mark.parametrize(
    "body",
    [
        "Patch the configmap: kubectl -n my-namespace patch configmap my-config ...\n",
        "    kubectl -n my-namespace delete pod my-pod\n    # Undo: none\n",
        "No fixes needed. But restart the kubelet on my-node-2.\n",
        "no fixes needed\n",
        "",
    ],
)
def test_fixes_without_a_fenced_block_fail(body):
    problems = report_problems(with_fixes(body))
    assert any("## Fixes has no fenced fix block" in p for p in problems), problems


@pytest.mark.parametrize("undo", ["# Undo:", "# Undo:   ", "  # Undo:\t"])
def test_empty_undo_fails(undo):
    body = f"Fix it.\n\n```bash\nkubectl -n my-namespace scale deployment my-app --replicas 2\n{undo}\n```\n"
    problems = report_problems(with_fixes(body))
    assert any("empty # Undo:" in p for p in problems), problems


def test_one_empty_undo_among_good_ones_fails():
    body = (
        "```bash\nkubectl -n my-namespace scale deployment my-app --replicas 2\n"
        "# Undo: kubectl -n my-namespace scale deployment my-app --replicas 1\n"
        "# Undo:\n```\n"
    )
    assert any("empty # Undo:" in p for p in report_problems(with_fixes(body)))
