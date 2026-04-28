#!/usr/bin/env bash
# fireworks-skill-memory — Codex setup helper
# Usage: ./install-codex.sh

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $*"; }
error() { echo -e "${RED}✗${NC} $*"; exit 1; }

echo ""
echo "🔥 fireworks-skill-memory Codex setup"
echo "──────────────────────────────────────"
echo ""

command -v python3 >/dev/null 2>&1 || error "Python 3 is required but not found."

CODEX_HOME_DIR="${CODEX_HOME:-}"
if [[ -z "$CODEX_HOME_DIR" ]]; then
  error "CODEX_HOME is not set. Start from a Codex environment or export CODEX_HOME first."
fi

MEMORY_HOME="$CODEX_HOME_DIR/memories/fireworks-skill-memory"
SKILLS_DIR="$MEMORY_HOME/skills"
GLOBAL_DIR="$MEMORY_HOME/global"

mkdir -p "$SKILLS_DIR" "$GLOBAL_DIR"
info "Created Codex memory directories under $MEMORY_HOME"

GLOBAL_KNOWLEDGE="$GLOBAL_DIR/KNOWLEDGE.md"
if [[ ! -f "$GLOBAL_KNOWLEDGE" ]]; then
  cat > "$GLOBAL_KNOWLEDGE" <<'EOF'
# Global Skills Principles

> **Scope**: Cross-skill principles and quality guidelines.
> Auto-maintained by fireworks-skill-memory.

## Principles

- [placeholder] No global principles recorded yet.
EOF
  info "Bootstrapped global knowledge file"
else
  warn "Global knowledge file already exists — leaving it untouched"
fi

echo ""
echo "Next commands:"
echo "  python3 cli/skill_memory.py inject --skill <skill-name>"
echo "  python3 cli/skill_memory.py checkpoint --skill <skill-name> --note \"...\""
echo "  python3 cli/skill_memory.py flush --skill <skill-name> --summary-file ./session-summary.md"
echo ""
echo "Recommended summary format:"
cat <<'EOF'
# Session Summary

## Lessons

- First distilled lesson
- Second distilled lesson
EOF
echo ""
info "Codex setup complete"
