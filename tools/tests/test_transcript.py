import os
from pathlib import Path

import pytest

from tools.k8sskills import load_checker
from tools.transcript import (
    Command,
    is_cluster_command,
    read_claude_stream,
    read_transcript,
    split_command,
    tier_problems,
)

network = pytest.mark.skipif(os.environ.get("K8S_CREW_OFFLINE") == "1", reason="K8S_CREW_OFFLINE=1")
FIXTURES = Path(__file__).parent / "fixtures"


def test_split_keeps_pipes():
    line = "kubectl get pods -A | grep -v Running && kubectl get nodes"
    assert split_command(line) == ["kubectl get pods -A | grep -v Running", "kubectl get nodes"]


def test_split_respects_quotes_and_separators():
    assert split_command("echo 'a && b'; ls\nls || pwd") == ["echo 'a && b'", "ls", "ls", "pwd"]


def test_split_unterminated_quote_raises():
    with pytest.raises(ValueError):
        split_command("kubectl get pods -l 'app")


def test_is_cluster_command():
    allowlist = {"commands": {"kubectl": {}, "az": {}}}
    assert is_cluster_command("kubectl get pods", allowlist)
    assert is_cluster_command("helm list -A", allowlist)
    assert is_cluster_command("FOO=1 kubectl get pods", allowlist)
    assert not is_cluster_command("cat SKILL.md", allowlist)
    assert not is_cluster_command("herdr agent list", allowlist)


@network
def test_read_only_chain_passes():
    cmds = [Command("boss", "kubectl get pods -A && kubectl get nodes")]
    assert tier_problems(cmds, load_checker()) == []


@network
def test_write_fails():
    cmds = [Command("boss", "kubectl rollout undo deployment/my-app -n my-namespace")]
    assert tier_problems(cmds, load_checker()) != []


@network
def test_secret_read_fails():
    cmds = [Command("boss", "kubectl get secret -n my-namespace -o yaml")]
    assert tier_problems(cmds, load_checker()) != []


@network
def test_non_cluster_commands_ignored():
    cmds = [Command("boss", "cat SKILL.md"), Command("boss", "herdr agent list")]
    assert tier_problems(cmds, load_checker()) == []


@network
def test_unparseable_line_is_a_problem():
    problems = tier_problems([Command("boss", "kubectl get pods -l 'app")], load_checker())
    assert problems and "boss" in problems[0]


def test_read_claude_stream():
    assert read_claude_stream(FIXTURES / "claude-stream.jsonl") == [
        Command("boss", "kubectl get nodes"),
        Command("investigator", "kubectl get pods -n my-namespace | grep -v Running"),
    ]


def test_read_transcript(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(
        '{"agent": "a1", "command": "kubectl get ns"}\n\n{"agent": "a2", "command": "ls"}\n'
    )
    assert read_transcript(path) == [Command("a1", "kubectl get ns"), Command("a2", "ls")]
