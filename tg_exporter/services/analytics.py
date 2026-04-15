"""
AnalyticsCollector + render functions — аналитика по сообщениям.

Чистые функции без side effects. Принимают ExportMessage, возвращают Markdown.
"""

from __future__ import annotations

import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional

from ..models.message import ExportMessage


# ---- Пределы памяти ----
# Обрезка длинных сообщений и лимит кол-ва сохранённых сообщений на автора
# предотвращают OOM на больших каналах (1M+ сообщений).
_MAX_ENTRY_CHARS = 2000
_MAX_MESSAGES_PER_AUTHOR = 5000


# ---- Data classes ----

@dataclass
class AuthorStats:
    """Статистика по одному автору."""
    user_id: int
    name: str
    username: str
    message_count: int
    messages: list[str] = field(default_factory=list)  # отформатированные тексты


@dataclass
class AnalyticsResult:
    """Результат сбора аналитики."""
    authors: list[AuthorStats] = field(default_factory=list)   # отсортированы по убыванию
    activity: dict[str, int] = field(default_factory=dict)     # date → count


# ---- Collector ----

class AnalyticsCollector:
    """
    Накапливает аналитику по сообщениям по мере их обработки.

    Использование:
        collector = AnalyticsCollector()
        for msg in messages:
            collector.add(msg, formatted_text)
        result = collector.result()
    """

    def __init__(
        self,
        max_entry_chars: int = _MAX_ENTRY_CHARS,
        max_messages_per_author: int = _MAX_MESSAGES_PER_AUTHOR,
    ) -> None:
        self._author_counts: dict[int, int] = {}
        # deque с maxlen сохраняет только последние N сообщений автора — защита от OOM
        self._author_messages: dict[int, Deque[str]] = {}
        self._author_meta: dict[int, dict] = {}
        self._activity: dict[str, int] = {}
        self._max_entry_chars = max_entry_chars
        self._max_messages_per_author = max_messages_per_author

    def add(self, msg: ExportMessage, formatted_text: str, is_outgoing: bool = False) -> None:
        """
        Добавляет сообщение в статистику.

        is_outgoing: исходящие сообщения не учитываются в авторской статистике.
        """
        author_id = msg.from_id
        if not is_outgoing and isinstance(author_id, int) and author_id > 0:
            name = (msg.from_name or "Без имени").strip() or "Без имени"
            username = (msg.from_username or "").strip()

            meta = self._author_meta.get(author_id, {})
            if not meta.get("name") and name:
                meta["name"] = name
            if not meta.get("username") and username:
                meta["username"] = username
            self._author_meta[author_id] = meta

            self._author_counts[author_id] = self._author_counts.get(author_id, 0) + 1

            # Обрезаем длинные сообщения — для аналитики полный текст не нужен
            truncated = formatted_text or ""
            if len(truncated) > self._max_entry_chars:
                truncated = truncated[: self._max_entry_chars].rstrip() + "…"
            entry = truncated
            if msg.id is not None:
                entry = f"ID: {msg.id}\n{truncated}".strip()

            bucket = self._author_messages.get(author_id)
            if bucket is None:
                bucket = deque(maxlen=self._max_messages_per_author)
                self._author_messages[author_id] = bucket
            bucket.append(entry)

        # Активность по дням
        date_key = _date_key(msg.date)
        if date_key:
            self._activity[date_key] = self._activity.get(date_key, 0) + 1

    def result(self) -> AnalyticsResult:
        sorted_authors = sorted(
            self._author_counts.items(), key=lambda x: x[1], reverse=True
        )
        authors = []
        for uid, count in sorted_authors:
            meta = self._author_meta.get(uid, {})
            authors.append(AuthorStats(
                user_id=uid,
                name=meta.get("name", "Без имени"),
                username=meta.get("username", ""),
                message_count=count,
                messages=list(self._author_messages.get(uid, [])),
            ))
        return AnalyticsResult(authors=authors, activity=dict(self._activity))


# ---- Render functions ----

def render_top_authors(result: AnalyticsResult, words_per_file: int = 50_000) -> list[str]:
    """
    Рендерит аналитику по авторам в список Markdown-строк.
    Каждый элемент — содержимое одного файла (разбивка по словам).
    """
    if not result.authors:
        return []

    summary_lines = [
        "# Топ авторов",
        "",
        "## Список участников",
        "",
    ]
    for a in result.authors:
        display = f"{a.name} (@{a.username})" if a.username else a.name
        summary_lines.append(f"- {display} — {a.message_count}")
    summary_lines.append("")

    summary_text = "\n".join(summary_lines)

    author_blocks: list[tuple[str, int]] = []
    for a in result.authors:
        display = f"{a.name} (@{a.username})" if a.username else a.name
        lines = [f"## {display} — {a.message_count}", ""]
        for entry in a.messages:
            if entry:
                lines.append(entry)
                lines.append("")
        block = "\n".join(lines)
        author_blocks.append((block, len(block.split())))

    parts: list[str] = []
    current = summary_text
    current_words = len(summary_text.split())

    for block, block_words in author_blocks:
        if current_words + block_words > words_per_file and current.strip() != summary_text.strip():
            parts.append(current)
            current = ""
            current_words = 0
        current = (current + "\n" + block) if current else block
        current_words += block_words

    if current.strip():
        parts.append(current)

    return [p.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n" for p in parts]


def render_activity(result: AnalyticsResult) -> str:
    """Рендерит активность по дням в Markdown-строку."""
    if not result.activity:
        return ""

    weekday_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

    lines = [
        "# Активность по дням",
        "",
        "| Дата | День недели | Сообщений |",
        "| --- | --- | --- |",
    ]
    for day in sorted(result.activity.keys()):
        weekday = ""
        try:
            dt = datetime.date.fromisoformat(day)
            weekday = weekday_names[dt.weekday()]
        except Exception:
            pass
        lines.append(f"| {day} | {weekday} | {result.activity[day]} |")

    total = sum(result.activity.values())
    hot = sorted(result.activity.items(), key=lambda x: x[1], reverse=True)[:3]
    if hot:
        lines += ["", "## Самые горячие дни", ""]
        for day, cnt in hot:
            weekday = ""
            try:
                dt = datetime.date.fromisoformat(day)
                weekday = f" ({weekday_names[dt.weekday()]})"
            except Exception:
                pass
            lines.append(f"- {day}{weekday}: {cnt}")
        lines += ["", f"Всего сообщений: {total}"]

    return "\n".join(lines).replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


# ---- Helpers ----

def _date_key(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if "T" in value:
        return value.split("T")[0]
    if " " in value:
        return value.split(" ")[0]
    return value[:10] if len(value) >= 10 else value
