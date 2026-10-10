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
  db/                # models, session, init_db
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
  api/               # FastAPI: schemas, deps, worker, main
  ui/                # Streamlit: Home.py, pages/, только HTTP
  bot/               # Telegram (будущее)
scripts/
  check_env.py       # отчёт OK/FAIL по окружению
  make_test_call.py  # data/raw/test_call.wav (macOS say / Linux espeak-ng + ffmpeg)
  record_call.sh     # запись с микрофона (avfoundation / pulse|alsa)
  transcribe_file.py # CLI без БД
  extract_file.py    # транскрипция + извлечение без БД
  run.sh             # uvicorn :8000 и streamlit :8501
  seed_demo.py       # Анна, ООО Ромашка, test_call.wav через API
tests/               # pytest (-m slow для полного пайплайна)
data/raw/, data/processed/  # аудио и артефакты (в .gitignore)
models/              # локальные веса whisper (в .gitignore)
```

## Модель данных (кратко)

- **clients** — имя, телефон, компания (nullable), created_at.
- **managers** — имя, telegram_chat_id (nullable), is_supervisor.
- **calls** — client_id, manager_id, audio_path, started_at, duration_sec, channels (1|2), status, error_message.
- **utterances** — call_id, speaker (manager|client), start_sec, end_sec, text.
- **agreements** — call_id, client_id, action, responsible, due_date, due_text, amount, conditions, quote, status, created_at, updated_at.

Статусы звонка: `new` → `processing` → `transcribed` → `extracted` | `error`.  
Статусы договорённости: `open`, `done`, `overdue`, `cancelled`.

## Соглашения

- Настройки: `app.config.settings`, файл `.env` (образец `.env.example`).
- Whisper: `WHISPER_BACKEND=auto` — mlx на macOS, faster-whisper на Linux. `WHISPER_MODEL` — путь или id модели. На macOS: локальные mlx-веса (`models/whisper-large-v3-turbo`) или `mlx-community/whisper-large-v3-turbo`. На Linux: CTranslate2 id (`large-v3-turbo`); mlx-community id из дефолта автоматически мапится. `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE`: `auto` (CUDA float16 или CPU int8).
- БД по умолчанию: `sqlite:///data/mtc.db`; инициализация: `init_db()` из `app.db.session`.
- Сессия: контекстный менеджер `get_session()`.
- Линтер: `ruff check .` (line-length 100).
- Тесты: `pytest -q` (без `@slow`); `pytest -m slow -q` — полный ASR; модели БД — in-memory SQLite.
- Тяжёлые optional-deps ставить только когда нужен соответствующий этап.

## Быстрый старт

```bash
python3.11 -m venv .venv
source .venv/bin/activate
uv pip install -p .venv -e ".[core,dev,audio,asr,llm,api,ui]"
# macOS: положить mlx-веса в models/whisper-large-v3-turbo
#   WHISPER_MODEL=models/whisper-large-v3-turbo
# Linux: faster-whisper сам скачает CTranslate2 large-v3-turbo
#   WHISPER_MODEL=large-v3-turbo
#   (дефолт mlx-community/... тоже сработает — смапится в large-v3-turbo)
# ffmpeg: brew install ffmpeg  |  sudo pacman -S ffmpeg  |  sudo apt install ffmpeg

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
- `POST /calls` — multipart `file`, `client_id`, `manager_id`, `started_at` (иначе время загрузки); файл в `data/raw/{call_id}_{имя}`, статус `new`, постановка в очередь
- `GET /calls?client_id=&manager_id=&status=` — список звонков
- `GET /calls/{id}` — звонок с репликами и договорённостями
- `POST /calls/{id}/reprocess` — снова поставить звонок в очередь
- `GET /calls/{id}/audio` — файл записи
- `GET /agreements?status=&responsible=&manager_id=&client_id=&due_before=` — список договорённостей
- `PATCH /agreements/{id}` — изменить `status`, `due_date`, `action`, `conditions`
- `GET /stats/managers` — по каждому менеджеру: open, overdue, done, done_on_time %

## UI

Streamlit ходит только в API (`httpx`, без прямого доступа к БД). Страницы:

- Главная — `app/ui/Home.py`
- Загрузка — менеджер, клиент или новый клиент, файл, дата; статус обновляется каждые 3 с, пока не `extracted` / `error`
- Клиенты — поиск и карточка: открытые договорённости (просроченные красным), история звонков, аудио, диалог, цитаты
- Договорённости — фильтры (статус, ответственный, менеджер, срок до), смена статуса и срока в строке
- Руководитель — таблица `/stats/managers` и все просроченные

Статусы по-русски: open «открыта», overdue «просрочена», done «выполнена», cancelled «отменена»; звонок: new «новый», processing «обрабатывается», transcribed «расшифрован», extracted «извлечено», error «ошибка».

## Статус

Этапы 6 и 7 ✅. Обычный телефонный звонок (моно) обрабатывается. Дальше — Telegram-бот.
