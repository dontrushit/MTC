"""Create demo manager Анна, client ООО Ромашка, and upload the sample call."""

from __future__ import annotations

from pathlib import Path

import httpx

from app.config import settings

ROOT = Path(__file__).resolve().parents[1]
WAV = ROOT / "data" / "raw" / "test_call.wav"
STARTED_AT = "2026-10-09T11:00:00"


def main() -> None:
    if not WAV.is_file():
        raise SystemExit(f"Нет файла {WAV}. Сначала: python scripts/make_test_call.py")

    base = settings.API_URL.rstrip("/")
    try:
        with httpx.Client(base_url=base, timeout=60) as client:
            manager = client.post("/managers", json={"name": "Анна"})
            manager.raise_for_status()
            manager_id = manager.json()["id"]

            customer = client.post(
                "/clients",
                json={
                    "name": "ООО Ромашка",
                    "phone": "+74951234567",
                    "company": "ООО Ромашка",
                },
            )
            customer.raise_for_status()
            client_id = customer.json()["id"]

            with WAV.open("rb") as audio:
                uploaded = client.post(
                    "/calls",
                    data={
                        "client_id": str(client_id),
                        "manager_id": str(manager_id),
                        "started_at": STARTED_AT,
                    },
                    files={"file": (WAV.name, audio, "audio/wav")},
                )
            uploaded.raise_for_status()
            call = uploaded.json()
    except httpx.ConnectError:
        raise SystemExit(f"API недоступен: {base}") from None
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        raise SystemExit(f"API вернул {exc.response.status_code}: {detail}") from None

    print(
        f"manager_id={manager_id} client_id={client_id} "
        f"call_id={call['id']} status={call['status']}"
    )


if __name__ == "__main__":
    main()
