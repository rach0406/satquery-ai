#!/usr/bin/env bash
# SatQuery AI - one-command launcher (macOS / Linux)
#
#   ./start.sh              install if needed, then run backend + frontend
#   ./start.sh --setup      force reinstall and retrain the RS classifier
#   ./start.sh --no-frontend
#   ./start.sh --build      build the frontend, serve it from the backend
#
# Requires Python 3.10+ and Node 18+.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"; FRONTEND="$ROOT/frontend"; VENV="$ROOT/.venv"
PORT="${SATQUERY_PORT:-8000}"; FE_PORT=5173
SETUP=0; NO_FRONTEND=0; BUILD=0
for a in "$@"; do
  case "$a" in
    --setup) SETUP=1 ;;
    --no-frontend) NO_FRONTEND=1 ;;
    --build) BUILD=1 ;;
    *) echo "unknown option: $a"; exit 2 ;;
  esac
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[90m%s\033[0m\n' "$1"; }
warn() { printf '    \033[33m%s\033[0m\n' "$1"; }

printf '\n  SatQuery AI - agentic remote-sensing analysis\n'
printf '  \033[90mSIH26167 (ISRO) - Team Avengers\033[0m\n'

PY="$VENV/bin/python"
if [ ! -x "$PY" ] || [ "$SETUP" = 1 ]; then
  step "Creating the Python environment"
  command -v python3 >/dev/null || { echo "Python 3.10+ not found"; exit 1; }
  [ -d "$VENV" ] || python3 -m venv "$VENV"
  step "Installing backend dependencies"
  "$PY" -m pip install --upgrade pip --quiet
  "$PY" -m pip install -r "$BACKEND/requirements.txt" --quiet
  ok "dependencies installed"
fi

MODEL="$ROOT/data/models/eurosat_rs_classifier.pkl"
if [ ! -f "$MODEL" ] || [ "$SETUP" = 1 ]; then
  step "Adapting the scene classifier to remote-sensing imagery (EuroSAT)"
  warn "Downloads ~95 MB of real Sentinel-2 patches, trains for ~3 minutes."
  warn "The app runs without it - that tool simply reports itself unavailable."
  ( cd "$BACKEND" && "$PY" -m app.ml.train_eurosat --limit-per-class 900 ) || warn "training skipped"
else
  ok "remote-sensing classifier already trained"
fi

FE_PID=""
if [ "$NO_FRONTEND" = 0 ]; then
  if [ ! -d "$FRONTEND/node_modules" ] || [ "$SETUP" = 1 ]; then
    step "Installing frontend dependencies"
    command -v npm >/dev/null || { echo "Node 18+/npm not found"; exit 1; }
    ( cd "$FRONTEND" && npm install )
  fi
  if [ "$BUILD" = 1 ]; then
    step "Building the frontend"; ( cd "$FRONTEND" && npm run build )
    ok "built - the backend serves it at /app"
  fi
fi

step "Starting the backend"
( cd "$BACKEND" && "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" ) &
API_PID=$!
ok "backend pid $API_PID -> http://127.0.0.1:$PORT"

for _ in $(seq 1 40); do
  sleep 0.5
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then ok "backend healthy"; break; fi
done

UI="http://127.0.0.1:$PORT/"
if [ "$NO_FRONTEND" = 0 ] && [ "$BUILD" = 0 ]; then
  step "Starting the frontend dev server"
  ( cd "$FRONTEND" && npm run dev ) & FE_PID=$!
  sleep 4
  UI="http://localhost:$FE_PORT/"
fi

printf '\n  \033[32mConsole : %s\033[0m\n' "$UI"
printf '  \033[32mAPI docs: http://127.0.0.1:%s/docs\033[0m\n\n' "$PORT"
printf '  \033[90mPress Ctrl+C to stop.\033[0m\n'
command -v xdg-open >/dev/null && xdg-open "$UI" >/dev/null 2>&1 || true
command -v open >/dev/null && open "$UI" >/dev/null 2>&1 || true

cleanup() { step "Shutting down"; kill "$API_PID" 2>/dev/null || true; [ -n "$FE_PID" ] && kill "$FE_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
wait "$API_PID"
