# Run transcripts

`tests/crew.sh` saves, for every run, a transcript of every shell command the session
and its subagents asked to run. `tests/score.sh` checks each cluster command in it
against the run-freely tier of the pinned k8s-skills allow-list. The check is script-only
and fails closed.

## Normalized format

`runs/<scenario>/<agent>-<mode>-<n>/transcript.jsonl`, one JSON object per line:

```json
{"agent": "boss", "command": "kubectl get nodes"}
{"agent": "k8s-crew-investigator", "command": "kubectl get pods -n my-namespace"}
```

`agent` is `boss` for the main session and the subagent's agent name otherwise. The raw
agent output is kept next to it, so the transcript can be rebuilt:
`python -m tools.score transcript --claude|--copilot SOURCE OUT`.

A missing, unparseable or empty transcript fails the tier check with
`transcript unavailable`. It never passes silently.

## Claude Code

Method: `claude -p --output-format stream-json --verbose`, saved as `stream.jsonl`, read
by `tools.transcript.read_claude_stream`.

- Every `Bash` tool call is an `assistant` event with a `tool_use` item. A subagent's
  events carry `parent_tool_use_id`, the id of the `Agent` call that started it, whose
  `subagent_type` names the agent.
- Calls the permission rules deny are in the stream too (the model asked for them), so
  attempts count, not just commands that ran.
- The final report is the `result` field of the last `type: "result"` event.

Limits: a subagent started by a subagent would be named after its own `Agent` call, which
is fine; a Bash call that never reaches the stream (a crash mid-message) is lost, and the
run then usually has no final report either.

## Copilot CLI

Method (checked with Copilot CLI 1.0.107): `copilot -p ... --session-id <uuid>
--output-format json`. The session's own event log,
`~/.copilot/session-state/<uuid>/events.jsonl`, is copied to the run folder as
`events.jsonl` and read by `tools.score.read_copilot_events`. If that file is missing,
the JSONL on stdout (`stream.jsonl`) is read instead; it carries the same
`assistant.message` events.

- Each `assistant.message` lists the tool calls the model asked for in
  `data.toolRequests`. Shell calls are `bash` (and `shell`/`powershell`) with
  `arguments.command`, and `write_bash`/`write_powershell` with `arguments.input` (text
  sent to a running shell, counted as a command).
- A subagent's events carry a top-level `agentId`; its `subagent.started` event names it
  in `data.agentName`.
- Denied calls are listed too (seen in a probe run: a denied `touch x` was in
  `toolRequests`).
- The final report is the last non-empty `content` of a main-session
  `assistant.message`.

Limits:

- Subagent attribution was checked on saved interactive sessions, not yet on a
  `copilot -p` crew run.
- The event format is not a documented interface and can change with any Copilot CLI
  update. A file that has no `session.*` or `assistant.*` events is rejected, and a run
  with no commands at all fails as `transcript unavailable`.
- Reading `~/.copilot/session-state` only reads files Copilot writes for every session;
  nothing in `~/.copilot` is changed by the test kit. Copilot still loads the user's own
  agents and skills from `~/.copilot`; Claude runs use `--setting-sources project,local`
  and do not.
- Whether Copilot runs `/k8s-crew <prompt>` as the skill in prompt mode is not checked
  yet; check the first crew run's `events.jsonl` for the skill being loaded.
