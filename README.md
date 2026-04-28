<div align="center">

<img src="https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/docs/logo.svg" alt="fireworks-skill-memory" width="80" />

# fireworks-skill-memory

**Persistent experience memory for Claude Code and Codex skills.**

Shared memory core, runtime-specific adapters, skill-scoped lessons.

[![Version](https://img.shields.io/badge/version-4.0.0-orange.svg)](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-compatible-8A2BE2)](https://claude.ai/code)
[![Codex](https://img.shields.io/badge/Codex-compatible-111111)](https://openai.com)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/pulls)

[中文文档](README.zh-CN.md) · [Report Bug](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/issues) · [Request Feature](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/issues)

</div>

---

## The Problem

Every coding-agent session starts from zero. The same mistakes repeat — wrong API parameters, broken sequences, proxy pitfalls — because the runtime has no durable skill memory between sessions.

```
Session 1:  "Don't forget — use index=0 for Feishu blocks"   ✓ works
Session 2:  same mistake again                                ✗ forgot
Session 3:  same mistake again                                ✗ forgot
```

## The Solution

`fireworks-skill-memory` gives Claude Code and Codex a persistent, skill-scoped memory that grows smarter with every session. The storage layer is shared; the hook and flush flows are runtime-specific.

```
Session 1:  mistake happens → lesson saved automatically
Session 2:  lesson injected before Claude responds            ✓ no repeat
Session 3:  lesson still there, more lessons added            ✓ keeps improving
```

---

## Install

### Claude Code

In Claude Code, just say:

> *"Help me install fireworks-skill-memory from https://github.com/yizhiyanhua-ai/fireworks-skill-memory"*

Or run directly in your terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/install.sh | bash
```

Then type `/hooks` in Claude Code to activate. No config files to edit manually.

### Codex

Codex does not use Claude-style hooks. The current integration path is explicit and runtime-driven:

```bash
python3 cli/skill_memory.py inject --skill lark-sync
python3 cli/skill_memory.py checkpoint --skill lark-sync --note "..."
python3 cli/skill_memory.py flush --skill lark-sync --summary-file ./session-summary.md
```

Codex memory defaults to:

```text
$CODEX_HOME/memories/fireworks-skill-memory/
```

---

## Architecture

### End-to-End Flow

<img src="https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/docs/architecture.svg" alt="Architecture diagram" width="100%"/>

Two runtimes, one shared memory core:

| Hook | Event | Job |
|------|-------|-----|
| `PreToolUse` (Skill) | Before any Skill call | Inject past lessons **before execution** — Claude plans with experience, not after mistakes |
| `PostToolUse` (Read) | When Claude reads a `SKILL.md` | Inject past lessons into context — **< 5ms, pure file I/O** |
| `PostToolUse` (all tools) | After every tool call | Capture error signals to session-scoped seed file — **broader coverage** |
| `Stop` (async) | When a session ends | Distil 1–3 new lessons from transcript via haiku — **non-blocking** |
| `Stop` (async, daily) | Once per day at session end | Check remote repo for updates, notify at next `SessionStart` if available |
| `SessionStart` | When a session begins | Show pending scheduled task notifications + update alerts |

Codex currently uses explicit commands instead of hooks:

| Runtime | Entry point | Job |
|---------|-------------|-----|
| `Codex` | `inject` | Prefix a task with the top ranked skill lessons |
| `Codex` | `checkpoint` | Save raw notes under the skill directory for later distillation |
| `Codex` | `flush` | Distil explicit lessons from summary/session sources back into `KNOWLEDGE.md` |

### Runtime Split

```text
memory_core/
  store.py           # skill/global knowledge storage, merge, eviction
  transcript.py      # transcript parsing helpers

runtimes/
  claude_runtime.py  # Claude transcript provider + Claude CLI distiller
  codex_runtime.py   # Codex checkpoint/flush provider

scripts/             # thin Claude hook adapters
cli/                 # thin Codex/manual adapter
```

Distillation is now behind a shared interface. The Claude runtime currently uses the `ClaudeCliDistiller` backend; Codex explicit flows remain local until you attach another backend.

The backend selector lives in `memory_core/distiller.py`. `OpenAIDistiller` now has stronger real-world debugging support: it parses more OpenAI-compatible response shapes, records structured HTTP/body failures, and emits raw-response previews through `SKILLS_DISTILLER_DEBUG` or `SKILLS_DISTILLER_LOG`.

**v4 harness optimizations (2026-04-05):**
- Observability — every Stop hook execution is logged to `~/.claude/skill-memory.log` (timestamp, session, skills, result)
- Broader error coverage — new `error-seed-capture.py` captures errors from ALL tool calls, not just SKILL.md reads
- Earlier injection — new `pre-skill-inject.py` fires on `PreToolUse`, so Claude sees lessons during planning
- Model fallback chain — if primary haiku model is deprecated, automatically tries next available model
- Cross-session usage stats — `skill-usage-stats.json` tracks per-skill usage frequency for smarter eviction
- Larger knowledge base — `SKILL_MAX` / `GLOBAL_MAX` expanded from 30/20 to 100 entries each
- Context-efficient injection — active invocations inject top-20 by HIT count, not full file

### Harness Engineering Pattern

<img src="https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/docs/harness-pattern.svg" alt="Harness pattern diagram" width="100%"/>

Claude Code's **Harness** is the orchestration layer between the model and the world — the model only reasons, while Harness handles all I/O: tool calls, file access, subprocess execution, permission enforcement. `fireworks-skill-memory` is a pure Harness-layer extension: it never modifies the model, never touches your prompts, and never intercepts user input.

It operates on exactly two lifecycle hook points that the Harness exposes:
- **`PostToolUse` on `Read`** — fires when any `SKILL.md` is read, injects `additionalContext` into the model's context window
- **`Stop` with `async: true`** — fires after every session completes, runs the distillation pipeline in the background without blocking

This is the correct engineering pattern for extending Claude Code: hook into the Harness lifecycle, not into the model itself.

---

## Knowledge Structure

```text
<memory-home>/
├── global/KNOWLEDGE.md          ← global cross-skill principles
└── skills/
    ├── browser-use/
    │   ├── KNOWLEDGE.md         ← distilled skill-specific lessons
    │   └── CHECKPOINTS.md       ← raw runtime notes, not injected by default
    └── {any-skill}/
        ├── KNOWLEDGE.md
        └── CHECKPOINTS.md

Legacy Claude runtime state remains under `~/.claude/`:
~/.claude/skills/<skill>/KNOWLEDGE.md
~/.claude/error-seeds/<session_id>.txt
~/.claude/skill-memory.log
~/.claude/skill-usage-stats.json
```

**Two-layer design:**
- **Global** — principles that help across all skills
- **Per-skill** — precise, actionable lessons scoped to that skill only

Context injection is scoped: only the relevant skill's file loads, keeping the model's context window clean.

---

## What Gets Remembered

Example entries that accumulate over real usage:

```markdown
# browser-use — experience

- [2026-03] [state before acting] Always run `browser-use state` before clicking —
  indices change after every page interaction. Never reuse a stale index.
- [2026-03] [daemon lifecycle] Run `browser-use close` when done. The daemon stays
  open and holds resources until explicitly closed.
- [2026-02] [auth via profile] Use --profile "Default" to access sites where you're
  already logged in. Headless Chromium has no saved cookies.
```

---

## Included Starter Knowledge

Ready-made lesson files for Claude Code's official skills are included out of the box. Codex can read the same lessons through the shared memory core or Claude fallback paths.

| Skill | Pre-loaded lessons |
|-------|-------------------|
| `find-skills` | CLI commands, install paths, network error patterns |
| `skills-updater` | Two update sources, version tracking, locale detection |
| `voice` | agent-voice setup, auth flow, ask vs say semantics |
| `browser-use` | state-before-act, daemon lifecycle, profile auth |
| `skill-adoption-planner` | Fast-path inputs, resistance diagnosis |
| `skill-knowledge-extractor` | No-script mode, pattern types |
| `skill-roi-calculator` | Minimum data, comparison mode |
| `hookify` | Rule format, regex field, naming conventions |
| `superpowers` | Mandatory invocation, user-instruction priority |

---

## Privacy & Security

| | Detail |
|--|--------|
| 📍 **Data location** | Everything stays on your machine — no cloud, no uploads |
| 📄 **Transcript access** | Claude runtime reads local Claude JSONL transcripts; Codex runtime currently uses explicit summary/session inputs |
| 🔑 **Secrets** | Distillation prompt explicitly excludes credentials and personal data |
| 🤖 **API calls** | Claude distillation runs through your existing Claude Code auth; Codex explicit flows stay local unless you add a model backend |

See [SECURITY.md](SECURITY.md) for the full security policy.

---

## Configuration

All optional. Set in `~/.claude/settings.json` under `"env"`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SKILLS_KNOWLEDGE_MODEL` | `claude-haiku-4-5` | Default model for the Claude CLI distiller backend (falls back automatically if deprecated) |
| `SKILLS_DISTILLER_BACKEND` | `claude-cli` | Distiller backend selector: `claude-cli`, `openai`, or `null` |
| `SKILLS_DISTILLER_DEBUG` | unset | When set to `1`/`true`, write backend debug logs to `~/.claude/skill-memory-distiller.log` |
| `SKILLS_DISTILLER_LOG` | unset | Optional explicit path for distiller debug logs |
| `SKILL_MAX` | `100` | Max entries per skill file |
| `GLOBAL_MAX` | `100` | Max entries in the global file |
| `TRANSCRIPT_LINES` | `300` | Lines of transcript to analyse |
| `SKILLS_KNOWLEDGE_DIR` | `~/.claude/skills` | Root of skill directories |
| `SKILLS_INJECT_TOP` | `20` | Max entries injected on active skill invocation (sorted by HIT count) |
| `SKILLS_SEEDS_DIR` | `~/.claude/error-seeds` | Directory for session-scoped error seed files |
| `SKILLS_STATS_FILE` | `~/.claude/skill-usage-stats.json` | Cross-session skill usage statistics |
| `SKILLS_MEMORY_LOG` | `~/.claude/skill-memory.log` | Stop hook execution log path |

When using the `openai` backend, also set:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | none | API key for the OpenAI distiller backend |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Base URL for OpenAI-compatible chat completions |
| `OPENAI_MODEL` | `gpt-5.4` | Model name for the OpenAI distiller backend |

For real debugging, enable either:

- `SKILLS_DISTILLER_DEBUG=1`
- `SKILLS_DISTILLER_LOG=/absolute/path/to/distiller.log`

---

## Codex Runtime

Shared storage defaults to:

```text
$CODEX_HOME/memories/fireworks-skill-memory/   # when running inside Codex
~/.ai-memory/                                  # otherwise
```

Directory layout:

```text
<memory-home>/
├── global/KNOWLEDGE.md
└── skills/
    └── <skill>/KNOWLEDGE.md
```

Legacy Claude skill knowledge under `~/.claude/skills/<skill>/KNOWLEDGE.md` is still read as a fallback.

Use the CLI directly:

```bash
python3 cli/skill_memory.py inject --skill lark-sync
python3 cli/skill_memory.py checkpoint --skill lark-sync --note "Feishu local image embeds must be uploaded first"
python3 cli/skill_memory.py flush --skill lark-sync --summary-file ./session-summary.md
python3 cli/skill_memory.py flush --skill lark-sync --session-file ./codex-session.jsonl
cat session-summary.md | python3 cli/skill_memory.py flush --skill lark-sync --stdin
python3 cli/skill_memory.py show --skill lark-sync
```

Recommended summary format for `flush`:

```md
# Session Summary

## Lessons

- Verify effective scopes before wiki writes
- `docs +create` does not resolve Obsidian local image embeds
- Replace `![[...]]` with `<image token="..."/>` before overwrite sync
```

Current commands:

- `inject` — prints a plain-text experience block suitable for prefixing into a Codex task
- `checkpoint` — appends raw session notes under the skill directory for later distillation
- `flush` — distils at most 3 explicit lessons from a summary file, session export, or stdin into `KNOWLEDGE.md`; it only reads lesson-style sections such as `## Lessons`, `## Takeaways`, or `## 经验沉淀`. Checkpoints stay separate unless `--include-checkpoints` is passed
- `show` — prints the current `KNOWLEDGE.md` for a skill, with Claude fallback support

Codex remains explicit by design for now: distilled knowledge is loaded progressively per skill, while raw notes stay in `CHECKPOINTS.md` until you intentionally flush them.

---

## Contributing

Contributions of new starter `KNOWLEDGE.md` files for popular skills are especially welcome.

1. Fork and branch: `git checkout -b feat/skill-name-knowledge`
2. Add your file to `examples/skill-knowledge/`
3. Open a PR — describe what lessons are included and why they matter

---

## License

MIT © 2026 [yizhiyanhua-ai](https://github.com/yizhiyanhua-ai)
