"""Claude-specific transcript and distillation adapters."""

from __future__ import annotations

import os
from pathlib import Path

from memory_core.distiller import ClaudeCliDistiller, DistillResult
from memory_core.transcript import locate_claude_transcript


def get_claude_projects_dir() -> Path:
    return Path(
        os.environ.get(
            "CLAUDE_PROJECTS_DIR",
            str(Path.home() / ".claude" / "projects"),
        )
    )


def locate_session_transcript(session_id: str) -> Path | None:
    return locate_claude_transcript(session_id, get_claude_projects_dir())


def distill_with_claude_cli(
    prompt: str,
    *,
    primary_model: str | None = None,
    timeout: int = 30,
) -> DistillResult:
    return ClaudeCliDistiller(primary_model=primary_model).distill(
        prompt,
        timeout=timeout,
    )
