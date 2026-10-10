#!/usr/bin/env bash
# Record a normal phone call: loudspeaker next to the computer, one microphone.
# Stop with Ctrl+C. The file is mono and is separated into speakers later.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/raw

OUT="data/raw/call_$(date +%Y%m%d_%H%M%S).wav"
OS="$(uname -s)"

list_linux_devices() {
  if command -v pactl >/dev/null 2>&1; then
    echo "Pulse/PipeWire sources:"
    pactl list short sources || true
  elif command -v arecord >/dev/null 2>&1; then
    echo "ALSA capture devices:"
    arecord -l || true
  fi
}

ffmpeg_has_demuxer() {
  local name="$1"
  ffmpeg -hide_banner -demuxers 2>/dev/null | grep -Eq "^ D[ .d]* ${name}[[:space:]]"
}

echo "Позвоните и включите громкую связь, телефон рядом с компьютером."
echo "Говорите по очереди. Остановка записи: Ctrl+C."
echo "Файл: ${OUT}"
echo

if [[ "$OS" == "Darwin" ]]; then
  DEVICE="${AUDIO_DEVICE:-0}"
  echo "Микрофон: устройство ${DEVICE} (другое — AUDIO_DEVICE=1 scripts/record_call.sh)"
  ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 \
    | sed -n '/audio devices:/,$p' | sed '/Error/d;/in#/d' || true
  echo
  ffmpeg -y -f avfoundation -i ":${DEVICE}" -ac 1 -ar 16000 -c:a pcm_s16le "$OUT" || true
else
  DEVICE="${AUDIO_DEVICE:-default}"
  echo "Микрофон: ${DEVICE} (другое — AUDIO_DEVICE=alsa_input.usb... scripts/record_call.sh)"
  list_linux_devices
  echo
  if ffmpeg_has_demuxer pulse; then
    ffmpeg -y -f pulse -i "${DEVICE}" -ac 1 -ar 16000 -c:a pcm_s16le "$OUT" || true
  elif ffmpeg_has_demuxer pipewire; then
    ffmpeg -y -f pipewire -i "${DEVICE}" -ac 1 -ar 16000 -c:a pcm_s16le "$OUT" || true
  elif ffmpeg_has_demuxer alsa; then
    ffmpeg -y -f alsa -i "${DEVICE}" -ac 1 -ar 16000 -c:a pcm_s16le "$OUT" || true
  else
    echo "ffmpeg без pulse/pipewire/alsa. Установите ffmpeg с поддержкой PulseAudio." >&2
    exit 1
  fi
fi

if [[ -f "$OUT" ]]; then
  echo
  echo "Запись сохранена: $OUT"
  echo "Проверка: .venv/bin/python scripts/check_call.py $OUT --date $(date +%F)"
fi
