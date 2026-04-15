"""
BaseTranscriber — абстрактный интерфейс транскрипции аудио.

Все провайдеры реализуют один метод: transcribe(audio_data, content_type, language).
Модели загружаются лениво при первом вызове и кешируются.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class TranscriptionError(Exception):
    """Ошибка транскрипции — описание проблемы для пользователя."""


class BaseTranscriber(ABC):
    """
    Базовый класс провайдера транскрипции.

    Жизненный цикл:
      1. create_transcriber() → возвращает нужный провайдер
      2. preload() — опционально, предзагружает модель с прогрессом
      3. transcribe(audio_data, content_type, language) → Optional[str]
      4. unload() — освобождает память (вызывается после экспорта)
    """

    MAX_DURATION_SEC = 15 * 60  # 15 минут — лимит для всех провайдеров

    @abstractmethod
    def preload(self) -> None:
        """
        Предзагружает модель/соединение.
        Безопасен для повторного вызова.
        """

    @abstractmethod
    def transcribe(
        self,
        audio_data: bytes,
        content_type: str,
        language: str = "multi",
    ) -> Optional[str]:
        """
        Транскрибирует аудио.

        Args:
            audio_data: Байты аудиофайла
            content_type: MIME-тип ("audio/ogg", "audio/wav")
            language: Код языка или "multi" для автоопределения

        Returns:
            Текст транскрипции, или None если не удалось

        Raises:
            TranscriptionError: Если провайдер недоступен (не установлен и т.д.)
        """

    def unload(self) -> None:
        """Освобождает кешированную модель из памяти."""
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__
