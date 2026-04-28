#!/usr/bin/env python3
"""
fireworks-skill-memory: Knowledge Base Updater
===============================================
Hook type : Stop (async: true — never blocks the session)
Trigger   : Every time a Claude Code session ends
Action    : Reads the session transcript, detects which skills were used,
            calls a lightweight model (haiku) to distil new learnings,
            and writes them back into the appropriate KNOWLEDGE.md.

Architecture
------------
  ~/.claude/skills-knowledge.md          ← global cross-skill principles  (≤ 20 entries)
  ~/.claude/skills/{name}/KNOWLEDGE.md   ← per-skill API/tool experience  (≤ 30 entries)
  ~/.claude/skills/{name}/.error_seeds   ← error+fix seeds captured mid-session

Optimizations
-------------
  v2:
  [1] Context-compression detection: skips distillation when the transcript
      looks like a summary-only session (no tool calls in last N lines),
      preventing low-quality lessons from summary text.
  [4] Frequency-weighted eviction: entries tagged [HIT:N] accumulate usage
      counts; on overflow, entries with lowest (hits × recency) are evicted
      instead of simple FIFO.

  v3:
  [5] Error-signal heuristic pre-filter: distillation (haiku) calls are only
      made when the transcript contains error/fix signal patterns, avoiding
      wasted inference on routine sessions. SKILL_KEYWORDS removed.
  [6] Multi-path skill detection: skills are detected from /.claude/skills/,
      /.skills/, and /.agents/skills/ paths (not just /.claude/skills/).
  [7] Timestamp [YYYY-MM] prefix + age-based decay: new entries are tagged
      with their creation month. Entries older than 3 months receive an
      eviction penalty, combining with HIT counts for smarter eviction.

Installation
------------
Add to ~/.claude/settings.json under hooks.Stop:

  {
    "hooks": [{
      "type": "command",
      "command": "python3 /path/to/update-skills-knowledge.py",
      "async": true
    }]
  }

Configuration (env vars, optional)
-----------------------------------
SKILLS_KNOWLEDGE_DIR      Path to skills directory
                          Default: ~/.claude/skills
SKILLS_KNOWLEDGE_GLOBAL   Path to the global knowledge file
                          Default: ~/.claude/skills-knowledge.md
SKILLS_DISTILLER_BACKEND  Distiller backend: claude-cli | openai | null
                          Default: claude-cli
SKILLS_KNOWLEDGE_MODEL    Primary Claude CLI distillation model
                          Default: claude-haiku-4-5
OPENAI_API_KEY            API key for the OpenAI distiller backend
OPENAI_BASE_URL           Base URL for OpenAI-compatible APIs
                          Default: https://api.openai.com/v1
OPENAI_MODEL              Model for the OpenAI distiller backend
                          Default: gpt-5.4
SKILLS_DISTILLER_DEBUG    When true, write backend debug logs
SKILLS_DISTILLER_LOG      Override distiller debug log file path
GLOBAL_MAX                Max entries in the global file   (default: 20)
SKILL_MAX                 Max entries per skill file        (default: 30)
TRANSCRIPT_LINES          How many recent transcript lines to scan (default: 300)
MIN_TOOL_CALLS            Min tool calls required to proceed (default: 5)
                          Sessions below this threshold are likely summary-only
                          and will be skipped to avoid low-quality distillation.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_core.store import merge_insight_text
from memory_core.store import merge_global_insight_text
from memory_core.distiller import get_distiller_from_env
from memory_core.transcript import (
    analyze_claude_transcript,
    load_recent_transcript_lines,
)
from runtimes.claude_runtime import locate_session_transcript

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_FILE = Path(os.environ.get("SKILLS_MEMORY_LOG", Path.home() / ".claude" / "skill-memory.log"))

def log(session_id: str, msg: str) -> None:
    """Append a single log line to skill-memory.log."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sid = session_id[:8] if session_id else "--------"
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{ts} | {sid} | {msg}\n")
    except Exception:
        pass

# ── Configuration ──────────────────────────────────────────────────────────────
SKILLS_DIR = Path(
    os.environ.get("SKILLS_KNOWLEDGE_DIR", Path.home() / ".claude" / "skills")
)
GLOBAL_KNOWLEDGE = Path(
    os.environ.get(
        "SKILLS_KNOWLEDGE_GLOBAL",
        Path.home() / ".claude" / "skills-knowledge.md",
    )
)
GLOBAL_MAX = int(os.environ.get("GLOBAL_MAX", "100"))
SKILL_MAX = int(os.environ.get("SKILL_MAX", "100"))
TRANSCRIPT_LINES = int(os.environ.get("TRANSCRIPT_LINES", "300"))
MIN_TOOL_CALLS = int(os.environ.get("MIN_TOOL_CALLS", "5"))
SEEDS_DIR = Path(os.environ.get("SKILLS_SEEDS_DIR", Path.home() / ".claude" / "error-seeds"))
STATS_FILE = Path(os.environ.get("SKILLS_STATS_FILE", Path.home() / ".claude" / "skill-usage-stats.json"))

# [Opt-5] Error/fix signal detection — used as a heuristic pre-filter for distillation.
# Only sessions containing these signals are worth distilling (avoids wasting haiku calls
# on routine sessions with no debugging/error content).
ERROR_SIGNAL_PATTERNS = re.compile(
    r'error|failed|failure|exception|traceback|bug|fix|workaround|'
    r'retry|timeout|denied|refused|rejected|deprecated|breaking|'
    r'调试|报错|失败|修复|踩坑|回退',
    re.IGNORECASE
)

def update_stats(skills: set) -> None:
    """[Opt-9] Update cross-session skill usage stats in skill-usage-stats.json."""
    try:
        stats = {}
        if STATS_FILE.exists():
            stats = json.loads(STATS_FILE.read_text(encoding="utf-8"))
        today = datetime.now().strftime("%Y-%m-%d")
        for skill in skills:
            entry = stats.setdefault(skill, {"total": 0, "last_seen": "", "daily": {}})
            entry["total"] += 1
            entry["last_seen"] = today
            entry["daily"][today] = entry["daily"].get(today, 0) + 1
        STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def ask_model(prompt: str, session_id: str) -> str:
    """Call the selected distillation backend via the shared distiller interface."""
    primary_model = os.environ.get("SKILLS_KNOWLEDGE_MODEL", "claude-haiku-4-5")
    distiller = get_distiller_from_env()
    result = distiller.distill(prompt, timeout=30)
    if result.backend == "claude-cli" and result.model and result.model != primary_model:
        log(session_id, f"FALLBACK | used model={result.model} (primary failed)")
    if result.backend != "claude-cli" and result.model:
        log(session_id, f"DISTILLER | backend={result.backend} model={result.model}")
    if result.error:
        log(session_id, f"DISTILLER_ERR | backend={result.backend} error={result.error[:180]}")
        if result.raw_preview:
            preview = result.raw_preview[:220].replace("\n", " ")
            log(session_id, f"DISTILLER_RAW | backend={result.backend} preview={preview}")
    return result.text


# ── Read hook input ────────────────────────────────────────────────────────────
try:
    hook_input = json.loads(sys.stdin.read())
except Exception:
    hook_input = {}

session_id = hook_input.get("session_id", "")
if not session_id:
    sys.exit(0)

# ── Locate session transcript ──────────────────────────────────────────────────
transcript_file = locate_session_transcript(session_id)
if not transcript_file:
    log(session_id, "SKIP | transcript not found")
    sys.exit(0)

# ── Parse transcript (last N lines) ───────────────────────────────────────────
try:
    lines = load_recent_transcript_lines(transcript_file, TRANSCRIPT_LINES)
except Exception:
    sys.exit(0)

analysis = analyze_claude_transcript(lines, error_signal_patterns=ERROR_SIGNAL_PATTERNS)
tool_uses = analysis.tool_uses
assistant_texts = analysis.assistant_texts
tool_result_texts = analysis.tool_result_texts
skill_invocations = analysis.skill_invocations
real_tool_call_count = analysis.real_tool_call_count

if real_tool_call_count < MIN_TOOL_CALLS:
    log(session_id, f"SKIP | tool_calls={real_tool_call_count} < MIN={MIN_TOOL_CALLS}")
    sys.exit(0)

has_error_signal = analysis.has_error_signal
error_snippets = analysis.error_snippets

session_seed_file = SEEDS_DIR / f"{session_id}.txt"
session_seed_text = ""
if session_seed_file.exists():
    try:
        session_seed_text = session_seed_file.read_text(encoding="utf-8").strip()[-2000:]
        session_seed_file.unlink()
        if session_seed_text and not has_error_signal:
            has_error_signal = True
        log(session_id, f"SEEDS | loaded {len(session_seed_text)} chars from session seeds")
    except Exception:
        pass

if session_seed_text:
    error_snippets = (session_seed_text + "\n" + error_snippets)[:2500]

if not skill_invocations and not has_error_signal:
    log(session_id, "SKIP | no skill invocations and no error signals")
    sys.exit(0)

log(session_id, f"START | tool_calls={real_tool_call_count} | skills={','.join(skill_invocations) or 'none'} | error_signal={has_error_signal}")

if skill_invocations:
    update_stats(skill_invocations)


# ── Update per-skill KNOWLEDGE.md files ───────────────────────────────────────
for skill_name in skill_invocations:
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.exists():
        continue

    knowledge_file = skill_dir / "KNOWLEDGE.md"
    existing = [
        ln.strip()
        for ln in knowledge_file.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("- ")
    ] if knowledge_file.exists() else []
    context = "\n".join(assistant_texts[:6])
    tools = ", ".join(set(tool_uses[:15]))

    # [Opt-2] Load error seeds captured mid-session by the inject hook
    seed_file = skill_dir / ".error_seeds"
    error_seed_text = ""
    if seed_file.exists():
        try:
            error_seed_text = seed_file.read_text(encoding="utf-8").strip()[-1200:]
            seed_file.unlink()  # Consume seeds — don't re-use next session
        except Exception:
            pass

    seed_section = (
        f"\n\nError/fix seeds captured mid-session (high-quality signals):\n{error_seed_text}"
        if error_seed_text else ""
    )

    # [Opt-5] Include error snippets from tool_result blocks for richer distillation
    snippet_section = (
        f"\n\nError snippets from tool results:\n{error_snippets}"
        if error_snippets else ""
    )

    # [Opt-5] Skip haiku call if no error signal AND no error seeds —
    # the error_seeds mechanism works independently from transcript-level signals
    if not has_error_signal and not error_seed_text:
        continue

    prompt = (
        f'You are an experience-distillation assistant. Below is a snippet of a Claude '
        f'Code session that used the "{skill_name}" skill.\n\n'
        f"Tools called: {tools}\n\n"
        f"Assistant output (excerpt):\n{context[:1500]}"
        f"{seed_section}"
        f"{snippet_section}\n\n"
        f"Already recorded (avoid duplicates):\n"
        f"{chr(10).join(existing[-10:]) if existing else '(none)'}\n\n"
        f"Extract 1-3 concrete, actionable lessons specifically about the \"{skill_name}\" "
        f"skill from this session. Requirements:\n"
        f"- Must be a real new finding: a bug, gotcha, workaround, or API detail\n"
        f"- Prefer lessons from the error/fix seeds section — they are ground truth\n"
        f"- Start each entry with '- [YYYY-MM] [Tag]' where YYYY-MM is the current month "
        f"and Tag names the specific API/feature\n"
        f"- If nothing new was found, output only: SKIP\n"
        f"Output only the bullet list or SKIP."
    )

    insights = ask_model(prompt, session_id)
    if insights and insights != "SKIP" and insights.startswith("-"):
        merge_insight_text(
            skill_name,
            insights,
            max_count=SKILL_MAX,
            target="legacy",
        )
        updated_entries = [
            ln.strip()
            for ln in knowledge_file.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith("- ")
        ] if knowledge_file.exists() else []
        log(session_id, f"UPDATED | skill={skill_name} | entries={len(updated_entries)}")
    else:
        log(session_id, f"SKIP | skill={skill_name} | haiku={insights[:40] if insights else 'empty'}")

# ── Update global cross-skill knowledge file ──────────────────────────────────
# [Opt-5] Only distill global knowledge when error signals are present AND skills were used
if has_error_signal and len(skill_invocations) > 0:
    global_existing = [
        ln.strip()
        for ln in GLOBAL_KNOWLEDGE.read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("- ")
    ] if GLOBAL_KNOWLEDGE.exists() else []
    context = "\n".join(assistant_texts[:4])

    global_prompt = (
        "You are an experience-distillation assistant reviewing a Claude Code session.\n\n"
        f"Tools called: {', '.join(set(tool_uses[:10]))}\n\n"
        f"Assistant output (excerpt):\n{context[:800]}\n\n"
        f"Current global principles (avoid duplicates):\n"
        f"{chr(10).join(global_existing)}\n\n"
        "Decide if this session produced any insight worth adding to the **global "
        "cross-skill principles** file. Criteria: applicable across multiple skills "
        "(e.g. error-handling strategy, debugging method, upload pattern) — NOT "
        "a single-API detail.\n\n"
        "If yes, output 1-2 entries starting with '- [Tag]'; otherwise output only: SKIP."
    )

    global_insights = ask_model(global_prompt, session_id)
    if global_insights and global_insights != "SKIP" and global_insights.startswith("-"):
        merge_global_insight_text(global_insights, max_count=GLOBAL_MAX)
        refreshed_global = [
            ln.strip()
            for ln in GLOBAL_KNOWLEDGE.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith("- ")
        ] if GLOBAL_KNOWLEDGE.exists() else []
        log(session_id, f"UPDATED | global | entries={len(refreshed_global)}")
    else:
        log(session_id, f"SKIP | global | haiku={global_insights[:40] if global_insights else 'empty'}")

# ── Daily update check for fireworks-skill-memory itself ──────────────────────
# [Opt-9] Once per day, check if the remote repo has updates. If so, write an
# UPDATE_AVAILABLE file so the SessionStart hook can notify the user.
UPDATE_CHECK_FILE = Path.home() / ".claude" / "skill-memory-update-check.txt"
UPDATE_AVAILABLE_FILE = Path.home() / ".claude" / "skill-memory-update-available.txt"
REPO_DIR = Path(__file__).resolve().parent.parent  # ~/.claude or fireworks-skill-memory root

def check_for_updates() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    # Only check once per day
    if UPDATE_CHECK_FILE.exists():
        if UPDATE_CHECK_FILE.read_text(encoding="utf-8").strip() == today:
            return

    # Write date marker BEFORE attempting fetch to ensure "once per day" guarantee
    # even if fetch fails/times out
    try:
        UPDATE_CHECK_FILE.write_text(today, encoding="utf-8")
    except Exception:
        return

    try:
        # Find the git repo containing this script
        script_dir = Path(__file__).resolve().parent
        # Try to find a git repo by walking up
        git_dir = script_dir
        for _ in range(4):
            if (git_dir / ".git").exists():
                break
            git_dir = git_dir.parent
        else:
            return  # no git repo found

        # Fetch remote silently with reduced timeout (5s instead of 10s)
        fetch = subprocess.run(
            ["git", "-C", str(git_dir), "fetch", "--quiet", "origin"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "ALL_PROXY": "socks5://127.0.0.1:7890"}
        )
        if fetch.returncode != 0:
            log(session_id, f"UPDATE_CHECK | fetch failed: {fetch.stderr[:100]}")
            return

        # Compare local HEAD vs remote
        local = subprocess.run(
            ["git", "-C", str(git_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=3
        ).stdout.strip()
        remote = subprocess.run(
            ["git", "-C", str(git_dir), "rev-parse", "origin/main"],
            capture_output=True, text=True, timeout=3
        ).stdout.strip()

        if local != remote:
            UPDATE_AVAILABLE_FILE.write_text(
                f"fireworks-skill-memory has updates available ({local[:7]}→{remote[:7]}).\n"
                f"Run: claude \"帮我从 github.com/yizhiyanhua-ai/fireworks-skill-memory 更新 fireworks-skill-memory\"\n",
                encoding="utf-8"
            )
            log(session_id, f"UPDATE_AVAILABLE | local={local[:7]} remote={remote[:7]}")
        else:
            # Remove stale notification if already up to date
            if UPDATE_AVAILABLE_FILE.exists():
                UPDATE_AVAILABLE_FILE.unlink()
            log(session_id, "UPDATE_CHECK | up to date")
    except Exception:
        pass

check_for_updates()
