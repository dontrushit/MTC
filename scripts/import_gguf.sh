#!/usr/bin/env bash
# Import a Qwen2.5 GGUF (e.g. from a flash drive) into Ollama and point .env at it.
# Usage: scripts/import_gguf.sh [path/to/Qwen2.5-7B-Instruct-Q4_K_M.gguf]
# Without an argument, searches /Volumes (macOS) and /run/media (Linux) for qwen2.5*.gguf.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="${1:-}"
if [[ -z "$SRC" ]]; then
  SRC=$(find /Volumes "/run/media/${USER:-}" -maxdepth 3 -iname "qwen2.5*.gguf" -not -name "._*" 2>/dev/null | head -1 || true)
fi
if [[ -z "$SRC" || ! -f "$SRC" ]]; then
  echo "GGUF не найден. Укажите путь: scripts/import_gguf.sh /Volumes/<флешка>/<файл>.gguf"
  exit 1
fi

name=$(basename "$SRC" | tr '[:upper:]' '[:lower:]')
case "$name" in
  *14b*) TAG="qwen2.5:14b" ;;
  *1.5b*) TAG="qwen2.5:1.5b" ;;
  *7b*) TAG="qwen2.5:7b" ;;
  *) echo "Не понял размер модели по имени файла: $name"; exit 1 ;;
esac

echo "Файл: $SRC ($(du -h "$SRC" | cut -f1))"
echo "Имя в Ollama: $TAG"

MODELFILE=$(mktemp)
# Qwen2.5 chat template (ChatML); system messages come through .Messages
cat > "$MODELFILE" <<EOF
FROM "$SRC"
TEMPLATE """{{- range .Messages }}<|im_start|>{{ .Role }}
{{ .Content }}<|im_end|>
{{ end }}<|im_start|>assistant
"""
PARAMETER stop "<|im_start|>"
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"
EOF

ollama create "$TAG" -f "$MODELFILE"
rm -f "$MODELFILE"

if [[ -f .env ]]; then
  sed -i.bak "s/^OLLAMA_MODEL=.*/OLLAMA_MODEL=$TAG/; s/^OLLAMA_FALLBACK_MODEL=.*/OLLAMA_FALLBACK_MODEL=$TAG/" .env && rm -f .env.bak
  echo ".env: OLLAMA_MODEL=$TAG"
fi

echo "Проверка модели:"
ollama run "$TAG" "Ответь одним словом: столица России?"
echo "Готово. Флешку можно извлечь — Ollama скопировала модель к себе."
