"""
ExportOrchestrator — выполняет одну задачу экспорта используя Phase 2 сервисы.

Работает целиком в фоновом потоке. Прогресс и результаты отправляются
через callback (обычно worker.put_event).

Отмена происходит через CancellationToken — проверяется в каждой итерации.
"""

from __future__ import annotations

import datetime
import os
from typing import Callable, Optional

from telethon.utils import get_peer_id

from .client import TelegramClientManager
from .converter import message_to_export
from ..exporters import JsonExporter, MarkdownExporter
from ..models.export_task import ExportTask, ExportProgress, ExportFormat
from ..models.config import AppConfig
from ..services.analytics import AnalyticsCollector, render_top_authors, render_activity
from ..services.export_history import ExportHistory
from ..services.media_downloader import MediaDownloader, MediaDirs, AudioPrepResult
from ..services.media_downloader import MediaTooLongError, MediaProcessingError
from ..services.transcription import create_transcriber, TranscriptionError
from ..utils.cancellation import CancellationToken, CancelledError
from ..utils.logger import logger


EventCallback = Callable[[str, object], None]


class ExportOrchestrator:
    """
    Запускает экспорт для одного чата/топика.

    Использование:
        orch = ExportOrchestrator(client_manager, config)
        orch.run(task, token, progress, send_event)
    """

    def __init__(
        self,
        client_manager: TelegramClientManager,
        config: AppConfig,
        history: ExportHistory,
        deepgram_key: Optional[str] = None,
    ) -> None:
        self._client = client_manager
        self._config = config
        self._history = history
        self._deepgram_key = deepgram_key
        self._media = MediaDownloader()

    def run(
        self,
        dialog,
        task: ExportTask,
        token: CancellationToken,
        progress: ExportProgress,
        send: EventCallback,
    ) -> None:
        """
        Основной метод — выполняется в фоновом потоке.
        Отправляет события: export_start, export_progress, export_status,
                            export_done, export_error, export_cancelled.
        """
        try:
            self._do_run(dialog, task, token, progress, send)
        except CancelledError:
            progress.cancel()
            send("export_cancelled", None)
        except Exception as exc:
            msg = _friendly_error(str(exc))
            progress.fail(msg)
            logger.error("Export failed", exc=exc)
            send("export_error", msg)

    # ---- Internal ----

    def _do_run(
        self,
        dialog,
        task: ExportTask,
        token: CancellationToken,
        progress: ExportProgress,
        send: EventCallback,
    ) -> None:
        token.raise_if_cancelled()
        c = self._client.ensure_connected()

        # --- Подготовка директории ---
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        chat_title = _safe_name(dialog.name or "chat", 60)
        if task.topic_title:
            chat_title = f"{chat_title}_topic_{_safe_name(task.topic_title, 40)}"
        export_dir = os.path.join(task.output_path, f"{chat_title}_{timestamp}")
        os.makedirs(export_dir, exist_ok=True)

        # --- Подсчёт сообщений ---
        total = self._count_messages(c, dialog, task)
        export_label = dialog.name or "Чат"
        if task.topic_title:
            export_label = f"{export_label} → {task.topic_title}"
        progress.start()
        progress.total_messages = total or 0
        send("export_start", (export_label, total))

        # --- Предзагрузка транскрибера ---
        transcriber = None
        transcribe_failed = False
        if task.transcribe_audio:
            try:
                transcriber = create_transcriber(self._config, self._deepgram_key)
                # Статус-колбэк (сообщения) + прогресс-колбэк (скачивание модели).
                status_setter = getattr(transcriber, "set_status_callback", None)
                if callable(status_setter):
                    status_setter(lambda text: send("export_status", text))
                progress_setter = getattr(transcriber, "set_progress_callback", None)
                if callable(progress_setter):
                    progress_setter(
                        lambda ratio, text: send("model_download_progress", (ratio, text))
                    )
                if self._config.transcription_provider != "deepgram":
                    send("export_status", "Подготовка модели транскрипции...")
                    logger.info(
                        f"transcription: preload start "
                        f"(provider={self._config.transcription_provider}, "
                        f"model={self._config.local_whisper_model})"
                    )
                    transcriber.preload()
                    logger.info("transcription: preload done")
                    send("export_status", "")
            except TranscriptionError as exc:
                logger.warning(f"transcription: preload failed: {exc}")
                send("export_status", "")
                send("info", f"Транскрипция недоступна: {exc}. Экспорт продолжен без неё.")
                transcriber = None
                transcribe_failed = True
            except Exception as exc:
                logger.error(f"transcription: unexpected preload error: {exc}", exc=exc)
                send("export_status", "")
                send("info", f"Транскрипция недоступна: {exc}. Экспорт продолжен без неё.")
                transcriber = None
                transcribe_failed = True

        # --- Медиа-директории ---
        media_dirs: Optional[MediaDirs] = None
        if task.download_media:
            try:
                media_dirs = MediaDirs.create(os.path.join(export_dir, "media"))
            except Exception:
                media_dirs = None

        # --- Создаём экспортёры ---
        json_exp: Optional[JsonExporter] = None
        md_exp: Optional[MarkdownExporter] = None

        if task.format in (ExportFormat.JSON, ExportFormat.BOTH):
            json_exp = JsonExporter(include_views=True)
            json_exp.open(export_dir, dialog.name or "Chat", task.topic_title)

        if task.format in (ExportFormat.MARKDOWN, ExportFormat.BOTH):
            md_exp = MarkdownExporter(
                settings=self._config.markdown,
                popular_min_reactions=0,  # популярные пока отключены — TODO в следующей итерации
            )
            md_exp.open(export_dir, dialog.name or "Chat", task.topic_title)

        # --- Аналитика ---
        analytics = AnalyticsCollector() if task.collect_analytics else None

        # --- Параметры итерации ---
        iter_kwargs: dict = {"reverse": True}
        if task.topic_id is not None:
            iter_kwargs["reply_to"] = task.topic_id
        if task.date_from is not None:
            iter_kwargs["offset_date"] = task.date_from
        if task.is_incremental_with_offset:
            iter_kwargs["min_id"] = task.last_exported_id

        date_to_end = (
            (task.date_to + datetime.timedelta(days=1)) if task.date_to else None
        )

        # --- Основной цикл ---
        count = 0
        max_msg_id = 0
        transcribe_warned = False
        video_note_saved_ids: set[int] = set()

        for msg in c.iter_messages(dialog, **iter_kwargs):
            token.raise_if_cancelled()

            if date_to_end and hasattr(msg, "date") and msg.date and msg.date >= date_to_end:
                break

            msg_id = getattr(msg, "id", 0) or 0
            if msg_id > max_msg_id:
                max_msg_id = msg_id

            # Фильтр авторов
            if not task.author_filter.is_empty():
                sender_id = getattr(msg, "sender_id", None)
                if not task.author_filter.matches(sender_id):
                    count += 1
                    _maybe_send_progress(send, count, total)
                    continue

            export_msg = message_to_export(msg)

            # Транскрипция
            if (
                transcriber is not None
                and not transcribe_failed
                and export_msg.media_type is not None
                and export_msg.media_type.value in ("voice", "video_note")
            ):
                token.raise_if_cancelled()
                try:
                    send("export_status", "Скачивание голосового сообщения...")
                    prep: Optional[AudioPrepResult] = self._media.prepare_audio(msg, token)
                    send("export_status", "")

                    if prep is not None:
                        token.raise_if_cancelled()
                        send("export_status", "Транскрипция...")
                        try:
                            text = transcriber.transcribe(
                                prep.audio_data,
                                prep.content_type,
                                self._config.transcription_language,
                            )
                        except TranscriptionError as exc:
                            text = None
                            if not transcribe_warned:
                                transcribe_warned = True
                                reason = str(exc)
                                send("info", f"Не удалось транскрибировать: {reason}. Экспорт продолжен.")
                        send("export_status", "")

                        if text:
                            export_msg = export_msg.with_transcription(text)

                        # Сохраняем WAV video_note в media/audio
                        if prep.saved_path and media_dirs:
                            audio_out = os.path.join(media_dirs.audio, f"vn_{msg_id}.wav")
                            try:
                                import shutil
                                shutil.move(prep.saved_path, audio_out)
                                video_note_saved_ids.add(msg_id)
                            except Exception:
                                pass

                except (MediaTooLongError, MediaProcessingError) as exc:
                    send("export_status", "")
                    if not transcribe_warned:
                        transcribe_warned = True
                        send("info", str(exc))
                except CancelledError:
                    raise
                except Exception:
                    send("export_status", "")

            # Запись в экспортёры
            if json_exp:
                json_exp.write(export_msg)
            if md_exp:
                md_exp.write(export_msg)

            # Аналитика
            if analytics and export_msg.type == "message":
                is_out = bool(getattr(msg, "out", False))
                formatted = export_msg.text or ""
                analytics.add(export_msg, formatted, is_out)

            # Скачивание медиа
            if media_dirs and export_msg.media_type is not None:
                token.raise_if_cancelled()
                self._media.download(msg, media_dirs, token, video_note_saved_ids)

            count += 1
            _maybe_send_progress(send, count, total)

        # --- Финализация ---
        token.raise_if_cancelled()

        output_files: list[str] = []
        if json_exp:
            output_files.extend(json_exp.finalize())
        if md_exp:
            output_files.extend(md_exp.finalize())

        # Аналитика → файлы
        if analytics:
            result = analytics.result()
            if result.authors:
                parts = render_top_authors(result, self._config.markdown.words_per_file)
                for i, part in enumerate(parts):
                    suffix = "" if i == 0 else f"_part_{i + 1}"
                    path = os.path.join(export_dir, f"top_authors{suffix}.md")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(part)
                    output_files.append(path)
            if result.activity:
                act_path = os.path.join(export_dir, "activity.md")
                with open(act_path, "w", encoding="utf-8") as f:
                    f.write(render_activity(result))
                output_files.append(act_path)

        # Инкрементальная история
        if max_msg_id > 0:
            try:
                peer_id = get_peer_id(dialog.entity)
                self._history.set_last_id(peer_id, max_msg_id)
            except Exception:
                pass

        # Освобождаем модель
        if transcriber:
            transcriber.unload()

        if total:
            send("export_progress", (total, total))

        progress.finish()
        progress.output_files = output_files
        send("export_done", (export_dir, output_files))

    # ---- Helpers ----

    def _count_messages(self, c, dialog, task: ExportTask) -> Optional[int]:
        try:
            kwargs: dict = {"limit": 0}
            if task.topic_id is not None:
                kwargs["reply_to"] = task.topic_id
            if task.is_incremental_with_offset:
                kwargs["min_id"] = task.last_exported_id

            total_all = getattr(c.get_messages(dialog, **kwargs), "total", None)
            if total_all is None:
                return None

            if task.date_from is not None:
                before_from = getattr(c.get_messages(dialog, offset_date=task.date_from, **kwargs), "total", 0) or 0
                total = max(0, total_all - before_from)
            else:
                total = total_all

            if task.date_to is not None:
                after_to = task.date_to + datetime.timedelta(days=1)
                before_to = getattr(c.get_messages(dialog, offset_date=after_to, **kwargs), "total", 0) or 0
                if task.date_from is not None:
                    total = max(0, total - (total_all - before_to))
                else:
                    total = before_to

            return total
        except Exception:
            return None


# ---- Helpers ----

def _safe_name(name: str, max_len: int) -> str:
    import re
    name = re.sub(r'[\\/:*?"<>|!@#$%^&*()+=\[\]{}|;:,.<>?`~]+', "_", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    if len(name) > max_len:
        name = name[:max_len].rstrip("_")
    return name or "chat"


def _maybe_send_progress(send: EventCallback, count: int, total: Optional[int]) -> None:
    if total and (count <= 1 or count % 20 == 0):
        send("export_progress", (count, total))
    elif not total and (count <= 1 or count % 50 == 0):
        send("export_progress", (count, None))


def _friendly_error(msg: str) -> str:
    if "WinError 2" in msg or "No such file" in msg:
        return "Не удалось создать файл. Выберите другую папку."
    if "WinError 5" in msg or "Access is denied" in msg:
        return "Нет доступа к папке. Выберите другую папку."
    return msg
