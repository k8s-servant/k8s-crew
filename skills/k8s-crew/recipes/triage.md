# Triage recipe

"Something is wrong in this cluster, find out where." The boss sweeps the cluster,
hands each real problem to one investigator, links what they find and writes one short
report. The crew reads; the user changes. This file is the same for every mode; how
investigators are started is in `runners/subagents.md` and `runners/herdr.md`.

Rules for the whole run:

- **The crew never runs a fix.** The session has only the view-only identity. Every fix
  is printed for the user to run in their own terminal, with their own access, each with
  an `# Undo:` line. This holds for fixes under an "Ask first" line too: in a crew run
  the boss does not run them, even if the user says yes; it hands them over.
- **Never read Secrets**, in any command, and never repeat credentials seen in output.
- **Trust prompts, permission prompts and investigator questions go to the user.** The
  boss never answers them.
- **"Not sure" is better than a guess.** A wrong answer is worse than an incomplete one.
- **One plain command per call**, for the boss and every investigator:
  - no `&&`, `;` or `||`, no redirection (`2>&1`, `>`), no `$VAR` or `$(...)`, no `cd`
    and no `echo`. Run scripts by their full path;
  - a pipe only into `grep`, `egrep`, `head`, `tail`, `sort`, `uniq`, `wc`, `cut`,
    `column` or `jq` (not `sed`, `awk`, `yq` or `xargs`);
  - prefer `-o name`, `-o wide` or `-o json | jq '<program>'` with the program in
    single quotes and no file arguments (no `import`, `include`, `env` or `$ENV`);
  - in jq, use only `-r`, `-c`, `-e`, `-s` or `--arg`, and no string interpolation
    (`\(...)`): build text with `+`, `join` or `@tsv` instead;
  - only these kubectl commands: `get`, `describe`, `logs`, `events`, `top`,
    `explain`, `api-resources`, `api-versions`, `version`, `cluster-info`,
    `auth can-i`, `auth whoami`, `rollout status` and `rollout history`. Use
    `kubectl auth whoami` to see the identity, not the kubeconfig context. When
    `kubectl top` fails, write "metrics not available" and go on.
- **Only the viewer identity.** Never pass `--kubeconfig`, `--context`, `--cluster`,
  `--server` or `-s`, `--user`, `--token`, `--as` or any other identity flag, never set
  `KUBECONFIG`, never call kubectl by its full path, and never read kubeconfig files.
  The session was started with the crew viewer kubeconfig and the kubectl guard
  refuses anything else.
- **Unauthorized, Forbidden everywhere, or an expired token: stop.** If kubectl
  answers `Unauthorized` or `You must be logged in`, or the kubectl guard refuses a
  call, do not look for another identity or kubeconfig. Stop and tell the user: the
  viewer token lasts 8 hours; they rerun `scripts/viewer-kubeconfig.sh` in their own
  terminal and start a new session with `scripts/crew-start.sh`. A single `Forbidden`
  is normal for a viewer: write down what could not be seen and go on.
- **A denied command is retried once, then reported.** If a permission rule denies a
  command, run it again once as a plain command. If it is still denied, the boss stops
  and tells the user which command was denied and why. A run never ends without a
  reply.

## 1. Sweep

Run the `k8s-triage` skill yourself, all of its Investigate steps, and read the results
as it says: rank by severity, apply "one cause, one issue" (a `NotReady` node is one
issue, with its pods as evidence), and note the next skill triage names for each issue.

**If the sweep is clean, stop here.** Start no investigators and do not invent issues.
Write the report (step 5) with "None found" under the issue sections, say what you
checked under `## What was checked`, and ask the user to narrow it down: which app,
namespace or URL, what exactly they saw, and since when.

## 2. Split

Pick the top issues from the ranked list and start one investigator per issue:

- **How many:** up to 3 by default, 4 at most. In Copilot CLI subagent mode, up to 2 by
  default (Copilot Free runs 2 subagents at a time); more only if the user says their
  plan allows it. Issues beyond the limit are listed in the report as not investigated.
- **One issue each.** Do not give an investigator two issues, and do not start two on
  the same issue.
- **The task** for each investigator names: the issue in one sentence, the object and
  namespace, the evidence triage saw (status, condition, event reason and message), the
  specialist skill triage named (for example `k8s-node-troubleshooting`,
  `k8s-coredns-troubleshooting`, `k8s-storage-troubleshooting`) and the path of its
  `SKILL.md` if you know it, and the reply shape from `roles/investigator.md`.

- **Scoped tasks.** Ask each investigator only about its issue and the evidence for
  it. Never ask it to note design weaknesses, risks or improvements: a weakness nobody
  saw break is not a finding.

If only one issue is found, one investigator is enough. If the specialist skill for an
issue is not installed, do not start an investigator for it: report the issue with
triage's evidence and first fix, and say which skill to install.

## 3. Investigate

Investigators follow `roles/investigator.md`: read-only commands only, the named skill,
and a reply with `### Finding`, `### Evidence`, `### Confidence` and
`### Proposed fixes`. While they work, do not start more investigators and do not
investigate their issues yourself.

If an investigator replies in another shape, take what you can from it and say so under
`## Helper details`. If it reports it ran a change, stop the run and tell the user
straight away, first line of your reply.

## 4. Correlate

Link the findings into one picture:

- **Root cause or knock-on effect.** For each finding, ask whether another finding
  explains it (CoreDNS crashing because its pods were on the broken node; an app timing
  out because DNS is down). Knock-on effects are listed under the root cause, not as
  separate issues.
- **Trigger, not precondition.** The root cause is the event that made things break
  now: the node that stopped, the bad rollout, the deleted object. A setting that has
  been there all along and only made the impact worse (all replicas pinned to one node,
  one replica, no PodDisruptionBudget) is a precondition, not a cause, even when it
  shows as a recent change in `managedFields`. Report it under Separate issues as
  a weakness to follow up, never as the root cause or part of it.
- **One issue, one section.** Each issue appears once: as the root cause, a knock-on
  effect or a separate issue. Do not list the root cause again elsewhere.
- **Separate issues** are causes that do not explain each other. Two independent
  problems are two root causes, not one.
- **Re-check before naming a root cause.** Run one read-only command yourself that shows
  the key claim (the node condition, the event, the missing object). If your check does
  not show it, lower the confidence and say why.
- **Disagreements.** When investigators disagree, check the disputed point yourself with
  a read-only command, say which one you believe and why.
- **Confirmed needs shown evidence.** Call something `confirmed` only when a command
  result in the report's evidence shows it; otherwise `likely` or `not sure`.
- **Timestamps are not history.** A `managedFields` time or a creation timestamp alone
  does not show that something changed recently or caused the fault. Say `not sure`
  about when it changed unless events or rollout history show it.
- **Thin evidence** gets `not sure`, with what would settle it. Never upgrade a
  `not sure` from an investigator to `confirmed` without your own evidence.

## 5. Report

One report, short, in this exact shape: these six headings, in this order, nothing else
at H2 level. A busy admin must get the point from the first lines.

````markdown
## Root cause

One or two sentences: what is broken and why, with confidence (confirmed, likely or
not sure). For a clean sweep: "None found."

## Knock-on effects

What else is broken because of the root cause, one line each with its evidence.
"None" if there are none.

## Separate issues

Other independent causes, each with its confidence and evidence. "None" if there are
none.

## Fixes

The fixes in the order to run them. For each: one sentence on what it changes, a
marker line, and a fenced bash block with the command and its "# Undo:" line. The
marker line is exactly one of:

> Ask first: changes the cluster. Run it yourself after review.

> Proposed fix: review before running. The agent does not run this.

**Fix the cause, not its effects.** Fixes target the root cause and genuinely separate
issues, never a knock-on effect: those recover when the cause is fixed (do not scale or
restart an app that only fails because of the root cause). A follow-up for a
precondition comes after the fix for the root cause.

Use Proposed fix for anything destructive or hard to undo, which needs extra review,
and wherever the specialist skill uses it. Do not copy the specialist skill's own Ask
first line: it says the agent runs the fix after approval, and in a crew run no agent
does. A host action (on a node, outside the cluster) also gets a fenced block, under
the Proposed fix line, with its "# Undo:" line. End with: "The crew did not run these.
Run the ones you agree with in your own terminal." For a clean sweep, the section is
exactly "No fixes needed." and nothing else.

## What was checked

What triage and the investigators looked at, and what could not be seen (Forbidden
access, metrics not available, issues beyond the helper limit).

## Helper details

One short entry per investigator: the issue it had, the skill it used, its finding and
confidence. Raw replies only if the user asks.
````

## 6. Hand over the fixes

The fixes in the report are the hand-over. Do not run them, do not offer to run them,
and do not ask the user to give the session more access. If the user asks the crew to
apply a fix, say that the crew session is view-only by design and that they can run the
command shown in their own terminal.
