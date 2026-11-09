# herdr runner

Investigators run as separate agents in visible [herdr](https://herdr.dev) panes next
to the boss. Use this mode when the boss runs inside herdr and the user asked for it, or
asked for helpers from more than one vendor (for example one Claude and one Copilot).
The recipe, the investigator instructions, the report and the approval rules are the
same as in subagent mode.

In the commands below, `<skill-dir>` is the full path of the k8s-crew skill folder (the
one with `SKILL.md`, `scripts/` and `roles/`), `<pane>` is a pane ID and `<name>` a
helper name. Use full paths: helper panes may start in another folder.

## 1. Check you are inside herdr

```bash
test "${HERDR_ENV:-}" = 1
```

If it fails, use subagent mode instead and tell the user why.

## 2. Plan the helpers

- **Count:** one helper per issue, up to 3 by default, 4 at most.
- **Kinds:** what the user asked for (`claude`, `copilot`). Default when not given: all
  `claude`, or one `copilot` and the rest `claude` when the user asked for mixed
  vendors.
- **Names:** `crew-<kind>`, with `-2`, `-3` for duplicates (`crew-claude`,
  `crew-claude-2`, `crew-copilot`). Check `herdr agent list` first and pick names that
  are not taken. Do not reuse helpers from an earlier run: start fresh ones, so each has
  the viewer identity set by step 4. Never prompt an agent you did not start.

## 3. Open the panes

Keep the user in their pane (`--no-focus`) and in the boss's folder. Build one helper
column to the right:

```bash
herdr pane split --current --direction right --cwd "$PWD" --no-focus
herdr pane split --pane <previous-helper-pane> --direction down --cwd "$PWD" --no-focus
```

The first command opens the first helper's pane; run the second once for each further
helper, splitting the previous helper's pane. Read each new pane ID from
`.result.pane.pane_id` in the JSON reply. If the boss pane is narrow (under about 120
columns in `herdr pane layout --pane "$HERDR_PANE_ID"`), split the first helper down
instead and the rest to the right.

## 4. Give every pane the viewer identity

A new pane starts from the herdr server's environment, not from the boss's shell, so it
does **not** have the boss's `KUBECONFIG`. Set it in every helper pane before starting
the agent, and check it with the preflight script.

Find the boss's kubeconfig path:

```bash
printenv KUBECONFIG
```

If it prints nothing, the boss uses the default file; use the full path of
`~/.kube/config`. Then, for each helper pane:

```bash
herdr pane run <pane> "export KUBECONFIG='<boss-kubeconfig-path>' && <skill-dir>/scripts/preflight.sh"
herdr pane wait-output <pane> --match "viewer ok" --timeout 30000
```

Start an agent in the pane only after `viewer ok` appears. If it does not, read the pane
with `herdr pane read <pane>`, do not start a helper there, and tell the user what the
preflight said.

## 5. Start the helpers

Start them in parallel and wait for all:

```bash
herdr agent start crew-claude --kind claude --pane <pane> --timeout 60000 -- --permission-mode default &
herdr agent start crew-copilot --kind copilot --pane <pane> --timeout 60000 &
wait
```

- **Claude helpers** start with `--permission-mode default`. If the user's default is
  plan mode, a helper would write a plan and stop at "ready to execute?" instead of
  replying.
- **Copilot helpers** should get the deny rules: add the flags that
  `<skill-dir>/config/copilot-deny-tools.sh` prints after the `--`.

If a start returns `agent_not_ready` (blocked during startup), it may only be loading:
Copilot often reports this for a few seconds while it starts. Give it a 15-second grace
wait before involving the user:

```bash
herdr agent wait <name> --until idle --timeout 15000
```

If that returns `idle`, carry on. If it times out or the helper is still `blocked`, read
its screen with `herdr agent read <name> --source visible` and tell the user what it is
asking. Folder trust and permission prompts are the user's decision: never answer them
yourself. Carry on with the helpers that did start, and pick the blocked one up when the
user says it is sorted.

## 6. Hand out the tasks

herdr helpers have no agent definition and no tool limits, so the prompt is their only
instruction. It carries the hard rules and the reply shape inline, and points to the
full role for the rest. Send it as **one line** (a line break can submit early in an
agent's terminal), with the placeholders filled in:

```text
You are a read-only k8s-crew investigator. Your kubeconfig is <boss-kubeconfig-path>; it is already set and checked in this pane. Hard rules: run only read-only (run-freely) commands; run one plain command per call: no &&, ; or ||, no redirection such as 2>&1, no $VAR or $(...), no cd and no echo, and a pipe only into grep, egrep, head, tail, sort, uniq, wc, cut, column, jq or yq; never run a command under an "Ask first" or a "Proposed fix" line, or any other command that changes the cluster; never read Secrets; do not change files. Use the skill <specialist-skill> (its SKILL.md is at <skill-path>). Your task: <issue, object and namespace, triage's evidence>. Your full instructions are in <skill-dir>/roles/investigator.md: read that file first, and if you cannot read it, say so in your reply and keep to these rules. Reply with exactly these sections, in this order: ### Finding, ### Evidence, ### Confidence (confirmed | likely | not sure), ### Proposed fixes (each fix with its command and an "# Undo:" line).
```

Send all prompts in parallel with a generous timeout:

```bash
herdr agent prompt crew-claude "<prompt>" --wait --timeout 600000 &
herdr agent prompt crew-copilot "<prompt>" --wait --timeout 600000 &
wait
```

Handle each result:

- **`idle` or `done`:** finished; read it (step 7).
- **`agent_prompt_stalled`:** herdr did not see the helper start working. Copilot often
  answers too fast for herdr to notice. **Never send the prompt again.** Read the pane:
  if the answer is there, use it; if the helper is still working, run
  `herdr agent wait <name> --timeout 600000` and read again.
- **`blocked`:** the helper wants approval or has a question. Read its screen, show the
  user what it asks, and wait for their decision. Never approve or answer for the user.
- **`timeout`:** read what is there and report it as unfinished. Do not resend.

## 7. Read the answers

```bash
herdr agent read <name> --source recent-unwrapped --lines 200
```

Take the helper's reply after its prompt line: the `### Finding`, `### Evidence`,
`### Confidence` and `### Proposed fixes` sections. If the reply is longer than the
lines you read, read again with more lines.

## 8. After the report

The helper panes stay open. Tell the user they can ask a helper a follow-up question or
ask you to close the panes. Close only panes you opened, and only when asked:

```bash
herdr pane close <pane>
```
