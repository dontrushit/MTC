# MTC — фиксация договорённостей из звонков

## Цель

Локальная система для B2B/B2C (продажи, поддержка, банки, телеком, недвижимость, логистика, клиники): из записи телефонного разговора извлекать **договорённости** — конкретные обязательства (действие, ответственный, срок, сумма/условия, цитата из разговора), вести карточку клиента, напоминания и контроль выполнения. Всё на Mac, без облачных API, только open source.

## Конвейер

1. Запись звонка (стерео: канал 0 — менеджер, канал 1 — клиент; моно — резерв через diarization).
2. Обработка аудио (ffmpeg, Silero VAD). ✅
3. Расшифровка (mlx-whisper, `large-v3-turbo`). ✅
4. Извлечение договорённостей (Ollama + qwen2.5, строгий JSON).
5. Карточка клиента и статусы договорённостей.
6. Напоминания (Telegram-бот) и контроль выполнения.

**Текущий этап:** этапы 2–3 (аудио + ASR). Стерео: split → VAD → whisper по каналам → merge → `utterances`. Моно пока `MonoNotSupportedError` (diarization — этап 5).

## Стек

| Слой | Технологии |
|------|------------|
| Python | 3.11 (не 3.13+: нет колёс torch/mlx/pyannote) |
| БД | SQLite, SQLAlchemy 2.x |
| ASR | mlx-whisper |
| Diarization | pyannote.audio 3.1 (опционально) |
| LLM | Ollama (qwen2.5:14b / 7b) |
| API | FastAPI |
| UI | Streamlit |
| Bot | python-telegram-bot |

Зависимости в `pyproject.toml` по группам: `core`, `audio`, `asr`, `diarization`, `llm`, `api`, `ui`, `bot`, `dev`.

## Структура

```
app/
  config.py          # pydantic-settings, .env
  pipeline.py        # process_call: probe → split → VAD → ASR → БД
  db/                # models, session, init_db
  audio/
    probe.py         # ffprobe → AudioInfo
    preprocess.py    # stereo → manager.wav / client.wav (16 kHz mono)
    vad.py           # Silero VAD, speech_segments
    exceptions.py    # MonoNotSupportedError
  asr/
    transcribe.py    # mlx-whisper + фильтр галлюцинаций
    merge.py         # merge_dialog по времени
  extraction/        # Ollama JSON (будущее)
  api/               # FastAPI (будущее)
  ui/                # Streamlit (будущее)
  bot/               # Telegram (будущее)
scripts/
  check_env.py       # отчёт OK/FAIL по окружению
  make_test_call.py  # data/raw/test_call.wav (macOS say + ffmpeg)
  transcribe_file.py # CLI без БД
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
- Whisper: `WHISPER_MODEL` — путь к локальной mlx-модели (например `models/whisper-large-v3-turbo`) или HF repo id.
- БД по умолчанию: `sqlite:///data/mtc.db`; инициализация: `init_db()` из `app.db.session`.
- Сессия: контекстный менеджер `get_session()`.
- Линтер: `ruff check .` (line-length 100).
- Тесты: `pytest -q` (без `@slow`); `pytest -m slow -q` — полный ASR; модели БД — in-memory SQLite.
- Тяжёлые optional-deps ставить только когда нужен соответствующий этап.

## Быстрый старт

```bash
python3.11 -m venv .venv
source .venv/bin/activate
uv pip install -p .venv -e ".[core,dev,audio,asr]"
# Положить mlx-whisper large-v3-turbo в models/whisper-large-v3-turbo, в .env:
# WHISPER_MODEL=models/whisper-large-v3-turbo

ruff check .
pytest -q

# Тестовый стерео-звонок (macOS, русский голос Milena/Yuri):
python scripts/make_test_call.py

# Расшифровка файла без БД:
python scripts/transcribe_file.py data/raw/test_call.wav

# Пайплайн по записи в БД:
# from app.pipeline import process_call
# process_call(call_id)
```
