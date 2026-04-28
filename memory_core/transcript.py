"""Transcript parsing helpers for Claude-style session logs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ERROR_SIGNAL_PATTERNS = re.compile(
    r"error|failed|failure|exception|traceback|bug|fix|workaround|"
    r"retry|timeout|denied|refused|rejected|deprecated|breaking|"
    r"调试|报错|失败|修复|踩坑|回退",
    re.IGNORECASE,
)

DEFAULT_SKILL_PATH_PATTERNS = (
    r"/.claude/skills/([^/]+)/",
    r"/.skills/([^/]+)/",
    r"/.agents/skills/([^/]+)/",
)


@dataclass(frozen=True)
class TranscriptAnalysis:
    tool_uses: list[str]
    assistant_texts: list[str]
    tool_result_texts: list[str]
    skill_invocations: set[str]
    real_tool_call_count: int
    has_error_signal: bool
    error_snippets: str


def locate_claude_transcript(session_id: str, projects_dir: Path) -> Path | None:
    if not session_id or not projects_dir.exists():
        return None
    for proj_dir in projects_dir.iterdir():
        candidate = proj_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate
    return None


def load_recent_transcript_lines(transcript_file: Path, transcript_lines: int) -> list[str]:
    return transcript_file.read_text(encoding="utf-8", errors="ignore").splitlines()[
        -transcript_lines:
    ]


def analyze_claude_transcript(
    lines: list[str],
    *,
    error_signal_patterns=DEFAULT_ERROR_SIGNAL_PATTERNS,
    skill_path_patterns=DEFAULT_SKILL_PATH_PATTERNS,
) -> TranscriptAnalysis:
    tool_uses: list[str] = []
    assistant_texts: list[str] = []
    tool_result_texts: list[str] = []
    skill_invocations: set[str] = set()
    real_tool_call_count = 0

    for raw in lines:
        try:
            entry = json.loads(raw)
            msg = entry.get("message", {})
            role = msg.get("role", "")
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if role == "assistant" and btype == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    tool_uses.append(name)
                    real_tool_call_count += 1
                    if name == "Skill":
                        skill_name = inp.get("skill", "")
                        if skill_name:
                            skill_invocations.add(skill_name)
                    elif name == "Read":
                        file_path = inp.get("file_path", "")
                        for pattern in skill_path_patterns:
                            match = re.search(
                                pattern.replace("([^/]+)/", r"([^/]+)/SKILL\.md"),
                                file_path,
                            )
                            if match:
                                skill_invocations.add(match.group(1))
                                break
                elif role == "assistant" and btype == "text":
                    text = block.get("text", "")
                    if len(text) > 80:
                        assistant_texts.append(text[:400])
                elif btype == "tool_result" or (role == "tool" and btype == "text"):
                    text = block.get("text", "")
                    if text:
                        tool_result_texts.append(text[:400])
        except Exception:
            continue

    all_text = " ".join(tool_uses + assistant_texts + tool_result_texts)
    has_error_signal = bool(error_signal_patterns.search(all_text))
    error_snippets = ""
    if has_error_signal:
        snippets = [text for text in tool_result_texts if error_signal_patterns.search(text)]
        error_snippets = "\n".join(snippets[:5])[:1500]

    return TranscriptAnalysis(
        tool_uses=tool_uses,
        assistant_texts=assistant_texts,
        tool_result_texts=tool_result_texts,
        skill_invocations=skill_invocations,
        real_tool_call_count=real_tool_call_count,
        has_error_signal=has_error_signal,
        error_snippets=error_snippets,
    )
