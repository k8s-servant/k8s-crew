# Subagent runner

The default mode: investigators run as subagents inside the user's own Claude Code or
GitHub Copilot CLI session. They use the `k8s-crew-investigator` agent definition, which
has read-only tools only (shell, read, search) and cannot edit files or start agents.

Investigators share the boss's process, shell and files, so they have the same
view-only kubeconfig the boss checked with `scripts/preflight.sh`. Nothing extra is
needed for their identity.

## Before you start

- **The agent definition must be installed.** `scripts/preflight.sh --subagents
  --platform claude` (or `--platform copilot`) checks it. If it is missing, tell the
  user to run `scripts/install-agents.sh` and stop. Never fall back to a general-purpose
  subagent: it would lose the tool limits.
- **Plan mode.** In Claude Code, a session in plan mode keeps every subagent in plan
  mode, so investigators would write plans instead of findings. If the session is in
  plan mode, ask the user to switch to normal mode (Shift+Tab) and run the crew again.
  Start crew sessions in normal mode.
- **Permission prompts** from investigators show up in the user's session. They are the
  user's to answer. Investigators cannot ask the user questions; if one needs something
  it cannot see, it says so in its reply.

## Claude Code

Start one investigator per issue with the Agent tool, `subagent_type:
"k8s-crew-investigator"`. Put all the Agent calls in **one message** so they run in
parallel, then wait for all of them. Each `prompt` is the investigator's task from
step 2 of the recipe: the issue, object and namespace, triage's evidence, the specialist
skill and its `SKILL.md` path if known, and "Run one plain read-only command per call
(no chaining, redirection, variables, cd or echo; pipe only into grep, egrep, head,
tail, sort, uniq, wc, cut, column, jq or yq). Reply in the shape from your instructions: Finding,
Evidence, Confidence, Proposed fixes."

Up to 3 investigators by default, 4 at most.

Docs: https://code.claude.com/docs/en/sub-agents.md

## Copilot CLI

Start one investigator per issue as the custom agent `k8s-crew-investigator` (the
`task` tool with that agent, or "use the k8s-crew-investigator agent to ..."). Start
them in parallel and wait for all of them. The task text is the same as for Claude
Code.

Up to 2 investigators by default: Copilot Free runs 2 subagents at a time (Pro 4,
Business 16, Enterprise 32). Use more only when the user says their plan allows it, and
never more than 4.

Copilot CLI applies the session's `--allow-tool` and `--deny-tool` rules to subagents
too. The user starts the session with `config/copilot-deny-tools.sh --run` (by its full
path, in place of `copilot`; any further arguments go to `copilot`). It denies every
kubectl command that is not read-only, and Secret reads, and allows nothing: Copilot
asks the user before each other kubectl call, and those prompts are the user's to
answer. Copilot rules match only a command's leading words: an allow rule cannot name
a subcommand, and a flag written before the subcommand (`-n my-namespace`,
`--context` or `--kubeconfig` before `delete`) is not matched by any deny rule.

`config/copilot-deny-tools.sh --auto-allow --run` also allows every kubectl call, so
investigators run without prompts. Then a flag before the subcommand gets past the
deny list and **only the view-only identity protects the cluster**. Use `--auto-allow`
only with the crew viewer kubeconfig.

Docs: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/create-custom-agents-for-cli

## When an investigator fails

- **No reply, or an error:** report the issue with triage's evidence only, mark it
  `not sure`, and say under `## Helper details` that the investigator did not finish.
  Do not start it again without asking the user.
- **A reply in another shape:** use what is there, say so under `## Helper details`.
