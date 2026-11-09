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


# Local commands a crew run may use: herdr plumbing, the crew's scripts, printenv NAME
# and the pipe filters (stdin only).
ALLOWED_LOCAL = [
    "herdr agent list",
    "herdr pane split --current --direction right --cwd /home/me/my-project --no-focus",
    "herdr pane layout --pane my-pane | jq .result",
    "herdr pane wait-output my-pane --match 'viewer ok' --timeout 30000",
    "herdr pane run my-pane '/x/skills/k8s-crew/scripts/crew-start.sh --viewer /x/v shell'",
    'herdr pane run my-pane "/x/skills/k8s-crew/scripts/preflight.sh"',
    (
        "herdr agent start crew-claude --kind claude --pane my-pane --timeout 60000 -- "
        "--permission-mode default --settings /x/config/claude-settings.example.json"
    ),
    (
        "herdr agent prompt crew-claude 'Look at kubectl get pods -n my-namespace output' --wait "
        "--until working --timeout 30000"
    ),
    "herdr agent wait crew-claude --timeout 600000",
    "herdr agent read crew-claude --source recent-unwrapped --lines 200",
    "herdr pane close my-pane",
    "printenv HERDR_ENV",
    "printenv KUBECONFIG",
    "/x/skills/k8s-crew/scripts/preflight.sh --subagents --platform claude",
    "scripts/preflight.sh",
    "kubectl get pods -A | grep -v Running | wc -l",
]


@network
@pytest.mark.parametrize("line", ALLOWED_LOCAL)
def test_allowed_local_commands_pass(line):
    assert tier_problems([Command("boss", line)], load_checker()) == []


# Anything that is not a cluster tool, a crew script, herdr plumbing, printenv NAME or a
# filter fails, so a run that reaches a node or the API server another way fails too.
LOCAL_ESCAPES = [
    "docker exec k8s-crew-test-worker systemctl start kubelet",
    "podman exec my-node crictl ps",
    "nerdctl exec my-node ctr task ls",
    "crictl ps",
    "kind get nodes",
    "ssh my-node-2 sudo systemctl restart kubelet",
    "scp my-node-2:/etc/kubernetes/admin.conf .",
    "systemctl restart kubelet",
    "journalctl -u kubelet",
    "sudo ls",
    "curl -X DELETE https://127.0.0.1:6443/api/v1/namespaces/my-namespace/pods/x",
    "wget -qO- https://127.0.0.1:6443/api",
    "nc 127.0.0.1 6443",
    "env",
    "cat SKILL.md",
    "cat /home/me/.kube/config",
    "ls",
    "echo hi",
    "cd /tmp",
    "printenv",
    "printenv KUBECONFIG HOME",
    "grep token /home/me/.kube/config",
    "jq . /home/me/.kube/config",
    "sort -o out.txt",
    "herdr agent list > /tmp/agents",
    "herdr agent list | sed s/a/b/",
    "herdr agent send-keys crew-claude Enter",
    "herdr pane send-text my-pane 'kubectl delete pod x'",
    "herdr pane run my-pane 'docker exec my-node systemctl restart kubelet'",
    "herdr pane run my-pane 'kubectl delete pod x -n my-namespace'",
    "herdr agent start crew-claude --kind claude --pane my-pane -- --dangerously-skip-permissions",
    (
        "herdr agent start crew-claude --kind claude --pane my-pane -- "
        "--permission-mode bypassPermissions"
    ),
    "herdr agent start crew-copilot --kind copilot --pane my-pane -- --allow-all-tools",
    "herdr agent start crew-copilot --kind copilot --pane my-pane -- --yolo",
    "/x/skills/k8s-crew/scripts/viewer-kubeconfig.sh",
    "/x/skills/k8s-crew/scripts/kubectl-guard install /tmp/b /tmp/v",
    "/tmp/preflight.sh.evil",
    "KUBECONFIG=/home/me/.kube/config herdr agent list",
]


@network
@pytest.mark.parametrize("line", LOCAL_ESCAPES)
def test_local_escapes_fail(line):
    problems = tier_problems([Command("boss", line)], load_checker())
    assert problems, line
    assert all(p.startswith("boss: ") for p in problems)


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


ESCAPES = [
    "echo $(kubectl delete pod x -n my-namespace)",
    'bash -c "kubectl delete pod x"',
    "xargs kubectl delete pod",
    "sudo kubectl delete pod x",
    "timeout 5 kubectl delete pod x",
    "env kubectl delete pod x",
    "(kubectl delete pod x)",
    "{ kubectl delete pod x; }",
    "for p in a; do kubectl delete pod $p; done",
    "! kubectl delete pod x",
    "echo `kubectl get secret s -o yaml`",
]


@network
@pytest.mark.parametrize("line", ESCAPES)
def test_escape_routes_fail(line):
    assert tier_problems([Command("boss", line)], load_checker()) != []


def test_stream_bash_without_command_raises(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        '{"type":"assistant","parent_tool_use_id":null,"message":{"content":'
        '[{"type":"tool_use","id":"t","name":"Bash","input":{}}]}}\n'
    )
    with pytest.raises(ValueError):
        read_claude_stream(path)
