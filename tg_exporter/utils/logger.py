"""
AppLogger — логгер приложения с автоматическим редактированием секретов.

Пишет в файл ~/.tg_exporter/app.log.
Чувствительные данные (api_hash, session, номера телефонов) автоматически
заменяются на <redacted> перед записью.
"""

from __future__ import annotations

import datetime
import os
import re
import threading
import traceback
from pathlib import Path
from typing import Optional


LOG_PATH = Path(os.path.expanduser("~/.tg_exporter/app.log"))
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB — ротация


# Узкие паттерны: редактируем только то, что реально похоже на секреты,
# не съедая timestamp'ы / message_id / chat_id.
# Телефон: обязательный префикс "+" и 10-15 цифр (международный формат).
_REDACT_PATTERNS = [
    (re.compile(r"(?i)api[_-]?hash\s*[:=]\s*[A-Za-z0-9]+"), "api_hash=<redacted>"),
    (re.compile(r"(?i)api[_-]?id\s*[:=]\s*\d+"), "api_id=<redacted>"),
    (re.compile(r"(?i)session\s*[:=]\s*[A-Za-z0-9+/=_\-]{20,}"), "session=<redacted>"),
    (re.compile(r"\+\d{10,15}\b"), "<phone>"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9+/=_\-]{20,}"), "Bearer <redacted>"),
    (re.compile(r"(?i)token\s+[A-Za-z0-9+/=_\-]{20,}"), "Token <redacted>"),
]

_LOG_LOCK = threading.Lock()


def redact(text: str) -> str:
    """Заменяет чувствительные данные в строке."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class AppLogger:
    """
    Простой файловый логгер с редактированием секретов.

    Использование:
        logger = AppLogger()
        logger.info("Начат экспорт чата")
        logger.error("Ошибка подключения", exc=e)
    """

    def __init__(self, path: Path = LOG_PATH) -> None:
        self._path = path

    def _write(self, level: str, message: str, exc: Optional[BaseException] = None) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().isoformat(timespec="seconds")
            line = f"{timestamp} [{level}] {redact(message)}"
            if exc is not None:
                tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                line += "\n" + redact(tb)
            # Lock вокруг ротации + записи: защита от перемешанных строк
            # при одновременном логировании из worker- и UI-потоков.
            with _LOG_LOCK:
                self._rotate_if_needed()
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass  # логгер не должен ронять приложение

    def _rotate_if_needed(self) -> None:
        try:
            if self._path.exists() and self._path.stat().st_size > MAX_LOG_SIZE:
                backup = self._path.with_suffix(".log.old")
                self._path.rename(backup)
        except Exception:
            pass

    def debug(self, message: str, exc: Optional[BaseException] = None) -> None:
        self._write("DEBUG", message, exc)

    def info(self, message: str, exc: Optional[BaseException] = None) -> None:
        self._write("INFO", message, exc)

    def warning(self, message: str, exc: Optional[BaseException] = None) -> None:
        self._write("WARN", message, exc)

    def error(self, message: str, exc: Optional[BaseException] = None) -> None:
        self._write("ERROR", message, exc)

    def fatal(self, message: str, exc: Optional[BaseException] = None) -> None:
        self._write("FATAL", message, exc)


# Глобальный экземпляр для удобства импорта
logger = AppLogger()
