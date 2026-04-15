"""
TelegramClientManager — управление жизненным циклом TelegramClient.

Отвечает за:
- Создание клиента из credentials
- Переподключение при обрыве
- Один asyncio event loop на фоновый поток

Не содержит UI-логики и не знает про очереди.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Optional

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

from .credentials import CredentialsManager
from ..models.config import AppConfig


class ClientNotConfiguredError(RuntimeError):
    """api_id или api_hash не заданы."""


class TelegramClientManager:
    """
    Держит один экземпляр TelegramClient на всё время жизни приложения.

    Создаётся один раз при старте App. Используется из фонового потока.
    Все методы Telethon должны вызываться из потока, где живёт event loop.
    """

    def __init__(self, config: AppConfig, credentials: CredentialsManager) -> None:
        self._config = config
        self._credentials = credentials
        self._client: Optional[TelegramClient] = None
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Явно заданная сессия (для профилей). Если None — берётся из Keyring
        # по `{api_id}:session`, как раньше.
        self._session_override: Optional[str] = None

    def update_config(self, config: AppConfig) -> None:
        """Обновляет конфиг. Если api_id изменился — сбрасывает клиент."""
        with self._lock:
            if self._config.api_id != config.api_id:
                self._destroy_client()
            self._config = config

    def use_session(self, session_string: Optional[str]) -> None:
        """
        Принудительно указывает сессию для клиента (для профилей).
        None — вернуться к дефолтной сессии из Keyring.
        Сбрасывает текущий клиент, чтобы следующий get_client() построил новый.
        """
        with self._lock:
            self._session_override = session_string or None
            self._destroy_client()

    # ---- Event loop ----

    def ensure_event_loop(self) -> asyncio.AbstractEventLoop:
        """Гарантирует наличие event loop в текущем потоке."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("closed")
            return loop
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            return loop

    # ---- Client lifecycle ----

    def get_client(self) -> TelegramClient:
        """
        Возвращает готовый TelegramClient.
        Создаёт новый если ещё не создан.
        Raises ClientNotConfiguredError если api_id/api_hash не заданы.
        """
        self.ensure_event_loop()
        with self._lock:
            if self._client is None:
                self._client = self._build_client()
        return self._client

    def ensure_connected(self) -> TelegramClient:
        """Возвращает клиент, гарантируя что он подключён."""
        client = self.get_client()
        if not client.is_connected():
            client.connect()
        return client

    def disconnect(self) -> None:
        """Отключает клиент. Безопасен для вызова если клиент не создан."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.disconnect()
                except Exception:
                    pass

    def destroy(self) -> None:
        """Отключает и удаляет клиент. Следующий get_client() создаст новый."""
        with self._lock:
            self._destroy_client()

    def save_session(self) -> None:
        """Сохраняет текущую сессию в Keyring."""
        with self._lock:
            if self._client is None:
                return
            try:
                session_str = self._client.session.save()
                if session_str and self._config.api_id:
                    self._credentials.save_session(self._config.api_id, session_str)
            except Exception:
                pass

    @property
    def is_created(self) -> bool:
        return self._client is not None

    # ---- Internal ----

    def _build_client(self) -> TelegramClient:
        api_id = self._config.api_id_int
        if not api_id:
            raise ClientNotConfiguredError(
                "api_id не задан. Откройте настройки и введите API ID."
            )

        api_hash = self._credentials.load_api_hash(self._config.api_id)
        if not api_hash:
            raise ClientNotConfiguredError(
                "api_hash не найден. Откройте настройки и введите API Hash."
            )

        session_str = self._session_override or self._credentials.load_session(self._config.api_id)
        session = StringSession(session_str) if session_str else StringSession()

        return TelegramClient(session, api_id, api_hash)

    def _destroy_client(self) -> None:
        """Вызывать только под self._lock."""
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
