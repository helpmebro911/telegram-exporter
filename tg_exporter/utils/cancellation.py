"""
CancellationToken — механизм кооперативной отмены операций.

Передаётся во все слои (exporter, media_downloader, transcription).
Каждый слой периодически вызывает raise_if_cancelled() в точках прерывания.

Пример использования:
    token = CancellationToken()

    # В фоновом потоке:
    for message in messages:
        token.raise_if_cancelled()
        process(message)

    # Из UI-потока:
    token.cancel()
"""

from __future__ import annotations

import threading


class CancelledError(Exception):
    """Операция была отменена пользователем."""


class CancellationToken:
    """
    Thread-safe токен отмены.

    Создаётся перед стартом задачи, отменяется из любого потока.
    Один токен — одна задача экспорта.
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        """Запрашивает отмену. Идемпотентен — вызывать можно несколько раз."""
        self._cancelled.set()

    @property
    def is_cancelled(self) -> bool:
        """True если отмена была запрошена."""
        return self._cancelled.is_set()

    def raise_if_cancelled(self) -> None:
        """
        Вызывает CancelledError если отмена запрошена.
        Должен вызываться в ключевых точках длинных операций.
        """
        if self._cancelled.is_set():
            raise CancelledError("Операция отменена пользователем")

    def reset(self) -> None:
        """Сбрасывает состояние отмены. Используется для повторного запуска."""
        self._cancelled.clear()

    def wait_for_cancel(self, timeout: float) -> bool:
        """
        Ожидает отмены в течение timeout секунд.
        Возвращает True если отмена произошла, False если timeout истёк.
        Используется вместо time.sleep() в циклах ожидания.
        """
        return self._cancelled.wait(timeout=timeout)

    def __repr__(self) -> str:
        state = "cancelled" if self.is_cancelled else "active"
        return f"CancellationToken({state})"
