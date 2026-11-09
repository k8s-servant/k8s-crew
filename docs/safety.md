# Safety model

k8s-crew is built so that a crew run cannot change your cluster. The crew looks; you
change. This page explains how that is enforced, what you have to set up, and where the
limits are.

## The short version

- Start every crew session with `<skill-dir>/scripts/crew-start.sh claude|copilot`.
  Setting `KUBECONFIG` to the viewer file is not enough: without the launcher, your
  admin kubeconfig (`~/.kube/config`) is still reachable from the session with
  `kubectl --kubeconfig` or `--context`.
- The launcher puts a kubectl guard first on `PATH` that refuses every kubeconfig but
  the viewer one and every flag that picks another kubeconfig, context, cluster or
  identity, and starts the agent with the crew's deny rules.
- The crew prints every fix with an `# Undo:` line. You run the fixes you agree with, in
  your own terminal, with your own access.
- The Kubernetes RBAC of the viewer identity refuses writes. It protects the cluster
  only while the session cannot reach other credentials, so keep your admin kubeconfig
  out of the session's reach where you can (see [Residual risk](#residual-risk)).

## Why the whole session is view-only

In subagent mode the helpers (investigators) run inside the boss's own Claude Code or
Copilot CLI session. They share its process, its shell and its files. Anything the boss
can reach, the helpers can reach too: if the boss's shell held an admin kubeconfig, a
helper could use it, whatever its instructions say.

So the crew session gets only the view-only identity, in both modes. Then RBAC stops a
write from any agent in the session, not only from the boss.

"Only the view-only identity" means more than `KUBECONFIG`. Your admin kubeconfig stays
on disk, and a cloud CLI login can mint a new one. `scripts/crew-start.sh` holds the
session to the viewer:

- It installs `scripts/kubectl-guard` as `kubectl` in a private temp folder first on
  `PATH`. The guard runs the real kubectl only when `KUBECONFIG` is exactly the viewer
  file (not a list), and refuses `--kubeconfig`, `--context`, `--cluster`, `--server`
  and `-s` (also attached, like `-shttps://...`), `--token`, `--user`, `--username`,
  `--password`, `--as`, `--as-group`, `--as-uid`, the client certificate and key flags
  and `--kuberc`, wherever they appear. It exits 126 with a message that tells the agent
  to stop and tell you.
- It exports `PATH`, `KUBECONFIG` and `K8S_CREW_GUARD`. The preflight refuses to start
  the crew unless the guard is active.
- It starts the agent with the crew's deny rules (see [Five layers](#five-layers)),
  passed on the command line; your own settings files are not changed.

In herdr mode each helper is its own agent in its own pane. A new herdr pane does not
inherit the boss's shell environment, so the boss runs
`scripts/crew-start.sh --viewer <path> shell` in every helper pane (a bash with the
guard and the viewer `KUBECONFIG`), runs the preflight there, and only then starts the
helper, Claude helpers with the same deny settings.

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

The script reads your current context's cluster entry with
`kubectl config view --raw --minify --flatten`, so a CA given as a file (also a
relative path) is copied in, and it keeps `tls-server-name` and `proxy-url`. It refuses
an `https` server with no CA, unless your context sets `insecure-skip-tls-verify`, which
it then keeps and warns about. It checks this before it changes anything in the
cluster.

Then start the crew session with it:

```bash
<skill-dir>/scripts/crew-start.sh claude                  # Claude Code
<skill-dir>/scripts/crew-start.sh copilot                 # Copilot CLI
<skill-dir>/scripts/crew-start.sh --viewer /path/to/viewer.kubeconfig claude
```

When the token expires, run the script again. To remove the identity from the cluster,
with your admin access:

```bash
kubectl delete -f <skill-dir>/rbac/crew-viewer.yaml
rm ~/.kube/k8s-crew-viewer
```

## The preflight refuses a writable identity

Before the boss runs anything against the cluster it runs `scripts/preflight.sh`. It
fails closed: whatever it cannot confirm blocks the crew.

1. It checks the kubectl guard is active (`K8S_CREW_GUARD` is set and `kubectl` on
   `PATH` is the guard). If not: exit 6, `kubectl guard not active`.
2. It asks the API server, with `kubectl auth can-i`, whether the identity can create
   Deployments, delete pods, patch nodes or read Secrets across the cluster, and then
   whether it can create Deployments, delete pods or read Secrets in each namespace it
   can list. The second round catches rights a RoleBinding gives in one namespace,
   which the cluster-wide questions do not see. It costs three API calls per namespace,
   once per session.
3. A denial is `no`, or `no - <reason>` when the authorizer gives one (webhook
   authorizers such as AKS Azure RBAC do). Any other answer: exit 3, `NOT view-only`.
4. When kubectl prints no answer at all (an expired token, an unreachable cluster, the
   guard refused the call): exit 5, `cannot check identity`, with kubectl's first error
   line. The boss then tells you the check failed, not that the identity can write.

## How fixes are handed over

The crew never runs a fix, even one marked "Ask first", and even when you say yes. The
report lists the fixes in order, each as a ready-to-run command with an `# Undo:` line
that reverses it. Fixes that are hard to undo are marked as needing extra review.

You read the report, decide, and run each fix in your own terminal with your own
access. If you ask the crew to apply a fix, it tells you the session is view-only by
design and points you to the command. The crew does not ask you for more access.

## Five layers

The guard and the RBAC are the locks. The others make it less likely that an agent ever
reaches them.

1. Instructions. The investigator role (`roles/investigator.md`) says: investigate
   only, run only read-only commands, one plain command per call, never run a command
   under an "Ask first" or a "Proposed fix" line, never read Secrets, never change
   files. The boss follows the same rules and is the only one that proposes fixes.
2. Tool limits. In subagent mode the investigator agent definition
   (`agents/k8s-crew-investigator.md`) has only shell, read and search tools. It cannot
   edit or write files and cannot start other agents. herdr helpers have no agent
   definition, so the hard rules are written into their prompt instead.
3. Command rules, which `scripts/crew-start.sh` passes to the agent. Both deny the same
   kubectl commands: every one that is not read-only, and Secret reads.
   - Claude Code: `config/claude-settings.example.json`, a `permissions.deny` list,
     passed with `claude --settings`. It also denies the identity flags anywhere in a
     kubectl command, kubectl by its full path, `KUBECONFIG=` and `PATH=` overrides,
     shell commands that name a `.kube` folder, and `Read` of `~/.kube/**`, the agents'
     settings, credential and session files, and the `gh`, `az`, `aws` and `gcloud`
     logins. Skill, agent and plugin folders under `~/.claude` stay readable: the crew
     reads its recipe there.
   - Copilot CLI: `config/copilot-deny-tools.sh --run` starts `copilot` with a
     `--deny-tool` rule for every kubectl command that is not read-only, Secret reads,
     the identity flags when they come first, and reads of the same private files.

   Both vendors match commands as text, and both warn that this is fragile. See
   [Limits of the command rules](#limits-of-the-command-rules).
4. The kubectl guard (`scripts/kubectl-guard`), described in
   [Why the whole session is view-only](#why-the-whole-session-is-view-only). It checks
   every kubectl call at run time, whatever form the command has.
5. RBAC. The viewer identity can read and nothing else. Whatever an agent types through
   the guard, the API server refuses a write.

## The RBAC

`rbac/crew-viewer.yaml` binds the ServiceAccount to the built-in `view` ClusterRole,
plus a `crew-viewer-extra` ClusterRole with `get`, `list` and `watch` on what `view`
leaves out but the k8s-skills skills read: nodes, PersistentVolumes, StorageClasses and
the other storage objects, admission webhooks and policies, RBAC objects, APIServices,
CRDs, API Priority and Fairness, and the custom resources of Argo CD, Gatekeeper,
cert-manager ClusterIssuers, the Prometheus Operator, Cilium, Istio, the Gateway API,
Envoy Gateway, Velero and CloudNativePG.

It is a trimmed copy of the identity the k8s-skills test kit uses. Left out on purpose:

- Secrets. `view` does not grant them, and the extra role never names them. No agent
  in the session can read a Secret with the viewer identity.
- `services/proxy`. The k8s-skills kit grants it for the Prometheus, Alertmanager
  and Envoy admin APIs. RBAC cannot limit the path behind the proxy, and Envoy's admin
  interface can show its full configuration and certificates. The triage scenarios do
  not need it.
- ClusterExternalSecrets. They describe how Secrets are made and hold no Secret
  data, but the test for this file refuses any resource named like a Secret, and the
  triage scenarios do not need them. This may come back with a narrower test.
- Velero DownloadRequests. Their status holds a signed URL to a backup's files.

Kept, with a cost: `monitoring.coreos.com/*` includes AlertmanagerConfig, whose plain
`url` fields can carry webhook tokens.

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
- `--auto-allow` (`crew-start.sh --auto-allow copilot`) also allows
  `shell(kubectl:*)`, so kubectl calls run without asking. Then a flag before the
  subcommand gets past the subcommand deny list, and the guard and the viewer identity
  protect the cluster. It is acceptable only under the launcher: `copilot-deny-tools.sh`
  refuses `--auto-allow` unless the guard is active. `crew-start.sh --auto-allow claude`
  allows the read-only kubectl commands, the pipe filters and the preflight in the same
  way.
- Claude Code permission rules also match command text; a command written in an
  unusual form can slip past them.
- Plugin agents ignore `permissionMode`. When the investigator comes from the
  Claude Code plugin, Claude Code ignores any `permissionMode` in its definition. The
  deny rules in `config/` and the session's own permission settings still apply, so set
  them up for plugin installs too.

## Residual risk

The guard is a net, not a sandbox:

- A program that calls a kubectl binary by its full path (`/usr/local/bin/kubectl`)
  does not pass through the guard. Claude Code's rules deny that form; Copilot's rules
  cannot match it. Other tools that talk to the API server (`curl` with a token, a
  script) skip it too.
- Then only the RBAC of whatever identity the agent finds protects the cluster. The
  viewer's RBAC holds only if the admin kubeconfig and other credentials are not
  readable from the session. The read denies cover the usual places, not every file.
- So where you can, keep the admin kubeconfig out of the session's reach: run crew
  sessions as a separate OS user, or in a container or VM that has only the viewer
  kubeconfig, and keep cloud CLI logins out of it.

The test kit's hard check fails any run whose transcript holds a command that is not
an allow-listed cluster command or one of the crew's own local commands, so such an
attempt does not pass a release check unnoticed.

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
are not a guarantee. The guard and the viewer identity are, as far as the session
cannot reach other credentials. Start crew sessions only with `scripts/crew-start.sh`,
and do not start one with any other kubeconfig.
