---
name: fireworks-skill-memory
description: Persistent cross-session experience memory for Claude Code and Codex skills. TRIGGER when user asks about skill memory, experience distillation, cross-session learning, skill knowledge injection, Claude/Codex memory, session-to-session improvement, or wants to install/configure fireworks-skill-memory.
---

# fireworks-skill-memory

Persistent experience memory for Claude Code and Codex skills. Shared memory core, runtime-specific adapters, skill-scoped lessons.

## What It Does

Every coding-agent session starts from zero. The same mistakes repeat — wrong API parameters, broken sequences, proxy pitfalls — because the runtime has no durable skill memory between sessions.

`fireworks-skill-memory` solves this by:

1. **Injecting past experience** when a skill is invoked
2. **Distilling new lessons** into skill-scoped knowledge files
3. **Keeping runtime-specific adapters thin** so Claude hooks and Codex explicit flows share one memory core

## Installation

### Quick Install (Recommended)

In Claude Code, say:

> "Help me install fireworks-skill-memory from https://github.com/yizhiyanhua-ai/fireworks-skill-memory"

Or run the one-command installer:

```bash
curl -fsSL https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/install.sh | bash
```

### npx skills Install

```bash
npx skills add yizhiyanhua-ai/fireworks-skill-memory -g
```

After installing via npx skills, run the installer to set up hooks:

```bash
curl -fsSL https://raw.githubusercontent.com/yizhiyanhua-ai/fireworks-skill-memory/main/install.sh | bash
```

### Codex Setup

Run:

```bash
./install-codex.sh
```

Then use:

```bash
python3 cli/skill_memory.py inject --skill <skill-name>
python3 cli/skill_memory.py checkpoint --skill <skill-name> --note "..."
python3 cli/skill_memory.py flush --skill <skill-name> --summary-file ./session-summary.md
```

## How It Works

Claude Code installs 4 hooks that run automatically:

| Hook | Trigger | Script | Purpose |
|------|---------|--------|---------|
| `PreToolUse` | Before Skill call | `pre-skill-inject.py` | Inject full KNOWLEDGE.md before skill executes |
| `PostToolUse` | After Read SKILL.md | `inject-skill-knowledge.py` | Inject top-N entries by relevance + capture error seeds |
| `PostToolUse` | After any tool call | `error-seed-capture.py` | Capture error signals to session-scoped file |
| `Stop` | Session end (async) | `update-skills-knowledge.py` | Distill new lessons via Haiku, update KNOWLEDGE.md |

Codex uses explicit runtime commands instead:

| Command | Purpose |
|---------|---------|
| `inject` | Load top-ranked lessons for a skill before a task |
| `checkpoint` | Save raw notes into the skill directory |
| `flush` | Distill explicit lesson sections from summary/session inputs into `KNOWLEDGE.md` |

### Data Flow

```
Skill invoked → PreToolUse injects experience → Claude executes with context
                                                    ↓
Session ends → Stop hook reads transcript → Haiku distills 1-3 lessons
                                                    ↓
                              KNOWLEDGE.md updated → Ready for next session
```

```text
Codex task starts → inject loads top lessons → Codex executes with context
                                                ↓
Checkpoint/summary captured → flush distills explicit lessons
                                                ↓
                      KNOWLEDGE.md updated → Ready for next session
```

### Knowledge Storage

```text
<memory-home>/skills/<skill-name>/KNOWLEDGE.md   ← Distilled per-skill experience
<memory-home>/skills/<skill-name>/CHECKPOINTS.md ← Raw runtime notes
<memory-home>/global/KNOWLEDGE.md                ← Global cross-skill principles

Claude legacy runtime also uses:
~/.claude/skills/<skill-name>/KNOWLEDGE.md
~/.claude/skill-usage-stats.json
~/.claude/skill-memory.log
```

Each entry is tagged with `[YYYY-MM]` timestamp and `[HIT:N]` usage counter. Low-frequency, old entries are evicted first.

## Configuration (Optional)

All settings are optional, configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SKILLS_KNOWLEDGE_MODEL` | `claude-haiku-4-5` | Default model for the Claude CLI distiller backend |
| `SKILLS_DISTILLER_BACKEND` | `claude-cli` | Distiller backend selector: `claude-cli`, `openai`, or `null` |
| `SKILLS_DISTILLER_DEBUG` | unset | Enable backend debug logging to the default distiller log file |
| `SKILLS_DISTILLER_LOG` | unset | Explicit path for distiller debug logs |
| `SKILL_MAX` | `100` | Max entries per skill |
| `GLOBAL_MAX` | `100` | Max global entries |
| `MIN_TOOL_CALLS` | `5` | Skip sessions with fewer calls (likely summaries) |
| `SKILLS_INJECT_TOP` | `20` | Max entries injected per active invocation |

## Requirements

- Python 3.9+
- Claude Code CLI for the automatic Claude runtime
- Claude Haiku access for the default Claude CLI distiller backend
- `CODEX_HOME` for the Codex runtime setup helper
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` when using the OpenAI distiller backend
- `SKILLS_DISTILLER_DEBUG` or `SKILLS_DISTILLER_LOG` when debugging backend failures

## More Information

- [Full Documentation](README.md)
- [中文文档](README.zh-CN.md)
- [Report Bug](https://github.com/yizhiyanhua-ai/fireworks-skill-memory/issues)
