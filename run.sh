#!/usr/bin/env bash
# One-command local launcher for macOS and Linux.
#
#   ./run.sh          install what is missing, build the UI, start on http://localhost:8000
#   ./run.sh --dev    same, but with the hot-reloading UI dev server on http://localhost:5173
#
# Requirements: Python 3.11+ and Node.js 20+. Settings: backend/.env (see backend/.env.example).
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"
MODE="${1:-}"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

# --- Python ---------------------------------------------------------------
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      PY="$candidate"; break
    fi
  done
fi
[ -n "$PY" ] || die "Python 3.11 or newer is required (https://www.python.org/downloads/). Set PYTHON=/path/to/python to choose one."

# --- Node.js --------------------------------------------------------------
command -v node >/dev/null 2>&1 || die "Node.js 20+ is required (https://nodejs.org)."
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 18 ] || die "Node.js $NODE_MAJOR is too old; install Node.js 20 or newer."

# --- Backend --------------------------------------------------------------
VENV="$ROOT/backend/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  say "Creating Python environment (backend/.venv) with $PY"
  "$PY" -m venv "$VENV"
fi
if [ ! -f "$VENV/.installed" ] || [ "$ROOT/backend/pyproject.toml" -nt "$VENV/.installed" ]; then
  say "Installing backend dependencies"
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  "$VENV/bin/python" -m pip install --quiet -e "$ROOT/backend[dev]"
  touch "$VENV/.installed"
fi

# --- Frontend -------------------------------------------------------------
cd "$ROOT/frontend"
if [ ! -d node_modules ] || [ package-lock.json -nt node_modules ]; then
  say "Installing frontend dependencies"
  npm ci --no-audit --no-fund
fi

if [ "$MODE" = "--dev" ]; then
  say "Starting backend on http://localhost:${PORT:-8000} and UI dev server on http://localhost:5173"
  (cd "$ROOT/backend" && exec "$VENV/bin/python" -m aisim) &
  BACKEND_PID=$!
  trap 'kill $BACKEND_PID 2>/dev/null' EXIT INT TERM
  AISIM_BACKEND="http://127.0.0.1:${PORT:-8000}" npx vite --port 5173
  exit 0
fi

if [ ! -f dist/index.html ] || [ -n "$(find src index.html package.json -newer dist/index.html -print -quit)" ]; then
  say "Building the UI"
  npm run build --silent
fi

say "Starting on http://localhost:${PORT:-8000}  (Ctrl+C to stop)"
cd "$ROOT/backend"
exec "$VENV/bin/python" -m aisim
