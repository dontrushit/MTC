# MTC — фиксация договорённостей из звонков

## Цель

Локальная система для B2B/B2C (продажи, поддержка, банки, телеком, недвижимость, логистика, клиники): из записи телефонного разговора извлекать **договорённости** — конкретные обязательства (действие, ответственный, срок, сумма/условия, цитата из разговора), вести карточку клиента, напоминания и контроль выполнения. Всё на Mac, без облачных API, только open source.

## Конвейер

1. Запись звонка (стерео: канал 0 — менеджер, канал 1 — клиент; моно — резерв через diarization).
2. Обработка аудио (ffmpeg, Silero VAD).
3. Расшифровка (mlx-whisper, `large-v3-turbo`).
4. Извлечение договорённостей (Ollama + qwen2.5, строгий JSON).
5. Карточка клиента и статусы договорённостей.
6. Напоминания (Telegram-бот) и контроль выполнения.

**Текущий этап:** каркас проекта (этап 0) и схема БД (этап 1). Бизнес-логика пайплайна — заглушка.

## Стек

| Слой | Технологии |
|------|------------|
| Python | 3.11+ |
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
  pipeline.py        # заглушка полного пайплайна
  db/                # models, session, init_db
  audio/             # ffmpeg, VAD (будущее)
  asr/               # whisper (будущее)
  extraction/        # Ollama JSON (будущее)
  api/               # FastAPI (будущее)
  ui/                # Streamlit (будущее)
  bot/               # Telegram (будущее)
scripts/check_env.py # отчёт OK/FAIL по окружению
tests/               # pytest
data/raw/, data/processed/  # аудио и артефакты (в .gitignore)
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
- БД по умолчанию: `sqlite:///data/mtc.db`; инициализация: `init_db()` из `app.db.session`.
- Сессия: контекстный менеджер `get_session()`.
- Линтер: `ruff check .` (line-length 100).
- Тесты: `pytest -q`; модели — in-memory SQLite.
- Тяжёлые optional-deps ставить только когда нужен соответствующий этап.

## Быстрый старт (этап 0–1)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[core,dev]"
ruff check .
pytest -q
python scripts/check_env.py
```
