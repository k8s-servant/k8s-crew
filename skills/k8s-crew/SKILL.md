---
name: k8s-crew
description: >-
  Use when something is wrong in a Kubernetes cluster and the cause could be in several
  places at once (nodes, workloads, DNS, networking, storage, add-ons), or when the user
  asks for a crew, parallel triage, or several agents to look at the cluster. Sweeps the
  cluster with k8s-triage, gives each top issue to a read-only investigator agent
  (subagents, or herdr panes), checks and links their findings, and writes one report:
  root cause, knock-on effects, separate issues, and fixes for the user to run. Never
  changes the cluster.
license: Apache-2.0
argument-hint: "[what is wrong], e.g. users say the app is down"
---

# k8s-crew

You are the boss of a small crew. You sweep the cluster, hand each real problem to one
read-only investigator, check and link what they find, and write one short report. The
investigators look; you coordinate and conclude. **The crew never runs a fix**: every
change is handed to the user, ready to run in their own terminal, with its undo.

Every path below (`scripts/`, `recipes/`, `roles/`, `runners/`, `config/`, `rbac/`) is
relative to the folder this `SKILL.md` is in, written `<skill-dir>` in commands. Run a
script by its full path (`<skill-dir>` written out in full), from the session's own
working folder: do not `cd` first. The preflight looks for a project-level
investigator from the working folder up to the git root.

## Your own commands

You follow the same rule as the investigators: **one plain command per call**. Each
shell call is one command written out in full: a script by its full path with its
flags, or one read-only kubectl command (pipes only into the filters the recipe lists).
No `&&`, `;` or `||`, no redirection, no shell variables or command substitution, no
`cd` and no `echo`. The session may run without anyone to approve a prompt, and there a
compound command is refused.

If a command is denied by the permission rules, retry it once as a plain command (split
or simplified as above). If that is denied too, stop and tell the user exactly which
command was denied and what the denial said. Never end the run without saying why.

Use only the session's viewer identity. Never pass `--kubeconfig`, `--context`,
`--cluster`, `--server` or `-s`, `--user`, `--token`, `--as` or any other identity
flag, never set `KUBECONFIG`, never call kubectl by its full path, and never read
kubeconfig files. If kubectl answers `Unauthorized` or `You must be logged in`, or the
kubectl guard refuses a call, stop: do not try another identity. Tell the user the
viewer token may have expired (it lasts 8 hours), to rerun
`scripts/viewer-kubeconfig.sh` in their own terminal and start a new session with
`scripts/crew-start.sh`.

## 1. Pick the mode

- **herdr mode** when `HERDR_ENV` is `1` and either the user asked for herdr (panes,
  "next to me") or asked for helpers from more than one vendor. Investigators are
  started as `runners/herdr.md` says.
- **Subagent mode** otherwise. Investigators are started as `runners/subagents.md`
  says.

If the user asked for herdr but `HERDR_ENV` is not `1`, use subagent mode and say why.
Decide the mode first, without running anything: the identity check in step 2 depends
on it. Do not start investigators until step 4.

## 2. Check the identity

The whole crew session must have only the view-only identity. The user starts it with
`scripts/crew-start.sh`, which puts the kubectl guard first on `PATH` and points
`KUBECONFIG` at the viewer kubeconfig; without it, any other kubeconfig on the machine
is reachable. Check it before you run anything against the cluster. In subagent mode,
pass the platform you run on:

```bash
<skill-dir>/scripts/preflight.sh --subagents --platform claude
<skill-dir>/scripts/preflight.sh --subagents --platform copilot
```

Run the first line in Claude Code, the second in GitHub Copilot CLI. In herdr mode, run
`<skill-dir>/scripts/preflight.sh` with no arguments: herdr helpers do not use the
agent definition.
Run it as one plain command: the script's full path and its flags, nothing chained
before or after it, and no `echo` of the exit code. Read the exit code and the output
from the tool result. Then:

- **Exit 0, `viewer ok`:** carry on. In subagent mode the output also has a line
  `investigator: <where> <name> (<path>)`. Start investigators with that `<name>`:
  `k8s-crew:k8s-crew-investigator` when `<where>` is `plugin` (the Claude Code plugin),
  `k8s-crew-investigator` otherwise.
- **Exit 3, `NOT view-only`:** stop. Show the user the script's output. The current
  identity can change the cluster or read Secrets, so the crew will not start. Tell them
  to create the viewer kubeconfig with `scripts/viewer-kubeconfig.sh` (an admin runs it
  in their own terminal) and start a new session with `scripts/crew-start.sh`.
- **Exit 5, `cannot check identity`:** stop. Show the user the output. Do not say the
  identity can write: the check itself failed. Say the crew could not reach the
  cluster or the viewer token has expired (it lasts 8 hours), and tell them to rerun
  `scripts/viewer-kubeconfig.sh` in their own terminal and start a new session with
  `scripts/crew-start.sh`.
- **Exit 6, `kubectl guard not active`:** stop. The session was not started with
  `scripts/crew-start.sh`, so other kubeconfigs on the machine are reachable from it.
  Tell the user to start a new session with
  `<skill-dir>/scripts/crew-start.sh claude` (or `copilot`).
- **Exit 4, `investigator agent missing`:** stop. Tell the user to run
  `scripts/install-agents.sh` and start a new session. Never fall back to a
  general-purpose subagent.
- **Any other result:** stop and show the user the output.

## 3. Check k8s-skills is installed

The crew depends on the k8s-skills skills: `k8s-triage`, and the specialists triage
hands off to, at least `k8s-workload-troubleshooting`, `k8s-node-troubleshooting`,
`k8s-network-troubleshooting`, `k8s-coredns-troubleshooting`,
`k8s-storage-troubleshooting` and `k8s-api-troubleshooting`. Check they are in your
list of available skills.

If `k8s-triage` is missing, stop and tell the user exactly what to install:
`npx skills add k8s-servant/k8s-skills` (or the k8s-skills Claude plugin), then start a
new session. If only some specialists are missing, carry on, and name the missing ones
in the report wherever an issue needed one.

## 4. Run the triage recipe

Follow `recipes/triage.md` from step 1 to step 6: sweep with `k8s-triage`, split the top
issues between investigators (default 3, at most 4; 2 in Copilot CLI subagent mode),
let them investigate, correlate and re-check, report in the fixed shape, and hand over
the fixes. Each investigator follows `roles/investigator.md`. The rules that matter
most:

- Investigator tasks are scoped to each issue's evidence: no speculative weaknesses.
- The root cause is what broke things now; standing settings that only made it worse
  are separate issues.
- `confirmed` only with a command result shown.
- A managedFields or creation time does not prove a change:
  a timestamp alone is not a recent change.
- The report gives fixes for the cause and not its knock-on effects.

If the user gave no problem description, start the sweep anyway: triage is built for
"something is wrong, I do not know where".

## 5. Never run a fix

- Do not run any command under an "Ask first" or a "Proposed fix" line, even if the
  user says yes. Print it for the user, with its `# Undo:` line.
- Do not run any other command that changes the cluster, and never read Secrets.
- Do not use any identity but the session's viewer kubeconfig (see "Your own
  commands").
- Do not ask the user for more access, and do not answer trust or permission prompts
  for them.
- If the user asks the crew to apply a fix, say the crew session is view-only by design
  and point them to the command in the report.

`scripts/crew-start.sh` starts the session with the guard and the crew's command
rules: `config/claude-settings.example.json` for Claude Code, `config/copilot-deny-tools.sh`
for Copilot CLI. The rules deny kubectl writes, Secret reads, identity flags and
reading kubeconfig files; they cannot match every form of a command (Copilot matches
only a command's leading words). The guard refuses any other kubeconfig or identity
flag at run time, and the view-only RBAC refuses writes. `--auto-allow` (kubectl runs
without asking) is only offered through `scripts/crew-start.sh`.
