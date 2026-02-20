import asyncio
import datetime
import json
import os
import queue
import re
import socket
import threading
import tkinter as tk
import subprocess
import tempfile
import time
import platform
import traceback
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional


class ExportCancelled(Exception):
    pass

import customtkinter as ctk
from telethon import functions
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.sync import TelegramClient
from telethon.utils import get_display_name, get_peer_id
try:
    import socks
except ImportError:
    socks = None
try:
    import keyring
except Exception:
    keyring = None

# --- CONFIG & THEME ---

ctk.set_appearance_mode("System")  # Follow OS theme (Light/Dark)
ctk.set_default_color_theme("blue")

COLORS = {
    "bg": ("#FFFFFF", "#1E1E1E"),           # Main background
    "card": ("#F3F4F6", "#2B2B2B"),         # Secondary/Card bg
    "text": ("#111827", "#F3F4F6"),         # Main Text
    "text_sec": ("#6B7280", "#9CA3AF"),     # Secondary Text
    "primary": ("#2563EB", "#3B82F6"),      # Action Blue
    "primary_hover": ("#1D4ED8", "#2563EB"),
    "border": ("#E5E7EB", "#374151"),       # Divider
    "success": ("#10B981", "#10B981"),
    "error": ("#EF4444", "#EF4444"),
}

# --- HELPERS ---

OS_NAME = platform.system()
if OS_NAME == "Windows":
    FONT_TEXT = "Segoe UI"
    FONT_DISPLAY = "Segoe UI"
elif OS_NAME == "Darwin":
    FONT_TEXT = "SF Pro Text"
    FONT_DISPLAY = "SF Pro Display"
else:
    FONT_TEXT = "Helvetica"
    FONT_DISPLAY = "Helvetica"

def get_color(key, mode="light"):
    # mode is handled by CTk automatically if we pass tuple (light, dark)
    return COLORS[key]

def pick_color(value):
    if isinstance(value, tuple):
        return value[0] if ctk.get_appearance_mode() == "Light" else value[1]
    return value


def _log_path() -> Path:
    return Path(os.path.expanduser("~/.tg_exporter/app.log"))


def _redact_sensitive(text: str) -> str:
    if not text:
        return text
    # Redact common secrets and identifiers from logs
    text = re.sub(r"(?i)api[_-]?hash\s*[:=]\s*[A-Za-z0-9]+", "api_hash=<redacted>", text)
    text = re.sub(r"(?i)api[_-]?id\s*[:=]\s*\d+", "api_id=<redacted>", text)
    text = re.sub(r"(?i)session\s*[:=]\s*[A-Za-z0-9+/=_-]{20,}", "session=<redacted>", text)
    text = re.sub(r"\+?\d{7,15}", "<redacted_phone>", text)
    return text


def _write_fatal_error(exc: BaseException) -> None:
    try:
        log_path = _log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write("\n==== FATAL ====\n")
            f.write(datetime.datetime.now().isoformat())
            f.write("\n")
            details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            f.write(_redact_sensitive(details))
            f.write("\n")
    except Exception:
        pass

MARKDOWN_SETTINGS = {
    "words_per_file": 50000,
    "date_format": "DD.MM.YYYY",
    "include_timestamps": True,
    "include_author": True,
    "include_replies": True,
    "include_reactions": False,
    "include_polls": False,
    "include_forwarded": True,
    "plain_text": True,
}


def _sanitize_md_filename(value: str) -> str:
    cleaned = sanitize_filename(value).replace(" ", "_")
    return cleaned if cleaned else "Telegram_Chat"


def _strip_markdown(text: str) -> str:
    cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    cleaned = cleaned.replace("**", "").replace("*", "").replace("`", "")
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned


def _format_reactions(reactions: list[dict]) -> str:
    items = []
    for reaction in reactions:
        emoji = reaction.get("emoji")
        count = reaction.get("count")
        if emoji:
            items.append(f"{emoji}×{count}")
        else:
            items.append(f"реакция×{count}")
    return f"Реакции: {' · '.join(items)}"


def _format_poll(poll: dict) -> str:
    question = normalize_text(poll.get("question", "")).strip()
    answers = poll.get("answers") or []
    lines = []
    for idx, answer in enumerate(answers, start=1):
        text = normalize_text(answer.get("text", ""))
        voters = answer.get("voters")
        prefix = f"{idx}."
        lines.append(f"{prefix} {text} — {voters}")
    header = f"Опрос: {question}" if question else "Опрос"
    total = poll.get("total_voters")
    return f"{header}\n" + "\n".join(lines) + f"\nВсего голосов: {total}"


def _build_topics_index(topic_map: dict[str, str]) -> str:
    if not topic_map:
        return ""
    items = []
    for topic_id, title in topic_map.items():
        normalized = title.strip() if title and str(title).strip() else ""
        if not normalized:
            continue
        items.append((topic_id, normalized))
    if not items:
        return ""
    items.sort(key=lambda x: (int(x[0]) if str(x[0]).isdigit() else 10**9, x[1]))
    lines = [f"{idx}. {title} (topic_id={topic_id})" for idx, (topic_id, title) in enumerate(items, 1)]
    return "# Темы чата (" + str(len(items)) + ")\n\n" + "\n".join(lines)


def _build_topic_comment(topic_id: str | None, topic_map: dict[str, str]) -> str:
    if not topic_id:
        return ""
    title = topic_map.get(topic_id, "")
    if not title:
        return f"<!-- topic_id={topic_id} -->\n"
    safe_title = str(title).replace("--", "—").replace('"', '\\"').strip()
    return f'<!-- topic_id={topic_id}; topic_title="{safe_title}" -->\n'


def _resolve_topic_id(msg: dict, service_topic_by_id: dict[int, str]) -> str | None:
    raw = msg.get("topic_id")
    if raw is None and msg.get("reply_to_message_id") in service_topic_by_id:
        raw = msg.get("reply_to_message_id")
    if raw is None:
        return None
    return str(raw).strip() or None


def _format_timestamp(value: str, date_format: str) -> str:
    try:
        date_str = value.replace("Z", "+00:00") if value else ""
        dt = datetime.datetime.fromisoformat(date_str)
        fmt_map = {
            "DD.MM.YYYY": "%d.%m.%Y",
            "YYYY-MM-DD": "%Y-%m-%d",
            "MM/DD/YYYY": "%m/%d/%Y",
        }
        fmt = fmt_map.get(date_format, "%d.%m.%Y")
        return dt.strftime(f"{fmt} %H:%M")
    except Exception:
        return value


def _process_text(value, plain_text: bool) -> str:
    text = normalize_text(value)
    if plain_text:
        text = _strip_markdown(text)
    return text


def _format_markdown_message(msg: dict) -> str:
    parts = []
    if MARKDOWN_SETTINGS["include_timestamps"]:
        parts.append(f"[{_format_timestamp(msg.get('date', ''), MARKDOWN_SETTINGS['date_format'])}]")
    if MARKDOWN_SETTINGS["include_author"] and msg.get("from"):
        name = msg.get("from")
        parts.append(f"{name}:" if MARKDOWN_SETTINGS["plain_text"] else f"**{name}**:")
    header = " ".join(parts).strip()

    body = _process_text(msg.get("text", ""), MARKDOWN_SETTINGS["plain_text"])

    extras: list[str] = []
    if msg.get("links"):
        link_lines = []
        for link in msg["links"]:
            url = link.get("url", "")
            label = link.get("text", "")
            if label and label != url:
                link_lines.append(f"[{label}]({url})")
            else:
                link_lines.append(url)
        if link_lines:
            all_in_body = all(l.get("url", "") in body for l in msg["links"] if not l.get("text"))
            has_text_links = any(l.get("text") for l in msg["links"])
            if has_text_links or not all_in_body:
                extras.append("🔗 " + " | ".join(link_lines))
    if MARKDOWN_SETTINGS["include_polls"] and msg.get("poll"):
        extras.append(_format_poll(msg.get("poll") or {}))
    if MARKDOWN_SETTINGS["include_reactions"] and msg.get("reactions"):
        extras.append(_format_reactions(msg.get("reactions") or []))

    if msg.get("views") is not None or msg.get("forwards") is not None:
        stats = []
        if msg.get("views") is not None:
            stats.append(f"👁 {msg['views']}")
        if msg.get("forwards") is not None:
            stats.append(f"↗ {msg['forwards']}")
        extras.append(" | ".join(stats))

    if MARKDOWN_SETTINGS["include_forwarded"] and msg.get("forwarded_from"):
        body = f"> Переслано от {msg['forwarded_from']}\n{body}"

    if MARKDOWN_SETTINGS["include_replies"] and msg.get("reply_to_message_id"):
        body = f"↪ ответ на сообщение #{msg['reply_to_message_id']}\n{body}"

    combined = "\n\n".join([body, *extras]).strip()
    if header:
        return f"{header}\n{combined}".strip()
    return combined

def sanitize_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "chat_export"

def normalize_text(value) -> str:
    if value is None: return ""
    if isinstance(value, str): return value
    if hasattr(value, "text"): return str(getattr(value, "text"))
    return str(value)

# [Existing helper functions kept for logic]
def build_forwarded_from(fwd_from) -> str | None:
    if not fwd_from: return None
    if getattr(fwd_from, "from_name", None): return fwd_from.from_name
    if getattr(fwd_from, "from_id", None): return f"from_id:{fwd_from.from_id}"
    if getattr(fwd_from, "channel_post", None): return f"channel_post:{fwd_from.channel_post}"
    return None

def build_reactions(message) -> list | None:
    reactions = getattr(message, "reactions", None)
    if not reactions or not getattr(reactions, "results", None): return None
    results = []
    for result in reactions.results:
        reaction = result.reaction
        emoji = getattr(reaction, "emoticon", None) or str(reaction)
        results.append({"emoji": emoji, "count": result.count})
    return results or None

def build_poll(message) -> dict | None:
    media_poll = getattr(message, "poll", None)
    if not media_poll: return None
    poll = getattr(media_poll, "poll", None)
    if not poll: return None
    poll_data = {"question": normalize_text(poll.question)}
    answers = []
    results = getattr(media_poll, "results", None)
    for answer in getattr(poll, "answers", []) or []:
        count = None
        if results and getattr(results, "results", None):
            for res in results.results:
                if res.option == answer.option:
                    count = res.voters
                    break
        answers.append({"text": normalize_text(answer.text), "voters": count})
    if answers: poll_data["answers"] = answers
    if results and getattr(results, "total_voters", None) is not None:
        poll_data["total_voters"] = results.total_voters
    return poll_data

def _extract_links(message) -> list[dict] | None:
    entities = getattr(message, "entities", None) or []
    raw = getattr(message, "raw_text", "") or ""
    links: list[dict] = []
    seen: set[str] = set()
    for ent in entities:
        cls_name = type(ent).__name__
        if cls_name == "MessageEntityTextUrl":
            url = getattr(ent, "url", None)
            if url and url not in seen:
                label = raw[ent.offset:ent.offset + ent.length] if ent.offset + ent.length <= len(raw) else ""
                links.append({"url": url, "text": label} if label and label != url else {"url": url})
                seen.add(url)
        elif cls_name == "MessageEntityUrl":
            url = raw[ent.offset:ent.offset + ent.length] if ent.offset + ent.length <= len(raw) else ""
            if url and url not in seen:
                links.append({"url": url})
                seen.add(url)
    return links or None


def message_to_export(message) -> dict:
    msg_type = "service" if message.action else "message"
    sender = None
    username = None
    if message.sender:
        sender = get_display_name(message.sender)
        username = getattr(message.sender, "username", None)
    
    raw_text = getattr(message, "raw_text", None)
    msg_text = raw_text if raw_text is not None else message.message

    msg = {
        "id": message.id,
        "type": msg_type,
        "date": message.date.isoformat(),
        "from": sender,
        "from_username": username,
        "from_id": message.sender_id,
        "text": normalize_text(msg_text),
    }
    links = _extract_links(message)
    if links:
        msg["links"] = links

    views = getattr(message, "views", None)
    if views is not None:
        msg["views"] = views
    forwards = getattr(message, "forwards", None)
    if forwards is not None:
        msg["forwards"] = forwards

    if message.reply_to_msg_id: msg["reply_to_message_id"] = message.reply_to_msg_id
    reply_to = getattr(message, "reply_to", None)
    if reply_to:
        top_id = getattr(reply_to, "top_msg_id", None) or getattr(reply_to, "reply_to_top_id", None)
        if top_id:
            msg["topic_id"] = top_id
            msg["is_topic_message"] = True
        forum_flag = getattr(reply_to, "forum_topic", None)
        if forum_flag is not None:
            msg["is_forum_topic"] = bool(forum_flag)
    if message.action and hasattr(message.action, "title"):
        msg["topic_title"] = normalize_text(getattr(message.action, "title", ""))
    forwarded = build_forwarded_from(message.fwd_from)
    if forwarded: msg["forwarded_from"] = forwarded
    reactions = build_reactions(message)
    if reactions: msg["reactions"] = reactions
    poll_data = build_poll(message)
    if poll_data: msg["poll"] = poll_data
    return msg

# --- CUSTOM WIDGETS ---

class ModernButton(ctk.CTkButton):
    def __init__(self, master, variant="primary", **kwargs):
        height = kwargs.pop("height", 38)
        fg_color = COLORS["primary"] if variant == "primary" else "transparent"
        text_color = "#FFFFFF" if variant == "primary" else COLORS["text"]
        hover_color = COLORS["primary_hover"] if variant == "primary" else COLORS["card"]
        border_width = 0 if variant == "primary" else 1
        border_color = COLORS["border"] if variant == "secondary" else None
        
        super().__init__(
            master,
            corner_radius=8,
            fg_color=fg_color,
            text_color=text_color,
            hover_color=hover_color,
            border_width=border_width,
            border_color=border_color,
            font=(FONT_TEXT, 13, "bold" if variant=="primary" else "normal"),
            height=height,
            **kwargs
        )

class ModernEntry(ctk.CTkEntry):
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            corner_radius=8,
            border_width=1,
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            placeholder_text_color=COLORS["text_sec"],
            height=38,
            font=(FONT_TEXT, 13),
            **kwargs
        )
        self._bind_clipboard()

    def _bind_clipboard(self):
        for seq in ("<Command-v>", "<Command-V>", "<Control-v>", "<Control-V>", "<<Paste>>"):
            self.bind(seq, self._paste)
        self.bind("<Control-KeyPress>", self._on_ctrl_keypress)
        self.bind("<Command-KeyPress>", self._on_cmd_keypress)

    def _on_ctrl_keypress(self, event):
        if getattr(event, "keysym", "") in ("v", "V", "Cyrillic_em", "Cyrillic_EM"):
            return self._paste(event)

    def _on_cmd_keypress(self, event):
        if getattr(event, "keysym", "") in ("v", "V", "Cyrillic_em", "Cyrillic_EM"):
            return self._paste(event)

    def _paste(self, event=None):
        try:
            text = self.clipboard_get()
            try:
                if self.selection_present():
                    self.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            self.insert(tk.INSERT, text)
            return "break"
        except: pass

# --- VIEWS (SCREENS) ---

class LoginView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._box_relheight_phone = 0.60
        self._box_relheight_code = 0.74
        
        # Center Box
        self.center_box = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=16, border_width=1, border_color=COLORS["border"])
        self.center_box.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.4, relheight=self._box_relheight_phone)
        
        # Title
        ctk.CTkLabel(
            self.center_box, 
            text="Вход в Telegram", 
            font=(FONT_DISPLAY, 20, "bold"), 
            text_color=COLORS["text"]
        ).pack(pady=(40, 5))
        
        ctk.CTkLabel(
            self.center_box, 
            text="Для экспорта чатов необходимо авторизоваться", 
            font=(FONT_TEXT, 13), 
            text_color=COLORS["text_sec"]
        ).pack(pady=(0, 30))

        # Config Check (API Keys)
        self.api_status_lbl = ctk.CTkLabel(self.center_box, text="API ключи не найдены", text_color=COLORS["error"], font=(FONT_TEXT, 12))
        self.api_status_lbl.pack(pady=(0, 10))
        
        self.settings_btn = ModernButton(self.center_box, text="Настроить API ключи", variant="secondary", command=self.app.show_settings)
        self.settings_btn.pack(pady=(0, 20), padx=40, fill="x")
        self.clear_api_btn = ModernButton(
            self.center_box,
            text="Сбросить API ключи",
            variant="secondary",
            command=self._on_clear_api,
        )

        # Phone Input
        self.phone_entry = ModernEntry(self.center_box, placeholder_text="Телефон (+7...)")
        self.phone_entry.pack(padx=40, pady=(0, 10), fill="x")
        
        self.action_btn = ModernButton(self.center_box, text="Получить код", command=self._on_action)
        # Give extra bottom padding on high DPI so the button doesn't touch the card border.
        self.action_btn.pack(padx=40, pady=(10, 16), fill="x")

        # Code/Password Input (Initially hidden)
        self.code_entry = ModernEntry(self.center_box, placeholder_text="Код из Telegram")
        self.password_entry = ModernEntry(self.center_box, placeholder_text="Пароль 2FA (если есть)", show="•")
        
        self.state = "phone" # phone -> code -> ready
        self._adjust_box_height()

    def _get_ui_scale(self) -> float:
        try:
            return float(ctk.get_window_scaling())
        except Exception:
            return 1.0

    def _adjust_box_height(self) -> None:
        # Windows DPI scaling can enlarge widgets and cause clipping inside the fixed-height card.
        # Increase the relative height a bit for large UI scale and for the code/2FA step.
        scale = self._get_ui_scale()
        base = self._box_relheight_code if self.state == "code" else self._box_relheight_phone
        extra = max(0.0, min(0.16, (scale - 1.0) * 0.25))
        relh = min(0.88, base + extra)
        try:
            self.center_box.place_configure(relheight=relh)
        except Exception:
            pass

    def refresh_state(self):
        self._adjust_box_height()
        if self.app.has_api_creds():
            self.api_status_lbl.configure(text="API ключи настроены", text_color=COLORS["success"])
            self.settings_btn.configure(text="Изменить API ключи")
            if self.settings_btn.winfo_ismapped() == 0:
                self.settings_btn.pack(pady=(0, 10), padx=40, fill="x", before=self.phone_entry)
            if self.clear_api_btn.winfo_ismapped() == 0:
                self.clear_api_btn.pack(pady=(0, 20), padx=40, fill="x", before=self.phone_entry)
            self.phone_entry.configure(state="normal")
            self.action_btn.configure(state="normal")
        else:
            self.api_status_lbl.configure(text="Сначала укажите API ID/Hash", text_color=COLORS["error"])
            self.phone_entry.configure(state="disabled")
            self.action_btn.configure(state="disabled")
            if self.clear_api_btn.winfo_ismapped() == 1:
                self.clear_api_btn.pack_forget()
            self.settings_btn.configure(text="Настроить API ключи")
            if self.settings_btn.winfo_ismapped() == 0:
                self.settings_btn.pack(pady=(0, 20), padx=40, fill="x", before=self.phone_entry)

    def _on_action(self):
        if self.state == "phone":
            phone = self.phone_entry.get().strip()
            if not phone: return
            self.app.send_code(phone)
        elif self.state == "code":
            code = self.code_entry.get().strip()
            pwd = self.password_entry.get().strip()
            if not code: return
            self.app.verify_code(code, pwd)

    def show_code_input(self):
        self.state = "code"
        self.phone_entry.configure(state="disabled")
        self.code_entry.pack(padx=40, pady=(10, 0), fill="x", after=self.phone_entry)
        self.password_entry.pack(padx=40, pady=(10, 0), fill="x", after=self.code_entry)
        self.action_btn.configure(text="Войти")
        self._adjust_box_height()

    def _on_clear_api(self):
        ok = messagebox.askyesno(
            "Сбросить API ключи",
            "Удалить сохраненные API ID/Hash и сессию?\nПосле этого нужно будет ввести ключи заново.",
        )
        if ok:
            self.app.clear_api_creds()


class ChatListView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.dialogs = []
        self.dialog_map = {}
        self._export_total = None
        self._folder_names = ["Все чаты"]
        self._folder_var = tk.StringVar(value="Все чаты")
        self._words_var = tk.IntVar(value=50)
        self._popular_var = tk.BooleanVar(value=False)
        self._popular_min_var = tk.StringVar(value="5")
        self._analytics_var = tk.BooleanVar(value=False)
        self._transcribe_var = tk.BooleanVar(value=False)
        self._views_var = tk.BooleanVar(value=False)
        self._incremental_var = tk.BooleanVar(value=False)
        self._period_options = ["Все время", "Неделя", "Месяц", "3 месяца", "Год", "Свой период"]
        self._period_days_map = {"Все время": 0, "Неделя": 7, "Месяц": 30, "3 месяца": 90, "Год": 365}
        self._period_var = tk.StringVar(value="Все время")
        
        # Header / Toolbar
        self.toolbar = ctk.CTkFrame(self, fg_color="transparent", height=60)
        self.toolbar.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(
            self.toolbar, text="Чаты", font=(FONT_DISPLAY, 24, "bold"), text_color=COLORS["text"]
        ).pack(side="left")
        
        self.logout_btn = ModernButton(self.toolbar, text="Выход", variant="secondary", width=80, command=self.app.logout)
        self.logout_btn.pack(side="right", padx=(10, 0))
        
        self.refresh_btn = ModernButton(self.toolbar, text="Обновить", variant="secondary", width=110, command=self.app.load_chats)
        self.refresh_btn.pack(side="right", padx=(0, 24))

        # Folders
        self.folder_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.folder_bar.pack(fill="x", padx=20, pady=(0, 12))
        self.folder_label = ctk.CTkLabel(self.folder_bar, text="Папка", text_color=COLORS["text_sec"])
        self.folder_label.pack(side="left")
        self.folder_menu = ctk.CTkOptionMenu(
            self.folder_bar,
            values=self._folder_names,
            variable=self._folder_var,
            command=self._on_folder_change,
            width=220,
            height=32,
        )
        self.folder_menu.pack(side="left", padx=(10, 0))
        self.export_folder_btn = ModernButton(
            self.folder_bar,
            text="Экспортировать папку",
            variant="secondary",
            width=200,
            command=self._export_folder,
        )
        self.export_folder_btn.pack(side="left", padx=(10, 0))

        # Period filter
        self.period_label = ctk.CTkLabel(self.folder_bar, text="Период", text_color=COLORS["text_sec"])
        self.period_label.pack(side="left", padx=(20, 0))
        self.period_menu = ctk.CTkOptionMenu(
            self.folder_bar,
            values=self._period_options,
            variable=self._period_var,
            command=self._on_period_change,
            width=140,
            height=32,
        )
        self.period_menu.pack(side="left", padx=(10, 0))

        # Custom date range (hidden by default)
        self.date_range_bar = ctk.CTkFrame(self, fg_color="transparent")
        self._date_from_var = tk.StringVar()
        self._date_to_var = tk.StringVar()
        ctk.CTkLabel(self.date_range_bar, text="От", text_color=COLORS["text_sec"]).pack(side="left")
        self.date_from_entry = ModernEntry(self.date_range_bar, placeholder_text="ГГГГ-ММ-ДД", width=130, textvariable=self._date_from_var)
        self.date_from_entry.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(self.date_range_bar, text="До", text_color=COLORS["text_sec"]).pack(side="left", padx=(14, 0))
        self.date_to_entry = ModernEntry(self.date_range_bar, placeholder_text="ГГГГ-ММ-ДД", width=130, textvariable=self._date_to_var)
        self.date_to_entry.pack(side="left", padx=(6, 0))
        self.date_range_hint = ctk.CTkLabel(self.date_range_bar, text="UTC (напр. 2025-01-15)", text_color=COLORS["text_sec"])
        self.date_range_hint.pack(side="left", padx=(10, 0))
        self.date_from_entry.bind("<FocusOut>", self._apply_custom_dates)
        self.date_to_entry.bind("<FocusOut>", self._apply_custom_dates)
        self.date_from_entry.bind("<Return>", self._apply_custom_dates)
        self.date_to_entry.bind("<Return>", self._apply_custom_dates)

        # Words per file slider
        self.words_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.words_bar.pack(fill="x", padx=20, pady=(0, 12))
        self.words_row = ctk.CTkFrame(self.words_bar, fg_color="transparent")
        self.words_row.pack(anchor="w")
        self.words_label = ctk.CTkLabel(self.words_row, text="Разбивка (слов)", text_color=COLORS["text_sec"])
        self.words_label.pack(side="left")
        self.words_value = ctk.CTkLabel(self.words_row, text="50 000", text_color=COLORS["text_sec"])
        self.words_value.pack(side="left", padx=(10, 0))
        self.words_slider = ctk.CTkSlider(
            self.words_bar,
            from_=50,
            to=500,
            number_of_steps=45,
            command=self._on_words_change,
            height=8,
            width=320,
        )
        self.words_slider.set(50)
        self.words_slider.pack(anchor="w", pady=(6, 0))

        # Popular messages toggle
        self.popular_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.popular_bar.pack(fill="x", padx=20, pady=(0, 12))
        self.popular_check = ctk.CTkCheckBox(
            self.popular_bar,
            text="★ Популярные",
            variable=self._popular_var,
            command=self._on_popular_toggle,
        )
        self.popular_check.pack(side="left")
        self.popular_hint = ctk.CTkLabel(self.popular_bar, text="порог реакций", text_color=COLORS["text_sec"])
        self.popular_hint.pack(side="left", padx=(12, 6))
        self.popular_entry = ctk.CTkEntry(self.popular_bar, textvariable=self._popular_min_var, width=70, height=28)
        self.popular_entry.pack(side="left")
        self.popular_entry.bind("<KeyRelease>", self._on_popular_min_change)

        self.analytics_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.analytics_bar.pack(fill="x", padx=20, pady=(0, 12))
        self.analytics_check = ctk.CTkCheckBox(
            self.analytics_bar,
            text="Аналитика (топ авторов + активность)",
            variable=self._analytics_var,
            command=self._on_analytics_toggle,
        )
        self.analytics_check.pack(side="left")

        self.transcribe_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.transcribe_bar.pack(fill="x", padx=20, pady=(0, 4))
        self.transcribe_check = ctk.CTkCheckBox(
            self.transcribe_bar,
            text="Транскрипция голосовых и видео (каналы)",
            variable=self._transcribe_var,
            command=self._on_transcribe_toggle,
        )
        self.transcribe_check.pack(side="left")

        # Провайдер: Локальная | Deepgram
        self.transcribe_provider_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.transcribe_provider_bar.pack(fill="x", padx=20, pady=(2, 2))
        ctk.CTkLabel(self.transcribe_provider_bar, text="Провайдер:", font=(FONT_TEXT, 12), text_color=COLORS["text_sec"]).pack(side="left")
        _pv = self.app.transcription_provider or "local"
        self._transcription_provider_var = tk.StringVar(
            value="Deepgram (облако)" if _pv == "deepgram" else "Локальная (Whisper / Silero / Parakeet)"
        )
        self.transcription_provider_menu = ctk.CTkOptionMenu(
            self.transcribe_provider_bar,
            values=["Локальная (Whisper / Silero / Parakeet)", "Deepgram (облако)"],
            variable=self._transcription_provider_var,
            width=280,
            height=28,
            command=self._on_transcription_provider_change,
        )
        self.transcription_provider_menu.pack(side="left", padx=(6, 12))

        # Локальная транскрипция: Whisper, Parakeet (NeMo), Silero
        self._LOCAL_WHISPER_MODELS = [
            ("tiny — ~39M, ~1 GB RAM, быстро (Whisper)", "tiny"),
            ("base — ~74M, ~1 GB RAM, быстро (Whisper)", "base"),
            ("small — ~244M, ~2 GB RAM (Whisper)", "small"),
            ("medium — ~769M, ~5 GB RAM (Whisper)", "medium"),
            ("large-v2 — ~1.5B, ~10 GB. Старшая версия, долго (Whisper)", "large-v2"),
            ("large-v3 — ~1.5B, ~10 GB. Новее и точнее v2, долго (Whisper)", "large-v3"),
            ("Parakeet-TDT 0.6B — NeMo, англ. (NVIDIA)", "parakeet-tdt-0.6b"),
            ("Parakeet-TDT 1.1B — NeMo, англ., точнее (NVIDIA)", "parakeet-tdt-1.1b"),
            ("Silero STT (рус.) — лёгкая, RU", "silero-ru"),
            ("Silero STT (англ.) — лёгкая, EN", "silero-en"),
        ]
        self._LOCAL_WHISPER_LARGE_IDS = {"large-v2", "large-v3"}
        self.transcribe_bar2 = ctk.CTkFrame(self, fg_color="transparent")
        self.transcribe_bar2.pack(fill="x", padx=20, pady=(0, 12))
        # Блок для локальной модели
        self.transcribe_local_frame = ctk.CTkFrame(self.transcribe_bar2, fg_color="transparent")
        ctk.CTkLabel(self.transcribe_local_frame, text="Модель:", font=(FONT_TEXT, 12), text_color=COLORS["text_sec"]).pack(side="left")
        _def_display = next((d for d, m in self._LOCAL_WHISPER_MODELS if m == (self.app.local_whisper_model or "base")), None)
        self._local_whisper_model_var = tk.StringVar(value=_def_display or self._LOCAL_WHISPER_MODELS[1][0])
        self.local_whisper_model_menu = ctk.CTkOptionMenu(
            self.transcribe_local_frame,
            values=[d for d, _ in self._LOCAL_WHISPER_MODELS],
            variable=self._local_whisper_model_var,
            width=420,
            height=28,
            command=self._on_local_whisper_model_change,
        )
        self.local_whisper_model_menu.pack(side="left", padx=(6, 12))
        self.local_whisper_warning_lbl = ctk.CTkLabel(
            self.transcribe_local_frame,
            text="",
            font=(FONT_TEXT, 11),
            text_color="#e67e22",
        )
        self.local_whisper_warning_lbl.pack(side="left")
        # Блок для Deepgram API ключа (показывается при выборе Deepgram)
        self.transcribe_deepgram_frame = ctk.CTkFrame(self.transcribe_bar2, fg_color="transparent")
        # Режим ввода: поле + Сохранить
        self.deepgram_edit_frame = ctk.CTkFrame(self.transcribe_deepgram_frame, fg_color="transparent")
        ctk.CTkLabel(self.deepgram_edit_frame, text="API ключ:", font=(FONT_TEXT, 12), text_color=COLORS["text_sec"]).pack(side="left")
        self.deepgram_api_entry = ModernEntry(
            self.deepgram_edit_frame,
            placeholder_text="Deepgram API Key",
            width=180,
            show="•",
        )
        self.deepgram_api_entry.pack(side="left", padx=(6, 8))
        self.deepgram_save_btn = ModernButton(
            self.deepgram_edit_frame,
            text="Сохранить",
            variant="secondary",
            width=90,
            command=self._on_deepgram_save,
        )
        self.deepgram_save_btn.pack(side="left")
        # Режим "сохранено": текст + Изменить
        self.deepgram_saved_frame = ctk.CTkFrame(self.transcribe_deepgram_frame, fg_color="transparent")
        self.deepgram_saved_lbl = ctk.CTkLabel(
            self.deepgram_saved_frame,
            text="API ключ сохранён",
            font=(FONT_TEXT, 12),
            text_color=COLORS["success"],
        )
        self.deepgram_saved_lbl.pack(side="left")
        self.deepgram_edit_btn = ModernButton(
            self.deepgram_saved_frame,
            text="Изменить",
            variant="secondary",
            width=90,
            command=self._on_deepgram_show_edit,
        )
        self.deepgram_edit_btn.pack(side="left", padx=(12, 0))
        self._update_large_model_warning()
        self._update_transcribe_provider_visibility()

        self.views_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.views_bar.pack(fill="x", padx=20, pady=(0, 12))
        self.views_check = ctk.CTkCheckBox(
            self.views_bar,
            text="Просмотры и пересылки (каналы)",
            variable=self._views_var,
            command=self._on_views_toggle,
        )
        self.views_check.pack(side="left")
        self._download_media_var = tk.BooleanVar(value=self.app.download_media_enabled)
        self.download_media_check = ctk.CTkCheckBox(
            self.views_bar,
            text="Скачивать медиа в папку (видео, фото, голосовые и т.д.)",
            variable=self._download_media_var,
            command=self._on_download_media_toggle,
        )
        self.download_media_check.pack(side="left", padx=(20, 0))

        # Incremental + Author filter
        self.incremental_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.incremental_bar.pack(fill="x", padx=20, pady=(0, 12))
        self.incremental_check = ctk.CTkCheckBox(
            self.incremental_bar,
            text="Только новые сообщения",
            variable=self._incremental_var,
            command=self._on_incremental_toggle,
        )
        self.incremental_check.pack(side="left")
        self.author_filter_btn = ModernButton(
            self.incremental_bar,
            text="Фильтр авторов",
            variant="secondary",
            width=160,
            command=self._on_author_filter,
        )
        self.author_filter_btn.pack(side="left", padx=(20, 0))
        self.author_filter_label = ctk.CTkLabel(
            self.incremental_bar, text="", text_color=COLORS["text_sec"],
        )
        self.author_filter_label.pack(side="left", padx=(10, 0))
        self.fav_btn = ModernButton(
            self.incremental_bar, text="★ Избранные", variant="secondary",
            width=140, command=self._on_favorites,
        )
        self.fav_btn.pack(side="left", padx=(8, 0))
        self.fav_count_label = ctk.CTkLabel(
            self.incremental_bar, text="", text_color=COLORS["text_sec"],
        )
        self.fav_count_label.pack(side="left", padx=(4, 0))
        self._update_fav_count()

        # Search
        self.search_entry = ModernEntry(self, placeholder_text="Поиск чатов...")
        self.search_entry.pack(fill="x", padx=20, pady=(0, 15))
        self.search_entry.bind("<KeyRelease>", self._on_search)

        # Прогресс экспорта — компактная строка сразу под поиском
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent", height=36)
        self.progress_frame.pack_propagate(False)
        self.progress_frame.grid_columnconfigure(3, weight=1)  # название чата забирает оставшееся место
        self.progress_label = ctk.CTkLabel(self.progress_frame, text="", font=(FONT_TEXT, 11), text_color=COLORS["text_sec"])
        self.progress_label.grid(row=0, column=0, sticky="w", padx=(20, 6))
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=6, corner_radius=3, width=90)
        self.progress_bar.grid(row=0, column=1, sticky="w", padx=4)
        self.cancel_btn = ModernButton(
            self.progress_frame,
            text="×",
            variant="secondary",
            width=28,
            height=24,
            command=self._on_cancel_export,
        )
        self.cancel_btn.grid(row=0, column=2, sticky="e", padx=(4, 20))
        self.progress_chat_label = ctk.CTkLabel(self.progress_frame, text="", font=(FONT_TEXT, 11), text_color=COLORS["text_sec"], anchor="e")
        self.progress_chat_label.grid(row=0, column=3, sticky="ew", padx=(0, 20))
        self.progress_frame.pack_forget()

        # Status
        self.status_lbl = ctk.CTkLabel(self, text="", text_color=COLORS["text_sec"])
        self.status_lbl.pack(fill="x", padx=20, pady=(0, 8))

        # List Area (fast listbox)
        self.list_container = ctk.CTkFrame(self, fg_color="transparent")
        self.list_container.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        self.listbox = tk.Listbox(
            self.list_container,
            activestyle="none",
            selectmode=tk.SINGLE,
            borderwidth=0,
            highlightthickness=1,
            relief="flat",
            font=(FONT_TEXT, 13),
            bg=pick_color(COLORS["card"]),
            fg=pick_color(COLORS["text"]),
            selectbackground=pick_color(COLORS["primary"]),
            selectforeground="#FFFFFF",
            highlightbackground=pick_color(COLORS["border"]),
            highlightcolor=pick_color(COLORS["border"]),
        )
        self.scrollbar = tk.Scrollbar(self.list_container, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=self.scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.listbox.bind("<Double-Button-1>", self._on_double_click)
        self.listbox.bind("<Return>", self._on_double_click)

        # Export button
        self.export_btn = ModernButton(self, text="Экспортировать выбранный чат", command=self._export_selected)
        self.export_btn.pack(fill="x", padx=20, pady=(0, 16))

    def show_loading(self, text="Получаем список чатов..."):
        self.status_lbl.configure(text=text)
        self.listbox.delete(0, tk.END)

    def render_chats(self, dialogs):
        self.dialogs = dialogs or []
        self.dialog_map = {}
        self.listbox.delete(0, tk.END)

        if not self.dialogs:
            self.status_lbl.configure(text="Ничего не найдено")
            return

        for idx, d in enumerate(self.dialogs):
            self.listbox.insert(tk.END, d.name or "Без названия")
            self.dialog_map[idx] = d

        self.status_lbl.configure(text=f"Чатов: {len(self.dialogs)}")

    def set_folders(self, folder_names):
        self._folder_names = ["Все чаты"] + (folder_names or [])
        try:
            self.folder_menu.configure(values=self._folder_names)
        except Exception:
            pass
        if self._folder_var.get() not in self._folder_names:
            self._folder_var.set("Все чаты")

    def _on_search(self, event):
        query = self.search_entry.get().strip()
        self.app.filter_chats(query)

    def _on_folder_change(self, value):
        self.app.set_current_folder(value)
        query = self.search_entry.get().strip()
        self.app.filter_chats(query)

    def _format_words(self, value: int) -> str:
        return f"{value:,}".replace(",", " ")

    def _on_words_change(self, value):
        rounded = int(round(value / 10) * 10)
        if rounded < 50:
            rounded = 50
        if rounded > 500:
            rounded = 500
        self._words_var.set(rounded)
        self.words_value.configure(text=self._format_words(rounded * 1000))
        self.app.set_md_words_per_file(rounded * 1000)

    def _on_popular_toggle(self):
        self.app.set_popular_enabled(bool(self._popular_var.get()))
        query = self.search_entry.get().strip()
        self.app.filter_chats(query)

    def _on_popular_min_change(self, event=None):
        raw = (self._popular_min_var.get() or "").strip()
        if not raw:
            return
        if not raw.isdigit():
            return
        value = int(raw)
        if value < 1:
            value = 1
            self._popular_min_var.set("1")
        self.app.set_popular_min_reactions(value)

    def _on_analytics_toggle(self):
        enabled = bool(self._analytics_var.get())
        self.app.set_analytics_enabled(enabled)
        query = self.search_entry.get().strip()
        self.app.filter_chats(query)

    def _export_folder(self):
        self.app.export_current_folder()

    def _on_period_change(self, value):
        if value == "Свой период":
            if not self.date_range_bar.winfo_ismapped():
                self.date_range_bar.pack(fill="x", padx=20, pady=(0, 12), after=self.folder_bar)
            self.app.set_date_period(0)
            self._apply_custom_dates()
        else:
            if self.date_range_bar.winfo_ismapped():
                self.date_range_bar.pack_forget()
            self.app.set_custom_date_range(None, None)
            days = self._period_days_map.get(value, 0)
            self.app.set_date_period(days)

    def _apply_custom_dates(self, *_args):
        raw_from = self._date_from_var.get().strip()
        raw_to = self._date_to_var.get().strip()
        d_from = self._parse_date(raw_from)
        d_to = self._parse_date(raw_to)
        self.app.set_custom_date_range(d_from, d_to)

    def _parse_date(self, text: str):
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.datetime.strptime(text, fmt).replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                continue
        return None

    def _update_large_model_warning(self):
        model_id = next((m for d, m in self._LOCAL_WHISPER_MODELS if d == self._local_whisper_model_var.get()), "base")
        if model_id in self._LOCAL_WHISPER_LARGE_IDS:
            self.local_whisper_warning_lbl.configure(
                text="Внимание: большая модель. Транскрипция займёт много времени и создаст нагрузку на систему."
            )
        else:
            self.local_whisper_warning_lbl.configure(text="")

    def _on_local_whisper_model_change(self, value: str):
        model_id = next((m for d, m in self._LOCAL_WHISPER_MODELS if d == value), "base")
        self.app.set_local_whisper_model(model_id)
        self._update_large_model_warning()

    def _on_transcription_provider_change(self, value: str):
        provider = "deepgram" if "Deepgram" in value else "local"
        self.app.set_transcription_provider(provider)
        try:
            self.app._write_config_file(self.app._config_payload())
        except Exception:
            pass
        self._update_transcribe_provider_visibility()

    def _update_transcribe_provider_visibility(self):
        is_local = (self.app.transcription_provider or "local") == "local"
        if is_local:
            self.transcribe_deepgram_frame.pack_forget()
            self.transcribe_local_frame.pack(side="left", fill="x", expand=True)
        else:
            self.transcribe_local_frame.pack_forget()
            self.transcribe_deepgram_frame.pack(side="left", fill="x", expand=True)
            self._update_deepgram_saved_state()

    def _update_deepgram_saved_state(self):
        """Показать поле ввода или блок «API ключ сохранён» в зависимости от наличия ключа."""
        has_key = bool((self.app.deepgram_api_key or "").strip())
        if has_key:
            self.deepgram_edit_frame.pack_forget()
            self.deepgram_saved_frame.pack(side="left")
        else:
            self.deepgram_saved_frame.pack_forget()
            self.deepgram_edit_frame.pack(side="left")

    def _on_deepgram_save(self):
        key = (self.deepgram_api_entry.get() or "").strip()
        if not key:
            return
        self.app.set_deepgram_api_key(key)
        try:
            self.app._write_config_file(self.app._config_payload())
        except Exception:
            pass
        self.deepgram_api_entry.delete(0, "end")
        self._update_deepgram_saved_state()

    def _on_deepgram_show_edit(self):
        """Показать поле для ввода ключа заново (ключ в приложении остаётся до нового сохранения)."""
        self.deepgram_saved_frame.pack_forget()
        self.deepgram_edit_frame.pack(side="left")
        self.deepgram_api_entry.delete(0, "end")
        self.deepgram_api_entry.insert(0, "")  # пусто, чтобы ввести новый или тот же

    def _update_transcribe_check_state(self):
        self.transcribe_check.configure(state="normal")
        if getattr(self, "search_entry", None) is not None and not self._transcribe_var.get():
            self._apply_channel_filter()

    def _on_transcribe_toggle(self):
        self.app.set_voice_transcribe_enabled(bool(self._transcribe_var.get()))
        self._apply_channel_filter()

    def _on_views_toggle(self):
        self.app.set_views_enabled(bool(self._views_var.get()))
        self._apply_channel_filter()

    def _on_download_media_toggle(self):
        self.app.set_download_media_enabled(bool(self._download_media_var.get()))

    def _apply_channel_filter(self):
        query = self.search_entry.get().strip()
        self.app.filter_chats(query)

    def _on_incremental_toggle(self):
        self.app.set_incremental_enabled(bool(self._incremental_var.get()))

    def _on_author_filter(self):
        dialog = self._get_selected_dialog()
        if not dialog:
            self.status_lbl.configure(text="Сначала выберите чат из списка.")
            return
        self.status_lbl.configure(text="Загрузка участников...")
        self.app.load_participants(dialog)

    def update_author_filter_label(self, count: int | None):
        if count is None:
            self.author_filter_label.configure(text="")
        else:
            self.author_filter_label.configure(text=f"Выбрано: {count}")

    def _update_fav_count(self):
        n = len(self.app.get_favorite_authors_list())
        if n > 0:
            self.fav_count_label.configure(text=f"({n})")
        else:
            self.fav_count_label.configure(text="")

    def _on_favorites(self):
        modal = FavoriteAuthorsModal(self.winfo_toplevel(), self.app)
        self.winfo_toplevel().wait_window(modal)
        self._update_fav_count()
        if modal.result_export:
            all_author_ids = set()
            chat_ids = []
            for chat_id, author_ids in modal.result_export:
                chat_ids.append(chat_id)
                all_author_ids.update(author_ids)
            if not chat_ids:
                return
            path = filedialog.askdirectory(title="Куда сохранить экспорт избранных?")
            if not path:
                return
            self.app.export_favorites_chats(chat_ids, all_author_ids, path)

    def show_folder_progress(self, current, total, label, log_lines=None):
        if not total:
            return
        self.progress_chat_label.configure(text=f"Чат {current}/{total}")
        text = f"Экспорт папки: {current}/{total} • {label}"
        if log_lines:
            text += "\n" + "\n".join(log_lines)
        self.status_lbl.configure(text=text)

    def show_folder_done(self, total, log_lines=None):
        text = f"Экспорт папки завершен. Чатов: {total}"
        if log_lines:
            text += "\n" + "\n".join(log_lines)
        self.status_lbl.configure(text=text)

    def _get_selected_dialog(self):
        selection = self.listbox.curselection()
        if not selection:
            return None
        return self.dialog_map.get(selection[0])

    def _on_double_click(self, event=None):
        dialog = self._get_selected_dialog()
        if dialog:
            self.app.show_export_dialog(dialog)

    def _export_selected(self):
        dialog = self._get_selected_dialog()
        if not dialog:
            self.status_lbl.configure(text="Выберите чат из списка.")
            return
        self.app.show_export_dialog(dialog)

    def show_export_progress(self, chat_name: str, total: Optional[int]):
        self._export_total = total
        self._set_progress_visible(True)
        if len(chat_name) > 35:
            chat_name = chat_name[:32].rstrip() + "..."
        self.progress_chat_label.configure(text=chat_name)
        self.cancel_btn.configure(state="normal")
        self.cancel_btn.grid()
        if total:
            self.progress_bar.configure(mode="determinate")
            self.progress_bar.set(0)
            self.progress_label.configure(text=f"Экспортировано 0/{total}")
        else:
            self.progress_bar.configure(mode="indeterminate")
            self.progress_bar.start()
            self.progress_label.configure(text="Экспорт...")

    def update_export_progress(self, count: int, total: Optional[int]):
        if total:
            frac = max(0.0, min(1.0, count / max(1, total)))
            self.progress_bar.set(frac)
            self.progress_label.configure(text=f"Экспортировано {count}/{total}")
        else:
            self.progress_label.configure(text=f"Экспортировано {count} сообщений...")

    def set_export_status(self, text: str):
        """Показать промежуточный статус экспорта (например, «Загрузка модели…»)."""
        self.progress_label.configure(text=text if text else "Экспорт...")

    def finish_export(self, ok: bool, message: str):
        try:
            self.progress_bar.stop()
        except Exception:
            pass
        self._set_progress_visible(False)
        self.status_lbl.configure(text=message if ok else f"Ошибка: {message}")

    def _on_cancel_export(self):
        self.cancel_btn.configure(state="disabled")
        self.progress_label.configure(text="Отмена...")
        self.app.cancel_export()

    def _set_progress_visible(self, visible: bool):
        visible = bool(visible)
        if visible:
            if not self.progress_frame.winfo_ismapped():
                self.progress_frame.pack(fill="x", padx=0, pady=(0, 6), after=self.search_entry)
        else:
            if self.progress_frame.winfo_ismapped():
                self.progress_frame.pack_forget()
            self.progress_chat_label.configure(text="")
            self.progress_label.configure(text="")


class SettingsModal(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Настройки API")
        self.geometry("400x300")
        self.resizable(False, False)
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        ctk.CTkLabel(self, text="Telegram API Keys", font=(FONT_DISPLAY, 16, "bold")).pack(pady=(20, 5))
        ctk.CTkLabel(self, text="Можно получить на my.telegram.org", font=(FONT_TEXT, 12), text_color=COLORS["text_sec"]).pack(pady=(0, 20))
        
        self.api_id = ModernEntry(self, placeholder_text="API ID")
        self.api_id.pack(padx=30, pady=(0, 10), fill="x")
        
        self.api_hash = ModernEntry(self, placeholder_text="API Hash")
        self.api_hash.pack(padx=30, pady=(0, 20), fill="x")
        
        ModernButton(self, text="Сохранить", command=self.save).pack(padx=30, fill="x")
        
        # Load existing
        cfg = parent._load_config()
        if cfg.get("api_id"): self.api_id.insert(0, cfg["api_id"])
        if cfg.get("api_hash"): self.api_hash.insert(0, cfg["api_hash"])

    def save(self):
        aid = self.api_id.get().strip()
        ahash = self.api_hash.get().strip()
        if aid and ahash:
            self.master.save_config(aid, ahash)
            self.destroy()


class TopicPickerModal(ctk.CTkToplevel):
    def __init__(self, parent, topics: list[dict]):
        super().__init__(parent)
        self.title("Выбор темы")
        self.geometry("500x450")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()

        self.result_topic_id: int | None = None
        self.result_topic_title: str = ""
        self.result_export_all: bool = False
        self._topics = topics

        ctk.CTkLabel(
            self, text="Темы форум-чата",
            font=(FONT_DISPLAY, 18, "bold"), text_color=COLORS["text"],
        ).pack(padx=20, pady=(16, 4))
        ctk.CTkLabel(
            self, text="Выберите тему для экспорта или экспортируйте весь чат",
            font=(FONT_TEXT, 12), text_color=COLORS["text_sec"],
        ).pack(padx=20, pady=(0, 12))

        list_frame = ctk.CTkFrame(self, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self.listbox = tk.Listbox(
            list_frame,
            activestyle="none",
            selectmode=tk.SINGLE,
            borderwidth=0,
            highlightthickness=1,
            relief="flat",
            font=(FONT_TEXT, 13),
            bg=pick_color(COLORS["card"]),
            fg=pick_color(COLORS["text"]),
            selectbackground=pick_color(COLORS["primary"]),
            selectforeground="#FFFFFF",
            highlightbackground=pick_color(COLORS["border"]),
            highlightcolor=pick_color(COLORS["border"]),
        )
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for t in self._topics:
            title = t.get("title") or "Без названия"
            count = t.get("count")
            label = f"{title} ({count} сообщ.)" if count else title
            self.listbox.insert(tk.END, label)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 16))
        ModernButton(
            btn_frame, text="Экспортировать тему",
            command=self._on_export_topic,
        ).pack(fill="x", pady=(0, 8))
        ModernButton(
            btn_frame, text="Экспортировать весь чат",
            variant="secondary", command=self._on_export_all,
        ).pack(fill="x")

        self.listbox.bind("<Double-Button-1>", lambda e: self._on_export_topic())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_export_topic(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        t = self._topics[sel[0]]
        self.result_topic_id = t.get("id")
        self.result_topic_title = t.get("title") or ""
        self.result_export_all = False
        self.grab_release()
        self.destroy()

    def _on_export_all(self):
        self.result_export_all = True
        self.grab_release()
        self.destroy()

    def _on_close(self):
        self.grab_release()
        self.destroy()


class AuthorFilterModal(ctk.CTkToplevel):
    def __init__(self, parent, participants: list[dict], app=None, chat_id: int | None = None, chat_name: str | None = None):
        super().__init__(parent)
        self.title("Фильтр авторов")
        self.geometry("500x520")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()

        self._participants = participants
        self._app = app
        self._chat_id = chat_id
        self._chat_name = chat_name
        self._vars: list[tk.BooleanVar] = []
        self._fav_labels: list[ctk.CTkLabel] = []
        self.result_ids: set[int] | None = None

        fav_ids = app.get_favorite_author_ids() if app else set()

        if app and chat_id and chat_name and fav_ids:
            for p in participants:
                uid = p.get("id")
                if uid and uid in fav_ids:
                    app.add_favorite_author(uid, p.get("name", ""), p.get("username", ""), chat_id, chat_name)

        ctk.CTkLabel(
            self, text="Фильтр авторов",
            font=(FONT_DISPLAY, 18, "bold"), text_color=COLORS["text"],
        ).pack(padx=20, pady=(16, 4))
        ctk.CTkLabel(
            self, text="Отметьте авторов для экспорта. ★ — добавить в избранные.",
            font=(FONT_TEXT, 12), text_color=COLORS["text_sec"],
        ).pack(padx=20, pady=(0, 12))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 8))
        ModernButton(btn_row, text="Выбрать всех", variant="secondary", width=120, command=self._select_all).pack(side="left")
        ModernButton(btn_row, text="Снять всех", variant="secondary", width=120, command=self._deselect_all).pack(side="left", padx=(8, 0))
        ModernButton(btn_row, text="Сбросить фильтр", variant="secondary", width=120, command=self._reset_filter).pack(side="left", padx=(8, 0))

        self._search_var = tk.StringVar()
        search_entry = ctk.CTkEntry(self, textvariable=self._search_var, placeholder_text="Поиск по имени или @username...")
        search_entry.pack(fill="x", padx=20, pady=(0, 8))
        self._search_var.trace_add("write", lambda *_: self._filter_rows())

        scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        self._rows: list[ctk.CTkFrame] = []
        self._row_keys: list[str] = []

        for p in self._participants:
            var = tk.BooleanVar(value=True)
            self._vars.append(var)
            name = p.get("name") or "Без имени"
            username = p.get("username") or ""
            label_text = f"{name} (@{username})" if username else name
            uid = p.get("id")

            row = ctk.CTkFrame(scroll_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkCheckBox(row, text=label_text, variable=var).pack(side="left", anchor="w")

            is_fav = uid in fav_ids if uid else False
            star_text = "★" if is_fav else "☆"
            star_color = ("#F59E0B", "#FBBF24") if is_fav else COLORS["text_sec"]
            star_lbl = ctk.CTkLabel(
                row, text=star_text, font=(FONT_TEXT, 16), text_color=star_color,
                cursor="hand2", width=24,
            )
            star_lbl.pack(side="right", padx=(4, 0))
            star_lbl.bind("<Button-1>", lambda e, u=uid, n=name, un=username, lbl=star_lbl: self._toggle_fav(u, n, un, lbl))
            self._fav_labels.append(star_lbl)
            self._rows.append(row)
            self._row_keys.append(f"{name} {username}".lower())

        ModernButton(self, text="Применить", command=self._on_apply).pack(fill="x", padx=20, pady=(0, 16))
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _filter_rows(self):
        q = self._search_var.get().strip().lower()
        for i, row in enumerate(self._rows):
            if not q or q in self._row_keys[i]:
                row.pack(fill="x", pady=1)
            else:
                row.pack_forget()

    def _toggle_fav(self, uid, name, username, lbl):
        if not self._app or uid is None:
            return
        if self._app.is_favorite_author(uid):
            self._app.remove_favorite_author(uid)
            lbl.configure(text="☆", text_color=COLORS["text_sec"])
        else:
            self._app.add_favorite_author(uid, name, username, self._chat_id, self._chat_name)
            lbl.configure(text="★", text_color=("#F59E0B", "#FBBF24"))

    def _select_all(self):
        for v in self._vars:
            v.set(True)

    def _deselect_all(self):
        for v in self._vars:
            v.set(False)

    def _reset_filter(self):
        self.result_ids = None
        self.grab_release()
        self.destroy()

    def _on_apply(self):
        ids = set()
        for i, v in enumerate(self._vars):
            if v.get():
                pid = self._participants[i].get("id")
                if pid is not None:
                    ids.add(pid)
        self.result_ids = ids if len(ids) < len(self._participants) else None
        self.grab_release()
        self.destroy()

    def _on_close(self):
        self.grab_release()
        self.destroy()


class FavoriteAuthorsModal(ctk.CTkToplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.title("★ Избранные авторы")
        self.geometry("520x560")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()

        self._app = app
        self.result_export: list[tuple[int, set[int]]] | None = None
        self._chat_vars: dict[int, dict[int, tk.BooleanVar]] = {}

        favorites = app.get_favorite_authors_list()

        ctk.CTkLabel(
            self, text="★ Избранные авторы",
            font=(FONT_DISPLAY, 18, "bold"), text_color=COLORS["text"],
        ).pack(padx=20, pady=(16, 4))

        if not favorites:
            ctk.CTkLabel(
                self, text="Список пуст.\nДобавляйте авторов через «Фильтр авторов» → ☆",
                font=(FONT_TEXT, 13), text_color=COLORS["text_sec"], justify="center",
            ).pack(padx=20, pady=40)
        else:
            ctk.CTkLabel(
                self, text=f"Авторов: {len(favorites)}. Раскройте автора — выберите чаты для экспорта.",
                font=(FONT_TEXT, 12), text_color=COLORS["text_sec"],
            ).pack(padx=20, pady=(0, 10))

            self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
            self._scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))

            for fav in favorites:
                uid = fav["id"]
                name = fav.get("name") or "Без имени"
                username = fav.get("username") or ""
                chats: dict[int, str] = fav.get("chats", {})
                self._chat_vars[uid] = {}

                author_frame = ctk.CTkFrame(self._scroll, fg_color=COLORS["card"], corner_radius=8)
                author_frame.pack(fill="x", pady=4, padx=2)

                header = ctk.CTkFrame(author_frame, fg_color="transparent")
                header.pack(fill="x", padx=10, pady=(8, 0))

                title_text = f"★ {name}" + (f"  @{username}" if username else "")
                title_lbl = ctk.CTkLabel(header, text=title_text, font=(FONT_TEXT, 14, "bold"), text_color=COLORS["text"], anchor="w")
                title_lbl.pack(side="left", fill="x", expand=True)

                remove_lbl = ctk.CTkLabel(header, text="✕", font=(FONT_TEXT, 14), text_color=COLORS["error"], cursor="hand2", width=20)
                remove_lbl.pack(side="right")
                remove_lbl.bind("<Button-1>", lambda e, u=uid, f=author_frame: self._remove_fav(u, f))

                chats_frame = ctk.CTkFrame(author_frame, fg_color="transparent")
                chats_frame.pack(fill="x", padx=20, pady=(4, 8))

                if chats:
                    for chat_id, chat_name in chats.items():
                        var = tk.BooleanVar(value=True)
                        self._chat_vars[uid][chat_id] = var
                        ctk.CTkCheckBox(
                            chats_frame, text=chat_name, variable=var,
                            font=(FONT_TEXT, 12),
                        ).pack(anchor="w", pady=1)
                else:
                    ctk.CTkLabel(
                        chats_frame, text="Нет привязанных чатов",
                        font=(FONT_TEXT, 11), text_color=COLORS["text_sec"],
                    ).pack(anchor="w")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(8, 16))

        ModernButton(
            btn_frame, text="Экспорт выбранных чатов",
            command=self._on_export,
        ).pack(fill="x")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _remove_fav(self, uid: int, frame: ctk.CTkFrame):
        self._app.remove_favorite_author(uid)
        self._chat_vars.pop(uid, None)
        frame.destroy()

    def _on_export(self):
        chat_to_authors: dict[int, set[int]] = {}
        for uid, chats in self._chat_vars.items():
            for chat_id, var in chats.items():
                if var.get():
                    chat_to_authors.setdefault(chat_id, set()).add(uid)
        if not chat_to_authors:
            return
        self.result_export = [(cid, aids) for cid, aids in chat_to_authors.items()]
        self.grab_release()
        self.destroy()

    def _on_close(self):
        self.grab_release()
        self.destroy()


# --- MAIN APP CONTROLLER ---

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Exporter")
        self.geometry("900x650")
        self.configure(fg_color=COLORS["bg"])
        
        # Data
        self.config_path = os.path.expanduser("~/.tg_exporter/config.json")
        self.api_creds = {}
        self.client = None
        self.phone_hash = None
        self.phone_number = None
        self._cancel_export = threading.Event()
        self.all_dialogs = []
        self.folder_peers = {}
        self.folder_filters = {}
        self.folder_excludes = {}
        self.current_folder = "Все чаты"
        self.md_words_per_file = 50000
        self.popular_enabled = False
        self.popular_min_reactions = 5
        self.analytics_enabled = False
        self.voice_transcribe_enabled = False
        self.transcription_provider: str = "local"  # "local" | "deepgram"
        self.deepgram_api_key: str = ""
        self.views_enabled = False
        self.download_media_enabled = False
        self.date_period_days = 0
        self.custom_date_from = None
        self.custom_date_to = None
        self.incremental_enabled = False
        self.author_filter_ids: set[int] | None = None
        self._export_history_path = os.path.expanduser("~/.tg_exporter/export_history.json")
        self.local_whisper_model: str = "base"
        self.transcription_language: str = "multi"
        self._whisper_model_cache = None
        self._parakeet_model_cache = None
        self._silero_model_cache = None  # dict: lang -> (model, decoder, utils)
        self._folder_active = False
        self._folder_queue = []
        self._folder_total = 0
        self._folder_index = 0
        self._folder_export_base = None
        self._folder_log = []
        self._folder_current_label = ""
        
        self._tg_queue = queue.Queue()
        self.queue = queue.Queue()
        
        # Views
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True)
        
        self.login_view = LoginView(self.container, self)
        self.chats_view = ChatListView(self.container, self)
        
        self.current_view = None
        self._load_config_file()
        self._cleanup_temp_voice_files()
        
        # Start
        self.show_login()
        self._start_worker()
        self.after(100, self._process_queue)

    # --- Navigation ---

    def show_login(self):
        if self.current_view: self.current_view.pack_forget()
        self.login_view.pack(fill="both", expand=True)
        self.current_view = self.login_view
        self.login_view.refresh_state()
        
        # Auto-login check
        if self.has_api_creds() and self.api_creds.get("session"):
            self._run_bg(self._check_session)

    def show_chats(self):
        if self.current_view: self.current_view.pack_forget()
        self.chats_view.pack(fill="both", expand=True)
        self.current_view = self.chats_view
        self.load_chats()

    def show_settings(self):
        SettingsModal(self)

    def _confirm_export_safety(self) -> bool:
        return messagebox.askyesno(
            "Внимание",
            "Экспорт содержит личные данные и сохранится на диск.\n"
            "Рекомендуется выбирать защищенную папку (не облако/Downloads).\n\n"
            "Продолжить экспорт?",
        )

    def show_export_dialog(self, dialog):
        self._cancel_export.clear()
        if not self._confirm_export_safety():
            return
        if self._is_forum(dialog):
            self.chats_view.status_lbl.configure(text="Загрузка тем...")
            self._run_bg(self._load_topics_task, dialog)
        else:
            self._start_export(dialog)

    def _start_export(self, dialog, topic_id=None, topic_title=None):
        path = filedialog.askdirectory(title="Куда сохранить экспорт?")
        if not path:
            return
        self._folder_active = False
        self.chats_view.status_lbl.configure(text="")
        self._run_bg(self._export_task, dialog, path, topic_id, topic_title)

    # --- Logic ---

    def has_api_creds(self):
        return bool(self.api_creds.get("api_id") and self.api_creds.get("api_hash"))

    def _keyring_service(self) -> str:
        return "tg_exporter"

    def _keyring_username(self, api_id: str | None = None, kind: str = "session") -> str:
        aid = api_id or self.api_creds.get("api_id")
        suffix = f"_{aid}" if aid else ""
        return f"{kind}{suffix}"

    def _load_session_from_keyring(self) -> str | None:
        if not keyring:
            return None
        try:
            return keyring.get_password(
                self._keyring_service(),
                self._keyring_username(kind="session"),
            )
        except Exception:
            return None

    def _save_session_to_keyring(self, session_str: str) -> bool:
        if not keyring or not session_str:
            return False
        try:
            keyring.set_password(
                self._keyring_service(),
                self._keyring_username(kind="session"),
                session_str,
            )
            return True
        except Exception:
            return False

    def _clear_session_in_keyring(self, api_id: str | None = None) -> None:
        if not keyring:
            return
        try:
            username = self._keyring_username(api_id, kind="session")
            if keyring.get_password(self._keyring_service(), username):
                keyring.delete_password(self._keyring_service(), username)
        except Exception:
            pass

    def _load_api_hash_from_keyring(self) -> str | None:
        if not keyring:
            return None
        try:
            return keyring.get_password(
                self._keyring_service(),
                self._keyring_username(kind="api_hash"),
            )
        except Exception:
            return None

    def _save_api_hash_to_keyring(self, api_hash: str) -> bool:
        if not keyring or not api_hash:
            return False
        try:
            keyring.set_password(
                self._keyring_service(),
                self._keyring_username(kind="api_hash"),
                api_hash,
            )
            return True
        except Exception:
            return False

    def _clear_api_hash_in_keyring(self, api_id: str | None = None) -> None:
        if not keyring:
            return
        try:
            username = self._keyring_username(api_id, kind="api_hash")
            if keyring.get_password(self._keyring_service(), username):
                keyring.delete_password(self._keyring_service(), username)
        except Exception:
            pass

    def _config_payload(self) -> dict:
        payload = {}
        if self.api_creds.get("api_id"):
            payload["api_id"] = self.api_creds["api_id"]
        if self.local_whisper_model:
            payload["local_whisper_model"] = self.local_whisper_model
        if self.transcription_language:
            payload["transcription_language"] = self.transcription_language
        if self.transcription_provider:
            payload["transcription_provider"] = self.transcription_provider
        if self.deepgram_api_key:
            payload["deepgram_api_key"] = self.deepgram_api_key
        return payload

    def _secure_config_permissions(self) -> None:
        if OS_NAME == "Windows":
            return
        try:
            os.chmod(self.config_path, 0o600)
        except Exception:
            pass

    def _write_config_file(self, payload: dict) -> None:
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(payload, f)
        self._secure_config_permissions()

    def _load_config_file(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    self.api_creds = json.load(f)
            if not self.api_creds:
                self.api_creds = {}

            stored_session = self.api_creds.pop("session", None)
            stored_hash = self.api_creds.pop("api_hash", None)

            if stored_hash:
                if self._save_api_hash_to_keyring(stored_hash):
                    self.api_creds["api_hash"] = stored_hash
                else:
                    self.api_creds["api_hash"] = stored_hash

            if stored_session:
                if self._save_session_to_keyring(stored_session):
                    self.api_creds["session"] = stored_session
                else:
                    self.api_creds["session"] = stored_session

            if stored_hash or stored_session:
                self._write_config_file(self._config_payload())

            if not self.api_creds.get("api_hash"):
                api_hash = self._load_api_hash_from_keyring()
                if api_hash:
                    self.api_creds["api_hash"] = api_hash

            if not self.api_creds.get("session"):
                session_str = self._load_session_from_keyring()
                if session_str:
                    self.api_creds["session"] = session_str

            self.local_whisper_model = self.api_creds.get("local_whisper_model", "base") or "base"
            self.transcription_language = self.api_creds.get("transcription_language", "multi") or "multi"
            self.transcription_provider = self.api_creds.get("transcription_provider", "local") or "local"
            self.deepgram_api_key = self.api_creds.get("deepgram_api_key", "") or ""
        except:
            pass

    def _load_config(self): return self.api_creds

    def save_config(self, api_id, api_hash):
        old_api_id = self.api_creds.get("api_id")
        old_api_hash = self.api_creds.get("api_hash")
        session_str = self.api_creds.get("session")
        self.api_creds = {
            "api_id": api_id,
            "api_hash": api_hash,
            "session": session_str,
        }
        if old_api_id and (old_api_id != api_id or old_api_hash != api_hash):
            self.api_creds["session"] = None
            self._clear_session_in_keyring(old_api_id)
            self._clear_api_hash_in_keyring(old_api_id)
        if not self._save_api_hash_to_keyring(api_hash):
            self.api_creds["api_hash"] = api_hash
        self._write_config_file(self._config_payload())
        self.login_view.refresh_state()

    def clear_api_creds(self):
        try:
            if self.client:
                self.client.disconnect()
                self.client = None
        except Exception:
            pass
        self.phone_hash = None
        self.phone_number = None
        self.api_creds = {}
        self._clear_session_in_keyring()
        self._clear_api_hash_in_keyring()
        self._write_config_file(self.api_creds)
        self.login_view.refresh_state()

    def _get_client(self):
        self._ensure_event_loop()
        if not self.client:
            session_str = self.api_creds.get("session")
            if not self.api_creds.get("api_hash"):
                api_hash = self._load_api_hash_from_keyring()
                if api_hash:
                    self.api_creds["api_hash"] = api_hash
            if not session_str:
                session_str = self._load_session_from_keyring()
                if session_str:
                    self.api_creds["session"] = session_str
            session = StringSession(session_str) if session_str else StringSession()
            self.client = TelegramClient(
                session,
                int(self.api_creds["api_id"]),
                self.api_creds["api_hash"],
            )
        return self.client

    def _run_bg(self, target, *args):
        self._tg_queue.put((target, args))

    def _ensure_event_loop(self):
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

    def _start_worker(self):
        def worker():
            self._ensure_event_loop()
            while True:
                target, args = self._tg_queue.get()
                try:
                    target(*args)
                except Exception as e:
                    self.queue.put(("error", str(e)))
        threading.Thread(target=worker, daemon=True).start()

    # --- Background Tasks ---

    def _check_session(self):
        try:
            c = self._get_client()
            c.connect()
            if c.is_user_authorized():
                self._persist_session()
                self.queue.put(("login_success", None))
            else:
                self.queue.put(("status", "Нужен вход"))
        except: pass

    def send_code(self, phone):
        self._run_bg(self._send_code_task, phone)

    def _send_code_task(self, phone):
        try:
            phone = (phone or "").strip()
            if not phone:
                self.queue.put(("error", "Введите номер телефона."))
                return
            c = self._get_client()
            c.connect()
            if c.is_user_authorized():
                self._persist_session()
                self.queue.put(("login_success", None))
                return
            
            sent = c.send_code_request(phone)
            self.phone_number = phone
            self.phone_hash = sent.phone_code_hash
            self.queue.put(("code_sent", None))
        except Exception as e:
            self.queue.put(("error", str(e)))

    def verify_code(self, code, password):
        self._run_bg(self._verify_task, code, password)

    def _verify_task(self, code, pwd):
        try:
            code = (code or "").strip()
            if not code:
                self.queue.put(("error", "Введите код из Telegram."))
                return
            if not self.phone_hash:
                self.queue.put(("error", "Сначала нажмите «Получить код»."))
                return
            phone = (self.phone_number or self.login_view.phone_entry.get() or "").strip()
            if not phone:
                self.queue.put(("error", "Введите номер телефона."))
                return
            c = self._get_client()
            c.sign_in(phone=phone, code=code, phone_code_hash=self.phone_hash)
            self._persist_session()
            self.queue.put(("login_success", None))
        except SessionPasswordNeededError:
            try:
                pwd = (pwd or "").strip()
                if not pwd:
                    self.queue.put(("error", "Нужен пароль 2FA."))
                    return
                c = self._get_client()
                c.sign_in(password=pwd)
                self._persist_session()
                self.queue.put(("login_success", None))
            except Exception as e:
                self.queue.put(("error", str(e)))
        except Exception as e:
            self.queue.put(("error", str(e)))

    def load_chats(self):
        if self.current_view == self.chats_view:
            self.chats_view.show_loading()
        self._run_bg(self._load_chats_task)

    def _load_chats_task(self):
        try:
            c = self._get_client()
            if not c.is_connected(): c.connect()
            dialogs = c.get_dialogs()
            self.all_dialogs = dialogs
            self.queue.put(("chats_loaded", dialogs))
            try:
                filters = c(functions.messages.GetDialogFiltersRequest())
                if hasattr(filters, "filters"):
                    filters = filters.filters
            except Exception:
                filters = []
            folder_peers = {}
            folder_filters = {}
            folder_excludes = {}
            folder_names = []
            for f in (filters or []):
                title = normalize_text(getattr(f, "title", None))
                include_peers = getattr(f, "include_peers", None) or []
                pinned_peers = getattr(f, "pinned_peers", None) or []
                exclude_peers = getattr(f, "exclude_peers", None) or []
                if not title:
                    continue
                peer_ids = set()
                for p in list(include_peers) + list(pinned_peers):
                    try:
                        peer_ids.add(get_peer_id(p))
                    except Exception:
                        continue
                exclude_ids = set()
                for p in exclude_peers:
                    try:
                        exclude_ids.add(get_peer_id(p))
                    except Exception:
                        continue
                has_flags = any(
                    getattr(f, attr, False)
                    for attr in ("contacts", "non_contacts", "groups", "broadcasts", "bots")
                )
                if peer_ids or has_flags or exclude_ids:
                    folder_peers[title] = peer_ids
                    folder_filters[title] = f
                    folder_excludes[title] = exclude_ids
                    folder_names.append(title)
            self.folder_peers = folder_peers
            self.folder_filters = folder_filters
            self.folder_excludes = folder_excludes
            self.queue.put(("folders_loaded", folder_names))
        except Exception as e:
            self.queue.put(("error", str(e)))

    def filter_chats(self, query):
        dialogs = self._get_folder_dialogs(self.current_folder)

        channels_only = self.voice_transcribe_enabled or self.views_enabled
        if channels_only:
            dialogs = [d for d in dialogs if self._is_broadcast_channel(d)]

        if query:
            q = query.lower()
            dialogs = [d for d in dialogs if q in (d.name or "").lower()]

        self.chats_view.render_chats(dialogs)

    def set_current_folder(self, folder_name):
        self.current_folder = folder_name or "Все чаты"

    def set_md_words_per_file(self, value: int):
        self.md_words_per_file = max(10000, int(value))

    def set_popular_enabled(self, value: bool):
        self.popular_enabled = bool(value)

    def set_popular_min_reactions(self, value: int):
        self.popular_min_reactions = max(1, int(value))

    def set_analytics_enabled(self, value: bool):
        self.analytics_enabled = bool(value)

    def set_voice_transcribe_enabled(self, value: bool):
        self.voice_transcribe_enabled = bool(value)

    def set_local_whisper_model(self, model: str):
        self.local_whisper_model = (model or "base").strip() or "base"
        self._whisper_model_cache = None
        self._write_config_file(self._config_payload())

    def set_transcription_language(self, lang: str):
        self.transcription_language = (lang or "multi").strip() or "multi"

    def set_transcription_provider(self, provider: str):
        self.transcription_provider = (provider or "local").strip().lower() or "local"
        if self.transcription_provider not in ("local", "deepgram"):
            self.transcription_provider = "local"

    def set_deepgram_api_key(self, key: str):
        self.deepgram_api_key = (key or "").strip()
        self._write_config_file(self._config_payload())

    def set_views_enabled(self, value: bool):
        self.views_enabled = bool(value)

    def set_download_media_enabled(self, value: bool):
        self.download_media_enabled = bool(value)

    def set_date_period(self, days: int):
        self.date_period_days = max(0, int(days))

    def set_custom_date_range(self, date_from, date_to):
        self.custom_date_from = date_from
        self.custom_date_to = date_to

    def set_incremental_enabled(self, value: bool):
        self.incremental_enabled = bool(value)

    # --- Favorite authors ---

    _FAV_AUTHORS_PATH = os.path.expanduser("~/.tg_exporter/favorite_authors.json")

    def _load_favorite_authors(self) -> dict[str, dict]:
        try:
            if os.path.exists(self._FAV_AUTHORS_PATH):
                with open(self._FAV_AUTHORS_PATH, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_favorite_authors(self, data: dict[str, dict]):
        try:
            os.makedirs(os.path.dirname(self._FAV_AUTHORS_PATH), exist_ok=True)
            with open(self._FAV_AUTHORS_PATH, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def add_favorite_author(self, uid: int, name: str, username: str, chat_id: int | None = None, chat_name: str | None = None):
        data = self._load_favorite_authors()
        key = str(uid)
        entry = data.get(key, {"name": name, "username": username, "chats": {}})
        entry["name"] = name
        entry["username"] = username
        if "chats" not in entry:
            entry["chats"] = {}
        if chat_id is not None and chat_name:
            entry["chats"][str(chat_id)] = chat_name
        data[key] = entry
        self._save_favorite_authors(data)

    def remove_favorite_author(self, uid: int):
        data = self._load_favorite_authors()
        data.pop(str(uid), None)
        self._save_favorite_authors(data)

    def is_favorite_author(self, uid: int) -> bool:
        return str(uid) in self._load_favorite_authors()

    def get_favorite_author_ids(self) -> set[int]:
        return {int(k) for k in self._load_favorite_authors().keys()}

    def get_favorite_authors_list(self) -> list[dict]:
        data = self._load_favorite_authors()
        result = []
        for uid_str, info in data.items():
            chats = info.get("chats", {})
            result.append({
                "id": int(uid_str),
                "name": info.get("name", ""),
                "username": info.get("username", ""),
                "chats": {int(k): v for k, v in chats.items()},
            })
        result.sort(key=lambda x: (x.get("name") or "").lower())
        return result

    def _find_dialog_by_peer_id(self, peer_id: int):
        for d in self.all_dialogs:
            try:
                if get_peer_id(d.entity) == peer_id:
                    return d
            except Exception:
                continue
        return None

    def export_favorites_chats(self, chat_peer_ids: list[int], author_ids: set[int], path: str):
        dialogs = []
        for pid in chat_peer_ids:
            d = self._find_dialog_by_peer_id(pid)
            if d:
                dialogs.append(d)
        if not dialogs:
            self.queue.put(("info", "Не найдено чатов для экспорта"))
            return
        self.author_filter_ids = author_ids
        self.incremental_enabled = True
        folder_name = "favorites_export"
        self._folder_queue = dialogs
        self._folder_total = len(dialogs)
        self._folder_index = 0
        self._folder_export_base = os.path.join(path, sanitize_filename(folder_name))
        try:
            os.makedirs(self._folder_export_base, exist_ok=True)
        except Exception as e:
            self.queue.put(("error", str(e)))
            return
        self._cancel_export.clear()
        self._folder_active = True
        self._folder_log = []
        self._folder_current_label = ""
        self.queue.put(("folder_progress", (0, self._folder_total, "Избранные авторы")))
        self._export_next_in_folder()

    def _load_export_history(self) -> dict:
        try:
            if os.path.exists(self._export_history_path):
                with open(self._export_history_path, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_export_history(self, peer_id: int, last_msg_id: int):
        history = self._load_export_history()
        history[str(peer_id)] = {
            "last_msg_id": last_msg_id,
            "last_export": datetime.datetime.now().isoformat(),
        }
        try:
            os.makedirs(os.path.dirname(self._export_history_path), exist_ok=True)
            with open(self._export_history_path, "w") as f:
                json.dump(history, f, indent=2)
        except Exception:
            pass

    def _get_last_export_id(self, dialog) -> int | None:
        try:
            pid = str(get_peer_id(dialog.entity))
            history = self._load_export_history()
            entry = history.get(pid)
            if entry and isinstance(entry.get("last_msg_id"), int):
                return entry["last_msg_id"]
        except Exception:
            pass
        return None

    def load_participants(self, dialog):
        self._run_bg(self._load_participants_task, dialog)

    def _load_participants_task(self, dialog):
        try:
            c = self._get_client()
            if not c.is_connected():
                c.connect()
            chat_id = None
            chat_name = dialog.name or "Чат"
            try:
                chat_id = get_peer_id(dialog.entity)
            except Exception:
                pass
            participants = []
            seen = set()
            for user in c.iter_participants(dialog, limit=500):
                uid = user.id
                if uid in seen:
                    continue
                seen.add(uid)
                name = get_display_name(user) or ""
                username = getattr(user, "username", None) or ""
                participants.append({"id": uid, "name": name, "username": username})
            participants.sort(key=lambda x: (x.get("name") or "").lower())
            self.queue.put(("participants_loaded", (participants, chat_id, chat_name)))
        except Exception as e:
            self.queue.put(("participants_loaded", ([], None, None)))
            self.queue.put(("info", f"Не удалось загрузить участников: {e}"))

    def _cleanup_temp_voice_files(self):
        temp_dir = tempfile.gettempdir()
        prefix = "tg_exporter_voice_"
        try:
            for name in os.listdir(temp_dir):
                if name.startswith(prefix):
                    path = os.path.join(temp_dir, name)
                    try:
                        os.remove(path)
                    except Exception:
                        pass
        except Exception:
            pass

    def _is_group_chat(self, dialog) -> bool:
        entity = getattr(dialog, "entity", None)
        if entity is None:
            return False
        if getattr(entity, "broadcast", False):
            return False
        if getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False):
            return True
        if entity.__class__.__name__ == "Chat":
            return True
        return False

    def _is_broadcast_channel(self, dialog) -> bool:
        entity = getattr(dialog, "entity", None)
        if entity is None:
            return False
        return bool(getattr(entity, "broadcast", False))

    def _is_forum(self, dialog) -> bool:
        entity = getattr(dialog, "entity", None)
        return bool(getattr(entity, "forum", False)) if entity else False

    def _load_topics_task(self, dialog):
        try:
            c = self._get_client()
            if not c.is_connected():
                c.connect()
            entity = getattr(dialog, "input_entity", None) or getattr(dialog, "entity", None) or dialog
            result = c(functions.messages.GetForumTopicsRequest(
                peer=entity,
                offset_date=datetime.datetime.now(datetime.timezone.utc),
                offset_id=0,
                offset_topic=0,
                limit=100,
            ))
            topics = []
            for t in getattr(result, "topics", []):
                topic_id = getattr(t, "id", None)
                title = normalize_text(getattr(t, "title", None))
                if topic_id is not None and title:
                    topics.append({"id": topic_id, "title": title})
            topics.sort(key=lambda x: x["title"].lower())
            self.queue.put(("topics_loaded", (dialog, topics)))
        except Exception as e:
            self.queue.put(("topics_loaded", (dialog, [])))
            self.queue.put(("info", f"Не удалось загрузить темы: {e}"))

    def _get_transcriber(self) -> str | None:
        """Возвращает 'local', 'deepgram' или None в зависимости от настроек транскрипции."""
        if not self.voice_transcribe_enabled:
            return None
        if (self.transcription_provider or "local") == "deepgram" and (self.deepgram_api_key or "").strip():
            return "deepgram"
        return "local"

    _TRANSCRIBE_MAX_DURATION_SEC = 15 * 60  # только голос и видеокружки до 15 мин; длинные и обычные видео не транскрибируем

    def _get_ffmpeg_path(self) -> str | None:
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
        import shutil
        return shutil.which("ffmpeg")

    def _extract_audio_to_wav(self, video_path: str) -> str | None:
        ffmpeg = self._get_ffmpeg_path()
        if not ffmpeg:
            return None
        try:
            fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="tg_exporter_audio_")
            os.close(fd)
            subprocess.run(
                [
                    ffmpeg, "-y", "-i", video_path,
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    wav_path,
                ],
                capture_output=True,
                timeout=600,
                check=True,
            )
            return wav_path
        except Exception:
            return None

    def _get_whisper_model(self):
        """Ленивая загрузка faster-whisper модели (кэш на время экспорта). Не используется для Parakeet/Silero."""
        mid = self.local_whisper_model or ""
        if mid.startswith("parakeet") or mid.startswith("silero"):
            return None
        if self._whisper_model_cache is not None:
            return self._whisper_model_cache
        try:
            try:
                self.queue.put(("export_status", "Загрузка модели транскрипции..."))
                time.sleep(0.25)
            except Exception:
                pass
            from faster_whisper import WhisperModel
        except ImportError:
            self._last_transcribe_error = "Установите: pip install faster-whisper"
            return None
        model_size = self.local_whisper_model or "base"
        try:
            device = "cuda"
            compute_type = "float16"
            try:
                import torch
                if not torch.cuda.is_available():
                    device = "cpu"
                    compute_type = "int8"
            except Exception:
                device = "cpu"
                compute_type = "int8"
            self._whisper_model_cache = WhisperModel(model_size, device=device, compute_type=compute_type)
            return self._whisper_model_cache
        except Exception as e:
            self._last_transcribe_error = str(e)[:200]
            return None

    def _get_silero_model(self):
        """Ленивая загрузка Silero STT (PyTorch Hub). Язык из id: silero-ru -> ru, silero-en -> en."""
        mid = (self.local_whisper_model or "").strip()
        if not mid.startswith("silero-"):
            return None
        lang = mid.replace("silero-", "").strip() or "en"
        if self._silero_model_cache is None:
            self._silero_model_cache = {}
        if lang in self._silero_model_cache:
            return self._silero_model_cache[lang]
        try:
            try:
                self.queue.put(("export_status", "Загрузка модели транскрипции..."))
                time.sleep(0.25)
            except Exception:
                pass
            import torch
        except ImportError:
            self._last_transcribe_error = "Для Silero установите: pip install torch torchaudio"
            return None
        try:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model, decoder, utils = torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_stt",
                language=lang,
                device=device,
                trust_repo=True,
            )
            (read_batch, split_into_batches, read_audio, prepare_model_input) = utils
            self._silero_model_cache[lang] = (model, decoder, read_batch, split_into_batches, prepare_model_input, device)
            return self._silero_model_cache[lang]
        except Exception as e:
            self._last_transcribe_error = str(e)[:200]
            return None

    def _get_parakeet_model(self):
        """Ленивая загрузка NVIDIA Parakeet (NeMo). Модель в основном для английского."""
        if self._parakeet_model_cache is not None:
            return self._parakeet_model_cache
        try:
            try:
                self.queue.put(("export_status", "Загрузка модели транскрипции..."))
                time.sleep(0.25)
            except Exception:
                pass
            import nemo.collections.asr as nemo_asr
        except ImportError:
            self._last_transcribe_error = "Для Parakeet установите: pip install nemo_toolkit[asr]"
            return None
        model_id = self.local_whisper_model or "parakeet-tdt-0.6b"
        name = "nvidia/parakeet-tdt-1.1b" if "1.1" in model_id else "nvidia/parakeet-tdt-0.6b"
        try:
            self._parakeet_model_cache = nemo_asr.models.ASRModel.from_pretrained(name)
            return self._parakeet_model_cache
        except Exception as e:
            self._last_transcribe_error = str(e)[:200]
            return None

    def _preload_transcription_model(self):
        """Предзагрузка модели транскрипции с показом статуса в UI, чтобы не «зависать» на первом голосовом сообщении."""
        if self._cancel_export.is_set():
            return
        try:
            self.queue.put(("export_status", "Загрузка модели транскрипции..."))
            time.sleep(0.3)
            mid = (self.local_whisper_model or "").strip().lower()
            if mid.startswith("silero"):
                self._get_silero_model()
            elif mid.startswith("parakeet"):
                self._get_parakeet_model()
            else:
                self._get_whisper_model()
        except Exception:
            pass
        finally:
            try:
                self.queue.put(("export_status", ""))
            except Exception:
                pass

    def _transcribe_audio_deepgram(self, audio_data: bytes, content_type: str) -> str | None:
        """Облачная транскрипция через Deepgram API. Требует API ключ."""
        if not audio_data or not (self.deepgram_api_key or "").strip():
            return None
        key = (self.deepgram_api_key or "").strip()
        ct = (content_type or "audio/ogg").split(";")[0].strip()
        if "wav" not in ct.lower():
            ct = "audio/ogg"
        else:
            ct = "audio/wav"
        url = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true"
        lang = (self.transcription_language or "multi").strip() or "multi"
        if lang != "multi":
            url += "&language=" + urllib.parse.quote(lang)
        req = urllib.request.Request(
            url,
            data=audio_data,
            method="POST",
            headers={
                "Authorization": "Token " + key,
                "Content-Type": ct,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            self._last_transcribe_error = f"Deepgram HTTP {e.code}"
            return None
        except Exception as e:
            self._last_transcribe_error = str(e)[:200]
            return None
        try:
            channels = data.get("results", {}).get("channels", [])
            if not channels:
                return None
            alts = channels[0].get("alternatives", [])
            if not alts:
                return None
            text = (alts[0].get("transcript") or "").strip()
            return text or None
        except Exception:
            return None

    def _transcribe_audio_local(self, audio_data: bytes, content_type: str) -> str | None:
        """Локальная транскрипция: Whisper, Parakeet (NeMo) или Silero. Пишет аудио во временный файл."""
        if not audio_data:
            return None
        mid = self.local_whisper_model or ""
        use_parakeet = mid.startswith("parakeet")
        use_silero = mid.startswith("silero")
        ext = ".wav" if "wav" in (content_type or "") else ".ogg"
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="tg_exporter_transcribe_")
            os.close(fd)
            with open(tmp_path, "wb") as f:
                f.write(audio_data)
            if use_parakeet:
                model = self._get_parakeet_model()
                if model is None:
                    return None
                result = model.transcribe([tmp_path])
                if result and len(result) and hasattr(result[0], "text"):
                    return (result[0].text or "").strip() or None
                return None
            if use_silero:
                silero = self._get_silero_model()
                if silero is None:
                    return None
                model, decoder, read_batch, split_into_batches, prepare_model_input, device = silero
                try:
                    batches = split_into_batches([tmp_path], batch_size=1)
                    inp = prepare_model_input(read_batch(batches[0]), device=device)
                    out = model(inp)
                    parts = []
                    for i in range(out.shape[0]):
                        text = decoder(out[i].cpu())
                        if text:
                            parts.append(text)
                    return " ".join(parts).strip() or None
                except Exception as e:
                    self._last_transcribe_error = str(e)[:200]
                    return None
            model = self._get_whisper_model()
            if model is None:
                return None
            lang = (self.transcription_language or "multi").strip() or "multi"
            segments, _ = model.transcribe(tmp_path, language=None if lang == "multi" else lang, beam_size=1)
            parts = [s.text for s in segments if s.text]
            return " ".join(parts).strip() or None
        except Exception as e:
            self._last_transcribe_error = str(e)[:200]
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def _prepare_audio_for_transcribe(self, msg):
        """Скачивает и подготавливает аудио (только в потоке с event loop — экспорт).
        Возвращает (bytes, content_type, media_audio_bytes_or_none) или None.
        media_audio_bytes_or_none: для видеокружков — те же байты (сохранить в media/audio вместо полного видео)."""
        if getattr(self, "_cancel_export", None) and self._cancel_export.is_set():
            return None
        voice = getattr(msg, "voice", None)
        video_note = getattr(msg, "video_note", None)
        if not voice and not video_note:
            return None
        duration_sec = getattr(voice or video_note, "duration", 0) or 0
        if duration_sec > self._TRANSCRIBE_MAX_DURATION_SEC:
            self._last_transcribe_error = f"длинное сообщение ({duration_sec // 60} мин), лимит {self._TRANSCRIBE_MAX_DURATION_SEC // 60} мин"
            return None
        tmp_path = None
        wav_path = None
        self._last_transcribe_error = None
        try:
            if voice:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg", prefix="tg_exporter_voice_") as tmp:
                    tmp_path = tmp.name
                msg.download_media(file=tmp_path)
                with open(tmp_path, "rb") as f:
                    return (f.read(), "audio/ogg", None)
            if not self._get_ffmpeg_path():
                self._last_transcribe_error = "для видеокружков нужен ffmpeg"
                return None
            if getattr(self, "_cancel_export", None) and self._cancel_export.is_set():
                return None
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4", prefix="tg_exporter_video_") as tmp:
                tmp_path = tmp.name
            msg.download_media(file=tmp_path)
            if getattr(self, "_cancel_export", None) and self._cancel_export.is_set():
                return None
            wav_path = self._extract_audio_to_wav(tmp_path)
            if not wav_path:
                self._last_transcribe_error = "не удалось извлечь звук из видеокружка"
                return None
            with open(wav_path, "rb") as f:
                data = f.read()
            return (data, "audio/wav", data)
        except Exception as e:
            self._last_transcribe_error = str(e)[:150]
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            if wav_path and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass

    def _transcribe_voice(self, msg, transcriber) -> str | None:
        """Только голосовые и видеокружки до 15 мин. Локальная транскрипция (faster-whisper)."""
        prepared = self._prepare_audio_for_transcribe(msg)
        if prepared is None:
            return None
        audio_data, content_type = prepared[0], prepared[1]
        return self._transcribe_audio_local(audio_data, content_type)

    def _is_popular_candidate(self, dialog) -> bool:
        entity = getattr(dialog, "entity", None)
        if entity is None:
            return False
        if entity.__class__.__name__ == "User":
            return False
        return True

    def _dialog_matches_filter(self, dialog, flt) -> bool:
        if not flt:
            return True
        entity = getattr(dialog, "entity", None)
        if entity is None:
            return False
        entity_type = entity.__class__.__name__
        is_user = entity_type == "User"
        is_bot = bool(getattr(entity, "bot", False))
        is_channel = entity_type == "Channel"
        is_group = entity_type == "Chat" or (is_channel and (getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False)))
        is_broadcast = is_channel and getattr(entity, "broadcast", False)
        is_contact = bool(getattr(entity, "contact", False))

        include_any = False
        allowed = False
        if getattr(flt, "contacts", False):
            include_any = True
            if is_user and is_contact and not is_bot:
                allowed = True
        if getattr(flt, "non_contacts", False):
            include_any = True
            if is_user and not is_contact and not is_bot:
                allowed = True
        if getattr(flt, "bots", False):
            include_any = True
            if is_user and is_bot:
                allowed = True
        if getattr(flt, "groups", False):
            include_any = True
            if is_group:
                allowed = True
        if getattr(flt, "broadcasts", False):
            include_any = True
            if is_broadcast:
                allowed = True
        if include_any and not allowed:
            return False

        if getattr(flt, "exclude_archived", False) and getattr(dialog, "archived", False):
            return False
        if getattr(flt, "exclude_muted", False) and getattr(dialog, "muted", False):
            return False
        if getattr(flt, "exclude_read", False):
            unread = getattr(dialog, "unread_count", 0) or 0
            unread_mentions = getattr(dialog, "unread_mentions_count", 0) or 0
            if unread == 0 and unread_mentions == 0:
                return False
        return True

    def _get_folder_dialogs(self, folder_name: str):
        dialogs = self.all_dialogs
        if folder_name and folder_name != "Все чаты":
            peer_ids = self.folder_peers.get(folder_name, set())
            flt = self.folder_filters.get(folder_name)
            exclude_ids = self.folder_excludes.get(folder_name, set())
            if peer_ids:
                filtered = []
                for d in dialogs:
                    try:
                        pid = get_peer_id(d.entity)
                    except Exception:
                        pid = d.id
                    if pid in peer_ids:
                        filtered.append(d)
                dialogs = filtered
            elif flt:
                dialogs = [d for d in dialogs if self._dialog_matches_filter(d, flt)]
            if exclude_ids:
                filtered = []
                for d in dialogs:
                    try:
                        pid = get_peer_id(d.entity)
                    except Exception:
                        pid = d.id
                    if pid not in exclude_ids:
                        filtered.append(d)
                dialogs = filtered
        if self.analytics_enabled:
            dialogs = [d for d in dialogs if self._is_group_chat(d)]
        if self.popular_enabled:
            dialogs = [d for d in dialogs if self._is_popular_candidate(d)]
        return dialogs

    def export_current_folder(self):
        folder_name = self.current_folder
        if not folder_name or folder_name == "Все чаты":
            self.queue.put(("error", "Выберите папку для экспорта."))
            return
        self._cancel_export.clear()
        if not self._confirm_export_safety():
            return
        dialogs = self._get_folder_dialogs(folder_name)
        if not dialogs:
            self.queue.put(("error", "В выбранной папке нет чатов."))
            return
        path = filedialog.askdirectory(title="Куда сохранить экспорт папки?")
        if not path:
            return
        self._folder_queue = dialogs
        self._folder_total = len(dialogs)
        self._folder_index = 0
        self._folder_export_base = os.path.join(path, sanitize_filename(folder_name))
        try:
            os.makedirs(self._folder_export_base, exist_ok=True)
        except Exception as e:
            self.queue.put(("error", str(e)))
            return
        self._folder_active = True
        self._folder_log = []
        self._folder_current_label = ""
        self.queue.put(("folder_progress", (0, self._folder_total, folder_name)))
        self._export_next_in_folder()

    def cancel_export(self):
        self._cancel_export.set()
        if self._folder_active:
            self._folder_active = False

    def _export_next_in_folder(self):
        if self._folder_index >= self._folder_total:
            self._folder_active = False
            self.queue.put(("folder_done", self._folder_total))
            return
        if self._cancel_export.is_set():
            self._folder_active = False
            self.queue.put(("export_cancelled", None))
            return
        dialog = self._folder_queue[self._folder_index]
        self._folder_index += 1
        self._folder_current_label = dialog.name or "Чат"
        self.queue.put(("folder_progress", (self._folder_index, self._folder_total, self._folder_current_label)))
        self._run_bg(self._export_task, dialog, self._folder_export_base)

    def _append_folder_log(self, ok: bool):
        name = self._folder_current_label or "Чат"
        prefix = "OK" if ok else "ERR"
        self._folder_log.append(f"{prefix}: {name}")
        if len(self._folder_log) > 5:
            self._folder_log = self._folder_log[-5:]

    def logout(self):
        self._run_bg(self._logout_task)

    def _logout_task(self):
        client = self.client
        if client:
            client.disconnect()
            self.client = None
        self.phone_hash = None
        self.phone_number = None
        self.api_creds["session"] = None
        self._clear_session_in_keyring()
        self._write_config_file(self._config_payload())
        self.queue.put(("logout_done", None))

    def _persist_session(self):
        try:
            c = self._get_client()
            session_str = c.session.save()
            if session_str:
                self.api_creds["session"] = session_str
                self._save_session_to_keyring(session_str)
                self._write_config_file(self._config_payload())
        except Exception:
            pass

    def _export_task(self, dialog, path, topic_id=None, topic_title=None):
        try:
            if self._cancel_export.is_set():
                raise ExportCancelled()
            c = self._get_client()
            if not c.is_connected():
                c.connect()
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            chat_title = sanitize_filename(dialog.name or "chat")
            if len(chat_title) > 60:
                chat_title = chat_title[:60].rstrip("_ ")
            if topic_title:
                safe_topic = sanitize_filename(topic_title)
                if len(safe_topic) > 40:
                    safe_topic = safe_topic[:40].rstrip("_ ")
                chat_title = f"{chat_title}_topic_{safe_topic}"
            export_dir = os.path.join(path, f"{chat_title}_{timestamp}")
            try:
                os.makedirs(export_dir, exist_ok=True)
            except Exception as e:
                msg = str(e)
                if "WinError" in msg:
                    msg = (
                        "Не удалось создать папку экспорта.\n"
                        f"Путь: {export_dir}\n"
                        "Выберите другую папку (Desktop/Downloads).\n"
                        "Если включена «Контролируемый доступ к папкам» "
                        "в Windows Security — добавьте TelegramExporter.exe в разрешенные."
                    )
                self.queue.put(("export_error", msg))
                return
            full_path = os.path.join(export_dir, "result.json")
            md_prefix = _sanitize_md_filename(dialog.name or "Telegram Chat")
            md_words_per_file = self.md_words_per_file
            md_current = ""
            md_word_count = 0
            md_next_index = 1
            md_pending_first: str | None = None
            md_written = 0
            popular_enabled = self.popular_enabled
            popular_min = self.popular_min_reactions
            popular_entries: list[tuple[str, int]] = []
            popular_written = False
            topic_map: dict[str, str] = {}
            service_topic_by_id: dict[int, str] = {}
            has_topics = False
            is_forum = bool(getattr(getattr(dialog, "entity", None), "forum", False))
            analytics_enabled = self.analytics_enabled and self._is_group_chat(dialog)
            transcribe_enabled = self.voice_transcribe_enabled and self._is_broadcast_channel(dialog)
            views_enabled = self.views_enabled
            download_media_enabled = self.download_media_enabled
            media_base = os.path.join(export_dir, "media") if download_media_enabled else None
            media_dirs = {}  # subdir path by type: "photo", "video", "audio", "documents"
            if media_base:
                try:
                    for sub in ("photo", "video", "audio", "documents"):
                        d = os.path.join(media_base, sub)
                        os.makedirs(d, exist_ok=True)
                        media_dirs[sub] = d
                except Exception:
                    media_base = None
                    media_dirs = {}
            author_counts: dict[int, int] = {}
            author_messages: dict[int, list[str]] = {}
            author_meta: dict[int, dict[str, str]] = {}
            activity_counts: dict[str, int] = {}
            transcriber = None
            transcribe_failed = False
            transcribe_warned = False
            video_note_audio_saved_ids = set()

            def _date_key(value: str | None) -> str | None:
                if not value:
                    return None
                if "T" in value:
                    return value.split("T")[0]
                if " " in value:
                    return value.split(" ")[0]
                return value[:10] if len(value) >= 10 else value

            def write_md_chunk(index: int, content: str) -> None:
                nonlocal md_written
                normalized = content.replace("\r\n", "\n").replace("\r", "\n")
                with_bom = "\ufeff" + normalized
                md_path = os.path.join(export_dir, f"{md_prefix}_part_{index}.md")
                with open(md_path, "w", encoding="utf-8") as mf:
                    mf.write(with_bom)
                md_written += 1

            def add_md_chunk() -> None:
                nonlocal md_current, md_word_count, md_pending_first, md_next_index
                trimmed = md_current.strip()
                if not trimmed:
                    md_current = ""
                    md_word_count = 0
                    return
                if md_pending_first is None:
                    md_pending_first = trimmed
                    if md_next_index == 1:
                        md_next_index = 2
                else:
                    write_md_chunk(md_next_index, trimmed)
                    md_next_index += 1
                md_current = ""
                md_word_count = 0

            date_from = None
            date_to = None
            if self.custom_date_from or self.custom_date_to:
                date_from = self.custom_date_from
                date_to = self.custom_date_to
            elif self.date_period_days > 0:
                date_from = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=self.date_period_days)

            incremental_min_id = None
            if self.incremental_enabled:
                incremental_min_id = self._get_last_export_id(dialog)
            max_msg_id = 0
            author_filter = self.author_filter_ids

            count_kwargs: dict = {"limit": 0}
            if topic_id is not None:
                count_kwargs["reply_to"] = topic_id
            if incremental_min_id:
                count_kwargs["min_id"] = incremental_min_id

            total = None
            try:
                total_all = getattr(c.get_messages(dialog, **count_kwargs), "total", None)
                if date_from is not None and total_all:
                    before_from = getattr(c.get_messages(dialog, offset_date=date_from, **count_kwargs), "total", 0) or 0
                    total = max(0, total_all - before_from)
                    if date_to is not None:
                        after_to = date_to + datetime.timedelta(days=1)
                        before_to = getattr(c.get_messages(dialog, offset_date=after_to, **count_kwargs), "total", 0) or 0
                        total = max(0, total - (total_all - before_to))
                elif date_to is not None and total_all:
                    after_to = date_to + datetime.timedelta(days=1)
                    before_to = getattr(c.get_messages(dialog, offset_date=after_to, **count_kwargs), "total", 0) or 0
                    total = before_to
                else:
                    total = total_all
            except Exception:
                total = None
            export_label = dialog.name or "Чат"
            if topic_title:
                export_label = f"{export_label} → {topic_title}"
            self.queue.put(("export_start", (export_label, total)))
            if transcribe_enabled and (self.transcription_provider or "local") == "local":
                self._preload_transcription_model()

            iter_kwargs: dict = {"reverse": True}
            if topic_id is not None:
                iter_kwargs["reply_to"] = topic_id
            if date_from is not None:
                iter_kwargs["offset_date"] = date_from
            if incremental_min_id:
                iter_kwargs["min_id"] = incremental_min_id

            with open(full_path, "w", encoding="utf-8") as f:
                json_header = '{\n  "name": ' + json.dumps(dialog.name, ensure_ascii=False)
                if topic_title:
                    json_header += ',\n  "topic": ' + json.dumps(topic_title, ensure_ascii=False)
                json_header += ',\n  "messages": [\n'
                f.write(json_header)
                first = True
                count = 0
                date_to_end = (date_to + datetime.timedelta(days=1)) if date_to else None
                for msg in c.iter_messages(dialog, **iter_kwargs):
                    if self._cancel_export.is_set():
                        raise ExportCancelled()
                    if date_to_end and hasattr(msg, "date") and msg.date and msg.date >= date_to_end:
                        break
                    msg_id = getattr(msg, "id", 0) or 0
                    if msg_id > max_msg_id:
                        max_msg_id = msg_id
                    if author_filter is not None:
                        sender_id = getattr(msg, "sender_id", None)
                        if sender_id is not None and sender_id not in author_filter:
                            count += 1
                            if total and (count <= 1 or count % 20 == 0):
                                self.queue.put(("export_progress", (count, total)))
                            continue
                    is_out = bool(getattr(msg, "out", False))
                    if not first: f.write(",\n")
                    first = False
                    msg_data = message_to_export(msg)
                    if not views_enabled:
                        msg_data.pop("views", None)
                        msg_data.pop("forwards", None)
                    json.dump(msg_data, f, ensure_ascii=False)

                    if msg_data.get("type") != "message":
                        if is_forum and msg_data.get("topic_title"):
                            has_topics = True
                            service_topic_id = msg_data.get("topic_id") or msg_data.get("id")
                            if service_topic_id is not None:
                                service_topic_id = str(service_topic_id)
                                topic_map[service_topic_id] = msg_data.get("topic_title") or ""
                                if isinstance(msg_data.get("id"), int):
                                    service_topic_by_id[msg_data["id"]] = msg_data.get("topic_title") or ""
                        count += 1
                        if total and (count <= 1 or count % 20 == 0):
                            self.queue.put(("export_progress", (count, total)))
                        elif not total and (count <= 1 or count % 50 == 0):
                            self.queue.put(("export_progress", (count, None)))
                        continue

                    topic_id = None
                    topic_comment = ""
                    if is_forum:
                        topic_id = _resolve_topic_id(msg_data, service_topic_by_id)
                        if topic_id:
                            has_topics = True
                            if topic_id not in topic_map:
                                topic_map[topic_id] = ""
                            if msg_data.get("topic_title"):
                                topic_map[topic_id] = msg_data.get("topic_title") or ""
                        if msg_data.get("is_topic_message") or msg_data.get("is_forum_topic"):
                            has_topics = True
                        topic_comment = _build_topic_comment(topic_id, topic_map) if has_topics else ""
                    formatted = _format_markdown_message(msg_data)
                    if self._cancel_export.is_set():
                        raise ExportCancelled()
                    if transcribe_enabled and not transcribe_failed:
                        if getattr(msg, "voice", None) or getattr(msg, "video_note", None):
                            if transcriber is None:
                                transcriber = self._get_transcriber()
                                if transcriber is None:
                                    transcribe_failed = True
                            if transcriber is not None:
                                try:
                                    self.queue.put(("export_progress", (count + 1, total)))
                                except Exception:
                                    pass
                                try:
                                    try:
                                        self.queue.put(("export_status", "Скачивание голосового сообщения..."))
                                    except Exception:
                                        pass
                                    prepared = self._prepare_audio_for_transcribe(msg)
                                finally:
                                    try:
                                        self.queue.put(("export_status", ""))
                                    except Exception:
                                        pass
                                if prepared is not None:
                                    audio_data, content_type = prepared[0], prepared[1]
                                    media_audio = prepared[2] if len(prepared) >= 3 else None
                                    if media_audio and media_dirs and msg_id:
                                        try:
                                            out_path = os.path.join(media_dirs.get("audio", ""), f"vn_{msg_id}.wav")
                                            if os.path.isdir(os.path.dirname(out_path)):
                                                with open(out_path, "wb") as af:
                                                    af.write(media_audio)
                                                video_note_audio_saved_ids.add(msg_id)
                                        except Exception:
                                            pass
                                    if self._cancel_export.is_set():
                                        raise ExportCancelled()
                                    try:
                                        try:
                                            self.queue.put(("export_status", "Транскрипция..."))
                                        except Exception:
                                            pass
                                        if transcriber == "deepgram":
                                            text = self._transcribe_audio_deepgram(audio_data, content_type)
                                        else:
                                            text = self._transcribe_audio_local(audio_data, content_type)
                                    except Exception:
                                        text = None
                                        if not getattr(self, "_last_transcribe_error", None):
                                            self._last_transcribe_error = "ошибка транскрипции"
                                    finally:
                                        try:
                                            self.queue.put(("export_status", ""))
                                        except Exception:
                                            pass
                                else:
                                    text = None
                                    if self._cancel_export.is_set():
                                        raise ExportCancelled()
                                if text:
                                    formatted = f"{formatted}\n\nТранскрипция: {text}"
                                else:
                                    reason = getattr(self, "_last_transcribe_error", None) or ""
                                    if reason and "длинное сообщение" in reason:
                                        formatted = f"{formatted}\n\n[Транскрипция пропущена: {reason}]"
                                    else:
                                        if not transcribe_warned:
                                            transcribe_warned = True
                                            self.queue.put(("info", f"Не удалось распознать часть голосовых и видео. Причина: {reason or 'нет текста в ответе'}. Экспорт продолжен без транскрипции."))
                            elif not transcribe_warned:
                                transcribe_warned = True
                                self.queue.put(("info", "Транскрипция недоступна (для видео нужен ffmpeg, для локальной — faster-whisper). Экспорт продолжен без неё."))
                    rendered = f"{topic_comment}{formatted}" if topic_comment else formatted
                    if self._cancel_export.is_set():
                        raise ExportCancelled()
                    if media_dirs and not getattr(msg, "sticker", None):
                        target_dir = None
                        if getattr(msg, "photo", None):
                            target_dir = media_dirs.get("photo")
                        elif getattr(msg, "video", None):
                            target_dir = media_dirs.get("video")
                        elif getattr(msg, "video_note", None):
                            if msg_id not in video_note_audio_saved_ids:
                                target_dir = media_dirs.get("video")
                        elif getattr(msg, "voice", None) or getattr(msg, "audio", None):
                            target_dir = media_dirs.get("audio")
                        elif getattr(msg, "document", None):
                            target_dir = media_dirs.get("documents")
                        if target_dir:
                            if self._cancel_export.is_set():
                                raise ExportCancelled()
                            try:
                                msg.download_media(file=target_dir)
                            except Exception:
                                pass
                            if self._cancel_export.is_set():
                                raise ExportCancelled()
                    if analytics_enabled:
                        author_id = msg_data.get("from_id")
                        if not is_out and isinstance(author_id, int) and author_id > 0:
                            author = (msg_data.get("from") or "Без имени").strip()
                            if not author:
                                author = "Без имени"
                            username = (msg_data.get("from_username") or "").strip()
                            meta = author_meta.get(author_id) or {"name": author, "username": username}
                            if not meta.get("name") and author:
                                meta["name"] = author
                            if not meta.get("username") and username:
                                meta["username"] = username
                            author_meta[author_id] = meta
                            author_counts[author_id] = author_counts.get(author_id, 0) + 1
                            entry = rendered
                            msg_id = msg_data.get("id")
                            if msg_id is not None:
                                entry = f"ID: {msg_id}\n{rendered}".strip()
                            author_messages.setdefault(author_id, []).append(entry)
                        date_key = _date_key(msg_data.get("date"))
                        if date_key:
                            activity_counts[date_key] = activity_counts.get(date_key, 0) + 1

                    msg_words = len(rendered.split()) if rendered else 0
                    if md_word_count + msg_words > md_words_per_file and md_current.strip():
                        add_md_chunk()
                    if rendered:
                        md_current += rendered + "\n\n"
                        md_word_count += msg_words

                        if popular_enabled:
                            reactions = msg_data.get("reactions") or []
                            total_reactions = 0
                            for reaction in reactions:
                                try:
                                    total_reactions += int(reaction.get("count", 0))
                                except Exception:
                                    continue
                            if total_reactions >= popular_min:
                                popular_entries.append((rendered, total_reactions))

                    count += 1
                    if total and (count <= 1 or count % 20 == 0):
                        self.queue.put(("export_progress", (count, total)))
                    elif not total and (count <= 1 or count % 50 == 0):
                        self.queue.put(("export_progress", (count, None)))
                f.write('\n  ]\n}\n')

            add_md_chunk()
            topics_index = _build_topics_index(topic_map) if is_forum else ""
            if md_pending_first or topics_index:
                first_content = ""
                if topics_index:
                    first_content = topics_index
                if md_pending_first:
                    first_content = f"{first_content}\n\n{md_pending_first}".strip()
                if first_content:
                    write_md_chunk(1, first_content)

            if popular_enabled:
                header = f"# Популярные сообщения (>= {popular_min} реакций)"
                content = header
                if popular_entries:
                    blocks = []
                    for entry_text, total_reactions in popular_entries:
                        blocks.append(f"## Реакций: {total_reactions}\n\n{entry_text}")
                    content = header + "\n\n" + "\n\n---\n\n".join(blocks)
                pop_path = os.path.join(export_dir, f"{md_prefix}_popular.md")
                normalized = content.replace("\r\n", "\n").replace("\r", "\n")
                with_bom = "\ufeff" + normalized
                with open(pop_path, "w", encoding="utf-8") as pf:
                    pf.write(with_bom)
                popular_written = True

            analytics_written = []
            if analytics_enabled:
                if author_counts:
                    sorted_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
                    summary_lines = [
                        f"# Топ активных участников ({len(sorted_authors)})",
                        "",
                        f"Сформировано: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        "",
                        "## Список участников",
                        "",
                    ]
                    for author_id, count_messages in sorted_authors:
                        meta = author_meta.get(author_id, {})
                        name = meta.get("name") or "Без имени"
                        username = meta.get("username") or ""
                        display = f"{name} (@{username})" if username else name
                        summary_lines.append(f"- {display} — {count_messages}")
                    summary_lines.append("")

                    author_blocks: list[tuple[str, int]] = []
                    for author_id, count_messages in sorted_authors:
                        meta = author_meta.get(author_id, {})
                        name = meta.get("name") or "Без имени"
                        username = meta.get("username") or ""
                        display = f"{name} (@{username})" if username else name
                        block_lines = [f"## {display} — {count_messages}", ""]
                        for entry in author_messages.get(author_id, []):
                            if entry:
                                block_lines.append(entry)
                                block_lines.append("")
                        block_text = "\n".join(block_lines)
                        block_words = len(block_text.split())
                        author_blocks.append((block_text, block_words))

                    words_limit = md_words_per_file
                    summary_text = "\n".join(summary_lines)
                    parts: list[str] = []
                    current_part = summary_text
                    current_words = len(summary_text.split())

                    for block_text, block_words in author_blocks:
                        if current_words + block_words > words_limit and current_part.strip() != summary_text.strip():
                            parts.append(current_part)
                            current_part = ""
                            current_words = 0
                        if current_part:
                            current_part += "\n" + block_text
                        else:
                            current_part = block_text
                        current_words += block_words
                    if current_part.strip():
                        parts.append(current_part)

                    ta_written = 0
                    for idx, part_content in enumerate(parts):
                        suffix = "" if idx == 0 else f"_part_{idx + 1}"
                        fname = f"top_authors{suffix}.md"
                        fpath = os.path.join(export_dir, fname)
                        normalized = part_content.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
                        with open(fpath, "w", encoding="utf-8") as tf:
                            tf.write("\ufeff" + normalized)
                        ta_written += 1
                    if ta_written == 1:
                        analytics_written.append("top_authors.md")
                    else:
                        analytics_written.append(f"top_authors (×{ta_written})")

                if activity_counts:
                    weekday_names = [
                        "Понедельник",
                        "Вторник",
                        "Среда",
                        "Четверг",
                        "Пятница",
                        "Суббота",
                        "Воскресенье",
                    ]
                    lines = [
                        "# Активность по дням",
                        "",
                        "| Дата | День недели | Сообщений |",
                        "| --- | --- | --- |",
                    ]
                    for day in sorted(activity_counts.keys()):
                        weekday = ""
                        try:
                            dt = datetime.date.fromisoformat(day)
                            weekday = weekday_names[dt.weekday()]
                        except Exception:
                            weekday = ""
                        lines.append(f"| {day} | {weekday} | {activity_counts[day]} |")
                    total_messages = sum(activity_counts.values())
                    hot_days = sorted(activity_counts.items(), key=lambda x: x[1], reverse=True)[:3]
                    if hot_days:
                        lines.append("")
                        lines.append("## Самые горячие дни")
                        lines.append("")
                        for day, count_messages in hot_days:
                            weekday = ""
                            try:
                                dt = datetime.date.fromisoformat(day)
                                weekday = weekday_names[dt.weekday()]
                            except Exception:
                                weekday = ""
                            suffix = f" ({weekday})" if weekday else ""
                            lines.append(f"- {day}{suffix}: {count_messages}")
                        lines.append("")
                        lines.append(f"Всего сообщений: {total_messages}")
                    act_path = os.path.join(export_dir, "activity.md")
                    normalized = "\n".join(lines).replace("\r\n", "\n").replace("\r", "\n")
                    with_bom = "\ufeff" + normalized.strip() + "\n"
                    with open(act_path, "w", encoding="utf-8") as af:
                        af.write(with_bom)
                    analytics_written.append("activity.md")

            if max_msg_id > 0:
                try:
                    peer_id = get_peer_id(dialog.entity)
                    self._save_export_history(peer_id, max_msg_id)
                except Exception:
                    pass
            if total:
                self.queue.put(("export_progress", (total, total)))
            done_msg = f"Готово: {export_dir}"
            if md_written:
                done_msg += f" (Markdown файлов: {md_written})"
            if popular_written:
                done_msg += f", popular: {md_prefix}_popular.md"
            if analytics_written:
                done_msg += f", аналитика: {', '.join(analytics_written)}"
            self.queue.put(("export_done", done_msg))
        except ExportCancelled:
            self.queue.put(("export_cancelled", None))
        except Exception as e:
            msg = str(e)
            if "WinError 2" in msg or "No such file" in msg:
                msg = (
                    "Не удалось создать файл экспорта.\n"
                    f"Путь: {export_dir}\n"
                    "Выберите другую папку (Desktop/Downloads).\n"
                    "Если включена «Контролируемый доступ к папкам» "
                    "в Windows Security — добавьте TelegramExporter.exe в разрешенные."
                )
            elif "WinError 5" in msg or "Access is denied" in msg:
                msg = (
                    "Нет доступа к папке экспорта.\n"
                    f"Путь: {export_dir}\n"
                    "Выберите другую папку или разрешите приложение в Windows Security."
                )
            self.queue.put(("export_error", msg))
        finally:
            self._whisper_model_cache = None
            self._parakeet_model_cache = None
            self._silero_model_cache = None

    # --- UI Updates ---

    def _process_queue(self):
        try:
            while True:
                kind, data = self.queue.get_nowait()
                if kind == "error":
                    if "database is locked" in data.lower():
                        messagebox.showerror(
                            "Ошибка",
                            "База сессии занята другим процессом.\n"
                            "Закройте все другие копии приложения и повторите.\n"
                            "Если не поможет — перезапустите приложение."
                        )
                    else:
                        messagebox.showerror("Ошибка", data)
                elif kind == "info": messagebox.showinfo("Инфо", data)
                elif kind == "code_sent": self.login_view.show_code_input()
                elif kind == "login_success": self.show_chats()
                elif kind == "chats_loaded":
                    query = self.chats_view.search_entry.get().strip()
                    self.filter_chats(query)
                elif kind == "folders_loaded": self.chats_view.set_folders(data)
                elif kind == "export_start":
                    chat_name, total = data
                    self.chats_view.show_export_progress(chat_name, total)
                elif kind == "export_progress":
                    count, total = data
                    self.chats_view.update_export_progress(count, total)
                elif kind == "export_status":
                    self.chats_view.set_export_status(data or "")
                elif kind == "export_done":
                    self._cancel_export.clear()
                    self.chats_view.finish_export(True, data)
                    if self._folder_active:
                        self._append_folder_log(True)
                        self._export_next_in_folder()
                elif kind == "export_error":
                    self._cancel_export.clear()
                    self.chats_view.finish_export(False, data)
                    if self._folder_active:
                        self._append_folder_log(False)
                        self._export_next_in_folder()
                elif kind == "export_cancelled":
                    self._cancel_export.clear()
                    self.chats_view.finish_export(True, "Экспорт отменен.")
                    self._folder_active = False
                elif kind == "folder_progress":
                    current, total, label = data
                    self.chats_view.show_folder_progress(current, total, label, self._folder_log)
                elif kind == "folder_done":
                    self.chats_view.show_folder_done(data, self._folder_log)
                elif kind == "topics_loaded":
                    dialog, topics = data
                    self.chats_view.status_lbl.configure(text="")
                    if topics:
                        picker = TopicPickerModal(self, topics)
                        self.wait_window(picker)
                        if picker.result_export_all:
                            self._start_export(dialog)
                        elif picker.result_topic_id is not None:
                            self._start_export(dialog, picker.result_topic_id, picker.result_topic_title)
                    else:
                        self._start_export(dialog)
                elif kind == "participants_loaded":
                    self.chats_view.status_lbl.configure(text="")
                    participants, chat_id, chat_name = data if isinstance(data, tuple) else (data, None, None)
                    if participants:
                        modal = AuthorFilterModal(self, participants, app=self, chat_id=chat_id, chat_name=chat_name)
                        self.wait_window(modal)
                        self.author_filter_ids = modal.result_ids
                        self.chats_view._update_fav_count()
                        if modal.result_ids is not None:
                            self.chats_view.update_author_filter_label(len(modal.result_ids))
                        else:
                            self.chats_view.update_author_filter_label(None)
                    else:
                        self.chats_view.status_lbl.configure(text="Не удалось загрузить участников")
                elif kind == "logout_done": self.show_login()
        except queue.Empty: pass
        self.after(100, self._process_queue)


if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    except Exception as exc:
        _write_fatal_error(exc)
        try:
            messagebox.showerror(
                "Ошибка запуска",
                "Приложение не смогло запуститься.\n"
                "Файл лога: ~/.tg_exporter/app.log",
            )
        except Exception:
            pass
