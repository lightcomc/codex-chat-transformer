#!/usr/bin/env bash
set -euo pipefail

REPO="lightcomc/codex-chat-transformer"
BRANCH="main"
CODEX_DIR="${CODEX_DIR:-$HOME/.codex}"
FILES=(
    codex_manager_gui.py
    codex_chat_transformer.py
    codex_manager.sh
    providers_template.json
)

echo "=== Codex Chat Transformer Installer ==="
echo ""

if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "Error: Python not found. Install: https://www.python.org/downloads/"
    exit 1
fi

mkdir -p "$CODEX_DIR"

for f in "${FILES[@]}"; do
    echo "Downloading $f..."
    curl -fsSL "https://raw.githubusercontent.com/$REPO/$BRANCH/$f" -o "$CODEX_DIR/$f"
done

chmod +x "$CODEX_DIR/codex_manager.sh"

echo ""
echo "Installed to $CODEX_DIR/"
echo "Run: $CODEX_DIR/codex_manager.sh"
