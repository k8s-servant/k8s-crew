# Gotchas

Things that went wrong while k8s-crew was built and tested, what causes them, and what
to do. Versions: Claude Code 2.1, Copilot CLI 1.0.107, herdr 0.9.

## Starting a session

### Start through `crew-start.sh`

`export KUBECONFIG=~/.kube/k8s-crew-viewer` and then `claude` is not enough: your admin
kubeconfig is still reachable with `--kubeconfig` or `--context`. Start every crew
session with `<skill-dir>/scripts/crew-start.sh claude` (or `copilot`). If you do not,
the preflight exits 6 with `kubectl guard not active` and the crew does not start.

The guard is refused too when something in the session changes `KUBECONFIG` or puts
another kubectl before it on `PATH`. In a herdr pane, `crew-start.sh ... shell` starts
bash without your startup files for that reason.

### Plan mode turns answers into plans

In Claude Code, a session in plan mode keeps every subagent in plan mode. Investigators
then write a plan and stop at "ready to execute?" instead of replying with findings.
Start crew sessions in normal mode (Shift+Tab switches). In herdr mode the boss starts
Claude helpers with `--permission-mode default` for the same reason.

### Folder trust prompts

Claude Code and Copilot CLI ask whether you trust a folder the first time you start them
in it. The prompt is yours to answer: the boss never answers it for a helper. Choose
"remember" once per folder so later runs do not stop at it. In herdr mode a helper
stuck at a trust prompt shows up as `blocked`; the boss shows you its screen and waits.

### The investigator agent is missing

`scripts/preflight.sh --subagents --platform claude|copilot` exits 4 with
`investigator agent missing` when it cannot find the investigator definition. Run
`scripts/install-agents.sh` and start a new session. Where the preflight looks, in
order:

- Claude Code: `.claude/agents/k8s-crew-investigator.md` in every folder from the
  session's working folder up to the git root, then
  `~/.claude/agents/k8s-crew-investigator.md`, then an installed k8s-crew Claude Code
  plugin.
- Copilot CLI: `~/.copilot/agents/k8s-crew-investigator.agent.md` (or `.md`), then
  `.github/agents/` and `.claude/agents/` (each `.agent.md` or `.md`) in every folder
  from the working folder up to the git root.

Start the session in the project you installed into. The preflight prints which
install it found (`investigator: project`, `user` or `plugin`); a plugin install is
named `k8s-crew:k8s-crew-investigator`.

The boss never falls back to a general-purpose subagent: it would lose the tool limits.

### The viewer token expires

The token in the viewer kubeconfig is valid for 8 hours. After that every command fails
with `Unauthorized`, and the preflight exits 5 with `cannot check identity` (the same
happens when the cluster cannot be reached). The agents are told to stop on
`Unauthorized`, not to look for another identity. Run `scripts/viewer-kubeconfig.sh`
again in your own terminal, with your admin context, and start a new session with
`scripts/crew-start.sh`.

`viewer-kubeconfig.sh` copies the cluster entry of your current context with
`--flatten` (a CA file, also a relative one, is copied in), including
`tls-server-name` and `proxy-url`. It refuses an `https` server without a CA unless
your context sets `insecure-skip-tls-verify`. If the viewer kubeconfig still cannot
connect while your own does, compare the two cluster entries.

### The preflight is slow on a cluster with many namespaces

The preflight asks three `can-i` questions in every namespace, to find rights a
RoleBinding gives in one namespace. On a cluster with hundreds of namespaces this takes
a while, once per session.

## Copilot CLI

### Two subagents at a time on Copilot Free

Copilot Free runs at most 2 subagents in parallel (Pro 4, Business 16, Enterprise 32).
The crew starts 2 investigators by default in Copilot subagent mode, and lists any
further issues in the report as not investigated. Tell the boss your plan allows more
if it does; it never starts more than 4.

### Permission rules match leading words only

Checked with Copilot CLI 1.0.107:

- An allow rule cannot name a kubectl subcommand: `shell(kubectl get:*)` allows
  nothing.
- A deny rule can: `shell(kubectl delete:*)` works.
- A flag cannot be denied. `kubectl -n my-namespace delete ...` starts with `kubectl -n`,
  so no `kubectl delete` rule matches it.

So `config/copilot-deny-tools.sh` is deny-only by default and Copilot asks you before
each other kubectl call. `--auto-allow` adds `shell(kubectl:*)`; then a flag before the
subcommand gets past the subcommand deny list, and the kubectl guard and the view-only
identity protect the cluster. That is why `--auto-allow` is refused unless the session
runs under `scripts/crew-start.sh`. Details in
[safety.md](safety.md#limits-of-the-command-rules).

### "blocked" for a few seconds at startup

When herdr starts a Copilot helper, herdr often reports it as blocked (`agent_not_ready`)
for a few seconds while Copilot loads. The boss waits 15 seconds for it to become idle
before it involves you. If it is still blocked after that, it is a real prompt: the boss
reads the screen and shows it to you.

### `agent_prompt_stalled` on fast answers

Copilot can answer a short prompt faster than herdr notices it working, and
`herdr agent prompt --wait` then returns `agent_prompt_stalled`. The answer is usually
already in the pane. Read the pane; never send the prompt again, or the helper does the
work twice. If it is still working, wait for it and read again.

### Skill and agent frontmatter

Copilot CLI is stricter than Claude Code about frontmatter:

- A skill needs `name`, and `argument-hint` must be a quoted string.
- An empty `skills:` key in an agent definition is read as null, and Copilot rejects the
  agent. The investigator has `skills: []`.

Keep both if you edit `SKILL.md` or the investigator.

## Commands

### Chained commands are denied

Agents like to chain commands: `kubectl get pods && echo done`, `kubectl logs my-pod
2>&1`, `kubectl get events | sed ...`. Permission rules are written for one plain
command, so in a non-interactive run (no one to approve a prompt) such a call is
denied, and the test kit's tier check fails the run.

The skill, the recipe and the investigator role tell every agent: one plain command per
call, no `&&`, `;` or `||`, no redirection, no variables or command substitution, no
`cd` or `echo`, and a pipe only into a short list of filters. When a call is denied
anyway, the agent retries once as a plain command, then stops and reports exactly which
command was denied.

## herdr mode

### Helper panes do not inherit `KUBECONFIG` or the guard

A new herdr pane starts from the herdr server's environment, not from the boss's shell.
A helper started there would use your default kubeconfig. The herdr runner runs
`scripts/crew-start.sh --viewer <path> shell` in each helper pane, then the preflight,
before it starts the helper. If you start a helper by hand, do the same.

### Prompts must not contain `$`, backticks or quotes

The boss sends each helper prompt through the shell in single quotes, on one line. A
single quote would end the string; a double quote, a backtick or a `$` can change it.
The runner tells the boss to write names and evidence without them. A line break can
submit the prompt early, so the prompt is one line.

## Test kit

### node-dns-cascade setup waits two minutes

`setup.sh` pins CoreDNS to the worker, removes the unpinned ReplicaSet and then waits
`CREW_PIN_SETTLE_SECONDS` (default 120) before `break.sh` may stop the kubelet. The pin
is meant as a standing weakness; set seconds before the fault, its `managedFields` time
made the crew read it as a co-cause. The API server stamps that time, so it cannot be
backdated; the wait only makes the gap minutes instead of seconds.

### healthy-noise must run within an hour of break.sh

The `healthy-noise` scenario depends on old Warning events from a pod that is healthy
now. The API server keeps events for 1 hour by default, so run the crew within that
hour after `break.sh`. After that the scenario no longer has its noise and the result
does not count.
