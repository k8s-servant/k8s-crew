# AGENTS.md

Guidance for AI coding assistants working in this repository. `CLAUDE.md` only imports
this file.

## Project

k8s-crew is a set of agent skills for a Kubernetes triage "crew" (a lead agent plus a few
read-only helpers), the tooling that checks them (`tools/crewcheck`) and a kind-based
test kit (`tests/`). It depends on [k8s-skills](https://github.com/k8s-servant/k8s-skills)
for the investigation skills and the command allow-list.

Layout: everything the crew needs at run time lives in the one skill folder
`skills/k8s-crew/` (its `SKILL.md`, `recipes/`, `roles/`, `runners/`, `agents/`,
`scripts/`, `config/`, `rbac/`), because `npx skills add` installs only that folder.
Paths in those files are relative to it. `tools/` and `tests/` stay at the repository
root.

The Claude Code plugin manifest is `.claude-plugin/plugin.json` (with `marketplace.json`);
its `agents` path points into the skill folder. User docs: `README.md`, `docs/safety.md`,
`docs/gotchas.md`, and the herdr release procedure in `docs/herdr-release-check.md`.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements-dev.txt   # setup
.venv/bin/pytest                                         # tests
.venv/bin/ruff check . && .venv/bin/ruff format --check .   # lint
.venv/bin/python -m tools.crewcheck check                # check the crew skills
tests/cluster.sh up | down                               # throwaway kind cluster
tests/crew.sh <scenario> --agent claude|copilot --mode subagents|single   # run a scenario
tests/score.sh runs/<scenario>/<agent>-<mode>-<n>         # score a run (score.json)
.venv/bin/python -m tools.score summarize runs           # pass table of all runs
npx --yes markdownlint-cli2@0.24.0 "**/*.md" "#.venv" "#node_modules" "#.cache"   # markdown lint
```

How transcripts are captured, and their limits: `docs/transcripts.md`.

## Rules (must follow)

- License Apache-2.0. Conventional Commits. release-please owns versions and
  `CHANGELOG.md`; never edit them by hand. No attribution lines in commits.
- **Placeholders only** (`my-namespace`, `my-app`, `example.com`). This is a public
  repository: no real cluster names, registries, hostnames, tenant IDs, company names or
  personal data.
- **Never read Secrets** in any command, script, example, test or prompt.
- **Never copy a k8s-skills skill.** Depend on it. Copying scripts from k8s-skills is fine.
- k8s-skills pin: `K8S_SKILLS_REF=v0.10.0` in `tests/versions.env`. The command
  allow-list and checker come from that ref, fetched into `.cache/k8s-skills-<ref>/`
  (git-ignored). `tools/crewcheck` and `tools/transcript.py` call private functions of
  the pinned checker (`_parse_markdown`, `_check_lines`, `_scan`, `_check_filter`, ...)
  and map the crew's ask-first marker to its `ASK_MARKER`: check them when you bump the
  pin.
- The crew session only ever has the view-only identity: sessions start with
  `scripts/crew-start.sh`, which puts `scripts/kubectl-guard` first on `PATH`. The crew
  never runs a fix; it prints each fix with an `# Undo:` line for the user to run.
- Helpers: default 3, max 4 (Claude Code subagents and herdr); Copilot CLI subagent mode
  default 2.
- Test cluster name `k8s-crew-test`, context `kind-k8s-crew-test`. Scripts refuse to run
  against any other context.
- Report sections, exact headings in this order: `## Root cause`, `## Knock-on effects`,
  `## Separate issues`, `## Fixes`, `## What was checked`, `## Helper details`.
- Investigator finding sections, exact headings: `### Finding`, `### Evidence`,
  `### Confidence` (one of `confirmed`, `likely`, `not sure`), `### Proposed fixes`.
- Scenario runs are not part of PR CI. PR CI: ruff, pytest, markdown lint,
  `python -m tools.crewcheck check`.
- Creating the GitHub repo `k8s-servant/k8s-crew`, pushing, and publishing need the
  author's explicit go-ahead at that moment.
- **TDD for tooling:** write a failing test first. Tests for `tools/` live in `tools/tests/`.
- Before every commit: `ruff check . && ruff format --check . && pytest`.
