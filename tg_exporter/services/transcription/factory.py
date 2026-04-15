"""
Фабрика транскриберов — создаёт нужный провайдер по настройкам.
"""

from __future__ import annotations

from typing import Optional

from .base import BaseTranscriber, TranscriptionError
from ...models.config import AppConfig


def create_transcriber(config: AppConfig, deepgram_key: Optional[str] = None) -> BaseTranscriber:
    """
    Создаёт транскрибер по настройкам конфига.

    Args:
        config: AppConfig с полями transcription_provider, local_whisper_model, etc.
        deepgram_key: API ключ Deepgram (берётся из Keyring отдельно, не из конфига)

    Returns:
        Нужный BaseTranscriber

    Raises:
        TranscriptionError: Если провайдер не настроен или недоступен
    """
    provider = (config.transcription_provider or "local").strip().lower()

    if provider == "deepgram":
        key = (deepgram_key or "").strip()
        if not key:
            raise TranscriptionError(
                "Deepgram API ключ не задан. Введите его в настройках."
            )
        from .deepgram import DeepgramTranscriber
        return DeepgramTranscriber(api_key=key)

    model_id = (config.local_whisper_model or "base").strip()

    from .whisper_local import WhisperTranscriber
    return WhisperTranscriber(model_size=model_id)
