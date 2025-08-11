#!/usr/bin/env bash
set -euo pipefail

MODE=${1:-}
ACTION=${2:-start}
CONFIG=${3:-}

if [[ -z "$MODE" || ("$MODE" != "spot") ]]; then
  echo "Usage: $0 spot [start|stop|tail] [config_path]"
  exit 1
fi

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROJECT_DIR="$REPO_ROOT/pionex_futures_bot"
LOGS_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOGS_DIR"

if [[ -z "$CONFIG" ]]; then
  CONFIG="$PROJECT_DIR/config/config.json"
fi

cd "$REPO_ROOT"

if [[ ! -d "$PROJECT_DIR/.venv" ]]; then
  python3 -m venv "$PROJECT_DIR/.venv"
fi

source "$PROJECT_DIR/.venv/bin/activate"
python -m pip install --upgrade pip >/dev/null
if [[ -f "$PROJECT_DIR/requirements.txt" ]]; then
  pip install -r "$PROJECT_DIR/requirements.txt" >/dev/null
fi

if [[ ! -f "$PROJECT_DIR/.env" && -f "$PROJECT_DIR/env.example" ]]; then
  cp "$PROJECT_DIR/env.example" "$PROJECT_DIR/.env"
fi

JOB_NAME="pionex_spot"
LOG_FILE="$LOGS_DIR/bot_dryrun.log"

case "$ACTION" in
  start)
    nohup bash -lc "source '$PROJECT_DIR/.venv/bin/activate' && python -m pionex_futures_bot spot --config '$CONFIG'" >"$LOG_FILE" 2>&1 &
    disown || true
    echo "Started $MODE. Logs: $LOG_FILE"
    ;;
  stop)
    # Best effort: find python -m pionex_futures_bot processes
    pkill -f "pionex_futures_bot spot" || true
    echo "Stopped $MODE (best-effort)"
    ;;
  tail)
    if [[ -f "$LOG_FILE" ]]; then
      tail -n 80 -f "$LOG_FILE"
    else
      echo "Log file not found: $LOG_FILE"
    fi
    ;;
  *)
    echo "Unknown action: $ACTION"
    exit 1
    ;;
esac


