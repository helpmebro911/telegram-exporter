"""
ExportTask — описание и состояние одной задачи экспорта.

Параметры задачи иммутабельны после создания.
Прогресс обновляется через ExportProgress (отдельный изменяемый объект).
"""

from __future__ import annotations

import dataclasses
import datetime
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class ExportFormat(str, Enum):
    JSON = "json"
    MARKDOWN = "markdown"
    BOTH = "both"


class ExportStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    DONE = auto()
    CANCELLED = auto()
    ERROR = auto()


@dataclass(frozen=True)
class AuthorFilter:
    """Фильтр по авторам сообщений."""
    user_ids: frozenset[int] = field(default_factory=frozenset)

    @classmethod
    def from_ids(cls, ids: list[int]) -> "AuthorFilter":
        return cls(user_ids=frozenset(ids))

    def is_empty(self) -> bool:
        return len(self.user_ids) == 0

    def matches(self, user_id: Optional[int]) -> bool:
        if self.is_empty():
            return True
        return user_id in self.user_ids


@dataclass(frozen=True)
class ExportTask:
    """
    Параметры задачи экспорта. Иммутабелен — создаётся один раз перед запуском.

    Содержит только то что нужно знать до начала экспорта.
    Прогресс хранится отдельно в ExportProgress.
    """

    # Идентификатор чата
    chat_id: int
    chat_name: str

    # Куда писать результат
    output_path: str

    # Формат экспорта
    format: ExportFormat = ExportFormat.BOTH

    # Фильтрация по дате
    date_from: Optional[datetime.datetime] = None
    date_to: Optional[datetime.datetime] = None

    # Топик (для форумов)
    topic_id: Optional[int] = None
    topic_title: Optional[str] = None

    # Медиа
    download_media: bool = False

    # Аналитика
    collect_analytics: bool = False

    # Транскрипция
    transcribe_audio: bool = False
    transcription_provider: str = "local"
    transcription_language: str = "multi"
    local_whisper_model: str = "base"
    deepgram_api_key: str = ""

    # Фильтр авторов
    author_filter: AuthorFilter = field(default_factory=AuthorFilter)

    # Инкрементальный экспорт (только новые сообщения)
    incremental: bool = False
    last_exported_id: Optional[int] = None  # для инкрементального

    # Лимит сообщений (0 = без лимита)
    message_limit: int = 0

    # Настройки Markdown
    words_per_file: int = 50_000

    def with_last_id(self, last_id: int) -> "ExportTask":
        return dataclasses.replace(self, last_exported_id=last_id)

    @property
    def is_incremental_with_offset(self) -> bool:
        return self.incremental and self.last_exported_id is not None


@dataclass
class ExportProgress:
    """
    Изменяемое состояние выполнения задачи.
    Обновляется в фоновом потоке, читается UI-потоком через очередь.
    """

    status: ExportStatus = ExportStatus.PENDING

    # Счётчики сообщений
    total_messages: int = 0          # известно не сразу — 0 пока не определено
    processed_messages: int = 0
    skipped_messages: int = 0

    # Медиа
    media_downloaded: int = 0
    media_failed: int = 0

    # Файлы вывода
    output_files: list[str] = field(default_factory=list)

    # Ошибки
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    # Время
    started_at: Optional[datetime.datetime] = None
    finished_at: Optional[datetime.datetime] = None

    def start(self) -> None:
        self.status = ExportStatus.RUNNING
        self.started_at = datetime.datetime.now()

    def finish(self) -> None:
        self.status = ExportStatus.DONE
        self.finished_at = datetime.datetime.now()

    def cancel(self) -> None:
        self.status = ExportStatus.CANCELLED
        self.finished_at = datetime.datetime.now()

    def fail(self, error: str) -> None:
        self.status = ExportStatus.ERROR
        self.error = error
        self.finished_at = datetime.datetime.now()

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def add_output_file(self, path: str) -> None:
        if path not in self.output_files:
            self.output_files.append(path)

    @property
    def elapsed_seconds(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.finished_at or datetime.datetime.now()
        return (end - self.started_at).total_seconds()

    @property
    def progress_ratio(self) -> Optional[float]:
        """0.0–1.0, или None если total неизвестен."""
        if self.total_messages <= 0:
            return None
        return min(self.processed_messages / self.total_messages, 1.0)

    @property
    def messages_per_second(self) -> Optional[float]:
        elapsed = self.elapsed_seconds
        if not elapsed or self.processed_messages == 0:
            return None
        return self.processed_messages / elapsed

    @property
    def eta_seconds(self) -> Optional[float]:
        """Оценка оставшегося времени в секундах."""
        ratio = self.progress_ratio
        elapsed = self.elapsed_seconds
        if ratio is None or ratio <= 0 or elapsed is None:
            return None
        if ratio >= 1.0:
            return 0.0
        return elapsed / ratio * (1.0 - ratio)
