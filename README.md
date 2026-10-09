# MTC — фиксация договорённостей из телефонных звонков

Локальная система: запись звонка → расшифровка → извлечение договорённостей (действие, ответственный, срок, сумма, цитата) → карточка клиента → напоминания. Всё работает офлайн, без облачных API. Подробный контекст — в `PROJECT.md`.

## Arch Linux (CPU, Intel; проверочная конфигурация)

Пример: ASUS Vivobook S15 OLED S5506MA (Intel Core Ultra, без NVIDIA). Распознавание — faster-whisper на CPU, извлечение — qwen2.5:1.5b.

```bash
sudo pacman -S --needed git ffmpeg uv ollama
sudo systemctl enable --now ollama
ollama pull qwen2.5:1.5b

git clone <url> mtc && cd mtc
git checkout arch-linux

# В Arch системный Python новее 3.12 — uv сам скачает 3.11
uv venv -p 3.11 .venv
# CPU-сборка torch (иначе pip потянет CUDA на ~3 ГБ)
uv pip install -p .venv torch torchaudio --index-url https://download.pytorch.org/whl/cpu
uv pip install -p .venv -e ".[core,dev,audio,asr-cpu,llm,api,ui]"

cp .env.example .env
# в .env раскомментировать блок «Linux / Windows / weak PC»
```

Проверка:

```bash
source .venv/bin/activate
python scripts/check_env.py
pytest -q
python scripts/transcribe_file.py samples/test_call.wav     # первый запуск скачает whisper small (~500 МБ)
python scripts/extract_file.py samples/test_call.wav --date 2026-10-09
```

Ожидаемый результат на `samples/test_call.wav` (сценарий — `samples/test_call.txt`): 6 реплик и 3 договорённости — менеджер высылает КП до 16.10, клиент оплачивает 150000 RUB до 20.10, менеджер перезванивает 10.10.

Важно:
- `qwen2.5:1.5b` подходит только для проверки, что конвейер работает: на русском маленькая модель пропускает договорённости и путает ответственных. Рабочая конфигурация — `qwen2.5:14b` (нужно ~10 ГБ RAM; на CPU медленно, но работает) или `qwen2.5:7b`.
- Качество расшифровки выше с `WHISPER_MODEL=large-v3-turbo`, но на CPU она в несколько раз медленнее `small`.
- `scripts/make_test_call.py` работает только на macOS (голоса `say`); на Linux используйте `samples/`.

## macOS (Apple Silicon M1–M4, основная конфигурация)

```bash
brew install ffmpeg ollama uv
ollama pull qwen2.5:14b
uv venv -p 3.11 .venv
uv pip install -p .venv -e ".[core,dev,audio,asr,llm,api,ui]"
cp .env.example .env
```

Распознавание — mlx-whisper large-v3-turbo на GPU Apple.
