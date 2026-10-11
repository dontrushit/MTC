#!/bin/sh
# ============================================================
#  Триггер завершения звонка (вызывается из hangup handler'а).
#  Пишет <base>.meta.json рядом с файлами записи — его подхватывает
#  recorder-notifier и отправляет вебхук ИИ-агенту.
#
#  Использование:
#    call-meta.sh <base> <caller> <callee> <uniqueid> <dialstatus> <answeredtime>
# ============================================================

BASE="$1"; CALLER="$2"; CALLEE="$3"; CALL_ID="$4"; DIAL="$5"; ANSW="$6"

# Метаданные нужны только для состоявшихся (отвеченных) звонков:
# без моста MixMonitor не создаёт файлов.
[ -f "${BASE}_mix.wav" ] || exit 0

cat > "${BASE}.meta.json" <<EOF
{
  "call_id": "${CALL_ID}",
  "caller": "${CALLER}",
  "callee": "${CALLEE}",
  "dial_status": "${DIAL}",
  "answered_seconds": "${ANSW}",
  "finished_at": $(date +%s),
  "files": {
    "mixed": "${BASE}_mix.wav",
    "caller_mono": "${BASE}_caller.wav",
    "callee_mono": "${BASE}_callee.wav"
  }
}
EOF
