"""Prompts for agreement extraction from numbered utterances."""

from __future__ import annotations

from datetime import datetime

from app.db.models import Utterance

SYSTEM_PROMPT = """\
Ты извлекаешь договорённости из расшифровки телефонного разговора между менеджером и клиентом.

Договорённость — конкретное обязательство: участник обещает выполнить действие \
(выслать, оплатить, перезвонить, приехать, подписать и т.п.).

НЕ извлекай: вопросы, намерения без обязательства («подумаем»), общие фразы, \
условия без обещания.

Правила:
- responsible — тот, кто берёт обязательство. «Мы со своей стороны оплатим» (клиент) → client. \
«Я вышлю» (менеджер) → manager.
- quote — дословная подстрока из одной реплики, без перефразирования.
- Одна договорённость = одно действие; две в одной реплике → две записи с одним utterance_index.
- due_text — фраза про срок из речи (например «до пятницы»), дословно; если срока нет — null.
- amount — если названа сумма, нормализуй: «150 тысяч рублей» → «150000 RUB»; иначе null.
- action — название: инфинитив и предмет. Срок и сумму в название не пиши, \
они идут в due_text и amount. «оплатить 150 рублей завтра» — плохо, «оплатить за кумыс» — хорошо.
- Каждый факт пиши один раз. brief не пересказывает договорённости.
- topic — тема, 3–6 слов.
- brief — одно-два предложения контекста, без списка шагов.
- unresolved — одно предложение, если что-то не решили. Иначе пустая строка.
- Если договорённостей нет — agreements пустой, topic и brief всё равно заполни.

Пример входа:
[0] manager: Я вышлю договор сегодня.
[1] client: Мы оплатим 50 тысяч рублей до понедельника.

Пример ответа (JSON):
{"topic": "договор и оплата", \
"brief": "Клиент согласен оплатить договор, менеджер берёт отправку на себя.", \
"unresolved": "", \
"agreements": [
  {"action": "выслать договор клиенту", "responsible": "manager", "due_text": "сегодня", \
"amount": null, "conditions": null, \
"quote": "Я вышлю договор сегодня", "utterance_index": 0},
  {"action": "оплатить за договор", "responsible": "client", \
"due_text": "до понедельника", \
"amount": "50000 RUB", "conditions": null, \
"quote": "Мы оплатим 50 тысяч рублей до понедельника", "utterance_index": 1}
]}
"""


def build_messages(
    utterances: list[Utterance],
    call_started_at: datetime,
) -> list[dict[str, str]]:
    """Build chat messages for Ollama structured extraction."""
    lines = [
        f"[{i}] {u.speaker.value}: {u.text}" for i, u in enumerate(utterances)
    ]
    transcript = "\n".join(lines)
    user_content = (
        f"Дата и время начала звонка: {call_started_at.isoformat()}\n\n"
        f"Расшифровка:\n{transcript}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
