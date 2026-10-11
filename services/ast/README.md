# Демонстрационная локальная АТС для ИИ-агента фиксации договорённостей

Легковесная АТС на Asterisk (PJSIP) в Docker: два внутренних SIP-аккаунта,
автоматическая запись всех звонков между ними (моно-микс + раздельные дорожки
абонентов + стерео-wav) и вебхук ИИ-агенту после завершения звонка.

## Архитектура

```
Android (Linphone) ──┐
                     │  Tailscale / LAN          ┌────────────────────────────┐
iPhone (Zoiper) ─────┼──► 5060/udp + RTP ───────►│  asterisk (Docker)         │
                     │                           │  - pjsip: 11111, 11119     │
                     │                           │  - MixMonitor: автозапись  │
                     │                           │  - hangup handler:         │
                     │                           │    call-meta.sh -> .json   │
                     │                           └──────────┬─────────────────┘
                     │                                      │ пишет в общий том
                     │                                      ▼
                     │                           ┌────────────────────────────┐
                     │                           │ recorder-notifier (Docker) │
                     │                           │  - ждёт *.meta.json        │
                     │                           │  - склеивает стерео-wav    │
                     │                           │  - HTTP POST вебхук ───────┼──► ИИ-агент
                     │                           └────────────────────────────┘    :8000
                     │
                     ▼
        ./audio_records/  ← общая папка записей (забирает ИИ-агент)
```

Структура проекта:

```
ASTService/
├── docker-compose.yml          # два сервиса: asterisk + recorder-notifier
├── attach.sh                   # привязка доставки записей к текущему устройству
├── .env.example                # шаблон переменных (PUID/PGID, WEBHOOK_URL)
├── asterisk/
│   ├── conf/
│   │   ├── pjsip.conf          # транспорт + экстеншены 11111 / 11119
│   │   ├── extensions.conf     # диалплан: звонки + автозапись + hangup-триггер
│   │   ├── rtp.conf            # диапазон RTP-портов
│   │   ├── modules.conf        # минимальный набор модулей
│   │   └── logger.conf         # логи в консоль (docker logs)
│   └── scripts/
│       └── call-meta.sh        # триггер hangup: пишет метаданные звонка
├── notifier/
│   └── notifier.py             # стерео-склейка + отправка записей ИИ-агенту
└── audio_records/              # записи звонков (создаётся при запуске)
```

## Куда уходят записи

Записи отправляются на то устройство, **с которого подняли сервис**.
На устройстве с основным проектом (ИИ-агентом) выполните:

```bash
./attach.sh        # привязать это устройство как получателя записей
```

Скрипт сам определит tailscale-IP устройства, обновит `WEBHOOK_URL` на сервере
и проверит достижимость основного проекта. Запуск на ПК — записи идут на ПК,
друг запустил `./attach.sh` на своём MacBook — записи идут на MacBook.
Требования: tailscale, ssh-доступ к серверу (`ssh-copy-id admin@100.91.32.58`),
основной проект слушает на `0.0.0.0:8000`.
```

## 1. Установка Docker (если ещё не установлен)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # после этого перелогиньтесь
```

## 2. Получение проекта на сервер

```bash
# вариант 1: git
git clone <URL-вашего-репозитория> ASTService && cd ASTService

# вариант 2: скопировать папку с машины, где файлы уже созданы
# scp -r ASTService/ user@server:~/ && ssh user@server
```

## 3. Настройка и запуск (одной командой)

```bash
cd ASTService
mkdir -p audio_records
printf 'PUID=%s\nPGID=%s\n' "$(id -u)" "$(id -g)" > .env
docker compose up -d
```

Если ИИ-агент слушает не на `:8000` — добавьте перед запуском:

```bash
# WEBHOOK_URL обычно не нужен вручную — его выставляет ./attach.sh
```

## 4. Проверка статуса

```bash
docker compose ps                                   # оба контейнера Up/healthy
docker compose logs -f asterisk                     # логи АТС (Ctrl+C для выхода)
docker compose exec asterisk asterisk -rx "pjsip show endpoints"   # 2 эндпоинта, Avail
docker compose logs -f recorder-notifier            # логи обработчика записей
```

## 5. Подключение мобильных SIP-клиентов

Узнайте IP сервера в Tailscale:

```bash
tailscale ip -4        # например 100.64.15.23
```

В **Linphone** (Android) и **Zoiper** (iPhone) создайте SIP-аккаунты:

| Параметр        | Абонент А (Android) | Абонент Б (iPhone)   |
|-----------------|---------------------|----------------------|
| Логин / user    | `11111`             | `11119`              |
| Пароль          | `Dm0-1111x-K7qZ`    | `Dm0-1119x-P4wN`     |
| Домен / сервер  | `100.64.15.23`      | `100.64.15.23`       |
| Порт            | `5060`              | `5060`               |
| Транспорт       | UDP                 | UDP                  |

> Пароли демонстрационные — смените их в `asterisk/conf/pjsip.conf`
> и выполните `docker compose restart asterisk`.

Проверка регистрации: `docker compose exec asterisk asterisk -rx "pjsip show contacts"`.

## 6. Тестовый звонок и записи

1. Позвоните с `11111` на `11119`, поговорите, завершите звонок.
2. Через ~5 секунд в `./audio_records/` появятся файлы:

```bash
ls -lh audio_records/
# 20261010-142233_11111_to_11119_mix.wav      — моно-микс обоих голосов
# 20261010-142233_11111_to_11119_caller.wav   — моно: голос абонента А
# 20261010-142233_11111_to_11119_callee.wav   — моно: голос абонента Б
# 20261010-142233_11111_to_11119_stereo.wav   — стерео: L=А, R=Б
# 20261010-142233_11111_to_11119.meta.json    — метаданные звонка
# 20261010-142233_11111_to_11119.sent         — маркер «вебхук отправлен»
```

Вебхук — `HTTP POST multipart/form-data` на `WEBHOOK_URL`
(по умолчанию `http://<macbook-tailscale-ip>:8000/api/v1/process-audio`):

- поле **`metadata`** — JSON-строка с метаданными звонка:

```json
{
  "call_id": "1731...0001",
  "caller": "11111",
  "callee": "11119",
  "dial_status": "ANSWER",
  "answered_seconds": "42",
  "finished_at": 1760101353,
  "record_dir": "/audio_records",
  "files": {
    "mixed": "/audio_records/20261010-142233_11111_to_11119_mix.wav",
    "caller_mono": "/audio_records/20261010-142233_11111_to_11119_caller.wav",
    "callee_mono": "/audio_records/20261010-142233_11111_to_11119_callee.wav",
    "stereo": "/audio_records/20261010-142233_11111_to_11119_stereo.wav"
  }
}
```

- аудиофайлы — полями `mixed`, `caller_mono`, `callee_mono`, `stereo`
  (прикладываются существующие; `stereo` — при включённой склейке).

Пример приёмника на FastAPI (на устройстве-получателе):

```python
from fastapi import FastAPI, Form, UploadFile, File
import json

app = FastAPI()

@app.post("/api/v1/process-audio")
async def process_audio(metadata: str = Form(...),
                        mixed: UploadFile | None = File(None),
                        caller_mono: UploadFile | None = File(None),
                        callee_mono: UploadFile | None = File(None),
                        stereo: UploadFile | None = File(None)):
    meta = json.loads(metadata)
    # ... локальная модель: транскрипция + фиксация договорённостей
    return {"ok": True}
```

Слушать нужно на `0.0.0.0:8000`, чтобы сервер достучался до устройства через
Tailscale. Если приёмник офлайн — записи накапливаются в `audio_records/`
на сервере и уходят автоматически, когда приёмник снова доступен.

## 7. Обслуживание

```bash
docker compose restart asterisk            # перезапуск после правки pjsip.conf
docker compose exec asterisk asterisk -rx "dialplan reload"   # перечитать диалплан
docker compose down && docker compose up -d                  # полный перезапуск
```

## 8. Troubleshooting

- **Клиент не регистрируется** — проверьте, что порт `5060/udp` доступен с
  устройства (`tailscale ping <server>`), и логин/пароль из `pjsip.conf`.
- **Звонок соединяется, но нет звука** — убедитесь, что `10000-10100/udp`
  не блокируется (в Tailscale обычно не блокируется) и диапазон совпадает
  в `asterisk/conf/rtp.conf` и `docker-compose.yml`.
- **Записи не появляются / permission denied** — проверьте `PUID`/`PGID` в
  `.env` (`id -u`, `id -g`) и выполните `docker compose up -d` заново.
- **Вебхук не уходит** — смотрите `docker compose logs -f recorder-notifier`;
  проверьте, что ИИ-агент доступен на `WEBHOOK_URL`.
- **Вебхук на агент на хосте: `urlopen error timed out`** — файрвол хоста режет
  трафик из docker-сетей. Разрешите docker-подсети (`ufw allow from 172.16.0.0/12
  to any port 8000`) либо запустите ИИ-агент как сервис в этом же
  `docker-compose.yml` и укажите `WEBHOOK_URL=http://<имя-сервиса>:8000/...`.
