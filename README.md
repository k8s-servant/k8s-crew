# k8s-crew

A Kubernetes triage crew for AI agents: one lead agent sweeps the cluster, hands each
problem to a read-only helper, and writes one report. It never changes the cluster.

When something is wrong in a cluster and the cause could be in several places at once
(workloads, networking, DNS, nodes, storage, add-ons), a single agent or a single person
checks them one after another. k8s-crew lets a boss agent look at all of them at the same
time: it sweeps the cluster with `k8s-triage`, hands each problem to a helper agent that
uses the matching specialist skill from
[k8s-skills](https://github.com/k8s-servant/k8s-skills), and merges what they find into
one picture: what is actually broken, what is only a knock-on effect, and what to do
about it. You run the fixes yourself.

k8s-crew works in Claude Code and GitHub Copilot CLI. It builds on k8s-skills and does
not copy its skills.

## What a run looks like

````text
> /k8s-crew users say my-app is timing out

The worker node my-node-2 stopped reporting. Both CoreDNS replicas ran on it, so the
cluster has no DNS, and my-app times out because it cannot resolve my-api.

## Root cause
my-node-2 is NotReady: its kubelet stopped posting status (confirmed).

## Knock-on effects
- CoreDNS in kube-system: both replicas are on my-node-2; kube-dns has no ready endpoints.
- my-app in my-namespace: lookups of my-api fail, so the pod is Running but not ready.

## Separate issues
None.

## Fixes
1. Bring the node back. This is a host action on my-node-2, not a cluster change.

   > Proposed fix: review before running. The agent does not run this.

   ```bash
   ssh my-node-2 sudo systemctl restart kubelet
   # Undo: none needed; a restart only brings the kubelet back to its configured state
   ```

2. To get DNS back before the node returns, let CoreDNS run on other nodes.

   > Ask first: changes the cluster. Run it yourself after review.

   ```bash
   kubectl -n kube-system patch deployment coredns --type json -p '[{"op":"remove","path":"/spec/template/spec/nodeSelector"}]'
   # Undo: kubectl -n kube-system patch deployment coredns --type merge -p '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.io/hostname":"my-node-2"}}}}}'
   ```

The crew did not run these. Run the ones you agree with in your own terminal.

## What was checked
...

## Helper details
...
````

Shortened, with placeholder names. The report always has these six sections in this
order. Every fix comes with a marker line and an `# Undo:` line, and the crew runs none
of them: "Ask first" marks a change you run after review, "Proposed fix" one that needs
extra review because it is destructive or hard to undo.

## Install

k8s-crew needs the k8s-skills skills (`k8s-triage` and the specialists it hands off
to). Install both with the [`skills` CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add k8s-servant/k8s-skills
npx skills add k8s-servant/k8s-crew
```

Add `-g` to install for your user instead of one project, and `-a claude-code` or
`-a github-copilot` to pick the agent.

Then, from the folder the CLI installed k8s-crew into (for example
`~/.claude/skills/k8s-crew` with `-g`, or `.claude/skills/k8s-crew` in a project):

```bash
scripts/install-agents.sh        # links the investigator into ~/.claude/agents and ~/.copilot/agents
scripts/viewer-kubeconfig.sh     # creates the view-only identity, writes ~/.kube/k8s-crew-viewer
```

`install-agents.sh` is needed because `npx skills add` installs skill folders only, and
subagent mode needs the investigator agent definition. Add `--claude` or `--copilot` to
link only one.

`viewer-kubeconfig.sh` is the one step that uses your admin access: it applies
`rbac/crew-viewer.yaml` with your current kubectl context and writes a kubeconfig that
holds only the viewer's token (valid for 8 hours). Run it yourself, outside any agent
session. See [docs/safety.md](docs/safety.md).

### Claude Code plugin

```text
/plugin marketplace add k8s-servant/k8s-skills
/plugin marketplace add k8s-servant/k8s-crew
/plugin install k8s-crew@k8s-crew
```

The plugin depends on the `k8s-skills` plugin and installs it too. It ships the
investigator agent as `k8s-crew:k8s-crew-investigator`, and the preflight finds it
there, so `install-agents.sh` is not needed for Claude Code. Create the viewer
kubeconfig as above, with `scripts/viewer-kubeconfig.sh` from the plugin's
`skills/k8s-crew` folder (under `~/.claude/plugins/cache/`).

## Run it

Start every crew session with the launcher, in normal mode (not plan mode):

```bash
<skill-dir>/scripts/crew-start.sh claude      # Claude Code
<skill-dir>/scripts/crew-start.sh copilot     # or Copilot CLI
```

`<skill-dir>` is the k8s-crew skill folder. Further arguments go to the agent;
`--viewer PATH` picks another viewer kubeconfig than `~/.kube/k8s-crew-viewer`. Then
ask: `/k8s-crew users say my-app is timing out`, or describe the problem in your own
words. With no description, the crew sweeps the whole cluster.

Why a launcher: `export KUBECONFIG=~/.kube/k8s-crew-viewer` alone does not take your
admin kubeconfig away. It is still on disk, and `kubectl --kubeconfig ~/.kube/config
...` or `--context <admin>` would use it from inside the session. `crew-start.sh` puts a
kubectl guard first on `PATH` that refuses any kubeconfig but the viewer one and any
flag that picks another kubeconfig, context, cluster or identity, and starts the agent
with the crew's deny rules (your own settings are not changed). Without it, the admin
kubeconfig is reachable.

The boss checks first. If the session was not started with the launcher, if the
identity can write or read Secrets (cluster-wide or in any namespace), or if the check
fails (an expired token, an unreachable cluster), it stops and tells you which, and
what to do.

`--auto-allow` (`crew-start.sh --auto-allow claude|copilot`) lets the read-only kubectl
commands run without a prompt. Use it only through the launcher: it relies on the guard
and the viewer identity, and `copilot-deny-tools.sh` refuses it without the guard.

## Two modes

- Subagent mode (default). The helpers are subagents inside your one Claude Code or
  Copilot CLI session, using the `k8s-crew-investigator` agent definition: shell, read
  and search tools only, no file edits, no starting other agents. Up to 3 helpers by
  default in Claude Code and 2 in Copilot CLI (Copilot Free runs 2 subagents at a
  time), 4 at most.
- herdr mode. When the boss runs inside [herdr](https://herdr.dev) and you ask for
  panes, or for helpers from more than one vendor, each helper runs as its own agent in
  a visible pane next to you, for example one Claude Code and one Copilot CLI helper.
  The boss gives every pane the viewer kubeconfig and checks it before it starts the
  helper. The panes stay open after the report, so you can ask a helper a follow-up.

The recipe, the helper instructions, the report and the safety rules are the same in
both modes.

## Safety

The crew session uses only the view-only kubeconfig, as long as you start it with
`scripts/crew-start.sh`. In subagent mode the helpers share the boss's shell, so
anything the boss can reach, they can too: holding the session to the viewer identity
keeps every agent in it read-only. The crew never runs a fix. It prints each fix ready
to copy, with its `# Undo:` line, and you run it in your own terminal with your own
access.

Five layers keep it that way: the instructions, the investigator's tool limits, the
command rules in `config/`, the kubectl guard, and the RBAC of the viewer identity. The
command rules cannot match every form of a command. The guard and the RBAC are the
locks, and the RBAC holds only while the session cannot reach other credentials: an
agent that runs a kubectl binary by its full path skips the guard (Claude Code denies
that form, Copilot cannot), and then uses whatever kubeconfig it can read. Keep your
admin kubeconfig out of the session's reach where you can, for example by running crew
sessions as a separate OS user or in a container that has only the viewer kubeconfig.
The viewer identity cannot read Secrets.

Details, including what the RBAC grants and leaves out and the limits of the Copilot
rules: [docs/safety.md](docs/safety.md). Things that tend to go wrong:
[docs/gotchas.md](docs/gotchas.md).

## Results

Each scenario breaks a kind cluster on purpose, then runs the crew and, as a baseline,
a single agent with k8s-skills and no crew. Every run is scored by script (only
read-only commands, no Secret reads, the report's shape) and by an AI judge against the
scenario's expected answer.

| Scenario | Agent | Mode | Runs | Hard-check passes | Judge passes | Median time |
|---|---|---|---|---|---|---|
| `node-dns-cascade` | | | | | | |
| `rollout-plus-storage` | | | | | | |
| `healthy-noise` | | | | | | |

The table is filled in before the first release, with crew and baseline side by side.

How runs are recorded: [docs/transcripts.md](docs/transcripts.md). The herdr mode
release check: [docs/herdr-release-check.md](docs/herdr-release-check.md).

## Limits

- One cluster. Nothing outside it: no cloud APIs, pipelines or external
  dependencies.
- For cluster admins and SREs with view access to the whole cluster. Not for users
  limited to their own namespaces.
- Triage only. One recipe: "something is wrong in this cluster, find out where".
- Agents: Claude Code and Copilot CLI, and herdr for the pane mode.

## Contributing

Setup, tests and the rules for this repository are in [AGENTS.md](AGENTS.md).

## License

[Apache-2.0](LICENSE)
