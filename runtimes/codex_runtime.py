"""Codex-specific adapters for explicit memory workflows."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from memory_core.store import (
    append_checkpoint,
    clear_checkpoints,
    extract_lessons_from_text,
    load_checkpoints,
    merge_lessons,
)


@dataclass(frozen=True)
class FlushResult:
    knowledge_path: Path
    lessons: list[str]
    checkpoints_cleared: bool


def get_codex_home() -> Path | None:
    codex_home = os.environ.get("CODEX_HOME")
    if not codex_home:
        return None
    return Path(codex_home)


def get_codex_sessions_dir() -> Path | None:
    codex_home = get_codex_home()
    if not codex_home:
        return None
    return codex_home / "sessions"


def add_checkpoint(skill_name: str, note: str) -> Path:
    return append_checkpoint(skill_name, note)


def _extract_text_from_json(value: object) -> list[str]:
    chunks: list[str] = []
    if isinstance(value, str):
        chunks.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "content", "summary", "message", "output"}:
                chunks.extend(_extract_text_from_json(item))
            else:
                chunks.extend(_extract_text_from_json(item))
    elif isinstance(value, list):
        for item in value:
            chunks.extend(_extract_text_from_json(item))
    return chunks


def load_codex_source_text(
    *,
    summary_path: Path | None = None,
    session_path: Path | None = None,
    stdin_text: str | None = None,
) -> str:
    if summary_path is not None:
        if not summary_path.exists():
            raise FileNotFoundError(f"summary file not found: {summary_path}")
        return summary_path.read_text(encoding="utf-8")

    if session_path is not None:
        if not session_path.exists():
            raise FileNotFoundError(f"session file not found: {session_path}")
        raw = session_path.read_text(encoding="utf-8")
        suffix = session_path.suffix.lower()
        if suffix in {".md", ".txt"}:
            return raw
        if suffix == ".json":
            try:
                data = json.loads(raw)
                return "\n".join(_extract_text_from_json(data))
            except Exception:
                return raw
        if suffix == ".jsonl":
            chunks: list[str] = []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    chunks.extend(_extract_text_from_json(data))
                except Exception:
                    chunks.append(line)
            return "\n".join(chunks)
        return raw

    if stdin_text is not None:
        text = stdin_text.strip()
        if not text:
            raise ValueError("stdin summary text is empty")
        return text

    raise ValueError("no Codex summary source provided")


def flush_summary_to_knowledge(
    skill_name: str,
    *,
    summary_path: Path | None = None,
    session_path: Path | None = None,
    stdin_text: str | None = None,
    include_checkpoints: bool = False,
    keep_checkpoints: bool = False,
    max_lessons: int = 3,
) -> FlushResult:
    summary_text = load_codex_source_text(
        summary_path=summary_path,
        session_path=session_path,
        stdin_text=stdin_text,
    )
    lessons = extract_lessons_from_text(summary_text)

    if include_checkpoints:
        checkpoint_text = "\n".join(load_checkpoints(skill_name))
        lessons.extend(extract_lessons_from_text(checkpoint_text))

    deduped: list[str] = []
    seen: set[str] = set()
    for lesson in lessons:
        normalized = lesson.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(lesson.strip())

    if not deduped:
        raise ValueError(
            "no lesson candidates found; expected a section like '## Lessons', "
            "'## Takeaways', or '## 经验沉淀' followed by bullet or numbered items"
        )

    selected = deduped[: max(max_lessons, 1)]
    knowledge_path = merge_lessons(skill_name, selected)

    if keep_checkpoints:
        cleared = False
    else:
        clear_checkpoints(skill_name)
        cleared = True

    return FlushResult(
        knowledge_path=knowledge_path,
        lessons=selected,
        checkpoints_cleared=cleared,
    )
