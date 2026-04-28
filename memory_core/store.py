#!/usr/bin/env python3
"""Shared storage primitives for Claude/Codex skill memory."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class MemoryPaths:
    memory_home: Path
    skills_dir: Path
    global_file: Path
    legacy_skills_dir: Path


def _expand_path(value: str) -> Path:
    return Path(os.path.expanduser(value)).resolve()


def get_paths() -> MemoryPaths:
    configured_home = os.environ.get("AI_MEMORY_HOME")
    if configured_home:
        memory_home = _expand_path(configured_home)
    else:
        codex_home = os.environ.get("CODEX_HOME")
        if codex_home:
            memory_home = _expand_path(
                str(Path(codex_home) / "memories" / "fireworks-skill-memory")
            )
        else:
            memory_home = _expand_path("~/.ai-memory")
    skills_dir = _expand_path(
        os.environ.get("AI_MEMORY_SKILLS_DIR", str(memory_home / "skills"))
    )
    global_file = _expand_path(
        os.environ.get(
            "AI_MEMORY_GLOBAL_FILE",
            str(memory_home / "global" / "KNOWLEDGE.md"),
        )
    )
    legacy_skills_dir = _expand_path(
        os.environ.get("SKILLS_KNOWLEDGE_DIR", "~/.claude/skills")
    )
    return MemoryPaths(
        memory_home=memory_home,
        skills_dir=skills_dir,
        global_file=global_file,
        legacy_skills_dir=legacy_skills_dir,
    )


def _normalize_skill_name(skill_name: str) -> str:
    name = skill_name.strip()
    if not name:
        raise ValueError("skill name must not be empty")
    return name.replace("/", "__")


def _skill_dir(skill_name: str, create: bool = False) -> Path:
    paths = get_paths()
    skill_dir = paths.skills_dir / _normalize_skill_name(skill_name)
    if create:
        skill_dir.mkdir(parents=True, exist_ok=True)
    return skill_dir


def _legacy_skill_dir(skill_name: str) -> Path:
    paths = get_paths()
    return paths.legacy_skills_dir / _normalize_skill_name(skill_name)


def _knowledge_path(skill_name: str, prefer_legacy: bool = False) -> Path:
    primary = _skill_dir(skill_name) / "KNOWLEDGE.md"
    legacy = _legacy_skill_dir(skill_name) / "KNOWLEDGE.md"
    if prefer_legacy and legacy.exists():
        return legacy
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


def resolve_skill_knowledge_path(skill_name: str, target: str = "auto") -> Path:
    if target == "legacy":
        path = _legacy_skill_dir(skill_name) / "KNOWLEDGE.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    if target == "shared":
        path = _skill_dir(skill_name, create=True) / "KNOWLEDGE.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    path = _knowledge_path(skill_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _checkpoints_path(skill_name: str) -> Path:
    return _skill_dir(skill_name, create=True) / "CHECKPOINTS.md"


def read_entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- ")
    ]


def load_knowledge_text(skill_name: str) -> str:
    path = _knowledge_path(skill_name, prefer_legacy=True)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_checkpoints(skill_name: str) -> list[str]:
    path = _checkpoints_path(skill_name)
    return read_entries(path)


def clear_checkpoints(skill_name: str) -> Path:
    path = _checkpoints_path(skill_name)
    header = (
        f"# {skill_name} — checkpoints\n\n"
        f"> Raw notes captured during Codex/Claude work.\n\n"
    )
    path.write_text(header, encoding="utf-8")
    return path


def _get_hit_count(entry: str) -> int:
    match = re.search(r"\[HIT:(\d+)\]", entry)
    return int(match.group(1)) if match else 0


def _set_hit_count(entry: str, count: int) -> str:
    tag = f"[HIT:{count}]"
    if re.search(r"\[HIT:\d+\]", entry):
        return re.sub(r"\[HIT:\d+\]", tag, entry)
    return f"{entry}  {tag}"


def _ensure_timestamp(entry: str) -> str:
    if re.search(r"\[\d{4}-\d{2}\]", entry):
        return entry
    return f"[{datetime.now().strftime('%Y-%m')}] {entry}"


def _render_knowledge(skill_name: str, entries: list[str]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    body = "\n".join(entries) if entries else "- [placeholder] No lessons recorded yet."
    return (
        f"# {skill_name} — experience\n\n"
        f"> Shared cross-session lessons for `{skill_name}`.\n"
        f"> Auto-maintained by fireworks-skill-memory. Last updated: {today}\n\n"
        f"## Entries\n\n"
        f"{body}\n"
    )


def _render_global_knowledge(entries: list[str]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    body = "\n".join(entries) if entries else "- [placeholder] No global principles recorded yet."
    return (
        "# Global Skills Principles\n\n"
        "> **Scope**: Cross-skill principles and quality guidelines.\n"
        "> For skill-specific API details, see each skill's `KNOWLEDGE.md`.\n"
        f"> Auto-maintained. Last updated: {today}\n\n"
        "## Principles\n\n"
        f"{body}\n"
    )


def _get_entry_age_months(entry: str) -> float:
    match = re.search(r"\[(\d{4})-(\d{2})\]", entry)
    if not match:
        return 999.0
    try:
        entry_year, entry_month = int(match.group(1)), int(match.group(2))
        now = datetime.now()
        age_months = (now.year - entry_year) * 12 + (now.month - entry_month)
        return max(0.0, float(age_months))
    except (ValueError, OverflowError):
        return 999.0


def _evict_entries(entries: list[str], max_count: int) -> list[str]:
    if len(entries) <= max_count:
        return entries
    overflow = len(entries) - max_count

    def eviction_score(entry: str, index: int) -> tuple[float, int]:
        hits = _get_hit_count(entry)
        age = _get_entry_age_months(entry)
        age_penalty = max(0.0, (age - 3.0) * 0.5)
        return (hits - age_penalty, index)

    indexed = sorted(
        enumerate(entries),
        key=lambda item: eviction_score(item[1], item[0]),
    )
    evict_indices = {index for index, _ in indexed[:overflow]}
    return [entry for index, entry in enumerate(entries) if index not in evict_indices]


def _merge_entry_lines(existing: list[str], lines: list[str]) -> list[str]:
    for lesson in lines:
        line = lesson.strip()
        if not line:
            continue
        if not line.startswith("- "):
            line = f"- {line}"
        key = line[2:].lower()
        matched = False
        for index, current in enumerate(existing):
            if key[:32] and key[:32] in current.lower():
                existing[index] = _set_hit_count(current, _get_hit_count(current) + 1)
                matched = True
                break
        if not matched:
            body = _ensure_timestamp(line[2:])
            existing.append(f"- {body}  [HIT:1]")
    return existing


def build_injection_text(skill_name: str, top_n: int = 20) -> str:
    selected = select_injection_entries(skill_name, top_n=top_n)
    if not selected:
        return ""
    body = "\n".join(selected)
    return (
        f"[fireworks-skill-memory: {skill_name}]\n\n"
        f"Past experience:\n"
        f"{body}\n"
    )


def select_injection_entries(skill_name: str, top_n: int = 20) -> list[str]:
    entries = read_entries(_knowledge_path(skill_name, prefer_legacy=True))
    if not entries:
        return []
    ranked = sorted(entries, key=_get_hit_count, reverse=True)
    return ranked[: max(top_n, 1)]


def merge_lessons(skill_name: str, lessons: list[str]) -> Path:
    if not lessons:
        raise ValueError("lessons must not be empty")

    path = resolve_skill_knowledge_path(skill_name)
    entries = read_entries(path)
    entries = _merge_entry_lines(entries, lessons)
    max_count = int(os.environ.get("SKILL_MAX", "100"))
    entries = _evict_entries(entries, max_count)
    path.write_text(_render_knowledge(skill_name, entries), encoding="utf-8")
    return path


def merge_insight_text(
    skill_name: str,
    insights_text: str,
    max_count: int = 100,
    target: str = "auto",
) -> Path:
    lines = [
        line.strip()
        for line in insights_text.splitlines()
        if line.strip().startswith("- ")
    ]
    if not lines:
        raise ValueError("insights_text must contain bullet entries")

    path = resolve_skill_knowledge_path(skill_name, target=target)
    entries = read_entries(path)
    entries = _merge_entry_lines(entries, lines)
    entries = _evict_entries(entries, max_count)
    path.write_text(_render_knowledge(skill_name, entries), encoding="utf-8")
    return path


def merge_global_insight_text(insights_text: str, max_count: int = 100) -> Path:
    lines = [
        line.strip()
        for line in insights_text.splitlines()
        if line.strip().startswith("- ")
    ]
    if not lines:
        raise ValueError("insights_text must contain bullet entries")

    paths = get_paths()
    path = paths.global_file
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = read_entries(path)
    entries = _merge_entry_lines(entries, lines)
    entries = _evict_entries(entries, max_count)
    path.write_text(_render_global_knowledge(entries), encoding="utf-8")
    return path


def append_checkpoint(skill_name: str, note: str) -> Path:
    clean_note = note.strip()
    if not clean_note:
        raise ValueError("checkpoint note must not be empty")

    path = _checkpoints_path(skill_name)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not path.exists():
        header = (
            f"# {skill_name} — checkpoints\n\n"
            f"> Raw notes captured during Codex/Claude work.\n\n"
        )
        path.write_text(header, encoding="utf-8")

    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{timestamp}] {clean_note}\n")
    return path


def extract_lessons_from_text(text: str) -> list[str]:
    lessons: list[str] = []
    seen: set[str] = set()
    in_lessons_section = False
    current_section_level = 0
    section_markers = (
        "lessons",
        "takeaways",
        "insights",
        "经验",
        "教训",
        "沉淀",
        "总结",
    )

    def add_lesson(raw: str) -> None:
        candidate = " ".join(raw.strip().split())
        if not candidate:
            return
        candidate = re.sub(r"^[-*]\s*", "", candidate)
        candidate = re.sub(r"^\d+\.\s*", "", candidate)
        lowered = candidate.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        lessons.append(candidate)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading_match:
            current_section_level = len(heading_match.group(1))
            normalized = heading_match.group(2).strip(" :").lower()
            in_lessons_section = any(marker in normalized for marker in section_markers)
            continue

        if in_lessons_section and re.match(r"^#{1,6}\s+", line):
            in_lessons_section = False
            current_section_level = 0
            continue

        if not in_lessons_section and current_section_level == 0:
            continue

        if not in_lessons_section:
            continue

        if line.startswith("- ") or line.startswith("* "):
            add_lesson(line)
            continue
        if re.match(r"^\d+\.\s+", line):
            add_lesson(line)
            continue
        if in_lessons_section:
            compact = " ".join(line.split())
            if 12 <= len(compact) <= 220:
                add_lesson(compact)

    return lessons
