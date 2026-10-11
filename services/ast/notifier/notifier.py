#!/usr/bin/env python3
"""
recorder-notifier — обработчик записей звонков.

Следит за каталогом /audio_records:
  1. Ждёт появления <base>.meta.json (его пишет hangup-триггер АТС).
  2. Дожидается, пока wav-файлы допишутся (размер стабилен N опросов).
  3. Склеивает моно-дорожки абонентов в стерео-wav (L=звонящий, R=отвечающий).
  4. Отправляет вебхук (HTTP POST, JSON) ИИ-агенту с метаданными и путями.
  5. Помечает звонок обработанным (<base>.sent + .meta.done.json).

Только стандартная библиотека Python — никаких зависимостей.
"""

import glob
import json
import os
import struct
import sys
import time
import urllib.request
import uuid
import wave

RECORD_DIR = os.environ.get("RECORD_DIR", "/audio_records")
WEBHOOK_URL = os.environ.get(
    "WEBHOOK_URL", "http://host.docker.internal:8000/api/v1/process-audio"
)
STEREO_MERGE = os.environ.get("STEREO_MERGE", "1") == "1"
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "2"))
STABLE_CHECKS = int(os.environ.get("STABLE_CHECKS", "2"))  # опросов с тем же размером
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "30"))

# path -> (последний размер, сколько опросов размер не менялся)
_sizes: dict = {}


def log(msg: str) -> None:
    print(f"[notifier] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def is_stable(path: str) -> bool:
    """True, если файл существует и его размер не менялся STABLE_CHECKS опросов."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    prev, count = _sizes.get(path, (None, 0))
    if size == prev and size > 0:
        count += 1
    else:
        count = 0
    _sizes[path] = (size, count)
    return count >= STABLE_CHECKS


def merge_stereo(left_path: str, right_path: str, out_path: str) -> None:
    """Склеивает два моно 16-bit PCM wav в один стерео-wav (stdlib wave/struct)."""
    with wave.open(left_path, "rb") as lf, wave.open(right_path, "rb") as rf:
        lp, rp = lf.getparams(), rf.getparams()
        if lp.sampwidth != 2 or rp.sampwidth != 2 or lp.nchannels != 1:
            raise ValueError("ожидаются моно 16-bit PCM wav")
        rate = lp.framerate
        left = lf.readframes(lp.nframes)
        right = rf.readframes(rp.nframes)

    n = max(len(left), len(right)) // 2  # число сэмплов (16 бит = 2 байта)
    left += b"\x00" * (n * 2 - len(left))    # добиваем тишиной более короткий канал
    right += b"\x00" * (n * 2 - len(right))
    lpcm = struct.unpack(f"<{n}h", left)
    rpcm = struct.unpack(f"<{n}h", right)

    frames = bytearray()
    for l, r in zip(lpcm, rpcm):
        frames += struct.pack("<hh", l, r)

    with wave.open(out_path, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(frames))


def build_multipart(fields: dict, files: dict) -> tuple:
    """Собирает multipart/form-data: поля метаданных + аудиофайлы."""
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode() + b"\r\n"
    for name, path in files.items():
        with open(path, "rb") as f:
            data = f.read()
        out += f"--{boundary}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{name}"; '
            f'filename="{os.path.basename(path)}"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), boundary


def send_webhook(payload: dict, files: dict) -> bool:
    """POST multipart (метаданные + аудиофайлы) на WEBHOOK_URL. True при 2xx."""
    body, boundary = build_multipart(
        {"metadata": json.dumps(payload, ensure_ascii=False)}, files
    )
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            ok = 200 <= resp.status < 300
    except Exception as exc:  # сеть/недоступный агент — повторим на следующем опросе
        log(f"webhook failed: {exc}")
        return False
    if ok:
        log(f"webhook sent ({len(body)} bytes) -> {WEBHOOK_URL}")
    return ok


def process(meta_path: str) -> None:
    base = meta_path[: -len(".meta.json")]
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    files = meta.get("files", {})
    mixed = files.get("mixed", "")
    if not mixed or not os.path.isfile(mixed):
        return  # звонок не отвечен / файлы ещё не появились
    if not is_stable(mixed):
        return  # запись ещё пишется

    payload = dict(meta)
    payload["record_dir"] = RECORD_DIR

    if STEREO_MERGE:
        left, right = files.get("caller_mono"), files.get("callee_mono")
        stereo = f"{base}_stereo.wav"
        if left and right and os.path.isfile(left) and os.path.isfile(right):
            try:
                merge_stereo(left, right, stereo)
                payload["files"] = {**files, "stereo": stereo}
                log(f"stereo merged: {os.path.basename(stereo)}")
            except Exception as exc:
                log(f"stereo merge failed: {exc}")

    # Прикладываем существующие аудиофайлы к вебхуку
    upload = {
        key: path
        for key, path in payload["files"].items()
        if path and os.path.isfile(path)
    }
    if send_webhook(payload, upload):
        with open(f"{base}.sent", "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.rename(meta_path, f"{base}.meta.done.json")
        log(f"call processed: {os.path.basename(base)}")


def main() -> None:
    log(f"watching {RECORD_DIR} (webhook: {WEBHOOK_URL})")
    while True:
        for meta_path in glob.glob(os.path.join(RECORD_DIR, "*.meta.json")):
            try:
                process(meta_path)
            except Exception as exc:
                log(f"error processing {meta_path}: {exc}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
