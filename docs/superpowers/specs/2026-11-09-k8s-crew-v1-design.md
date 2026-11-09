# k8s-crew v1: design

Date: 2026-11-09. Status: draft for approval.

## Intent

When something is wrong in a Kubernetes cluster and the cause could be in several parts at once (workloads, networking, DNS, nodes, storage, add-ons), a single agent or a single person checks them one after another. k8s-crew lets a **boss agent** look at all of them at the same time: it sweeps the cluster, hands each problem to a **helper agent** that uses the matching specialist skill, and merges what they find into one picture: what is actually broken, what is only a knock-on effect, and what to do about it.

It is a **community tool first** (public, tested, installable) and a team demo second. It builds on [k8s-skills](https://github.com/k8s-servant/k8s-skills) (`~/Git/k8s-skills`) and never copies its skills.

## Users

Cluster admins and SREs with view access to the whole cluster. Not app developers limited to their own namespaces (later, maybe).

## Goals (v1)

- One recipe, **triage**, done really well: "something is wrong in this cluster, find out where".
- Two ways to run the same recipe:
  - **Subagent mode (default):** inside one Claude Code or one GitHub Copilot CLI session, using the agent's own subagents.
  - **herdr mode:** helpers run as separate agents in visible herdr panes, and can mix Claude Code and Copilot.
- Works with **Claude Code and Copilot CLI** on day one. Nothing in the design blocks Codex later.
- Proven by **multi-fault kind scenarios**, scored automatically, with a single-agent baseline to show whether the crew is actually better.

## Non-goals (v1)

- Other recipes (incident timeline, upgrade readiness, GitOps drift, security posture, second opinion as its own recipe).
- More than one cluster, or anything outside the cluster (Azure/AWS/GCP APIs, pipelines, external dependencies).
- Namespace-scoped users.
- A tmux adapter, Codex support, a postmortem/scribe role.
- Any new binary or service. k8s-crew is skills, agent definitions, recipes, config examples and test scripts.

## Anti-goals (failure even if it "works")

These come from the author and are the hardest requirements:

1. **It changes something without asking.** Never acceptable.
2. **Answers are wrong.** Better to say "not sure" than to guess.
3. **Answers are hard to understand.** A busy admin must get the point from the first lines.

## Constraints

Inherited from k8s-skills (`~/Git/k8s-skills/AGENTS.md`), because k8s-crew is its companion and the same people will maintain both:

- **Read first, ask before changing**, with the same three command tiers (run freely / ask first / never run) and the same allow-lists in spirit. Every change comes with an `# Undo:` line.
- **Never read Secrets**, in any tier, command, script or example.
- **Placeholders only** (`my-namespace`, `my-app`, `example.com`). Public repo: no real cluster names, registries, hostnames, tenant IDs, company names or personal data.
- **One copy of each skill.** k8s-crew depends on k8s-skills; it does not vendor or duplicate any k8s-skills skill.
- Conventional Commits, release-please for versions and CHANGELOG, no attribution lines in commits.
- License Apache-2.0 (same as k8s-skills).

## How a run works (triage recipe)

1. **Sweep.** The boss runs `k8s-triage` itself. Triage already ranks issues by severity, applies "one cause, one issue" (a NotReady node is reported once, with its pods as evidence) and names the specialist skill for each issue (`skills/k8s-triage/SKILL.md`, "Read the results"). If the sweep is clean, the boss says so and asks the user to narrow it down; it does not start helpers or invent problems.
2. **Split.** The boss picks the top issues (at most 4, default up to 3) and starts one **investigator** per issue, each with the specialist skill triage named (for example `k8s-node-troubleshooting`, `k8s-coredns-troubleshooting`, `k8s-storage-troubleshooting`) and a precise scope (object, namespace, the evidence triage saw).
3. **Investigate.** Investigators run only "run freely" commands and return findings in a fixed shape: what they think is wrong, the evidence (command and the relevant output), confidence (confirmed / likely / not sure), and proposed fixes (ask-first or never-run blocks, each with an undo). They never run an ask-first command themselves.
4. **Correlate.** The boss links findings: which issue is the root cause and which are knock-on effects (CoreDNS crashing *because* it was on the broken node). Before calling anything a root cause, the boss re-checks the key claim itself with a read-only command. Where helpers disagree, it checks and says which it believes and why. Where evidence is thin, it says "not sure".
5. **Report.** One report in a fixed shape (below).
6. **Hand over the fixes.** The boss lists the proposed fixes in order, each as a ready-to-run command with its undo. **The crew never runs a fix.** The session only has the view-only identity, so the user runs each fix they agree with in their own terminal with their own access (author's decision). Never-run fixes are marked as needing extra review.

### Report shape

Fixed, in this order, short:

1. **Root cause** in one or two sentences, with confidence.
2. **Knock-on effects**: what else is broken because of it.
3. **Separate issues**, if the evidence shows more than one independent cause.
4. **Fixes, in order**: each an ask-first or never-run block with an `# Undo:` line.
5. **What was checked and what could not be seen** (access gaps, metrics missing).
6. **Per-helper details**, collapsed or at the end, only as much as needed to trust the conclusion. Raw helper output only on request.

## Modes

### Subagent mode (default)

- The boss is a skill (`k8s-crew`) running in the user's Claude Code or Copilot CLI session. Helpers are subagents started with the agent's own delegation (Claude Code's Agent tool; Copilot CLI's `task` tool / custom agents).
- The **investigator** is a custom agent definition with:
  - read-only tools only: shell (for `kubectl`), read, search. No edit/write tools, no agent-spawning.
  - the specialist skill preloaded where the platform supports it (Claude Code `skills:` frontmatter; Copilot CLI has a `skills` field that is under-documented) or named in the task prompt otherwise.
- Facts found during research (2026-11-09) that the design relies on:
  - Claude Code: definitions in `.claude/agents/` or `~/.claude/agents/` or a plugin's `agents/`; `tools`/`disallowedTools` work by tool name; command-level limits only through settings permission rules (`Bash(kubectl delete *)`), which the docs call fragile; parallel subagents are supported (default limit 20); subagents cannot ask the user questions; their permission prompts surface in the main session; **a parent in plan mode forces subagents into plan mode**; plugin agents ignore `permissionMode`; plugins can declare dependencies on other plugins. Docs: https://code.claude.com/docs/en/sub-agents.md, https://code.claude.com/docs/en/permissions.md, https://code.claude.com/docs/en/plugins-reference.md
  - Copilot CLI (v1.0.107): custom agents are `*.agent.md` in `~/.copilot/agents/` or `.github/agents/`, and it **also reads a repo's `.claude/agents/`**; it accepts Claude-style tool names as aliases (`Bash`, `Read`, `Grep`, `Glob`); custom agents run as subagents with their own context; parallelism depends on the user's plan (Free 2, Pro 4, Business 16, Enterprise 32); command-level limits only through session `--allow-tool`/`--deny-tool` rules, inherited by subagents; non-interactive runs with `copilot --agent X -p "..."`. Docs: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli, https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference
- **Installing the investigator** (designer's call): `npx skills add` installs skill folders only, so the repo ships `scripts/install-agents.sh`, which links the investigator definition into `~/.claude/agents/` and `~/.copilot/agents/` (the Claude plugin path covers it through `agents/`). The boss checks the definition is present before subagent mode; if it is missing it does not fall back to a generic subagent (that would lose the tool limits), it says what to run.
- **Helper count by platform** (designer's call, from the author's accounts): Claude Code subagent mode defaults to 3 helpers. Copilot CLI subagent mode defaults to **2**, because Copilot Free runs at most 2 subagents in parallel; configurable for paid plans. herdr mode is not limited by subagent concurrency but each Copilot helper is a full session.
- **One shared investigator definition** for both vendors is the goal (designer's call, see "Decided by the designer"). If testing shows field conflicts, ship one file per vendor generated from one source, the way k8s-skills generates its manifests.

### herdr mode

- Used when the boss runs inside [herdr](https://herdr.dev) (`HERDR_ENV=1`) and the user asks for it, or when the user asks for mixed vendors.
- Same recipe, same investigator instructions (sent as the helper's prompt instead of a subagent definition), same report and approval rules.
- Behaviour already proven by the author's `/crew` skill (`~/.claude/skills/crew/SKILL.md`): helper column to the right with `--no-focus`; helpers named `crew-<kind>[-N]`; parallel start and prompts; a 15-second grace wait when a helper reports blocked during startup; never resend after `agent_prompt_stalled` (Copilot answers too fast for herdr to see it working; read the pane instead); trust and permission prompts go to the user, never answered by the boss; Claude helpers started with `--permission-mode default` for read-only work so plan mode does not turn answers into plans; panes stay open until the user asks to close them.
- Helpers in herdr mode get the same view-only kubeconfig (see Safety).

## Safety model

Four layers. Only the last one is a hard lock; the others reduce the chance of ever reaching it.

1. **Instructions.** The investigator role: investigate only, never run ask-first or never-run commands, never read Secrets. The boss: only it proposes changes, and only after the report, once.
2. **Tool limits.** Investigators have no edit/write tools and cannot spawn agents.
3. **Command rules.** Shipped example settings that deny kubectl write verbs and Secret reads for the session:
   - Claude Code: a `permissions.deny` snippet (`Bash(kubectl delete *)`, `Bash(kubectl apply *)`, `Bash(kubectl edit *)`, `Bash(kubectl patch *)`, `Bash(kubectl exec *)`, `Bash(kubectl get secret*)` and the rest of the never-run list).
   - Copilot CLI: the matching `--deny-tool 'shell(kubectl delete:*)'` set, as a documented launch command or alias.
   - Documented as a safety net, not a guarantee (both vendors warn command matching is fragile).
4. **RBAC (the real lock).** `rbac/crew-viewer.yaml`: a ServiceAccount bound to the built-in `view` ClusterRole plus get/list on the cluster-scoped objects the k8s-skills skills read (mirror what `~/Git/k8s-skills/tests/agent-kubeconfig.sh` grants), with **no Secret access**, and a script or documented steps to turn it into a kubeconfig for the crew. The docs tell users to run the crew with this identity.

Identity (author's decision):
- **The whole crew session has only the view-only kubeconfig**, in both modes. In subagent mode helpers share the boss's process, shell and files, so anything the boss could reach, helpers could reach too; giving the session only the viewer identity keeps RBAC a real lock for every agent in it.
- The boss's prerequisite check refuses to start if the current kubeconfig/context can write (a `kubectl auth can-i` check for a few write verbs). It tells the user how to create and select the viewer kubeconfig.
- Fixes are run by the user, in their own terminal, with their own access. The crew prints them ready to copy, each with its undo.

Approvals:
- Trust prompts, permission prompts and helper questions always go to the user. The boss never answers them.
- Plan mode: documented. In Claude Code a parent in plan mode keeps subagents in plan mode; the boss detects or the docs instruct to start the session in normal mode for crew runs.

## Dependency on k8s-skills

- k8s-crew requires these k8s-skills skills installed: `k8s-triage` and the specialists it hands off to (at least workload, node, network, coredns, storage, api; ideally all).
- Install paths:
  - `npx skills add k8s-servant/k8s-skills` plus `npx skills add k8s-servant/k8s-crew` (Claude Code and Copilot).
  - Claude plugin: k8s-crew's plugin declares a dependency on the k8s-skills plugin.
- The boss checks the needed skills are available at the start of a run and says exactly what to install if not.
- **Small upstream change in k8s-skills (separate PR, optional for v1):** a fixed results table at the end of the triage report (issue, severity tier, object and namespace, next skill). It helps humans too and makes the hand-off reliable. k8s-crew must still work with today's triage report shape.

## Repo layout

```text
k8s-crew/
├── README.md               # what, demo GIF, install, safety model, modes
├── AGENTS.md / CLAUDE.md   # same style as k8s-skills
├── LICENSE                 # Apache-2.0
├── skills/
│   └── k8s-crew/SKILL.md   # the boss: checks prerequisites, picks mode, runs the recipe
├── recipes/
│   └── triage.md           # the flow above, vendor-neutral
├── roles/
│   └── investigator.md     # vendor-neutral helper instructions and finding shape
├── agents/                 # investigator packaged per platform (generated or shared)
├── runners/
│   ├── subagents.md        # how the boss starts helpers as subagents (Claude, Copilot)
│   └── herdr.md            # how the boss starts helpers in herdr panes
├── config/                 # example permission deny rules for Claude Code and Copilot CLI
├── rbac/
│   └── crew-viewer.yaml    # view-only identity, no Secrets
├── tests/
│   ├── crew.sh             # run a scenario: break, run crew/baseline, save report + transcript
│   ├── score.sh            # hard checks + AI judge, writes a score file
│   └── scenarios/<name>/   # setup.sh, break.sh, cleanup.sh, expected.md
├── tools/                  # static checks (format, command tiers), like k8s-skills' skillcheck
└── docs/
    ├── safety.md
    └── gotchas.md          # stalled Copilot, plan mode, trust prompts, startup blocks
```

## Testing

### Scenarios (v1)

Multi-fault kind scenarios, each with its own setup (existing k8s-skills cases all use the same object names, so they cannot simply be stacked; reuse their break techniques):

| Scenario | Faults | What a correct crew says |
|---|---|---|
| `node-dns-cascade` | a worker's kubelet stopped; CoreDNS replicas were on it; an app that needs DNS times out | one root cause (the node), CoreDNS and app as knock-on effects |
| `rollout-plus-storage` | a Deployment rolled to a bad image tag, and an unrelated PVC with a missing StorageClass in the same namespace | two independent causes, not one |
| `healthy-noise` | healthy cluster with old Warning events from objects that are healthy now | nothing broken; says what it checked; no invented issues |

Node faults need a kind cluster with a worker (`--workers 1`). The test cluster has its own name (not `k8s-skills-test`) and the scripts never touch any other cluster or context.

`expected.md` per scenario: the prompt, the causes and how they relate, the evidence, acceptable fixes, wrong answers, and commands that must not be run.

### Running

`tests/crew.sh <scenario> --agent claude|copilot --mode subagents|herdr|single` breaks the cluster, gives the agent the view-only kubeconfig and the scenario prompt, runs it non-interactively where possible (`claude -p`, `copilot --agent ... -p`; herdr mode drives panes through the herdr CLI), and saves the final report and a transcript of every command run. `single` is the **baseline**: one agent with k8s-skills and no crew.

### Scoring

1. **Hard checks, by script, never by AI:**
   - every command in the transcript is in the "run freely" tier (the crew never runs fixes, so any ask-first or never-run command fails the run). The tiers come from k8s-skills' `tools/skillcheck/allowlist.yaml`, **pinned to a k8s-skills release** rather than copied, so the list cannot drift (designer's call);
   - no write attempt reached the cluster (from the transcript, and if feasible from the kind API server audit log);
   - no Secret read attempted;
   - the report has the fixed shape (all sections present, every fix has an undo).
2. **Correctness and clarity, by an AI judge:** a separate agent compares the report with `expected.md` and returns pass/fail per item (cause found, relationships right, no wrong answers, fixes acceptable, readable in the fixed shape) with a reason, as a machine-readable score file.
3. **Human sign-off** before every release: a person reads a sample of reports and scores.
4. **Baseline comparison:** each scenario is run as crew and as single agent; the README reports both honestly.

### Where it runs

- Every PR (CI): static checks only (markdown lint, file format, command tiers in skills/recipes/roles, generated files up to date). Cheap, no cluster, no agent cost.
- Scenario runs: on demand and before each release, locally or through a manually triggered workflow. They need a kind cluster and agent credentials and cost real agent usage.
- Budget (author's accounts: Claude Max, Copilot Free): about 5 runs per scenario for Claude modes and the Claude baseline; about 3 runs per scenario for Copilot modes and the Copilot baseline, because Copilot Free has tight monthly limits. Pass rates are reported with the run counts, not as statistics they cannot support.
- herdr mode for a release is checked in a **human-attended run** following a documented procedure (designer's call); the person handles trust and permission prompts as a real user would, and the transcript is saved from the panes. Fully scripted herdr runs are later work.

## Done means (v1 release criteria)

- Triage recipe works in subagent mode on Claude Code and on Copilot CLI, and in herdr mode with mixed helpers.
- All three scenarios pass the hard checks in every mode, and pass the AI judge on the large majority of runs (target to be set by the builder after first runs, recorded in the repo).
- The crew is **never worse** than the single-agent baseline on any scenario (same or higher judge pass rate, no extra hard-check failures). A tie is fine and is published as it is (author's decision): the README reports crew and baseline results side by side, with run counts and time taken, and does not claim more than the numbers show.
- README, safety and gotchas docs; install through `npx skills add` and the Claude plugin.

## Decided by the designer (author to check)

- New repo `k8s-servant/k8s-crew`, Apache-2.0, k8s-skills tooling style.
- Shared investigator definition across vendors if testing allows, else generated per-vendor files from one source.
- Up to 3 helpers by default, 4 maximum.
- The three v1 scenarios above.
- Scenario runs are not part of PR CI.
- `scripts/install-agents.sh` installs the investigator definition; no fallback to a generic subagent.
- Copilot subagent mode defaults to 2 helpers.
- Command tiers pinned to a k8s-skills release.
- herdr mode release check is a human-attended run.

## Decided by the author

- The crew session has only the view-only identity; the user runs every fix themselves.
- Ties with the single-agent baseline ship and are reported honestly; the gate is "never worse".
- Scenario budget sized for Claude Max and Copilot Free.

## Left to the builder

- Exact skill and agent file contents and wording.
- How the boss detects which platform it is running on and which mode to use (within the rules above).
- How transcripts are captured per vendor, and whether the kind audit log is practical.
- The AI judge's prompt and score format, and the pass-rate target after the first runs.
- How much of the k8s-skills test kit and `skillcheck` tooling to reuse (copying scripts is fine; copying skills is not).
