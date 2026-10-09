#!/usr/bin/env bash
# Record a normal phone call: loudspeaker next to the computer, one microphone.
# Stop with Ctrl+C. The file is mono and is separated into speakers later.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/raw

DEVICE="${AUDIO_DEVICE:-0}"
OUT="data/raw/call_$(date +%Y%m%d_%H%M%S).wav"

echo "Микрофон: устройство ${DEVICE} (другое — AUDIO_DEVICE=1 scripts/record_call.sh)"
ffmpeg -f avfoundation -list_devices true -i "" 2>&1 | sed -n '/audio devices:/,$p' | sed '/video devices:/d'
echo
echo "Позвоните и включите громкую связь, телефон рядом с компьютером."
echo "Говорите по очереди. Остановка записи: Ctrl+C."
echo "Файл: ${OUT}"
echo

ffmpeg -y -f avfoundation -i ":${DEVICE}" -ac 1 -ar 16000 -c:a pcm_s16le "$OUT" || true

if [[ -f "$OUT" ]]; then
  echo
  echo "Запись сохранена: $OUT"
  echo "Проверка: .venv/bin/python scripts/check_call.py $OUT --date $(date +%F)"
fi
