"""
ExportHistory — хранит последний экспортированный message_id для каждого чата.

Используется для инкрементального экспорта (только новые сообщения).
Файл: ~/.tg_exporter/export_history.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_HISTORY_PATH = Path(os.path.expanduser("~/.tg_exporter/export_history.json"))


class ExportHistory:
    """
    Персистентное хранилище последних exported message_id.

    Ключ — строковый peer_id чата.
    Значение — максимальный message_id из прошлого экспорта.
    """

    def __init__(self, path: Path = _HISTORY_PATH) -> None:
        self._path = path
        self._data: dict[str, int] = {}
        self._load()

    def get_last_id(self, peer_id: int) -> Optional[int]:
        """Возвращает последний экспортированный message_id для чата."""
        return self._data.get(str(peer_id))

    def set_last_id(self, peer_id: int, message_id: int) -> None:
        """Обновляет последний message_id и сохраняет на диск."""
        key = str(peer_id)
        current = self._data.get(key, 0)
        if message_id > current:
            self._data[key] = message_id
            self._save()

    def clear(self, peer_id: int) -> None:
        """Сбрасывает историю для конкретного чата."""
        key = str(peer_id)
        if key in self._data:
            del self._data[key]
            self._save()

    # ---- Internal ----

    def _load(self) -> None:
        try:
            if self._path.exists():
                with self._path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                # Только целочисленные значения
                self._data = {
                    k: int(v)
                    for k, v in raw.items()
                    if str(v).isdigit()
                }
        except Exception:
            self._data = {}

    def _save(self) -> None:
        """Атомарная запись: tmp + fsync + os.replace. Защита от поломки файла при крэше."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp_path, self._path)
        except Exception:
            pass
