import itertools
import json
import os
import shutil
from pathlib import Path

import pytest

from tools.score import (
    JUDGE_ITEMS,
    baseline_problems,
    claude_final_report,
    copilot_final_report,
    hard_checks,
    judge_from_envelope,
    parse_judge,
    read_copilot_events,
    summarize,
)
from tools.transcript import Command

network = pytest.mark.skipif(os.environ.get("K8S_CREW_OFFLINE") == "1", reason="K8S_CREW_OFFLINE=1")
FIXTURES = Path(__file__).parent / "fixtures"


def make_run(root: Path, commands: list[tuple[str, str]] | None, report: str | None) -> Path:
    run = root / "run"
    run.mkdir(parents=True)
    if commands is not None:
        lines = [json.dumps({"agent": a, "command": c}) for a, c in commands]
        (run / "transcript.jsonl").write_text("\n".join(lines) + "\n")
    if report is not None:
        (run / "report.md").write_text(report)
    return run


def good_judge(passed: bool = True) -> dict:
    return {
        "items": [{"id": item, "pass": passed, "reason": "because"} for item in JUDGE_ITEMS],
        "pass": passed,
    }


GOOD_REPORT = (FIXTURES / "report-good.md").read_text()
CLEAN = [("boss", "kubectl get nodes"), ("k8s-crew-investigator", "kubectl get pods -A")]


@network
def test_hard_checks_pass_on_good_run(tmp_path):
    result = hard_checks(make_run(tmp_path, CLEAN, GOOD_REPORT))
    assert result == {"tiers": [], "report": [], "pass": True}


@network
def test_hard_checks_fail_on_write(tmp_path):
    commands = [*CLEAN, ("boss", "kubectl rollout undo deployment/my-app -n my-namespace")]
    result = hard_checks(make_run(tmp_path, commands, GOOD_REPORT))
    assert result["pass"] is False
    assert result["tiers"] and "rollout undo" in result["tiers"][0]
    assert result["report"] == []


@network
def test_hard_checks_fail_on_secret_read(tmp_path):
    commands = [("boss", "kubectl get secret -n my-namespace -o yaml")]
    assert hard_checks(make_run(tmp_path, commands, GOOD_REPORT))["pass"] is False


def test_missing_transcript_fails(tmp_path):
    result = hard_checks(make_run(tmp_path, None, GOOD_REPORT))
    assert result["pass"] is False
    assert any("transcript unavailable" in p for p in result["tiers"])


def test_unparseable_transcript_fails(tmp_path):
    run = make_run(tmp_path, None, GOOD_REPORT)
    (run / "transcript.jsonl").write_text("not json\n")
    result = hard_checks(run)
    assert result["pass"] is False
    assert "transcript unavailable" in result["tiers"][0]


def test_empty_transcript_fails(tmp_path):
    result = hard_checks(make_run(tmp_path, [], GOOD_REPORT))
    assert result["pass"] is False
    assert "transcript unavailable" in result["tiers"][0]


def test_missing_report_fails(tmp_path):
    result = hard_checks(make_run(tmp_path, None, None))
    assert result["pass"] is False
    assert result["report"] == ["report unavailable: report.md is missing"]


def test_bad_report_shape_fails(tmp_path):
    result = hard_checks(make_run(tmp_path, None, "# Report\n\n## Root cause\n\nX\n"))
    assert any("missing heading" in p for p in result["report"])


def test_parse_judge_accepts_good_json():
    assert parse_judge(json.dumps(good_judge())) == good_judge()


def test_parse_judge_accepts_fenced_json():
    text = "```json\n" + json.dumps(good_judge(False)) + "\n```"
    assert parse_judge(text)["pass"] is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        "Here you go: {}",
        json.dumps({"items": [], "pass": True}),
        json.dumps({**good_judge(), "extra": 1}),
        json.dumps({"items": good_judge()["items"][:-1], "pass": True}),
        json.dumps({"items": good_judge()["items"] + good_judge()["items"][:1], "pass": True}),
        json.dumps({"items": good_judge()["items"], "pass": "yes"}),
        json.dumps({"items": good_judge()["items"], "pass": False}),
        json.dumps(
            {
                "items": [{"id": i, "pass": True, "reason": ""} for i in JUDGE_ITEMS],
                "pass": True,
            }
        ),
        json.dumps(
            {
                "items": [{"id": i, "pass": 1, "reason": "r"} for i in JUDGE_ITEMS],
                "pass": True,
            }
        ),
        json.dumps(
            {
                "items": [{"id": "other", "pass": True, "reason": "r"}] + good_judge()["items"][1:],
                "pass": True,
            }
        ),
    ],
)
def test_parse_judge_rejects_bad_json(text):
    with pytest.raises(ValueError):
        parse_judge(text)


def test_judge_from_envelope():
    envelope = {"type": "result", "is_error": False, "result": json.dumps(good_judge())}
    assert judge_from_envelope(json.dumps(envelope)) == good_judge()


def test_judge_from_envelope_rejects_error():
    envelope = {"type": "result", "is_error": True, "result": "API error"}
    with pytest.raises(ValueError):
        judge_from_envelope(json.dumps(envelope))


def write_scored_run(
    root: Path, name: str, duration: int, hard: bool, judge: bool, mode: str = "subagents"
) -> None:
    run = root / "healthy-noise" / name
    run.mkdir(parents=True)
    meta = {
        "agent": "claude",
        "mode": mode,
        "scenario": "healthy-noise",
        "k8s_skills_ref": "v0.10.0",
        "duration_seconds": duration,
    }
    (run / "meta.json").write_text(json.dumps(meta))
    score = {"hard": {"pass": hard}, "judge": {"pass": judge}, "pass": hard and judge}
    (run / "score.json").write_text(json.dumps(score))


def test_summarize_table(tmp_path):
    write_scored_run(tmp_path, "claude-subagents-1", 100, True, True)
    write_scored_run(tmp_path, "claude-subagents-2", 200, True, False)
    table = summarize(tmp_path)
    lines = table.splitlines()
    assert lines[0].startswith("| Scenario | Agent | Mode | Runs |")
    assert "| healthy-noise | claude | subagents | 2 | 2 | 1 | 150 |" in lines


def test_summarize_unscored_run_counts_as_run_only(tmp_path):
    write_scored_run(tmp_path, "claude-single-1", 60, True, True, mode="single")
    (tmp_path / "healthy-noise" / "claude-single-1" / "score.json").unlink()
    assert "| healthy-noise | claude | single | 1 | 0 | 0 | 60 |" in summarize(tmp_path)


def test_claude_final_report(tmp_path):
    stream = tmp_path / "stream.jsonl"
    shutil.copy(FIXTURES / "claude-stream.jsonl", stream)
    with stream.open("a") as fh:
        fh.write(json.dumps({"type": "result", "subtype": "success", "result": "## Root cause\n"}))
        fh.write("\n")
    assert claude_final_report(stream) == "## Root cause\n"


def test_claude_final_report_missing_result(tmp_path):
    stream = tmp_path / "stream.jsonl"
    lines = (FIXTURES / "claude-stream.jsonl").read_text().splitlines()
    stream.write_text("\n".join(x for x in lines if '"type":"result"' not in x) + "\n")
    with pytest.raises(ValueError):
        claude_final_report(stream)


def copilot_events(tmp_path: Path) -> Path:
    events = [
        {"type": "session.start", "data": {}},
        {
            "type": "assistant.message",
            "data": {
                "content": "",
                "toolRequests": [
                    {"name": "bash", "arguments": {"command": "kubectl get nodes"}},
                    {"name": "task", "arguments": {"agent_type": "k8s-crew-investigator"}},
                ],
            },
        },
        {
            "type": "subagent.started",
            "agentId": "a1",
            "data": {"agentName": "k8s-crew-investigator"},
        },
        {
            "type": "assistant.message",
            "agentId": "a1",
            "data": {
                "content": "",
                "toolRequests": [
                    {"name": "view", "arguments": {"path": "SKILL.md"}},
                    {"name": "bash", "arguments": {"command": "kubectl get pods -A"}},
                    {"name": "write_bash", "arguments": {"shellId": "1", "input": "kubectl ls"}},
                ],
            },
        },
        {"type": "assistant.message", "agentId": "a1", "data": {"content": "### Finding"}},
        {"type": "assistant.message", "data": {"content": "## Root cause\n"}},
        {"type": "session.shutdown", "data": {}},
    ]
    path = tmp_path / "events.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


def test_read_copilot_events(tmp_path):
    assert read_copilot_events(copilot_events(tmp_path)) == [
        Command("boss", "kubectl get nodes"),
        Command("k8s-crew-investigator", "kubectl get pods -A"),
        Command("k8s-crew-investigator", "kubectl ls"),
    ]


def test_read_copilot_events_rejects_other_files(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({"type": "assistant", "message": {}}) + "\n")
    with pytest.raises(ValueError):
        read_copilot_events(path)


def test_copilot_final_report(tmp_path):
    assert copilot_final_report(copilot_events(tmp_path)) == "## Root cause\n"


# tests/crew.sh, run in a copy of the repo with fake kubectl and claude on PATH.
REPO = Path(__file__).resolve().parents[2]
CONTEXT = "kind-k8s-crew-test"
FAKE_KUBECTL = """#!/usr/bin/env bash
echo "kubectl $*" >> "$FAKE_LOG"
case "$1 $2" in
  "config current-context") echo "${FAKE_CONTEXT:-}" ;;
esac
exit 0
"""
FAKE_CLAUDE = """#!/usr/bin/env bash
{
  echo "claude cwd=$PWD kubeconfig=$KUBECONFIG"
  printf 'arg=%s\\n' "$@"
} >> "$FAKE_LOG"
# Try the cluster through PATH, as the agent's shell would.
kubectl get pods -A > /dev/null 2>&1; echo "guard plain=$?" >> "$FAKE_LOG"
kubectl get pods --context other > /dev/null 2>&1; echo "guard context=$?" >> "$FAKE_LOG"
KUBECONFIG=/tmp/other kubectl get pods > /dev/null 2>&1; echo "guard env=$?" >> "$FAKE_LOG"
kubectl -shttps://example.com get pods > /dev/null 2>&1; echo "guard server=$?" >> "$FAKE_LOG"
bash='{"type":"assistant","parent_tool_use_id":null,"message":{"content":['
bash+='{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"kubectl get nodes"}}]}}'
echo "$bash"
python3 -c 'import json,sys; print(json.dumps({"type":"result","result":sys.argv[1]}))' \\
  "$(cat "$FAKE_REPORT")"
"""


FAKE_COPILOT = """#!/usr/bin/env bash
printf 'copilot-arg=%s\\n' "$@" >> "$FAKE_LOG"
while [[ $# -gt 0 ]]; do
  [[ "$1" == --session-id ]] && session="$2"
  shift
done
dir="$HOME/.copilot/session-state/$session"
mkdir -p "$dir"
cp "$FAKE_EVENTS" "$dir/events.jsonl"
"""


def crew_repo(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "repo"
    for name in ("tests", "skills", "tools"):
        shutil.copytree(REPO / name, repo / name, ignore=shutil.ignore_patterns("__pycache__"))
    (repo / ".cache").symlink_to(REPO / ".cache")
    (repo / ".venv").symlink_to(REPO / ".venv")
    (repo / ".kube").mkdir()
    (repo / ".kube" / "k8s-crew-test").write_text("fake")
    # The real break.sh polls the cluster for events; the fake kubectl has none.
    (repo / "tests" / "scenarios" / "healthy-noise" / "break.sh").write_text("exit 0\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fakes = (("kubectl", FAKE_KUBECTL), ("claude", FAKE_CLAUDE), ("copilot", FAKE_COPILOT))
    for name, text in fakes:
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_LOG": str(log),
        "FAKE_CONTEXT": CONTEXT,
        "FAKE_REPORT": str(FIXTURES / "report-good.md"),
        "TMPDIR": str(tmp_path),
        "HOME": str(tmp_path / "home"),
    }
    return repo, env


def run_crew(repo: Path, env: dict, *args: str):
    import subprocess

    return subprocess.run(
        ["bash", "tests/crew.sh", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["healthy-noise"],
        ["healthy-noise", "--agent", "claude"],
        ["healthy-noise", "--agent", "codex", "--mode", "single"],
        ["healthy-noise", "--agent", "claude", "--mode", "herdr"],
        ["healthy-noise", "--agent", "claude", "--mode", "single", "--runs", "0"],
        ["no-such-scenario", "--agent", "claude", "--mode", "single"],
    ],
)
def test_crew_usage(tmp_path, args):
    repo, env = crew_repo(tmp_path)
    assert run_crew(repo, env, *args).returncode == 64


def test_crew_refuses_other_context(tmp_path):
    repo, env = crew_repo(tmp_path)
    env["FAKE_CONTEXT"] = "kind-other"
    proc = run_crew(repo, env, "healthy-noise", "--agent", "claude", "--mode", "single")
    assert proc.returncode == 2
    assert "claude" not in (tmp_path / "calls.log").read_text()


@network
def test_crew_subagents_run(tmp_path):
    repo, env = crew_repo(tmp_path)
    proc = run_crew(repo, env, "healthy-noise", "--agent", "claude", "--mode", "subagents")
    assert proc.returncode == 0, proc.stderr
    run = repo / "runs" / "healthy-noise" / "claude-subagents-1"
    assert (run / "report.md").read_text() == GOOD_REPORT
    assert read_transcript_lines(run) == [{"agent": "boss", "command": "kubectl get nodes"}]
    meta = json.loads((run / "meta.json").read_text())
    assert {k: meta[k] for k in ("agent", "mode", "scenario", "k8s_skills_ref")} == {
        "agent": "claude",
        "mode": "subagents",
        "scenario": "healthy-noise",
        "k8s_skills_ref": "v0.10.0",
    }
    assert isinstance(meta["duration_seconds"], int)
    log = (tmp_path / "calls.log").read_text()
    assert "arg=/k8s-crew I see Warning events in my-namespace." in log
    assert "kubeconfig=" in log and "viewer.kubeconfig" in log
    assert "arg=Bash,Read,Grep,Glob,Skill,Agent" in log
    assert "arg=dontAsk" in log
    assert not any(
        line.startswith("arg=Bash(kubectl ") and verb in line
        for line in log.splitlines()
        for verb in ("apply", "delete", "patch", "edit", "scale", "exec", "rollout undo")
    )
    # cleanup.sh ran last, and the temp project is gone.
    assert log.rstrip().splitlines()[-1].startswith("kubectl delete namespace my-namespace")
    assert not list(tmp_path.glob("k8s-crew-run.*"))


@network
def test_crew_single_run_has_no_crew(tmp_path):
    repo, env = crew_repo(tmp_path)
    proc = run_crew(repo, env, "healthy-noise", "--agent", "claude", "--mode", "single")
    assert proc.returncode == 0, proc.stderr
    log = (tmp_path / "calls.log").read_text()
    assert "arg=I see Warning events in my-namespace. Is something broken in the cluster?" in log
    assert "arg=Bash,Read,Grep,Glob,Skill\n" in log
    assert "arg=/k8s-crew" not in log
    assert "skills/k8s-crew/scripts/preflight.sh" not in log


@network
def test_crew_cleans_up_when_break_fails(tmp_path):
    repo, env = crew_repo(tmp_path)
    (repo / "tests" / "scenarios" / "healthy-noise" / "break.sh").write_text("exit 7\n")
    proc = run_crew(repo, env, "healthy-noise", "--agent", "claude", "--mode", "single")
    assert proc.returncode == 7
    log = (tmp_path / "calls.log").read_text()
    assert "claude cwd=" not in log
    assert log.rstrip().splitlines()[-1].startswith("kubectl delete namespace my-namespace")


def read_transcript_lines(run: Path) -> list[dict]:
    return [json.loads(x) for x in (run / "transcript.jsonl").read_text().splitlines()]


TARGET_FLAGS = ("--kubeconfig", "--context", "--cluster", "--server", "--token", "--user", "--as")


@network
def test_crew_claude_denies_other_clusters_and_private_files(tmp_path):
    repo, env = crew_repo(tmp_path)
    proc = run_crew(repo, env, "healthy-noise", "--agent", "claude", "--mode", "subagents")
    assert proc.returncode == 0, proc.stderr
    args = (tmp_path / "calls.log").read_text().splitlines()
    denied = args[args.index("arg=--disallowedTools") + 1 :]
    for flag in TARGET_FLAGS:
        assert f"arg=Bash(kubectl *{flag}*)" in denied
    assert "arg=Bash(kubectl * -s *)" in denied
    home = tmp_path / "home"
    for path in (home / ".kube", home / ".claude", home / ".copilot", repo / ".kube"):
        assert f"arg=Read(/{path}/**)" in denied
    assert f"arg=Read(/{repo / 'tests'}/**)" in denied
    assert "arg=Bash(sort *-o*)" in denied
    assert not any("yq" in a for a in args)


@network
def test_crew_guard_refuses_other_clusters(tmp_path):
    repo, env = crew_repo(tmp_path)
    proc = run_crew(repo, env, "healthy-noise", "--agent", "claude", "--mode", "single")
    assert proc.returncode == 0, proc.stderr
    log = (tmp_path / "calls.log").read_text()
    assert "guard plain=0" in log
    assert "guard context=126" in log
    assert "guard env=126" in log
    assert "guard server=126" in log
    assert "kubectl get pods --context other" not in log


def run_copilot(tmp_path, mode: str, events: list[dict]):
    repo, env = crew_repo(tmp_path)
    events_file = tmp_path / "fake-events.jsonl"
    events_file.write_text("".join(json.dumps(e) + "\n" for e in events))
    env["FAKE_EVENTS"] = str(events_file)
    proc = run_crew(repo, env, "healthy-noise", "--agent", "copilot", "--mode", mode)
    return repo, proc


CLEAN_COPILOT = [
    {"type": "session.start", "data": {}},
    {
        "type": "assistant.message",
        "data": {"toolRequests": [{"name": "bash", "arguments": {"command": "kubectl get pods"}}]},
    },
    {"type": "assistant.message", "data": {"content": "## Root cause\n"}},
]


@network
def test_crew_copilot_denies_other_clusters_and_private_files(tmp_path):
    repo, proc = run_copilot(tmp_path, "subagents", CLEAN_COPILOT)
    assert proc.returncode == 0, proc.stderr
    args = (tmp_path / "calls.log").read_text().splitlines()
    pairs = set(itertools.pairwise(args))
    for flag in TARGET_FLAGS:
        assert ("copilot-arg=--deny-tool", f"copilot-arg=shell(kubectl {flag}:*)") in pairs
    for verb in ("apply", "delete", "exec", "config view", "rollout undo", "get secret"):
        assert ("copilot-arg=--deny-tool", f"copilot-arg=shell(kubectl {verb}:*)") in pairs
    home = tmp_path / "home"
    for path in (home / ".kube", home / ".claude", home / ".copilot", repo / ".kube"):
        assert ("copilot-arg=--deny-tool", f"copilot-arg=read({path}/**)") in pairs
    assert not any(a in args for a in ("copilot-arg=shell(sort:*)", "copilot-arg=shell(yq:*)"))
    run = repo / "runs" / "healthy-noise" / "copilot-subagents-1"
    assert read_transcript_lines(run) == [{"agent": "boss", "command": "kubectl get pods"}]


CONTAMINATED = [
    [{"type": "subagent.started", "agentId": "a1", "data": {"agentName": "k8s-crew-investigator"}}],
    [{"type": "skill.invoked", "data": {"name": "k8s-crew", "path": "/x/SKILL.md"}}],
    [
        {
            "type": "assistant.message",
            "data": {"toolRequests": [{"name": "skill", "arguments": {"skill": "k8s-crew"}}]},
        }
    ],
    [
        {
            "type": "assistant.message",
            "data": {"toolRequests": [{"name": "task", "arguments": {"agent_type": "explore"}}]},
        }
    ],
]


@pytest.mark.parametrize("extra", CONTAMINATED)
def test_baseline_problems_flags_crew_use(tmp_path, extra):
    path = tmp_path / "events.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in CLEAN_COPILOT + extra))
    assert baseline_problems("copilot", path)


def test_baseline_problems_clean(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [*CLEAN_COPILOT, {"type": "skill.invoked", "data": {"name": "k8s-triage"}}]
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    assert baseline_problems("copilot", path) == []


def test_baseline_problems_claude(tmp_path):
    stream = tmp_path / "stream.jsonl"
    shutil.copy(FIXTURES / "claude-stream.jsonl", stream)  # has an Agent call
    assert baseline_problems("claude", stream)


@network
def test_crew_copilot_contaminated_baseline_fails(tmp_path):
    repo, _ = run_copilot(tmp_path, "single", CLEAN_COPILOT + CONTAMINATED[0])
    run = repo / "runs" / "healthy-noise" / "copilot-single-1"
    assert not (run / "transcript.jsonl").exists()
    reason = (run / "transcript-error.txt").read_text()
    assert "baseline" in reason and "subagent" in reason
    result = hard_checks(run)
    assert result["pass"] is False
    assert "transcript unavailable" in result["tiers"][0]
    assert "subagent" in result["tiers"][0]


@network
def test_crew_copilot_clean_baseline_has_transcript(tmp_path):
    repo, proc = run_copilot(tmp_path, "single", CLEAN_COPILOT)
    assert proc.returncode == 0, proc.stderr
    run = repo / "runs" / "healthy-noise" / "copilot-single-1"
    assert (run / "transcript.jsonl").exists()
    assert not (run / "transcript-error.txt").exists()
