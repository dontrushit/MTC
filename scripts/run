#!/usr/bin/env bash
# Start the API (8000) and Streamlit (8501). Ctrl+C stops both.
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PWD}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Не найден .venv. Создайте окружение и установите зависимости." >&2
  exit 1
fi

pids=()

cleanup() {
  trap - INT TERM EXIT
  local pid
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup INT TERM EXIT

echo "API: http://127.0.0.1:8000"
echo "UI:  http://127.0.0.1:8501"

export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
"$PY" -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 &
pids+=($!)
"$PY" -m streamlit run app/ui/Home.py \
  --server.port 8501 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --browser.gatherUsageStats false &
pids+=($!)

while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      exit 0
    fi
  done
  sleep 1
done
