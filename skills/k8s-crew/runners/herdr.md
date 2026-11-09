# herdr runner

Investigators run as separate agents in visible [herdr](https://herdr.dev) panes next
to the boss. Use this mode when the boss runs inside herdr and the user asked for it, or
asked for helpers from more than one vendor (for example one Claude and one Copilot).
The recipe, the investigator instructions, the report and the approval rules are the
same as in subagent mode.

In the commands below, `<skill-dir>` is the full path of the k8s-crew skill folder (the
one with `SKILL.md`, `scripts/` and `roles/`), `<pane>` is a pane ID and `<name>` a
helper name. Use full paths: helper panes may start in another folder.

Every command here is one plain command, as `SKILL.md` asks: no shell variables, no
chaining, no `&` or `wait`. Where a command needs a value from the environment, the
runner reads it first with `printenv` and you write the value out in full.

## 1. Check you are inside herdr

```bash
printenv HERDR_ENV
```

If it does not print `1`, use subagent mode instead and tell the user why.

## 2. Plan the helpers

- **Count:** one helper per issue, up to 3 by default, 4 at most.
- **Kinds:** what the user asked for (`claude`, `copilot`). Default when not given: all
  `claude`, or one `copilot` and the rest `claude` when the user asked for mixed
  vendors.
- **Names:** `crew-<kind>`, with `-2`, `-3` for duplicates (`crew-claude`,
  `crew-claude-2`, `crew-copilot`). Check `herdr agent list` first and pick names that
  are not taken. Do not reuse helpers from an earlier run: start fresh ones, so each has
  the guard and the viewer identity set by step 4. Never prompt an agent you did not
  start.

## 3. Open the panes

Keep the user in their pane (`--no-focus`) and in the boss's folder. Read the boss's
folder and pane ID:

```bash
printenv PWD
printenv HERDR_PANE_ID
```

Then build one helper column to the right, with the folder written out in full as
`<boss-folder>`:

```bash
herdr pane split --current --direction right --cwd <boss-folder> --no-focus
herdr pane split --pane <previous-helper-pane> --direction down --cwd <boss-folder> --no-focus
```

The first command opens the first helper's pane; run the second once for each further
helper, splitting the previous helper's pane. Read each new pane ID from
`.result.pane.pane_id` in the JSON reply. If the boss pane is narrow (under about 120
columns in `herdr pane layout --pane <boss-pane>`), split the first helper down instead
and the rest to the right.

## 4. Give every pane the guard and the viewer identity

A new pane starts from the herdr server's environment, not from the boss's shell, so it
has neither the kubectl guard nor the viewer `KUBECONFIG`. A helper started there would
reach your default kubeconfig. So every helper pane runs the crew's guarded shell from
`scripts/crew-start.sh` before any agent starts in it, and the preflight checks it.

Find the viewer kubeconfig the boss session was started with:

```bash
printenv KUBECONFIG
```

It prints one file path (`scripts/crew-start.sh` set it, and the boss's preflight
checked it). If it prints nothing or a list with `:`, stop: the boss session was not
started with `scripts/crew-start.sh`. Then, for each helper pane, with that path
written out as `<viewer-kubeconfig-path>`:

```bash
herdr pane run <pane> "<skill-dir>/scripts/crew-start.sh --viewer <viewer-kubeconfig-path> shell"
herdr pane run <pane> "<skill-dir>/scripts/preflight.sh"
herdr pane wait-output <pane> --match "viewer ok" --timeout 30000
```

The first command replaces the pane's shell with a bash that has the guard first on
`PATH`, `KUBECONFIG` set to the viewer file and no startup files. Run it exactly in this
form: `crew-start.sh` refuses arguments after `shell`, and the test kit's hard check
fails any other use of it. Start an agent in the
pane only after `viewer ok` appears. If it does not, read the pane with
`herdr pane read <pane>`, do not start a helper there, and tell the user what the
preflight said.

## 5. Start the helpers

Start them one call each; each call returns when its helper is ready:

```bash
herdr agent start crew-claude --kind claude --pane <pane> --timeout 60000 -- --permission-mode default --settings <skill-dir>/config/claude-settings.example.json
herdr agent start crew-copilot --kind copilot --pane <pane> --timeout 60000 -- <copilot-rule-arguments>
```

Use exactly these helper arguments, nothing more: the hard check fails a helper started
with any other.

- **Claude helpers** start with `--permission-mode default` and the crew's deny rules
  (`--settings <skill-dir>/config/claude-settings.example.json`), the same rules
  `scripts/crew-start.sh claude` gives the boss. Without `--permission-mode default`, a
  user whose default is plan mode would get a helper that writes a plan and stops at
  "ready to execute?" instead of replying.
- **Copilot helpers** get the crew's Copilot rules as `<copilot-rule-arguments>`. Run
  `<skill-dir>/config/copilot-deny-tools.sh --lines`: it prints one argument per line,
  with no quotes. Add each line after the `--`, in single quotes (the arguments contain
  spaces and parentheses but never a quote). The rules are deny-only, so the helper
  asks before each other kubectl call; those prompts go to the user. Use
  `copilot-deny-tools.sh --auto-allow --lines` only when the user started the boss with
  `crew-start.sh --auto-allow`: kubectl then runs without asking, and the guard in the
  pane and the viewer identity protect the cluster.

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
agent's terminal), with the placeholders filled in. The prompt is sent in single quotes,
so the filled-in text must not contain a single quote, a double quote, a backtick or a
dollar sign: write names and evidence without them.

```text
You are a read-only k8s-crew investigator. Your kubeconfig is <viewer-kubeconfig-path>; it is already set and checked in this pane. Hard rules: run only read-only (run-freely) commands; run one plain command per call: no &&, ; or ||, no redirection such as 2>&1, no shell variables or command substitution, no cd and no echo, and a pipe only into grep, egrep, head, tail, sort, uniq, wc, cut, column or jq; prefer -o name, -o wide or -o json piped into jq with no file arguments; in jq use only -r, -c, -e, -s or --arg, and no string interpolation: build text with + or join; use only this pane identity: never pass --kubeconfig, --context, --cluster, --server, --user, --token, --as or another identity flag, never set KUBECONFIG, never run a cluster tool by its full path and never read kubeconfig files; if a command fails with Unauthorized or You must be logged in, or the crew guard refuses it, stop and say so in your reply; never run a command under an Ask first or a Proposed fix line, or any other command that changes the cluster; never read Secrets; do not change files; no speculative weaknesses, confirmed only with a command result shown, a timestamp alone is not a recent change, and fix the cause, never a knock-on effect. Use the skill <specialist-skill> (its SKILL.md is at <skill-path>). Your task: <issue, object and namespace, and the evidence triage saw>. Your full instructions are in <skill-dir>/roles/investigator.md: read that file first, and if you cannot read it, say so in your reply and keep to these rules. Reply with exactly these sections, in this order: ### Finding, ### Evidence, ### Confidence (confirmed | likely | not sure), ### Proposed fixes (each fix with the marker line > Ask first: changes the cluster. Run it yourself after review. or > Proposed fix: review before running. The agent does not run this. then its command and a line that starts with # Undo: and reverses it).
```

Send each prompt in its own call. `--wait --until working --until blocked` returns as
soon as the helper has started on it, so the helpers work in parallel while you send
the next prompt:

```bash
herdr agent prompt crew-claude '<prompt>' --wait --until working --until blocked --timeout 30000
herdr agent prompt crew-copilot '<prompt>' --wait --until working --until blocked --timeout 30000
```

When every prompt is sent, wait for each helper in turn, one call each:

```bash
herdr agent wait crew-claude --timeout 600000
herdr agent wait crew-copilot --timeout 600000
```

Handle each result:

- **`working` (from the prompt):** it started; go on to the next helper.
- **`idle` or `done` (from the wait):** finished; read it (step 7).
- **`agent_prompt_stalled`:** herdr did not see the helper start working. Copilot often
  answers too fast for herdr to notice. **Never send the prompt again.** Read the pane:
  if the answer is there, use it; if the helper is still working, wait for it as above
  and read again.
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
