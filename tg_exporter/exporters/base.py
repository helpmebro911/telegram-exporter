"""
BaseExporter — абстрактный базовый класс для всех экспортёров.

Контракт:
  1. open(export_dir, chat_name, topic_title) — начать запись
  2. write(msg) — записать одно сообщение
  3. finalize() → list[str] — завершить и вернуть пути к файлам
  4. close() — закрыть ресурсы (вызывается автоматически в контекстном менеджере)

Экспортёры не знают про Telethon, работают только с ExportMessage.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from typing import Optional

from ..models.message import ExportMessage


_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """
    Безопасное имя файла: запрещённые символы, control chars, обход через ..,
    Windows-зарезервированные имена, длина.
    """
    if not isinstance(name, str):
        name = str(name) if name is not None else ""
    cleaned = re.sub(r'[\x00-\x1f\x7f\\/:*?"<>|]+', "_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.replace("..", "_")
    cleaned = cleaned.strip(". ")
    if cleaned.split(".", 1)[0].upper() in _WIN_RESERVED:
        cleaned = "_" + cleaned
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("_ .")
    return cleaned or "chat_export"


class BaseExporter(ABC):
    """
    Абстрактный экспортёр. Использовать как контекстный менеджер:

        with JsonExporter(settings) as exp:
            exp.open(export_dir, "Chat Name")
            for msg in messages:
                exp.write(msg)
        files = exp.output_files
    """

    def __init__(self) -> None:
        self._export_dir: Optional[str] = None
        self._chat_name: str = ""
        self._topic_title: Optional[str] = None
        self.output_files: list[str] = []

    def open(self, export_dir: str, chat_name: str, topic_title: Optional[str] = None) -> None:
        """Инициализирует экспортёр для конкретной директории."""
        self._export_dir = export_dir
        self._chat_name = chat_name
        self._topic_title = topic_title
        self.output_files = []
        self._open()

    @abstractmethod
    def _open(self) -> None:
        """Открывает файловые ресурсы. Вызывается после open()."""

    @abstractmethod
    def write(self, msg: ExportMessage) -> None:
        """Записывает одно сообщение."""

    @abstractmethod
    def finalize(self) -> list[str]:
        """
        Завершает запись, сбрасывает буферы, закрывает файлы.
        Возвращает список созданных файлов.
        """

    def close(self) -> None:
        """Освобождает ресурсы без финализации (например при отмене)."""
        pass

    def __enter__(self) -> "BaseExporter":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.finalize()
        else:
            self.close()

    # ---- Helpers ----

    def _path(self, filename: str) -> str:
        assert self._export_dir, "open() must be called first"
        return os.path.join(self._export_dir, filename)

    def _register(self, path: str) -> str:
        if path not in self.output_files:
            self.output_files.append(path)
        return path
