<div align="center">

<img src="https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/docs/logo.svg" alt="fireworks-skill-memory" width="80" />

# fireworks-skill-memory

**Persistent experience memory for Claude Code skills.**

Claude remembers what it learned — session after session, skill by skill.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-compatible-8A2BE2)](https://claude.ai/code)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/pulls)

[中文文档](README.zh-CN.md) · [Report Bug](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/issues) · [Request Feature](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/issues)

</div>

---

## The Problem

Every Claude Code session starts from zero. The same mistakes repeat — wrong API parameters, broken sequences, proxy pitfalls — because Claude has no memory between sessions.

```
Session 1:  "Don't forget — use index=0 for Feishu blocks"   ✓ works
Session 2:  same mistake again                                ✗ forgot
Session 3:  same mistake again                                ✗ forgot
```

## The Solution

`fireworks-skill-memory` gives Claude a persistent, skill-scoped memory that grows smarter with every session — automatically, in the background, with zero impact on your workflow.

```
Session 1:  mistake happens → lesson saved automatically
Session 2:  lesson injected before Claude responds            ✓ no repeat
Session 3:  lesson still there, more lessons added            ✓ keeps improving
```

---

## Install

**In Claude Code, just say:**

> *"Help me install fireworks-skill-memory from https://github.com/yizhiyanhua-ai/fireworks-skill-memory"*

Or run directly in your terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/install.sh | bash
```

Then type `/hooks` in Claude Code to activate. No config files to edit manually.

---

## Architecture

### End-to-End Flow

<img src="https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/docs/architecture.svg" alt="Architecture diagram" width="100%"/>

Two hooks, two jobs:

| Hook | Event | Job |
|------|-------|-----|
| `PostToolUse` (Read) | When Claude reads a `SKILL.md` | Inject past lessons into context — **< 5ms, pure file I/O** |
| `Stop` (async) | When a session ends | Distil 1–3 new lessons from transcript via haiku — **non-blocking** |

**v2 distillation improvements (transparent, no config changes needed):**
- Context-compression detection — skips distillation on summary-only sessions to prevent low-quality lessons
- Error-seed capture — snapshots raw error signals mid-session for ground-truth distillation input
- Intent filtering — full injection for active skill use, top-5 highlights for exploratory reads
- Frequency-weighted eviction — high-hit entries survive; rarely-triggered but critical lessons are protected

### Harness Engineering Pattern

<img src="https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/docs/harness-pattern.svg" alt="Harness pattern diagram" width="100%"/>

Claude Code's **Harness** is the orchestration layer between the model and the world — the model only reasons, while Harness handles all I/O: tool calls, file access, subprocess execution, permission enforcement. `fireworks-skill-memory` is a pure Harness-layer extension: it never modifies the model, never touches your prompts, and never intercepts user input.

It operates on exactly two lifecycle hook points that the Harness exposes:
- **`PostToolUse` on `Read`** — fires when any `SKILL.md` is read, injects `additionalContext` into the model's context window
- **`Stop` with `async: true`** — fires after every session completes, runs the distillation pipeline in the background without blocking

This is the correct engineering pattern for extending Claude Code: hook into the Harness lifecycle, not into the model itself.

---

## Knowledge Structure

```
~/.claude/
├── skills-knowledge.md          ← global cross-skill principles (≤ 20 entries)
│     "Test proxy connectivity before any external call"
│     "Batch insert blocks top→bottom; never use index=0 to prepend"
│
└── skills/
    ├── browser-use/
    │   ├── KNOWLEDGE.md         ← skill-specific lessons (≤ 30 entries)
    │   │     "Run state before every click — indices change after interaction"
    │   │     "Use --profile for sites with saved logins"
    │   └── .error_seeds         ← transient: raw errors captured mid-session,
    │                               consumed by Stop hook then deleted
    │
    ├── find-skills/
    │   └── KNOWLEDGE.md
    │
    └── {any-skill}/
        └── KNOWLEDGE.md         ← auto-created on first lesson
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

- [state before acting] Always run `browser-use state` before clicking —
  indices change after every page interaction. Never reuse a stale index.
- [daemon lifecycle] Run `browser-use close` when done. The daemon stays
  open and holds resources until explicitly closed.
- [auth via profile] Use --profile "Default" to access sites where you're
  already logged in. Headless Chromium has no saved cookies.
```

---

## Included Starter Knowledge

Ready-made lesson files for Claude Code's official skills — included out of the box:

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
| 📄 **Transcript access** | Reads only JSONL files Claude Code already stores locally |
| 🔑 **Secrets** | Distillation prompt explicitly excludes credentials and personal data |
| 🤖 **API calls** | Runs through your existing Claude Code auth — no third-party endpoints |

See [SECURITY.md](SECURITY.md) for the full security policy.

---

## Configuration

All optional. Set in `~/.claude/settings.json` under `"env"`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SKILLS_KNOWLEDGE_MODEL` | `claude-haiku-4-5` | Model used for distillation |
| `SKILL_MAX` | `30` | Max entries per skill file |
| `GLOBAL_MAX` | `20` | Max entries in the global file |
| `TRANSCRIPT_LINES` | `300` | Lines of transcript to analyse |
| `SKILLS_KNOWLEDGE_DIR` | `~/.claude/skills` | Root of skill directories |

---

## Contributing

Contributions of new starter `KNOWLEDGE.md` files for popular skills are especially welcome.

1. Fork and branch: `git checkout -b feat/skill-name-knowledge`
2. Add your file to `examples/skill-knowledge/`
3. Open a PR — describe what lessons are included and why they matter

---

## License

MIT © 2026 [yizhiyanhua-ai](https://github.com/yizhiyanhua-ai)
