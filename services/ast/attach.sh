#!/usr/bin/env bash
# ============================================================
#  attach.sh — привязать доставку записей звонков к ЭТОМУ устройству.
#
#  Запускается НА УСТРОЙСТВЕ, где поднят основной проект (ИИ-агент):
#  на вашем ПК или на MacBook друга — кто поднял, к тому и летят записи.
#
#  Что делает:
#    1. Определяет tailscale-IP этого устройства
#    2. По SSH обновляет WEBHOOK_URL на сервере и перезапускает notifier
#    3. Проверяет, что сервер достучался до основного проекта
#
#  Требования: tailscale, ssh-доступ к серверу (ssh-copy-id), основной
#  проект, слушающий на 0.0.0.0:${AGENT_PORT}.
#
#  Использование:
#    ./attach.sh                 # привязать это устройство
#    SERVER=user@host ./attach.sh  # нестандартный сервер
# ============================================================
set -euo pipefail

SERVER="${SERVER:-admin@100.91.32.58}"
AGENT_PORT="${AGENT_PORT:-8000}"
AGENT_PATH="${AGENT_PATH:-/api/v1/process-audio}"

command -v tailscale >/dev/null 2>&1 || { echo "Ошибка: tailscale не установлен"; exit 1; }
MY_IP=$(tailscale ip -4 | head -1)
URL="http://${MY_IP}:${AGENT_PORT}${AGENT_PATH}"

echo "Устройство: $(hostname) (${MY_IP})"
echo "Целевой URL основного проекта: ${URL}"

# Предупреждение, если основной проект ещё не слушает порт локально
if ! curl -s -o /dev/null --max-time 3 "http://127.0.0.1:${AGENT_PORT}" 2>/dev/null; then
  echo "ВНИМАНИЕ: на этом устройстве порт ${AGENT_PORT} пока никто не слушает."
  echo "          Запустите основной проект (на 0.0.0.0), записи уйдут, как только он ответит."
fi

echo "Обновляю WEBHOOK_URL на сервере ${SERVER}..."
ssh "$SERVER" "cd ~/ASTService && \
  (grep -q '^WEBHOOK_URL=' .env && sed -i 's|^WEBHOOK_URL=.*|WEBHOOK_URL=${URL}|' .env \
   || echo 'WEBHOOK_URL=${URL}' >> .env) && \
  docker compose up -d recorder-notifier >/dev/null && \
  echo 'WEBHOOK_URL на сервере:' && grep '^WEBHOOK_URL=' .env"

# Проверка достижимости основного проекта с сервера
echo "Проверка достижимости с сервера..."
CODE=$(ssh "$SERVER" "curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X POST -d '{}' '${URL}' 2>/dev/null || echo 000")
case "$CODE" in
  000) echo "НЕ ДОСТУПНО: сервер не смог подключиться к ${URL} (проект не поднят / слушает не на 0.0.0.0 / файрвол). Записи будут копиться и уйдут автоматически, когда эндпоинт ответит." ;;
  *)   echo "ДОСТУПНО (HTTP ${CODE}): записи будут отправляться на это устройство." ;;
esac
