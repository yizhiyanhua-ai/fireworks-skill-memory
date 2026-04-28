#!/usr/bin/env python3
"""Minimal CLI for shared Claude/Codex skill memory."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_core.store import (
    build_injection_text,
    load_knowledge_text,
)
from runtimes.codex_runtime import add_checkpoint, flush_summary_to_knowledge


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-memory",
        description="Shared skill-memory CLI for Claude Code and Codex.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inject = subparsers.add_parser(
        "inject",
        help="Print experience text for a skill.",
    )
    inject.add_argument("--skill", required=True, help="Skill name to load.")
    inject.add_argument(
        "--top",
        type=int,
        default=int(os.environ.get("SKILLS_INJECT_TOP", "20")),
        help="Maximum number of ranked entries to include.",
    )

    checkpoint = subparsers.add_parser(
        "checkpoint",
        help="Append a raw checkpoint note for a skill.",
    )
    checkpoint.add_argument("--skill", required=True, help="Skill name to update.")
    checkpoint.add_argument("--note", required=True, help="Checkpoint note to append.")

    show = subparsers.add_parser(
        "show",
        help="Print a skill's current knowledge file.",
    )
    show.add_argument("--skill", required=True, help="Skill name to show.")

    flush = subparsers.add_parser(
        "flush",
        help="Distil explicit lesson sections from a summary back into KNOWLEDGE.md.",
    )
    flush.add_argument("--skill", required=True, help="Skill name to update.")
    source_group = flush.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--summary-file",
        help="Path to a prepared session summary.",
    )
    source_group.add_argument(
        "--session-file",
        help="Path to a Codex session export or transcript file (.md/.txt/.json/.jsonl).",
    )
    source_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read summary text from stdin.",
    )
    flush.add_argument(
        "--include-checkpoints",
        action="store_true",
        help="Also extract lesson candidates from CHECKPOINTS.md.",
    )
    flush.add_argument(
        "--max-lessons",
        type=int,
        default=3,
        help="Maximum number of distilled lessons to merge into KNOWLEDGE.md.",
    )
    flush.add_argument(
        "--keep-checkpoints",
        action="store_true",
        help="Do not clear CHECKPOINTS.md after a successful merge.",
    )

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "inject":
        text = build_injection_text(args.skill, top_n=args.top)
        if not text:
            print(f"[fireworks-skill-memory] No knowledge found for skill: {args.skill}", file=sys.stderr)
            return 1
        print(text)
        return 0

    if args.command == "checkpoint":
        path = add_checkpoint(args.skill, args.note)
        print(path)
        return 0

    if args.command == "show":
        text = load_knowledge_text(args.skill)
        if not text:
            print(f"[fireworks-skill-memory] No knowledge found for skill: {args.skill}", file=sys.stderr)
            return 1
        print(text)
        return 0

    if args.command == "flush":
        summary_path = (
            Path(args.summary_file).expanduser().resolve()
            if args.summary_file else None
        )
        session_path = (
            Path(args.session_file).expanduser().resolve()
            if args.session_file else None
        )
        stdin_text = sys.stdin.read() if args.stdin else None
        try:
            result = flush_summary_to_knowledge(
                args.skill,
                summary_path=summary_path,
                session_path=session_path,
                stdin_text=stdin_text,
                include_checkpoints=args.include_checkpoints,
                keep_checkpoints=args.keep_checkpoints,
                max_lessons=args.max_lessons,
            )
        except FileNotFoundError:
            missing_path = summary_path or session_path
            print(f"[fireworks-skill-memory] Source file not found: {missing_path}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"[fireworks-skill-memory] {exc}", file=sys.stderr)
            return 1

        print(result.knowledge_path)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
