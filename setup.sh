#!/usr/bin/env sh
# macOS / Linux: install uv if missing, then create .venv and install deps.
set -e
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv sync
command -v potrace >/dev/null 2>&1 || echo "note: 'brew install potrace' for trace.py's best backend"
echo "ready -> uv run clean.py --help"
