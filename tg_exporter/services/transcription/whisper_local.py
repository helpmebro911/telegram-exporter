"""
WhisperTranscriber — локальная транскрипция через faster-whisper.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from typing import Callable, Optional, Any

from ...utils.logger import logger
from .base import BaseTranscriber, TranscriptionError


# Ориентировочные размеры моделей (для сообщения пользователю).
# Размер учитывает ~2x от распакованных весов (временные файлы + кеш).
_MODEL_SIZE_MB: dict[str, int] = {
    "tiny": 75,
    "base": 140,
    "small": 460,
    "medium": 1500,
    "large": 2900,
    "large-v2": 2900,
    "large-v3": 2900,
}

# HF repo-id для каждой модели faster-whisper (Systran — официальный репо faster-whisper).
_MODEL_REPO: dict[str, str] = {
    "tiny":     "Systran/faster-whisper-tiny",
    "base":     "Systran/faster-whisper-base",
    "small":    "Systran/faster-whisper-small",
    "medium":   "Systran/faster-whisper-medium",
    "large":    "Systran/faster-whisper-large-v3",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
}


StatusCallback = Callable[[str], None]
ProgressCallback = Callable[[float, str], None]  # (ratio 0..1, status_text)


class WhisperTranscriber(BaseTranscriber):
    """
    Транскрипция через faster-whisper (CPU/CUDA).

    Модель загружается лениво при первом вызове transcribe()
    и кешируется до вызова unload().
    """

    def __init__(
        self,
        model_size: str = "base",
        status_cb: Optional[StatusCallback] = None,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> None:
        self._model_size = model_size or "base"
        self._model: Optional[Any] = None
        self._status_cb = status_cb
        self._progress_cb = progress_cb

    def set_status_callback(self, cb: Optional[StatusCallback]) -> None:
        """Колбэк для промежуточных сообщений пользователю (из orchestrator)."""
        self._status_cb = cb

    def set_progress_callback(self, cb: Optional[ProgressCallback]) -> None:
        """Колбэк для прогресса скачивания модели (0..1, текст)."""
        self._progress_cb = cb

    def preload(self) -> None:
        self._load_model()

    def transcribe(
        self,
        audio_data: bytes,
        content_type: str,
        language: str = "multi",
    ) -> Optional[str]:
        if not audio_data:
            return None

        model = self._load_model()
        ext = ".wav" if "wav" in (content_type or "") else ".ogg"
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="tg_whisper_")
            os.close(fd)
            with open(tmp_path, "wb") as f:
                f.write(audio_data)

            lang = None if language == "multi" else language
            t0 = time.monotonic()
            logger.info(
                f"whisper: transcribe start (model={self._model_size}, "
                f"lang={lang or 'auto'}, size={len(audio_data)} bytes)"
            )
            segments, _ = model.transcribe(tmp_path, language=lang, beam_size=1)
            parts = [s.text for s in segments if s.text]
            result = " ".join(parts).strip() or None
            logger.info(
                f"whisper: transcribe done in {time.monotonic() - t0:.1f}s, "
                f"text_len={len(result) if result else 0}"
            )
            return result
        except Exception as exc:
            logger.error(f"whisper: transcribe failed: {exc}", exc=exc)
            raise TranscriptionError(str(exc)[:200]) from exc
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def unload(self) -> None:
        self._model = None

    # ---------------------------------------------------------- model loading

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            logger.error(f"whisper: faster-whisper not installed: {exc}")
            raise TranscriptionError(
                "Установите faster-whisper: pip install faster-whisper"
            ) from exc

        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"

        compute_type = "float16" if device == "cuda" else "int8"
        size_mb = _MODEL_SIZE_MB.get(self._model_size, 140)
        cached = _whisper_cache_exists(self._model_size)

        # Проверка свободного места на диске перед скачиванием
        if not cached:
            self._check_disk_space(size_mb)
            # Пробуем скачать модель с реальным прогрессом через huggingface_hub
            self._download_model_with_progress(size_mb)

        # Теперь модель гарантированно в кеше (или уже была) — WhisperModel
        # просто подхватит её локально без сети.
        self._emit_status(f"Загрузка модели Whisper «{self._model_size}»...")
        self._emit_progress(0.0, f"Инициализация модели «{self._model_size}»...")
        logger.info(
            f"whisper: loading model {self._model_size} ({device}/{compute_type})"
        )

        t0 = time.monotonic()
        try:
            self._model = WhisperModel(
                self._model_size, device=device, compute_type=compute_type
            )
            elapsed = time.monotonic() - t0
            logger.info(
                f"whisper: model loaded in {elapsed:.1f}s "
                f"(size={self._model_size}, device={device})"
            )
            self._emit_progress(1.0, f"Модель загружена ({elapsed:.0f}с)")
            self._emit_status("")
            return self._model
        except Exception as exc:
            elapsed = time.monotonic() - t0
            logger.error(
                f"whisper: model load failed after {elapsed:.1f}s "
                f"(size={self._model_size}): {exc}",
                exc=exc,
            )
            raise TranscriptionError(
                f"Не удалось загрузить модель Whisper «{self._model_size}»: "
                f"{str(exc)[:150]}"
            ) from exc

    def _download_model_with_progress(self, size_mb: int) -> None:
        """
        Скачивает модель через huggingface_hub.snapshot_download с реальным
        прогресс-баром. Если hub недоступен — тихо возвращается, и
        WhisperModel скачает её сам (без прогресса, но всё ещё работает).
        """
        repo_id = _MODEL_REPO.get(self._model_size)
        if not repo_id:
            logger.info(f"whisper: no known repo for {self._model_size}, skip progress download")
            return

        try:
            from huggingface_hub import snapshot_download
        except Exception as exc:
            logger.warning(f"whisper: huggingface_hub not available: {exc}")
            return

        tqdm_class = _make_progress_tqdm(self._progress_cb, self._model_size, size_mb)
        msg = (
            f"Скачивание модели Whisper «{self._model_size}» (~{size_mb} МБ). "
            "Это происходит один раз."
        )
        logger.info(f"whisper: downloading {repo_id} (~{size_mb} MB)")
        self._emit_status(msg)
        self._emit_progress(0.0, msg)
        t0 = time.monotonic()
        try:
            snapshot_download(repo_id=repo_id, tqdm_class=tqdm_class)
            elapsed = time.monotonic() - t0
            logger.info(f"whisper: download done in {elapsed:.1f}s")
            self._emit_progress(1.0, f"Модель скачана ({elapsed:.0f}с)")
        except Exception as exc:
            logger.error(f"whisper: download failed: {exc}", exc=exc)
            # Проверяем причину — чаще всего это нехватка места
            msg = str(exc).lower()
            if "no space" in msg or "enospc" in msg or "errno 28" in msg:
                raise TranscriptionError(
                    f"Недостаточно места на диске для модели «{self._model_size}» "
                    f"(~{size_mb} МБ). Освободите место и попробуйте снова."
                ) from exc
            raise TranscriptionError(
                f"Не удалось скачать модель «{self._model_size}»: "
                f"{str(exc)[:150]}"
            ) from exc

    def _check_disk_space(self, needed_mb: int) -> None:
        """
        Проверяет свободное место в директории HF-кеша.
        Требуем минимум needed_mb * 2.5 (запас на временные файлы и доппакеты).
        """
        try:
            cache_root = os.path.expanduser("~/.cache/huggingface")
            os.makedirs(cache_root, exist_ok=True)
            free_bytes = shutil.disk_usage(cache_root).free
            free_mb = free_bytes // (1024 * 1024)
            required_mb = int(needed_mb * 2.5)
            logger.info(
                f"whisper: disk check — free={free_mb} MB, required={required_mb} MB "
                f"(model={needed_mb} MB x2.5)"
            )
            if free_mb < required_mb:
                raise TranscriptionError(
                    f"Недостаточно места на диске для модели «{self._model_size}»: "
                    f"нужно ≈{required_mb} МБ, доступно {free_mb} МБ. "
                    f"Освободите место и попробуйте снова."
                )
        except TranscriptionError:
            raise
        except Exception as exc:
            logger.warning(f"whisper: disk space check failed: {exc}")

    # ---------------------------------------------------------- callbacks

    def _emit_status(self, text: str) -> None:
        if self._status_cb is not None:
            try:
                self._status_cb(text)
            except Exception:
                pass

    def _emit_progress(self, ratio: float, text: str) -> None:
        if self._progress_cb is not None:
            try:
                self._progress_cb(ratio, text)
            except Exception:
                pass


def _whisper_cache_exists(model_size: str) -> bool:
    """Эвристика: есть ли модель в HF-кеше."""
    try:
        from pathlib import Path
        home = Path(os.path.expanduser("~"))
        hf_hub = home / ".cache" / "huggingface" / "hub"
        if not hf_hub.exists():
            return False
        candidates = [
            f"models--Systran--faster-whisper-{model_size}",
            f"models--guillaumekln--faster-whisper-{model_size}",
        ]
        for c in candidates:
            d = hf_hub / c
            if d.exists():
                snapshots = d / "snapshots"
                if snapshots.exists() and any(snapshots.iterdir()):
                    return True
        return False
    except Exception:
        return False


def _make_progress_tqdm(
    progress_cb: Optional[ProgressCallback],
    model_size: str,
    size_mb: int,
):
    """
    Возвращает класс-заглушку tqdm, совместимый с huggingface_hub.
    Агрегирует байты по всем параллельным загрузкам файлов и шлёт ratio в UI.
    """
    # Общая статистика между экземплярами tqdm (snapshot_download создаёт их
    # отдельно для каждого файла).
    shared = {"total": 0, "done": 0, "last_emit": 0.0}

    def _emit(force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - shared["last_emit"]) < 0.3:
            return
        shared["last_emit"] = now
        total = shared["total"] or (size_mb * 1024 * 1024)
        done = min(shared["done"], total)
        ratio = done / total if total > 0 else 0.0
        mb_done = done / (1024 * 1024)
        mb_total = total / (1024 * 1024)
        text = (
            f"Скачивание модели Whisper «{model_size}»: "
            f"{mb_done:.0f} / {mb_total:.0f} МБ ({int(ratio * 100)}%)"
        )
        if progress_cb is not None:
            try:
                progress_cb(ratio, text)
            except Exception:
                pass

    class _ProgressTqdm:
        def __init__(self, *args, **kwargs) -> None:
            self._total = kwargs.get("total") or 0
            self._n = 0
            if self._total:
                shared["total"] += self._total

        def update(self, n: int = 1) -> None:
            self._n += n
            shared["done"] += n
            _emit()

        def close(self) -> None:
            # Если total был неизвестен — финальный n идёт в done как факт.
            _emit(force=True)

        def set_description(self, *_a, **_kw) -> None:
            pass

        def set_postfix(self, *_a, **_kw) -> None:
            pass

        def refresh(self, *_a, **_kw) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            self.close()

        def __iter__(self):
            return iter([])

        @property
        def n(self) -> int:
            return self._n

        @n.setter
        def n(self, value: int) -> None:
            delta = value - self._n
            self._n = value
            shared["done"] += delta
            _emit()

    return _ProgressTqdm
