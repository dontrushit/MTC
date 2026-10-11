# MTC — фиксация договорённостей из звонков

## Цель

Локальная система для B2B/B2C (продажи, поддержка, банки, телеком, недвижимость, логистика, клиники): из записи телефонного разговора извлекать **договорённости** — конкретные обязательства (действие, ответственный, срок, сумма/условия, цитата из разговора), вести карточку клиента, напоминания и контроль выполнения. Работает на **macOS и Linux**, без облачных API, только open source.

## Конвейер

1. Запись звонка (стерео: канал 0 — менеджер, канал 1 — клиент; моно — резерв через diarization).
2. Обработка аудио (ffmpeg, Silero VAD). ✅
3. Расшифровка (`large-v3-turbo`: mlx-whisper на macOS, faster-whisper на Linux). ✅
4. Извлечение договорённостей (Ollama + qwen2.5, строгий JSON). ✅ код готов, ждёт модель в Ollama
5. Обычный звонок (один канал) — голоса разделяются локально, первый говорящий считается менеджером. ✅
6. API (FastAPI): карточка клиента, звонки, договорённости, статистика. ✅
7. Интерфейс (Streamlit) поверх API. ✅
8. Напоминания (Telegram-бот) и контроль выполнения.

**Текущий этап:** этапы 6 и 7 ✅. Конвейер обработки звонка: split → VAD → whisper → merge → `utterances` → Ollama JSON → проверка цитаты → `agreements` + `resolve_due`. **Принцип:** LLM извлекает факты из текста; Python детерминированно считает даты; каждая договорённость проверяется по цитате в реплике. Обычная запись (моно или два одинаковых канала) разделяется по голосам в `app/audio/diarize.py`; настоящее стерео по-прежнему режется по каналам. Очередь API — один поток: whisper и LLM не работают параллельно.

## Стек

| Слой | Технологии |
|------|------------|
| Python | 3.11–3.12 (не 3.13+: нет колёс torch/mlx/pyannote) |
| БД | SQLite, SQLAlchemy 2.x |
| ASR | mlx-whisper (macOS) / faster-whisper (Linux) |
| Diarization | pyannote.audio 3.1 (опционально) |
| LLM | Ollama (qwen2.5:14b / 7b) |
| API | FastAPI |
| UI | Streamlit |
| Bot | python-telegram-bot |

Зависимости в `pyproject.toml` по группам: `core`, `audio`, `asr` (по `sys_platform`: mlx на Darwin, faster-whisper на Linux), `asr-macos`, `asr-linux`, `diarization`, `llm`, `api`, `ui`, `bot`, `dev`.

## Структура

```
app/
  config.py          # pydantic-settings, .env
  system.py          # подсказки установки ffmpeg/TTS по ОС
  pipeline.py        # process_call: probe → split → VAD → ASR → БД
  secure.py          # Fernet: записи шифруются на диске (data/recording.key)
  audit.py           # журнал доступов: кто открыл звонок/запись/отправил в CRM
  rules.py           # правила: ключевые слова → тип и приоритет договорённости
  audio/
    probe.py         # ffprobe → AudioInfo
    preprocess.py    # stereo → manager.wav / client.wav (16 kHz mono)
    vad.py           # Silero VAD, speech_segments
    exceptions.py    # MonoNotSupportedError
  asr/
    backend.py       # mlx (macOS) или faster-whisper (Linux)
    transcribe.py    # ASR + фильтр галлюцинаций
    merge.py         # merge_dialog по времени
  agreements_service.py  # mark_overdue (API и будущий бот)
  extraction/        # schema, prompt, llm, dates, verify
  integrations/
    ics.py           # событие календаря по договорённости (.ics, без зависимостей)
    crm.py           # webhook CRM: Bitrix24/amoCRM/любой POST (без зависимостей)
  atc/               # Автосекретарь МТС: /CallEvent → договорённость без клика
  api/               # FastAPI: schemas, deps, worker, main, atc
  ui/                # Streamlit: Home.py, pages/, только HTTP
  bot/               # Telegram (будущее)
scripts/
  setup.sh           # окружение одной командой: .venv + зависимости + check_env
  check_env.py       # отчёт OK/FAIL по окружению
  make_test_call.py  # data/raw/test_call.wav (macOS say / Linux espeak-ng + ffmpeg)
  record_call.sh     # запись с микрофона (avfoundation / pulse|alsa)
  transcribe_file.py # CLI без БД
  extract_file.py    # транскрипция + извлечение без БД
  accuracy_check.py  # замер точности на 15 тестовых фразах (цель ≥ 90%)
  run.sh             # uvicorn :8000 и streamlit :8501
  seed_demo.py       # Анна, ООО Ромашка, test_call.wav через API
tests/               # pytest (-m slow для полного пайплайна)
data/raw/, data/processed/  # аудио (шифрованное) и артефакты (в .gitignore)
data/recording.key   # ключ Fernet, права 600 (в .gitignore)
models/              # локальные веса whisper (в .gitignore)
```

## Модель данных (кратко)

- **clients** — имя, телефон, компания (nullable), created_at.
- **managers** — имя, telegram_chat_id (nullable), is_supervisor.
- **calls** — client_id, manager_id, audio_path (файл шифрован Fernet), started_at, duration_sec, channels (1|2), status, consent (клиент предупреждён о записи), error_message.
- **utterances** — call_id, speaker (manager|client), start_sec, end_sec, text.
- **agreements** — call_id, client_id, action, responsible, due_date, due_text, amount, conditions, quote, category (КП|встреча|оплата|…), priority (high|normal|low), status, created_at, updated_at.
- **atc_calls** — внешние звонки Автосекретаря до постановки в очередь.
- **audit_log** — кто, когда, что открыл/изменил/отправил (open_call, listen_audio, send_crm, …).

Статусы звонка: `new` → `processing` → `transcribed` → `extracted` | `error`.  
Статусы договорённости: `open`, `done`, `overdue`, `cancelled`.

## Соглашения

- Настройки: `app.config.settings`, файл `.env` (образец `.env.example`).
- Whisper: `WHISPER_BACKEND=auto` — mlx на macOS, faster-whisper на Linux. `WHISPER_MODEL` — путь или id модели. На macOS: локальные mlx-веса (`models/whisper-large-v3-turbo`) или `mlx-community/whisper-large-v3-turbo`. На Linux: CTranslate2 id (`large-v3-turbo`); mlx-community id из дефолта автоматически мапится. `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE`: `auto` (CUDA float16 или CPU int8).
- БД по умолчанию: `sqlite:///data/mtc.db`; инициализация: `init_db()` из `app.db.session`.
- Сессия: контекстный менеджер `get_session()`.
- Линтер: `ruff check .` (line-length 100).
- Тесты: `pytest -q` (без `@slow`); `pytest -m slow -q` — полный ASR; модели БД — in-memory SQLite.
- Обёртки: `make setup|lint|test|test-slow|check|run`.
- Тяжёлые optional-deps ставить только когда нужен соответствующий этап.

## Быстрый старт

Проект работает на macOS и Linux: ASR сами (`app/asr/backend.py`) — mlx-whisper на Mac, faster-whisper на Linux; запускается `scripts/setup.sh` → `scripts/run` (или `scripts/run.sh`).

```bash
# Всё окружение одной командой (macOS/Linux; uv, если установлен, иначе pip):
scripts/setup.sh

# Или вручную:
python3.12 -m venv .venv          # только 3.11/3.12; системный Python 3.13+ не подходит
source .venv/bin/activate
python -m pip install -e ".[core,dev,audio,asr,llm,api,ui]"
# с uv (отдельно: pipx install uv): uv pip install -p .venv -e ".[core,dev,audio,asr,llm,api,ui]"
python scripts/check_env.py
```

**Важно:**

- Зависимости ставятся **только** в активированный `.venv`. `pacman/apt/dnf` и `pipx` ставят
  пакеты для системного Python — внутри `.venv` они невидимы (`ModuleNotFoundError`).
- Arch/CachyOS: системный Python 3.13+ не подходит (`requires-python <3.13`) —
  `sudo pacman -S python312`, затем `python3.12 -m venv .venv`.
- macOS: положить mlx-веса в `models/whisper-large-v3-turbo`
  (`WHISPER_MODEL=models/whisper-large-v3-turbo`).
- Linux: faster-whisper сам скачает CTranslate2 `large-v3-turbo`
  (`WHISPER_MODEL=large-v3-turbo`; дефолт `mlx-community/...` тоже сработает — смапится).
- ffmpeg: `brew install ffmpeg` | `sudo pacman -S ffmpeg` | `sudo apt install ffmpeg`

```bash
ruff check .
pytest -q

# Тестовый стерео-звонок (macOS: say Milena/Yuri; Linux: espeak-ng):
python scripts/make_test_call.py

# Расшифровка файла без БД:
python scripts/transcribe_file.py data/raw/test_call.wav

# Расшифровка + договорённости (нужна модель Ollama):
python scripts/extract_file.py data/raw/test_call.wav --date 2026-10-09

# Пайплайн по записи в БД:
# from app.pipeline import process_call
# process_call(call_id)

# API и интерфейс (Ctrl+C останавливает оба):
scripts/run.sh
# API http://127.0.0.1:8000  UI http://127.0.0.1:8501
python scripts/seed_demo.py
```

## API

База: `API_URL`, по умолчанию `http://localhost:8000`. `GET /agreements`, `GET /clients/{id}` и `GET /stats/managers` сначала вызывают `mark_overdue` (open с `due_date` < сегодня → overdue). `done_on_time` — доля выполненных в срок среди `done`, в процентах (`null`, если выполненных нет).

- `POST /managers` — создать менеджера
- `GET /managers` — список менеджеров
- `POST /clients` — создать клиента
- `GET /clients?q=` — поиск по имени, телефону или компании
- `GET /clients/{id}` — карточка: данные, звонки (новые сверху), договорённости (open/overdue сверху, по сроку)
- `POST /calls` — multipart `file`, `client_id`, `manager_id`, `started_at` (иначе время загрузки), `consent` (флаг согласия); файл в `data/raw/{call_id}_{имя}` и шифруется Fernet'ом, статус `new`, постановка в очередь
- `GET /calls?client_id=&manager_id=&status=` — список звонков
- `GET /calls/{id}` — звонок с репликами и договорённостями; открытие попадает в audit_log
- `PATCH /calls/{id}/consent` — отметить, что клиент предупреждён о записи
- `POST /calls/{id}/reprocess` — снова поставить звонок в очередь
- `GET /calls/{id}/audio` — файл записи (шифрованная копия расшифровывается во временный файл; просмотр пишется в журнал)
- `GET /calls/{id}/calendar.ics` — все договорённости звонка одним событием
- `GET /agreements?status=&responsible=&manager_id=&client_id=&due_before=` — список договорённостей
- `GET /agreements/{id}/calendar.ics` — событие календаря по договорённости
- `POST /agreements/{id}/send-to-crm` — отправить договорённость как задачу в CRM (webhook)
- `GET/PUT /crm/settings` — адрес webhook CRM и токен (руководитель)
- `GET/PUT /agreement-rules` — правила «ключевые слова → тип/приоритет» (руководитель)
- `GET /audit` — журнал доступов (руководитель)
- `PATCH /agreements/{id}` — изменить `status`, `due_date`, `action`, `conditions`, `category`, `priority`
- `GET /stats/managers` — по каждому менеджеру: open, overdue, done, done_on_time %

## UI

Streamlit ходит только в API (`httpx`, без прямого доступа к БД). Страницы:

- Главная — `app/ui/Home.py`: согласие на запись, микрофон/файл, отчёт, кнопки «В календарь (.ics)» и «Отправить в CRM»
- Клиенты — поиск и карточка: открытые договорённости (просроченные красным), история звонков, аудио, диалог, цитаты
- История — личные звонки сотрудника и живые звонки АТС
- Настройка АТС — событие/запись, CRM webhook, правила договорённостей (руководитель)
- Журнал доступов — кто открывал звонки (руководитель)

Статусы по-русски: open «открыта», overdue «просрочена», done «выполнена», cancelled «отменена»; звонок: new «новый», processing «обрабатывается», transcribed «расшифрован», extracted «извлечено», error «ошибка».

## Комплаенс и «жизнь у оператора» (для защиты)

- Регуляторика: вторая сторона предупреждается о записи, согласие фиксируется флагом `calls.consent`; записи и расшифровки не покидают страну хранения (центр обработки — РБ, МТС); тайна связи не нарушается — доступ к содержимому только у сотрудника с логином.
- Журнал доступов (`audit_log`) отвечает на вопрос «кто открывал звонок/расшифровку» — право на обзор и контроль.
- Записи лежат на диске шифрованными (Fernet, AES-128-CBC + HMAC); ключ — в `data/recording.key` с правом 600; alt-хранилище в ЦОД МТС меняет только место, не схему.
- Интеграция: `/CallEvent` Автосекретаря, не «чужой номер»; тут подключаются URL записи, далее — биллинг МТС, канал в кабинете/приложении.
- Масштаб: сейчас 1 worker и SQLite → план: очередь задач, несколько воркеров, корпоративная БД оператора, модели в ЦОД МТС.
- Монетизация: подписка за сотрудника/за минуту, корпоративный тариф, доля оператору за минуты и хранение.

## Без действий пользователя

`/CallEvent` принимает события АТС: после завершения разговора запись скачивается по шаблону URL (`ATC_RECORDING_URL`, экран «Настройка АТС») либо приходит файлом `POST /atc/calls/{CallID}/recording`, после чего пайплайн ставится в очередь автоматически. Менеджер только открывает готовую карточку. Это «обработка сразу после разговора», не live-ASR в эфире.

## Телефон через Linphone (services/ast)

Собственная АТС на Asterisk в Docker (`services/ast/`, деплой на отдельном сервере
`100.91.32.58`, клиенты — Linphone/Zoiper через Tailscale):

- звонок `11111` ↔ `11119`, MixMonitor пишет `mix`/`caller`/`callee`, hangup-хендler пишет `.meta.json`;
- `recorder-notifier` на сервере склеивает стерео (L=звонящий, R=отвечающий) и отправляет
  multipart-вебхук на `WEBHOOK_URL` — `POST /api/v1/process-audio` этого приложения;
- вебхук (`app/atc/ast.py`): caller-экстеншен → сотрудник по короткому номеру, callee → клиент,
  файл шифруется и уходит в очередь пайплайна без клика;
- связь привязывается командой `./services/ast/attach.sh` (обновляет `WEBHOOK_URL` на сервере по SSH);
- ручная запись из интерфейса (микрофон/файл) остаётся как была.

## Статус

Этапы 6, 7 ✅ и обязательный срез ТЗ трека 2: автозабор записи АТС, ICS-календарь, CRM-webhook, согласие, шифрование, журнал доступов, правила/типы/приоритеты. Адаптивный веб под телефон. Точность замеряется `scripts/accuracy_check.py`. Дальше — Telegram-бот, дашборд руководителя.
