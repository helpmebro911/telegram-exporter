"""
ProfileManager — управление несколькими Telegram-аккаунтами.

Метаданные профилей (несекретные): ~/.tg_exporter/profiles.json.
Сессии (секретные) хранятся в Keyring под ключом `{api_id}:session:{phone}`.

Формат profiles.json:
{
  "active_phone": "+7999...",
  "profiles": [
    {"phone": "+7999...", "display_name": "Max", "api_id": "123"},
    ...
  ]
}
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .credentials import CredentialsManager
from ..utils.logger import logger


_PROFILES_FILE = Path(os.path.expanduser("~/.tg_exporter/profiles.json"))


@dataclass
class Profile:
    phone: str
    display_name: str = ""
    api_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def _session_key(api_id: str, phone: str) -> str:
    return f"{api_id}:session:{phone}"


class ProfileManager:
    """
    CRUD над списком профилей + активным профилем.

    Thread-safe: внутренний lock защищает загрузку/сохранение файла.
    Секреты (session string) всегда идут через CredentialsManager/Keyring.
    """

    def __init__(self, credentials: CredentialsManager) -> None:
        self._credentials = credentials
        self._lock = threading.Lock()
        self._profiles: list[Profile] = []
        self._active_phone: Optional[str] = None
        self._load()

    # ---------------------------------------------------------- persistence

    def _load(self) -> None:
        if not _PROFILES_FILE.exists():
            return
        try:
            with _PROFILES_FILE.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            self._active_phone = raw.get("active_phone") or None
            self._profiles = [
                Profile.from_dict(p) for p in (raw.get("profiles") or [])
                if isinstance(p, dict) and p.get("phone")
            ]
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            logger.warning(f"profiles: load failed: {exc}")

    def _save(self) -> None:
        _PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "active_phone": self._active_phone,
            "profiles": [p.to_dict() for p in self._profiles],
        }
        tmp = _PROFILES_FILE.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, _PROFILES_FILE)
        _secure_permissions(_PROFILES_FILE)

    # ---------------------------------------------------------- queries

    def list(self) -> list[Profile]:
        with self._lock:
            return list(self._profiles)

    def active(self) -> Optional[Profile]:
        with self._lock:
            if not self._active_phone:
                return None
            return next((p for p in self._profiles if p.phone == self._active_phone), None)

    def active_phone(self) -> Optional[str]:
        with self._lock:
            return self._active_phone

    def get(self, phone: str) -> Optional[Profile]:
        phone = _normalize_phone(phone)
        with self._lock:
            return next((p for p in self._profiles if p.phone == phone), None)

    def is_empty(self) -> bool:
        with self._lock:
            return not self._profiles

    # ---------------------------------------------------------- mutations

    def add_or_update(
        self,
        phone: str,
        api_id: str,
        session_string: str,
        display_name: str = "",
        set_active: bool = True,
    ) -> Profile:
        """Добавляет новый профиль (или обновляет существующий по phone)."""
        phone = _normalize_phone(phone)
        if not phone:
            raise ValueError("phone required")
        if not api_id:
            raise ValueError("api_id required")
        if session_string:
            self._credentials._require_keyring()  # type: ignore[attr-defined]
            import keyring
            keyring.set_password("tg_exporter", _session_key(api_id, phone), session_string)
        with self._lock:
            existing = next((p for p in self._profiles if p.phone == phone), None)
            if existing is not None:
                existing.api_id = api_id
                if display_name:
                    existing.display_name = display_name
                profile = existing
            else:
                profile = Profile(phone=phone, display_name=display_name or phone, api_id=api_id)
                self._profiles.append(profile)
            if set_active or self._active_phone is None:
                self._active_phone = phone
            self._save()
            return profile

    def set_active(self, phone: str) -> Optional[Profile]:
        phone = _normalize_phone(phone)
        with self._lock:
            profile = next((p for p in self._profiles if p.phone == phone), None)
            if profile is None:
                return None
            self._active_phone = profile.phone
            self._save()
            return profile

    def remove(self, phone: str) -> bool:
        """Удаляет профиль и его сессию из Keyring."""
        phone = _normalize_phone(phone)
        with self._lock:
            profile = next((p for p in self._profiles if p.phone == phone), None)
            if profile is None:
                return False
            self._profiles = [p for p in self._profiles if p.phone != phone]
            if self._active_phone == phone:
                self._active_phone = self._profiles[0].phone if self._profiles else None
            self._save()
            api_id = profile.api_id
        self._delete_session(api_id, phone)
        return True

    def rename(self, phone: str, display_name: str) -> bool:
        phone = _normalize_phone(phone)
        with self._lock:
            profile = next((p for p in self._profiles if p.phone == phone), None)
            if profile is None:
                return False
            profile.display_name = display_name or phone
            self._save()
            return True

    # ---------------------------------------------------------- session I/O

    def load_session(self, profile: Profile) -> Optional[str]:
        if not profile.api_id or not profile.phone:
            return None
        try:
            import keyring
            return keyring.get_password("tg_exporter", _session_key(profile.api_id, profile.phone)) or None
        except Exception:
            return None

    def save_session(self, profile: Profile, session_string: str) -> None:
        if not session_string or not profile.api_id or not profile.phone:
            return
        try:
            import keyring
            keyring.set_password("tg_exporter", _session_key(profile.api_id, profile.phone), session_string)
        except Exception as exc:
            logger.error(f"profiles: save_session failed: {exc}")

    def _delete_session(self, api_id: str, phone: str) -> None:
        if not api_id or not phone:
            return
        try:
            import keyring
            key = _session_key(api_id, phone)
            if keyring.get_password("tg_exporter", key):
                keyring.delete_password("tg_exporter", key)
        except Exception:
            pass


def _normalize_phone(phone: str) -> str:
    phone = (phone or "").strip()
    if not phone:
        return ""
    # Оставляем только `+` в начале и цифры
    digits = "".join(c for c in phone if c.isdigit())
    if phone.startswith("+"):
        return "+" + digits
    return digits


def _secure_permissions(path: Path) -> None:
    import platform
    if platform.system() == "Windows":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
