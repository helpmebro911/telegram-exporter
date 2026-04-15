"""Tests for ProfileManager — хранение, CRUD, активный профиль, сессии в keyring."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class _FakeKeyring:
    """In-memory замена keyring для изоляции тестов от системного хранилища."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, key: str, value: str) -> None:
        self.store[(service, key)] = value

    def get_password(self, service: str, key: str):
        return self.store.get((service, key))

    def delete_password(self, service: str, key: str) -> None:
        self.store.pop((service, key), None)


class TestProfileManager(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._fake_home = Path(self._tmp.name)

        # Подмена keyring на in-memory fake (до импорта ProfileManager)
        self._fake_kr = _FakeKeyring()
        sys.modules["keyring"] = self._fake_kr  # type: ignore[assignment]
        self.addCleanup(lambda: sys.modules.pop("keyring", None))

        # Импортируем и патчим путь к profiles.json
        from tg_exporter.core import profiles as profiles_mod
        from tg_exporter.core.credentials import CredentialsManager
        from tg_exporter.core.profiles import ProfileManager

        self._profiles_mod = profiles_mod
        self._orig_path = profiles_mod._PROFILES_FILE
        profiles_mod._PROFILES_FILE = self._fake_home / "profiles.json"
        self.addCleanup(lambda: setattr(profiles_mod, "_PROFILES_FILE", self._orig_path))

        self._creds = CredentialsManager()
        # CredentialsManager._require_keyring() должен возвращать True с фейком
        self._creds._require_keyring = lambda: True  # type: ignore[method-assign]
        self.pm = ProfileManager(self._creds)

    def test_empty_initial_state(self):
        self.assertTrue(self.pm.is_empty())
        self.assertIsNone(self.pm.active())
        self.assertEqual(self.pm.list(), [])

    def test_add_and_list(self):
        p = self.pm.add_or_update(
            phone="+79991112233", api_id="42",
            session_string="session-A", display_name="Max",
        )
        self.assertEqual(p.phone, "+79991112233")
        self.assertEqual(p.display_name, "Max")
        self.assertFalse(self.pm.is_empty())
        self.assertEqual(self.pm.active_phone(), "+79991112233")
        self.assertEqual(len(self.pm.list()), 1)

    def test_session_stored_in_keyring(self):
        self.pm.add_or_update(
            phone="+79991112233", api_id="42",
            session_string="session-A",
        )
        key = ("tg_exporter", "42:session:+79991112233")
        self.assertEqual(self._fake_kr.store.get(key), "session-A")

    def test_add_second_profile_preserves_active(self):
        self.pm.add_or_update(phone="+71111111111", api_id="42", session_string="s1")
        self.pm.add_or_update(
            phone="+72222222222", api_id="42",
            session_string="s2", set_active=False,
        )
        self.assertEqual(len(self.pm.list()), 2)
        self.assertEqual(self.pm.active_phone(), "+71111111111")

    def test_set_active_switches(self):
        self.pm.add_or_update(phone="+71111111111", api_id="42", session_string="s1")
        self.pm.add_or_update(
            phone="+72222222222", api_id="42",
            session_string="s2", set_active=False,
        )
        result = self.pm.set_active("+72222222222")
        self.assertIsNotNone(result)
        self.assertEqual(self.pm.active_phone(), "+72222222222")

    def test_set_active_unknown_returns_none(self):
        self.pm.add_or_update(phone="+71111111111", api_id="42", session_string="s1")
        self.assertIsNone(self.pm.set_active("+70000000000"))
        self.assertEqual(self.pm.active_phone(), "+71111111111")

    def test_remove_deletes_session(self):
        self.pm.add_or_update(phone="+71111111111", api_id="42", session_string="s1")
        self.pm.add_or_update(
            phone="+72222222222", api_id="42",
            session_string="s2", set_active=False,
        )
        self.assertTrue(self.pm.remove("+71111111111"))
        # Активный должен переключиться на оставшийся
        self.assertEqual(self.pm.active_phone(), "+72222222222")
        # Сессия удалена из keyring
        self.assertNotIn(("tg_exporter", "42:session:+71111111111"), self._fake_kr.store)

    def test_remove_last_clears_active(self):
        self.pm.add_or_update(phone="+71111111111", api_id="42", session_string="s1")
        self.pm.remove("+71111111111")
        self.assertIsNone(self.pm.active_phone())
        self.assertTrue(self.pm.is_empty())

    def test_remove_unknown_returns_false(self):
        self.assertFalse(self.pm.remove("+70000000000"))

    def test_rename(self):
        self.pm.add_or_update(phone="+71111111111", api_id="42", session_string="s1")
        self.assertTrue(self.pm.rename("+71111111111", "Работа"))
        self.assertEqual(self.pm.get("+71111111111").display_name, "Работа")

    def test_load_session_roundtrip(self):
        p = self.pm.add_or_update(
            phone="+71111111111", api_id="42",
            session_string="my-session-string",
        )
        self.assertEqual(self.pm.load_session(p), "my-session-string")

    def test_persistence_across_instances(self):
        self.pm.add_or_update(phone="+71111111111", api_id="42", session_string="s1")
        self.pm.add_or_update(
            phone="+72222222222", api_id="42",
            session_string="s2", set_active=False,
        )
        self.pm.set_active("+72222222222")

        from tg_exporter.core.profiles import ProfileManager
        pm2 = ProfileManager(self._creds)
        self.assertEqual(pm2.active_phone(), "+72222222222")
        self.assertEqual(len(pm2.list()), 2)

    def test_phone_normalization(self):
        p = self.pm.add_or_update(
            phone="7 999 111-22-33", api_id="42", session_string="s",
        )
        self.assertEqual(p.phone, "79991112233")

    def test_empty_phone_raises(self):
        with self.assertRaises(ValueError):
            self.pm.add_or_update(phone="   ", api_id="42", session_string="s")

    def test_empty_api_id_raises(self):
        with self.assertRaises(ValueError):
            self.pm.add_or_update(phone="+71111111111", api_id="", session_string="s")

    def test_update_existing_keeps_phone(self):
        self.pm.add_or_update(
            phone="+71111111111", api_id="42",
            session_string="v1", display_name="Old",
        )
        updated = self.pm.add_or_update(
            phone="+71111111111", api_id="42",
            session_string="v2", display_name="New",
        )
        self.assertEqual(updated.display_name, "New")
        self.assertEqual(len(self.pm.list()), 1)
        key = ("tg_exporter", "42:session:+71111111111")
        self.assertEqual(self._fake_kr.store.get(key), "v2")

    def test_file_has_no_session_secrets(self):
        self.pm.add_or_update(
            phone="+71111111111", api_id="42",
            session_string="super-secret-session",
        )
        path = self._fake_home / "profiles.json"
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("super-secret-session", raw)
        data = json.loads(raw)
        self.assertEqual(data["active_phone"], "+71111111111")
        self.assertEqual(len(data["profiles"]), 1)


if __name__ == "__main__":
    unittest.main()
