#!/usr/bin/env python3
"""
fireworks-skill-memory: Skill Knowledge Injector
=================================================
Hook type : PostToolUse on Read
Trigger   : When Claude reads any skill's SKILL.md file
Action    : Injects the corresponding KNOWLEDGE.md into model context
            so Claude benefits from past experience before acting

Optimizations
-------------
  [2] Error-seed capture: when Claude reads a SKILL.md right after a tool
      returned an error result, the error text is appended to a temporary
      .error_seeds file in the skill directory. The Stop hook picks this up
      as high-quality raw material for distillation — no haiku inference needed.
  [3] Intent filtering: distinguishes "actively invoking" vs "passively browsing"
      a skill. If the preceding tool call was Skill (active invocation) or the
      Read is part of a tool sequence, inject the full KNOWLEDGE.md. If the
      SKILL.md read appears to be exploratory (no prior Skill call in recent
      history), inject only a concise header to reduce noise.

Performance: Pure file I/O only — no network calls, <5 ms latency.

Installation
------------
Add to ~/.claude/settings.json under hooks.PostToolUse:

  {
    "matcher": "Read",
    "hooks": [{
      "type": "command",
      "command": "python3 /path/to/inject-skill-knowledge.py",
      "if": "Read(**/.claude/skills/*/SKILL.md)"
    }]
  }

Configuration (env vars, optional)
-----------------------------------
SKILLS_KNOWLEDGE_DIR   Path to the skills directory
                       Default: ~/.claude/skills
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_core.store import get_paths, select_injection_entries

# [Opt-6] Multi-path skill detection — support skills installed under various paths
SKILL_PATH_PATTERNS = [
    r'/.claude/skills/([^/]+)/',
    r'/.skills/([^/]+)/',
    r'/.agents/skills/([^/]+)/',
]

SKILLS_DIR = get_paths().legacy_skills_dir

# ── Read hook input ────────────────────────────────────────────────────────────
try:
    hook_input = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)

# Only act on Read tool calls
if hook_input.get("tool_name") != "Read":
    sys.exit(0)

# Only act when a SKILL.md inside a skills directory is being read
file_path = hook_input.get("tool_input", {}).get("file_path", "")
if "SKILL.md" not in file_path:
    sys.exit(0)

# ── Extract skill name from path ───────────────────────────────────────────────
# [Opt-6] Try multiple skill installation paths
skill_name = ""
for pattern in SKILL_PATH_PATTERNS:
    m = re.search(pattern, file_path)
    if m:
        skill_name = m.group(1)
        break

if not skill_name:
    sys.exit(0)

# ── [Opt-3] Intent detection ──────────────────────────────────────────────────
# Check if there was a preceding Skill tool call in the session context.
# The hook_input may contain session transcript hints or tool call history.
# We use a lightweight heuristic: look for a "tool_call_history" or similar
# field. If the immediately preceding tool call was "Skill", this is an active
# invocation; otherwise treat as exploratory.
preceding_tool = hook_input.get("tool_call_history", [])
is_active_invocation = False

if isinstance(preceding_tool, list) and preceding_tool:
    # Check last few entries for a Skill call targeting this skill
    for entry in reversed(preceding_tool[-5:]):
        if isinstance(entry, dict):
            if entry.get("tool_name") == "Skill":
                skill_arg = entry.get("tool_input", {}).get("skill", "")
                if skill_name in skill_arg or skill_arg in skill_name:
                    is_active_invocation = True
                    break
            # Stop looking back if we hit another Read (different context)
            if entry.get("tool_name") == "Read":
                break

# Fallback: if no history available, assume active (conservative — don't withhold)
if not preceding_tool:
    is_active_invocation = True

# ── [Opt-2] Error-seed capture ─────────────────────────────────────────────────
# If the tool_result from the *previous* tool use in this hook batch contained
# an error, snapshot it as a seed for the Stop-hook distillation.
tool_result = hook_input.get("tool_result", {})
result_content = ""
if isinstance(tool_result, dict):
    # tool_result might be {"type": "tool_result", "content": [...]} or plain string
    content_field = tool_result.get("content", "")
    if isinstance(content_field, list):
        for block in content_field:
            if isinstance(block, dict):
                result_content += block.get("text", "")
    elif isinstance(content_field, str):
        result_content = content_field

# Detect error signals in the previous tool result
ERROR_SIGNALS = [
    "error", "failed", "exception", "traceback", "errno",
    "invalid", "not found", "permission denied", "timeout",
    "错误", "失败", "异常", "无效",
]
has_error = any(sig in result_content.lower() for sig in ERROR_SIGNALS)

if has_error and result_content.strip():
    seed_file = SKILLS_DIR / skill_name / ".error_seeds"
    seed_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Append (not overwrite) — multiple errors per session accumulate
        with seed_file.open("a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"\n--- error seed {datetime.now().isoformat()} ---\n")
            f.write(result_content[:800])
            f.write("\n")
    except Exception:
        pass

if is_active_invocation:
    top_n = int(os.environ.get("SKILLS_INJECT_TOP", "20"))
    active_entries = select_injection_entries(skill_name, top_n=top_n)
    if not active_entries:
        sys.exit(0)
    injection_body = "\n".join(active_entries)
    injection_note = f"top-{len(active_entries)} by relevance (active invocation)"
else:
    exploratory_entries = select_injection_entries(skill_name, top_n=5)
    if not exploratory_entries:
        sys.exit(0)
    injection_body = "\n".join(exploratory_entries)
    injection_note = "top-5 highlights (exploratory read)"

# ── Inject into model context via additionalContext ───────────────────────────
output = {
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": (
            f"\n---\n"
            f"📚 **[fireworks-skill-memory] {skill_name} — past experience** ({injection_note})\n\n"
            f"{injection_body}\n"
            f"---\n"
        ),
    }
}

print(json.dumps(output, ensure_ascii=False))
