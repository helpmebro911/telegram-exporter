"""
AddAccountModal — модалка добавления нового Telegram-аккаунта.

Использует отдельный TelegramClient поверх StringSession, не трогая текущий
активный клиент приложения. После успеха:
  - сохраняет session string в профиль (через App.save_active_profile_session
    логика вызывается с параметрами нового аккаунта)
  - переключает активный аккаунт

Flow: phone → code → (опц. 2FA) → success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional
import customtkinter as ctk

from ..theme import C, SPACING, WIDGET, font, font_display
from ..components.button import AppButton
from ..components.entry import AppEntry
from ..modal_utils import prepare_modal, show_modal

if TYPE_CHECKING:
    from ..app import App


class AddAccountModal(ctk.CTkToplevel):
    """Мини-флоу логина в отдельной модалке для второго+ аккаунта."""

    def __init__(self, app: "App") -> None:
        super().__init__(app)
        prepare_modal(self, app, 440, 460, "Добавить аккаунт")
        self._app = app
        self._client = None
        self._phone_hash: Optional[str] = None
        self._phone: str = ""
        self._step: str = "phone"  # phone | code | done
        self._build()
        show_modal(self, app)

    # ---------------------------------------------------------- build

    def _build(self) -> None:
        pad = SPACING["2xl"]

        ctk.CTkLabel(
            self, text="Добавить аккаунт",
            font=font_display(16, "bold"), text_color=C["text"],
        ).pack(pady=(pad, SPACING["xs"]))

        ctk.CTkLabel(
            self, text="Текущий аккаунт не выйдет — просто сохранится.",
            font=font(11), text_color=C["text_sec"],
            wraplength=360, justify="center",
        ).pack(pady=(0, SPACING["md"]))

        self._body = ctk.CTkFrame(self, fg_color="transparent")
        self._body.pack(fill="x", padx=pad)

        # Phone
        self._phone_frame = ctk.CTkFrame(self._body, fg_color="transparent")
        ctk.CTkLabel(
            self._phone_frame, text="Номер телефона",
            font=font(12), text_color=C["text_sec"], anchor="w",
        ).pack(fill="x")
        self._phone_entry = AppEntry(self._phone_frame, placeholder_text="+79991234567", size="md")
        self._phone_entry.pack(fill="x", pady=(SPACING["xs"], 0))
        self._phone_entry.bind("<Return>", lambda _e: self._on_send_code())

        # Code / 2FA
        self._code_frame = ctk.CTkFrame(self._body, fg_color="transparent")
        ctk.CTkLabel(
            self._code_frame, text="Код из Telegram",
            font=font(12), text_color=C["text_sec"], anchor="w",
        ).pack(fill="x")
        self._code_entry = AppEntry(self._code_frame, placeholder_text="12345", size="md")
        self._code_entry.pack(fill="x", pady=(SPACING["xs"], SPACING["sm"]))
        self._code_entry.bind("<Return>", lambda _e: self._on_submit_code())

        ctk.CTkLabel(
            self._code_frame, text="Пароль 2FA (если включён)",
            font=font(12), text_color=C["text_sec"], anchor="w",
        ).pack(fill="x")
        self._password_entry = AppEntry(
            self._code_frame, placeholder_text="пароль или пусто",
            show="•", size="md",
        )
        self._password_entry.pack(fill="x", pady=(SPACING["xs"], 0))
        self._password_entry.bind("<Return>", lambda _e: self._on_submit_code())

        # Status
        self._status_lbl = ctk.CTkLabel(
            self, text="", font=font(11),
            text_color=C["error"], wraplength=360, justify="left", anchor="w",
        )
        self._status_lbl.pack(fill="x", padx=pad, pady=(SPACING["sm"], 0))

        # Buttons — фикс-высота ряда чтобы кнопки не сжимались при packing
        btn_h = WIDGET["btn_h"]
        btn_row = ctk.CTkFrame(self, fg_color="transparent", height=btn_h)
        btn_row.pack(side="bottom", fill="x", padx=pad, pady=(SPACING["md"], pad))
        btn_row.pack_propagate(False)
        AppButton(btn_row, text="Отмена", variant="secondary", size="md",
                  command=self._on_cancel).pack(
            side="left", expand=True, fill="both", padx=(0, SPACING["sm"]),
        )
        self._primary_btn = AppButton(
            btn_row, text="Получить код", variant="primary", size="md",
            command=self._on_send_code,
        )
        self._primary_btn.pack(side="left", expand=True, fill="both")

        self._phone_frame.pack(fill="x")

    # ---------------------------------------------------------- actions

    def _on_send_code(self) -> None:
        phone = self._phone_entry.get().strip()
        if not phone:
            self._set_error("Введите номер телефона.")
            return
        if not phone.startswith("+"):
            phone = "+" + "".join(c for c in phone if c.isdigit())
        self._phone = phone
        self._set_error("")
        self._primary_btn.configure(state="disabled", text="Отправка кода...")
        self._app._worker.submit(self._bg_send_code, phone)

    def _on_submit_code(self) -> None:
        code = self._code_entry.get().strip()
        password = self._password_entry.get().strip()
        if not code:
            self._set_error("Введите код из Telegram.")
            return
        self._set_error("")
        self._primary_btn.configure(state="disabled", text="Проверка...")
        self._app._worker.submit(self._bg_verify_code, code, password)

    def _on_cancel(self) -> None:
        self._dispose_client()
        self.destroy()

    # ---------------------------------------------------------- background

    def _bg_send_code(self, phone: str) -> None:
        try:
            self._app._client_mgr.ensure_event_loop()
            client = self._make_client()
            if client is None:
                self._emit("add_account_error", "Сначала войдите в первый аккаунт — нужны API ID и Hash.")
                return
            self._client = client
            client.connect()
            sent = client.send_code_request(phone)
            self._phone_hash = sent.phone_code_hash
            self._emit("add_account_code_sent", None)
        except Exception as exc:
            self._emit("add_account_error", _friendly(exc))

    def _bg_verify_code(self, code: str, password: str) -> None:
        try:
            client = self._client
            if client is None or not self._phone_hash:
                self._emit("add_account_error", "Сначала запросите код.")
                return
            try:
                client.sign_in(phone=self._phone, code=code, phone_code_hash=self._phone_hash)
            except Exception as exc:
                if "SessionPasswordNeededError" in type(exc).__name__ or "SESSION_PASSWORD" in str(exc):
                    if not password:
                        self._emit("add_account_2fa", None)
                        return
                    client.sign_in(password=password)
                else:
                    raise
            session_str = client.session.save()
            me = client.get_me()
            phone = "+" + str(getattr(me, "phone", "") or "").lstrip("+")
            if phone == "+":
                phone = self._phone
            display_name = " ".join(filter(None, [
                getattr(me, "first_name", "") or "",
                getattr(me, "last_name", "") or "",
            ])).strip() or phone
            self._app._profiles.add_or_update(
                phone=phone,
                api_id=self._app.config.api_id,
                session_string=session_str,
                display_name=display_name,
                set_active=True,
            )
            try:
                client.disconnect()
            except Exception:
                pass
            self._client = None
            self._emit("add_account_done", phone)
        except Exception as exc:
            self._emit("add_account_error", _friendly(exc))

    def _make_client(self):
        """Собирает отдельный TelegramClient — не трогает активный `_client_mgr._client`."""
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
        api_id_int = self._app.config.api_id_int
        api_hash = self._app.credentials.load_api_hash(self._app.config.api_id)
        if not api_id_int or not api_hash:
            return None
        return TelegramClient(StringSession(), api_id_int, api_hash)

    def _dispose_client(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def _emit(self, event: str, payload) -> None:
        # Модалка сама регистрируется в App.on(...) через колбэки в handle_event
        self._app._worker.put_event(event, (self, payload))

    # ---------------------------------------------------------- ui updates (вызываются из App)

    def on_code_sent(self) -> None:
        self._step = "code"
        self._phone_frame.pack_forget()
        self._code_frame.pack(fill="x")
        self._primary_btn.configure(state="normal", text="Войти", command=self._on_submit_code)
        self._code_entry.focus_set()
        self._set_error("Код отправлен в Telegram.", color=C["text_sec"])

    def on_2fa_required(self) -> None:
        self._primary_btn.configure(state="normal", text="Войти", command=self._on_submit_code)
        self._set_error("Требуется пароль 2FA.", color=C["text_sec"])
        self._password_entry.focus_set()

    def on_done(self, phone: str) -> None:
        self.destroy()

    def on_error(self, message: str) -> None:
        self._primary_btn.configure(
            state="normal",
            text="Войти" if self._step == "code" else "Получить код",
        )
        self._set_error(message, color=C["error"])

    def _set_error(self, text: str, color=None) -> None:
        self._status_lbl.configure(text=text, text_color=color or C["error"])


def _friendly(exc: Exception) -> str:
    msg = str(exc)
    if "PHONE_CODE_INVALID" in msg:
        return "Неверный код."
    if "PHONE_CODE_EXPIRED" in msg:
        return "Код устарел. Запросите новый."
    if "PHONE_NUMBER_INVALID" in msg:
        return "Неверный номер."
    if "PHONE_NUMBER_BANNED" in msg:
        return "Номер заблокирован."
    if "PASSWORD_HASH_INVALID" in msg or ("password" in msg.lower() and "invalid" in msg.lower()):
        return "Неверный пароль 2FA."
    if "API_ID_INVALID" in msg:
        return "Неверный API ID/Hash."
    if "FLOOD_WAIT" in msg:
        return "Слишком много попыток. Подождите."
    if "network" in msg.lower() or "connect" in msg.lower():
        return "Ошибка сети."
    return msg[:200]
