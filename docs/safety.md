# Safety model

k8s-crew is built so that a crew run cannot change your cluster. The crew looks; you
change. This page explains how that is enforced, what you have to set up, and where the
limits are.

## The short version

- Start the crew session with a view-only kubeconfig and nothing else.
- The crew prints every fix with an `# Undo:` line. You run the fixes you agree with, in
  your own terminal, with your own access.
- The command rules in `config/` are a second line of defence. The Kubernetes RBAC of
  the viewer identity is the real lock.

## Why the whole session is view-only

In subagent mode the helpers (investigators) run inside the boss's own Claude Code or
Copilot CLI session. They share its process, its shell and its files. Anything the boss
can reach, the helpers can reach too: if the boss's shell held an admin kubeconfig, a
helper could use it, whatever its instructions say.

So the crew session gets only the view-only identity, in both modes. Then RBAC stops a
write from any agent in the session, not only from the boss.

In herdr mode each helper is its own agent in its own pane. A new herdr pane does not
inherit the boss's shell environment, so the boss sets `KUBECONFIG` to the viewer
kubeconfig in every helper pane and runs the preflight there before it starts the
helper.

## Create and select the viewer kubeconfig

This is the one step that uses your admin access. Run it yourself, in your own
terminal, outside any agent session, with your normal kubectl context pointing at the
cluster you want to triage:

```bash
<skill-dir>/scripts/viewer-kubeconfig.sh                       # writes ~/.kube/k8s-crew-viewer
<skill-dir>/scripts/viewer-kubeconfig.sh --out /path/to/viewer.kubeconfig
```

`<skill-dir>` is the folder the k8s-crew skill was installed into (the one with
`SKILL.md`). The script:

1. applies `rbac/crew-viewer.yaml`: a namespace `k8s-crew`, a ServiceAccount
   `crew-viewer`, and two ClusterRoleBindings (see [RBAC](#the-rbac)),
2. asks the API server for a token for that ServiceAccount, valid for 8 hours,
3. writes a kubeconfig that holds only that token, the cluster's address and its CA,
   with file mode 600. It never prints the token.

Then start the crew session with it:

```bash
export KUBECONFIG=~/.kube/k8s-crew-viewer
claude          # or: <skill-dir>/config/copilot-deny-tools.sh --run
```

When the token expires, run the script again. To remove the identity from the cluster,
with your admin access:

```bash
kubectl delete -f <skill-dir>/rbac/crew-viewer.yaml
rm ~/.kube/k8s-crew-viewer
```

## The preflight refuses a writable identity

Before the boss runs anything against the cluster it runs `scripts/preflight.sh`. The
script asks the API server, with `kubectl auth can-i`, whether the current identity can
create Deployments, delete pods, patch nodes, or read Secrets. If any answer is not a
plain `no` (including an error or no answer), the crew stops with `NOT view-only` and
tells you to create the viewer kubeconfig. It fails closed: an unreachable cluster
blocks the run too.

## How fixes are handed over

The crew never runs a fix, even one marked "Ask first", and even when you say yes. The
report lists the fixes in order, each as a ready-to-run command with an `# Undo:` line
that reverses it. Fixes that are hard to undo are marked as needing extra review.

You read the report, decide, and run each fix in your own terminal with your own
access. If you ask the crew to apply a fix, it tells you the session is view-only by
design and points you to the command. The crew does not ask you for more access.

## Four layers

Only the last layer is a hard lock. The others make it less likely that an agent ever
reaches it.

1. Instructions. The investigator role (`roles/investigator.md`) says: investigate
   only, run only read-only commands, one plain command per call, never run a command
   under an "Ask first" or a "Proposed fix" line, never read Secrets, never change
   files. The boss follows the same rules and is the only one that proposes fixes.
2. Tool limits. In subagent mode the investigator agent definition
   (`agents/k8s-crew-investigator.md`) has only shell, read and search tools. It cannot
   edit or write files and cannot start other agents. herdr helpers have no agent
   definition, so the hard rules are written into their prompt instead.
3. Command rules. Example rules that deny kubectl write commands and Secret reads:
   - Claude Code: `config/claude-settings.example.json`, a `permissions.deny` list.
     Merge it into your `~/.claude/settings.json` or a project's
     `.claude/settings.json`, or pass it with `claude --settings <file>`.
   - Copilot CLI: `config/copilot-deny-tools.sh --run` starts `copilot` with a
     `--deny-tool` rule for every kubectl command that is not read-only, and for Secret
     reads.

   Both vendors match commands as text, and both warn that this is fragile. See
   [Limits of the command rules](#limits-of-the-command-rules).
4. RBAC. The viewer identity can read and nothing else. Whatever an agent types, the
   API server refuses a write. This is the layer to rely on.

## The RBAC

`rbac/crew-viewer.yaml` binds the ServiceAccount to the built-in `view` ClusterRole,
plus a `crew-viewer-extra` ClusterRole with `get`, `list` and `watch` on what `view`
leaves out but the k8s-skills skills read: nodes, PersistentVolumes, StorageClasses and
the other storage objects, admission webhooks and policies, RBAC objects, APIServices,
CRDs, API Priority and Fairness, and the custom resources of Argo CD, Gatekeeper,
cert-manager ClusterIssuers, the Prometheus Operator, Cilium, Istio, the Gateway API,
Envoy Gateway, Velero and CloudNativePG.

It is a trimmed copy of the identity the k8s-skills test kit uses. Left out on purpose:

- Secrets. `view` does not grant them, and the extra role never names them. No
  agent in the session can read a Secret.
- `services/proxy`. The k8s-skills kit grants it for the Prometheus, Alertmanager
  and Envoy admin APIs. RBAC cannot limit the path behind the proxy, and Envoy's admin
  interface can show its full configuration and certificates. The triage scenarios do
  not need it.
- ClusterExternalSecrets. They describe how Secrets are made and hold no Secret
  data, but the test for this file refuses any resource named like a Secret, and the
  triage scenarios do not need them. This may come back with a narrower test.
- Velero DownloadRequests. Their status holds a signed URL to a backup's files.

The cost: the Prometheus, Envoy and External Secrets specialist skills see less under
the crew viewer than under the k8s-skills test identity. They say what they could not
see.

## Limits of the command rules

The command rules catch common mistakes. They are not a lock:

- Copilot CLI (checked with 1.0.107) matches a rule against the leading words of a
  command only. A deny rule can name a subcommand (`shell(kubectl delete:*)`), but an
  allow rule cannot (`shell(kubectl get:*)` allows nothing), and a flag written before
  the subcommand (`kubectl -n my-namespace delete ...`) is not matched by any deny rule.
  So `copilot-deny-tools.sh` is deny-only by default: Copilot asks you before each other
  kubectl call, and you see the command before it runs.
- `--auto-allow` (`copilot-deny-tools.sh --auto-allow --run`) also allows
  `shell(kubectl:*)`, so kubectl calls run without asking. Then a flag before the
  subcommand gets past the deny list, and only the view-only identity protects the
  cluster. Use it only with the crew viewer kubeconfig.
- Claude Code permission rules also match command text; a command written in an
  unusual form can slip past them.
- Plugin agents ignore `permissionMode`. When the investigator comes from the
  Claude Code plugin, Claude Code ignores any `permissionMode` in its definition. The
  deny rules in `config/` and the session's own permission settings still apply, so set
  them up for plugin installs too.

## Prompts and approvals

- Folder trust prompts, permission prompts and helper questions are yours to answer.
  The boss never answers them for you, in either mode.
- Investigators in subagent mode cannot ask you questions. Their permission prompts
  show up in your session.

## Plan mode

In Claude Code, a session in plan mode keeps every subagent in plan mode: investigators
would write plans instead of findings. Start crew sessions in normal mode. If you are in
plan mode, switch with Shift+Tab before you run `/k8s-crew`. In herdr mode the boss
starts Claude helpers with `--permission-mode default` for the same reason.

## Your agent, your decision

How you run your agent, and with which permissions, is your decision and your risk.
The crew is written and tested to stay read-only, but instructions and command rules
are not a guarantee. The viewer identity is. Do not start a crew session with any other
kubeconfig.
