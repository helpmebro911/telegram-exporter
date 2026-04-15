"""
DeepgramTranscriber — облачная транскрипция через Deepgram API.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .base import BaseTranscriber, TranscriptionError

_API_BASE = "https://api.deepgram.com/v1/listen"
_DEFAULT_MODEL = "nova-3"

# Deepgram обрабатывает большие файлы несколько минут; на мобильных/медленных
# каналах upload тоже занимает заметное время. 60 сек недостаточно.
_REQUEST_TIMEOUT = 300  # сек
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF = (2, 5)  # сек перед попыткой 2 и 3

# nova-3 поддерживает только en/multi для multilang. Для всего остального
# fallback на nova-2, который принимает явный `language=...` на многих языках.
_NOVA3_LANGS = {"en", "multi"}


class DeepgramTranscriber(BaseTranscriber):
    """
    Транскрипция через Deepgram nova-3 (или nova-2 для non-EN).

    Требует api_key. Не требует локальных моделей.
    """

    def __init__(self, api_key: str) -> None:
        api_key = (api_key or "").strip()
        if not api_key:
            raise TranscriptionError(
                "Deepgram API ключ не задан. Введите его в настройках."
            )
        self._api_key = api_key

    def preload(self) -> None:
        pass  # Облачный сервис — ничего предзагружать не нужно

    def transcribe(
        self,
        audio_data: bytes,
        content_type: str,
        language: str = "multi",
    ) -> Optional[str]:
        if not audio_data:
            return None

        ct = (content_type or "audio/ogg").split(";")[0].strip()
        ct = "audio/wav" if "wav" in ct.lower() else "audio/ogg"

        lang = (language or "multi").strip().lower()
        # nova-3 — самая свежая/быстрая, но надёжно поддерживает только en+multi.
        # Для русского/французского/etc. откатываемся на nova-2.
        model = _DEFAULT_MODEL if lang in _NOVA3_LANGS else "nova-2"
        params = {"model": model, "smart_format": "true"}
        if lang == "multi":
            params["language"] = "multi"
        elif lang != "multi":
            params["language"] = lang
        url = _API_BASE + "?" + urllib.parse.urlencode(params)

        req = urllib.request.Request(
            url,
            data=audio_data,
            method="POST",
            headers={
                "Authorization": "Token " + self._api_key,
                "Content-Type": ct,
            },
        )
        raw: Optional[str] = None
        last_exc: Optional[BaseException] = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                    raw = resp.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                # 4xx — клиентская ошибка, retry бесполезен
                if 400 <= exc.code < 500 and exc.code != 429:
                    raise TranscriptionError(
                        f"Deepgram HTTP {exc.code}: {exc.reason}"
                    ) from exc
                last_exc = exc
            except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
                last_exc = exc
            except Exception as exc:
                raise TranscriptionError(str(exc)[:200]) from exc
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF[attempt - 1])
        if raw is None:
            msg = str(last_exc) if last_exc else "unknown error"
            raise TranscriptionError(f"Deepgram недоступен: {msg[:200]}") from last_exc

        try:
            data = json.loads(raw)
            channels = data.get("results", {}).get("channels", [])
            if not channels:
                return None
            alts = channels[0].get("alternatives", [])
            if not alts:
                return None
            text = (alts[0].get("transcript") or "").strip()
            return text or None
        except Exception as exc:
            raise TranscriptionError(f"Deepgram ответ не распарсить: {exc}") from exc

    def unload(self) -> None:
        pass
