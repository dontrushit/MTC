#!/usr/bin/env bash
# Start the API (8000), Streamlit (8501), and the Telegram bot. Ctrl+C stops all.
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PWD}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Не найден .venv. Создайте окружение и установите зависимости." >&2
  exit 1
fi


# Останавливаем прошлые экземпляры этого проекта, если они остались.
kill_own() {
  local pattern="$1"
  local pid
  for pid in $(pgrep -f "$pattern" 2>/dev/null); do
    kill "$pid" 2>/dev/null || true
  done
}
kill_own "uvicorn app.api.main:app"
kill_own "streamlit run app/ui/Home[.]py"
kill_own "scripts/tg_bot[.]py"
sleep 1
# Если порт всё ещё занят — это не наш процесс: показываем его и выходим.
if command -v lsof >/dev/null 2>&1; then
  pid=$(lsof -ti :8000 2>/dev/null | head -1)
  if [[ -n "${pid:-}" ]]; then
    echo "Порт 8000 занят процессом PID=${pid} — это не наш запуск. Остановите его или смените порт." >&2
    ps o pid,command -p "$pid" | tail -1 >&2 || true
    exit 1
  fi
fi
# Конец предочистки.

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
echo "Bot: включится при заданном TELEGRAM_BOT_TOKEN"

export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
"$PY" -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 &
pids+=($!)
"$PY" -m streamlit run app/ui/Home.py \
  --server.port 8501 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --browser.gatherUsageStats false &
pids+=($!)
"$PY" scripts/tg_bot.py &
pids+=($!)

while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      exit 0
    fi
  done
  sleep 1
done
