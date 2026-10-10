"""Measure extraction accuracy on key phrases. Run: python scripts/accuracy_check.py.

Uses Ollama (see app.config). Prints a table: phrase → recognized agreements,
expected, and the final percent. The target for the defense is >= 90%.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings
from app.extraction.llm import extract
from app.extraction.verify import verify_agreements

TZ = ZoneInfo(settings.TZ)


@dataclass(frozen=True)
class Case:
    phrase: str
    expect_action_words: tuple[str, ...]
    expect_category: str = ""


CASES: list[Case] = [
    Case("Пришлём КП до пятницы, посмотрите и свяжитесь с нами", ("кп",), "КП"),
    Case("Я отправлю коммерческое предложение завтра", ("коммерческое", "кп"), "КП"),
    Case("Давайте встретимся в среду в два часа в нашем офисе", ("встрет", "встреч"), "встреча"),
    Case("Устроим демонстрацию в следующий вторник", ("демонстр", "демо"), "встреча"),
    Case("Оплату внесём до десятого числа", ("оплат",), "оплата"),
    Case("Счёт выставим и оплатим в течение недели", ("оплат", "счёт"), "оплата"),
    Case("Предоплата 50 процентов, остальное после сдачи", ("предоплат", "оплат"), "оплата"),
    Case("Я перезвоню вам завтра после обеда", ("перезвон", "звонок"), "встреча"),
    Case("Подготовим договор до конца месяца и отправим на подпись", ("договор", "подпис"), ""),
    Case("Анкету пришлём в понедельник", ("анкет", "пришлём"), ""),
    Case("Ждём поставку товара на следующей неделе", ("поставк", "товар"), ""),
    Case("Тестовый период подключим в пятницу", ("тест", "подключ"), ""),
    Case("Вернёмся с решением к четвергу", ("верн", "решен"), ""),
    Case("Не знаю, я подумать надо", ()),
    Case("Спасибо, всё понятно", ()),
]


def main() -> int:
    now = datetime.now(TZ)
    passed = 0
    rows: list[dict] = []
    for case in CASES:
        utterances = [
            type("U", (), dict(speaker="client", start_sec=0, end_sec=10, text=case.phrase))
        ]
        try:
            result = extract(utterances, now)
            agreements = verify_agreements(utterances, result.agreements)
        except Exception as exc:  # noqa: BLE001
            print(f"Ошибка на фразе «{case.phrase}»: {exc}")
            return 1
        recognized = any(
            any(word in ag.action.casefold() for word in case.expect_action_words)
            for ag in agreements
        )
        objective = recognized or not case.expect_action_words
        rows.append(
            {
                "phrase": case.phrase,
                "expect": case.expect_action_words
                or "— (нет договорённостей, должно так и распознать)",
                "got": " / ".join(ag.action for ag in agreements) or "нет договорённостей",
                "ok": objective,
            }
        )
        if objective:
            passed += 1
    width = max(len(row["phrase"]) for row in rows) + 2
    for row in rows:
        mark = "✔" if row["ok"] else "✘"
        print(f"{mark} {row['phrase']:<{width}} → {row['got']}")
    percent = round(passed / len(rows) * 100, 1)
    print(f"\nРаспознано {passed} из {len(rows)} — {percent}% (цель ≥ 90%)")
    return 0 if percent >= 90 else 2


if __name__ == "__main__":
    sys.exit(main())
