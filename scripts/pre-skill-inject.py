#!/usr/bin/env python3
"""
fireworks-skill-memory: Pre-Skill Knowledge Injector
=====================================================
Hook type : PreToolUse on Skill
Trigger   : Before any Skill tool call
Action    : Injects the corresponding KNOWLEDGE.md into model context
            BEFORE the skill executes — so Claude sees past experience
            during planning, not after the skill has already started.

Why this matters:
  The PostToolUse/Read hook fires when SKILL.md is read, which happens
  *after* the Skill tool is invoked. By then Claude is already executing.
  This PreToolUse hook fires *before* execution, giving Claude a chance
  to apply lessons learned before making mistakes.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_core.store import select_injection_entries

# ── Read hook input ────────────────────────────────────────────────────────────
try:
    hook_input = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)

if hook_input.get("tool_name") != "Skill":
    sys.exit(0)

# ── Extract skill name ─────────────────────────────────────────────────────────
skill_name = hook_input.get("tool_input", {}).get("skill", "")
if not skill_name:
    sys.exit(0)

entries = select_injection_entries(skill_name)
if not entries:
    sys.exit(0)
injection_body = "\n".join(entries)

# ── Inject into model context ──────────────────────────────────────────────────
output = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": (
            f"\n---\n"
            f"📚 **[fireworks-skill-memory] {skill_name} — past experience** (pre-execution inject)\n\n"
            f"{injection_body}\n"
            f"---\n"
        ),
    }
}

print(json.dumps(output, ensure_ascii=False))
