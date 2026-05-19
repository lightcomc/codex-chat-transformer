#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "Python not found. Install: https://www.python.org/downloads/"
    read -rp "Press Enter to exit"
    exit 1
fi

PYTHON="python3"
command -v python3 &>/dev/null || PYTHON="python"

exec "$PYTHON" "$DIR/codex_manager_gui.py" "$@"
