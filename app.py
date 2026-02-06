import asyncio
import datetime
import json
import os
import queue
import re
import threading
import tkinter as tk
import platform
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk
from telethon import functions
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.sync import TelegramClient
from telethon.utils import get_display_name, get_peer_id

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


def _write_fatal_error(exc: BaseException) -> None:
    try:
        log_path = _log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write("\n==== FATAL ====\n")
            f.write(datetime.datetime.now().isoformat())
            f.write("\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
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
        title = title.strip() if title and str(title).strip() else "Без названия"
        items.append((topic_id, title))
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
    if MARKDOWN_SETTINGS["include_polls"] and msg.get("poll"):
        extras.append(_format_poll(msg.get("poll") or {}))
    if MARKDOWN_SETTINGS["include_reactions"] and msg.get("reactions"):
        extras.append(_format_reactions(msg.get("reactions") or []))

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

def message_to_export(message) -> dict:
    msg_type = "service" if message.action else "message"
    sender = None
    if message.sender:
        sender = get_display_name(message.sender)
    
    raw_text = getattr(message, "raw_text", None)
    msg_text = raw_text if raw_text is not None else message.message

    msg = {
        "id": message.id,
        "type": msg_type,
        "date": message.date.isoformat(),
        "from": sender,
        "from_id": message.sender_id,
        "text": normalize_text(msg_text),
    }

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
            height=38,
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
        
        # Center Box
        self.center_box = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=16, border_width=1, border_color=COLORS["border"])
        self.center_box.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.4, relheight=0.6)
        
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

        # Phone Input
        self.phone_entry = ModernEntry(self.center_box, placeholder_text="Телефон (+7...)")
        self.phone_entry.pack(padx=40, pady=(0, 10), fill="x")
        
        self.action_btn = ModernButton(self.center_box, text="Получить код", command=self._on_action)
        self.action_btn.pack(padx=40, pady=(10, 0), fill="x")

        # Code/Password Input (Initially hidden)
        self.code_entry = ModernEntry(self.center_box, placeholder_text="Код из Telegram")
        self.password_entry = ModernEntry(self.center_box, placeholder_text="Пароль 2FA (если есть)", show="•")
        
        self.state = "phone" # phone -> code -> ready

    def refresh_state(self):
        if self.app.has_api_creds():
            self.api_status_lbl.configure(text="API ключи настроены", text_color=COLORS["success"])
            self.settings_btn.pack_forget()
            self.phone_entry.configure(state="normal")
            self.action_btn.configure(state="normal")
        else:
            self.api_status_lbl.configure(text="Сначала укажите API ID/Hash", text_color=COLORS["error"])
            self.phone_entry.configure(state="disabled")
            self.action_btn.configure(state="disabled")
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


class ChatListView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.dialogs = []
        self.dialog_map = {}
        self._export_total = None
        self._folder_names = ["Все чаты"]
        self._folder_var = tk.StringVar(value="Все чаты")
        
        # Header / Toolbar
        self.toolbar = ctk.CTkFrame(self, fg_color="transparent", height=60)
        self.toolbar.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(
            self.toolbar, text="Чаты", font=(FONT_DISPLAY, 24, "bold"), text_color=COLORS["text"]
        ).pack(side="left")
        
        self.logout_btn = ModernButton(self.toolbar, text="Выход", variant="secondary", width=80, command=self.app.logout)
        self.logout_btn.pack(side="right", padx=(10, 0))
        
        self.refresh_btn = ModernButton(self.toolbar, text="Обновить", variant="secondary", width=110, command=self.app.load_chats)
        self.refresh_btn.pack(side="right")

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

        # Search
        self.search_entry = ModernEntry(self, placeholder_text="Поиск чатов...")
        self.search_entry.pack(fill="x", padx=20, pady=(0, 15))
        self.search_entry.bind("<KeyRelease>", self._on_search)

        # Status
        self.status_lbl = ctk.CTkLabel(self, text="", text_color=COLORS["text_sec"])
        self.status_lbl.pack(fill="x", padx=20, pady=(0, 8))

        # Export progress (top)
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent", width=360)
        self.progress_header = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        self.progress_header.pack(fill="x", padx=2, pady=(0, 6))
        self.progress_label = ctk.CTkLabel(self.progress_header, text="", text_color=COLORS["text_sec"])
        self.progress_label.pack(side="left", anchor="w")
        self.progress_chat_label = ctk.CTkLabel(self.progress_header, text="", text_color=COLORS["text_sec"])
        self.progress_chat_label.pack(side="right", anchor="e")
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=8, corner_radius=6, width=320)
        self.progress_bar.pack(anchor="w")
        self.progress_frame.pack(anchor="w", padx=20, pady=(0, 12))
        self.progress_frame.pack_forget()

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
        self.progress_frame.pack(anchor="w", padx=20, pady=(0, 12), before=self.list_container)
        self.progress_chat_label.configure(text=chat_name)
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

    def finish_export(self, ok: bool, message: str):
        try:
            self.progress_bar.stop()
        except Exception:
            pass
        self.progress_frame.pack_forget()
        self.progress_chat_label.configure(text="")
        self.progress_label.configure(text="")
        self.status_lbl.configure(text=message if ok else f"Ошибка: {message}")


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
        self.all_dialogs = []
        self.folder_peers = {}
        self.current_folder = "Все чаты"
        
        self._tg_queue = queue.Queue()
        self.queue = queue.Queue()
        
        # Views
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True)
        
        self.login_view = LoginView(self.container, self)
        self.chats_view = ChatListView(self.container, self)
        
        self.current_view = None
        self._load_config_file()
        
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

    def show_export_dialog(self, dialog):
        path = filedialog.askdirectory(title="Куда сохранить экспорт?")
        if not path: return
        self.chats_view.status_lbl.configure(text="")
        self._run_bg(self._export_task, dialog, path)

    # --- Logic ---

    def has_api_creds(self):
        return bool(self.api_creds.get("api_id") and self.api_creds.get("api_hash"))

    def _load_config_file(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    self.api_creds = json.load(f)
        except:
            pass

    def _load_config(self): return self.api_creds

    def save_config(self, api_id, api_hash):
        self.api_creds = {
            "api_id": api_id,
            "api_hash": api_hash,
            "session": self.api_creds.get("session"),
        }
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self.api_creds, f)
        self.login_view.refresh_state()

    def _get_client(self):
        self._ensure_event_loop()
        if not self.client:
            session_str = self.api_creds.get("session")
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
            folder_names = []
            for f in (filters or []):
                title = normalize_text(getattr(f, "title", None))
                include_peers = getattr(f, "include_peers", None)
                if not title or not include_peers:
                    continue
                peer_ids = set()
                for p in include_peers:
                    try:
                        peer_ids.add(get_peer_id(p))
                    except Exception:
                        continue
                if peer_ids:
                    folder_peers[title] = peer_ids
                    folder_names.append(title)
            self.folder_peers = folder_peers
            self.queue.put(("folders_loaded", folder_names))
        except Exception as e:
            self.queue.put(("error", str(e)))

    def filter_chats(self, query):
        dialogs = self.all_dialogs
        folder_name = self.current_folder
        if folder_name and folder_name != "Все чаты":
            peer_ids = self.folder_peers.get(folder_name, set())
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
        if not query:
            self.chats_view.render_chats(dialogs)
            return
        q = query.lower()
        res = [d for d in dialogs if q in (d.name or "").lower()]
        self.chats_view.render_chats(res)

    def set_current_folder(self, folder_name):
        self.current_folder = folder_name or "Все чаты"

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
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self.api_creds, f)
        self.queue.put(("logout_done", None))

    def _persist_session(self):
        try:
            c = self._get_client()
            session_str = c.session.save()
            if session_str:
                self.api_creds["session"] = session_str
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
                with open(self.config_path, "w") as f:
                    json.dump(self.api_creds, f)
        except Exception:
            pass

    def _export_task(self, dialog, path):
        try:
            c = self._get_client()
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            chat_title = sanitize_filename(dialog.name or "chat")
            if len(chat_title) > 60:
                chat_title = chat_title[:60].rstrip("_ ")
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
            md_words_per_file = MARKDOWN_SETTINGS["words_per_file"]
            md_current = ""
            md_word_count = 0
            md_next_index = 1
            md_pending_first: str | None = None
            md_written = 0
            topic_map: dict[str, str] = {}
            service_topic_by_id: dict[int, str] = {}
            has_topics = False

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

            total = None
            try:
                total_list = c.get_messages(dialog, limit=0)
                total = getattr(total_list, "total", None)
            except Exception:
                total = None
            self.queue.put(("export_start", (dialog.name or "Чат", total)))

            with open(full_path, "w", encoding="utf-8") as f:
                f.write('{\n  "name": ' + json.dumps(dialog.name, ensure_ascii=False) + ',\n  "messages": [\n')
                first = True
                count = 0
                for msg in c.iter_messages(dialog, reverse=True):
                    if not first: f.write(",\n")
                    first = False
                    msg_data = message_to_export(msg)
                    json.dump(msg_data, f, ensure_ascii=False)

                    if msg_data.get("type") != "message":
                        if msg_data.get("topic_title"):
                            has_topics = True
                            service_topic_id = msg_data.get("topic_id") or msg_data.get("id")
                            if service_topic_id is not None:
                                service_topic_id = str(service_topic_id)
                                topic_map[service_topic_id] = msg_data.get("topic_title") or ""
                                if isinstance(msg_data.get("id"), int):
                                    service_topic_by_id[msg_data["id"]] = msg_data.get("topic_title") or ""
                        count += 1
                        if total and count % 100 == 0:
                            self.queue.put(("export_progress", (count, total)))
                        elif not total and count % 200 == 0:
                            self.queue.put(("export_progress", (count, None)))
                        continue

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
                    rendered = f"{topic_comment}{formatted}" if topic_comment else formatted
                    msg_words = len(rendered.split()) if rendered else 0
                    if md_word_count + msg_words > md_words_per_file and md_current.strip():
                        add_md_chunk()
                    if rendered:
                        md_current += rendered + "\n\n"
                        md_word_count += msg_words

                    count += 1
                    if total and count % 100 == 0:
                        self.queue.put(("export_progress", (count, total)))
                    elif not total and count % 200 == 0:
                        self.queue.put(("export_progress", (count, None)))
                f.write('\n  ]\n}\n')

            add_md_chunk()
            topics_index = _build_topics_index(topic_map)
            if md_pending_first or topics_index:
                first_content = ""
                if topics_index:
                    first_content = topics_index
                if md_pending_first:
                    first_content = f"{first_content}\n\n{md_pending_first}".strip()
                if first_content:
                    write_md_chunk(1, first_content)

            if total:
                self.queue.put(("export_progress", (total, total)))
            done_msg = f"Готово: {export_dir}"
            if md_written:
                done_msg += f" (Markdown файлов: {md_written})"
            self.queue.put(("export_done", done_msg))
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
                elif kind == "chats_loaded": self.chats_view.render_chats(data)
                elif kind == "folders_loaded": self.chats_view.set_folders(data)
                elif kind == "export_start":
                    chat_name, total = data
                    self.chats_view.show_export_progress(chat_name, total)
                elif kind == "export_progress":
                    count, total = data
                    self.chats_view.update_export_progress(count, total)
                elif kind == "export_done":
                    self.chats_view.finish_export(True, data)
                elif kind == "export_error":
                    self.chats_view.finish_export(False, data)
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
