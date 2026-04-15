"""
ChatListView — основной экран: список чатов, фильтры, поиск.

Опции экспорта вынесены в ExportModal (открывается по кнопке).
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Optional
import tkinter as tk
import customtkinter as ctk

from ..theme import C, RADIUS, SPACING, WIDGET, font, font_display
from ..components.button import AppButton
from ..components.entry import AppEntry

if TYPE_CHECKING:
    from ..app import App


_PERIOD_OPTIONS = ["Все время", "Неделя", "Месяц", "3 месяца", "Год", "Свой период"]
_PERIOD_DAYS: dict[str, int] = {
    "Все время": 0, "Неделя": 7, "Месяц": 30, "3 месяца": 90, "Год": 365
}


class ChatListView(ctk.CTkFrame):
    """
    Главный экран после логина.

    Layout:
        [Header]     Telegram Exporter | Обновить | Выход
        [Toolbar]    Папка ▾  |  Период ▾  |  Экспортировать папку
        [DateRange]  (видима только при "Свой период")
        [Search]     🔍 Поиск чатов...
        [Status]     Чатов: 42
        [List]       Прокручиваемый список
        [Export]     Экспортировать выбранный чат
    """

    def __init__(self, master, app: "App") -> None:
        super().__init__(master, fg_color="transparent")
        self._app = app
        self._dialogs: list = []
        self._dialog_map: dict[int, object] = {}
        self._folder_names: list[str] = ["Все чаты"]
        self._folder_var = tk.StringVar(value="Все чаты")
        self._period_var = tk.StringVar(value="Все время")
        self._date_from_var = tk.StringVar()
        self._date_to_var = tk.StringVar()
        self._build()

    # ---- Build ----

    def _build(self) -> None:
        # === HEADER ===
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=SPACING["xl"], pady=(SPACING["lg"], SPACING["md"]))

        ctk.CTkLabel(
            header, text="Telegram Exporter",
            font=font_display(22, "bold"), text_color=C["text"],
        ).pack(side="left")

        AppButton(header, text="Инструкция", variant="ghost", size="sm",
                  command=self._app.show_help).pack(side="left", padx=(SPACING["md"], 0))

        AppButton(header, text="Выход", variant="ghost", size="sm",
                  command=self._app.logout).pack(side="right")
        AppButton(header, text="Настройки", variant="ghost", size="sm",
                  command=self._app.show_settings).pack(side="right", padx=(0, SPACING["sm"]))
        AppButton(header, text="Обновить", variant="secondary", size="sm",
                  command=self._app.load_chats).pack(side="right", padx=(0, SPACING["sm"]))

        # Переключатель аккаунтов — слева от «Обновить»
        self._account_btn = AppButton(
            header, text="Аккаунт ▾", variant="ghost", size="sm",
            command=self._show_account_menu,
        )
        self._account_btn.pack(side="right", padx=(0, SPACING["sm"]))

        # === TOOLBAR (одна строка, на всю ширину; минимальная высота) ===
        _toolbar_h = WIDGET["entry_h_sm"] + SPACING["sm"] * 2  # 30 + 8 = 38
        toolbar = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=RADIUS["lg"],
                               height=_toolbar_h)
        toolbar.pack_propagate(False)
        toolbar.pack(fill="x", padx=SPACING["xl"], pady=(0, SPACING["xs"]))

        _py = SPACING["xs"]

        # Папка
        ctk.CTkLabel(toolbar, text="Папка", font=font(12), text_color=C["text_sec"]).pack(
            side="left", padx=(SPACING["md"], SPACING["xs"]), pady=_py
        )
        self._folder_menu = ctk.CTkOptionMenu(
            toolbar,
            values=self._folder_names,
            variable=self._folder_var,
            command=self._on_folder_change,
            width=160, height=WIDGET["entry_h_sm"],
            font=font(12),
        )
        self._folder_menu.pack(side="left", pady=_py)

        # Разделитель
        ctk.CTkFrame(toolbar, width=1, fg_color=C["border"]).pack(
            side="left", fill="y", padx=SPACING["sm"], pady=SPACING["xs"]
        )

        # Период
        ctk.CTkLabel(toolbar, text="Период", font=font(12), text_color=C["text_sec"]).pack(
            side="left", padx=(0, SPACING["xs"]), pady=_py
        )
        ctk.CTkOptionMenu(
            toolbar,
            values=_PERIOD_OPTIONS,
            variable=self._period_var,
            command=self._on_period_change,
            width=120, height=WIDGET["entry_h_sm"],
            font=font(12),
        ).pack(side="left", pady=_py)

        # Разделитель перед действием
        ctk.CTkFrame(toolbar, width=1, fg_color=C["border"]).pack(
            side="left", fill="y", padx=SPACING["sm"], pady=SPACING["xs"]
        )

        # Кнопка экспорта папки
        AppButton(toolbar, text="Экспортировать папку", variant="secondary", size="sm",
                  command=self._export_folder).pack(side="left", pady=_py)

        # Режим
        self._folder_mode_var = tk.StringVar(value="По чатам")
        ctk.CTkOptionMenu(
            toolbar,
            values=["По чатам", "Один .md на чат", "Один .md на папку"],
            variable=self._folder_mode_var,
            width=150, height=WIDGET["entry_h_sm"],
            font=font(12),
        ).pack(side="left", padx=(SPACING["sm"], 0), pady=_py)

        # Транскрипция
        self._folder_transcribe_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            toolbar,
            text="Транскрипция",
            variable=self._folder_transcribe_var,
            font=font(12),
            text_color=C["text_sec"],
            checkbox_width=16, checkbox_height=16,
            corner_radius=4,
        ).pack(side="left", padx=(SPACING["sm"], SPACING["md"]), pady=_py)

        # === КАСТОМНЫЙ ДИАПАЗОН ДАТ ===
        self._date_range_row = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self._date_range_row, text="От", text_color=C["text_sec"], font=font(12)).pack(side="left", padx=(SPACING["xl"], SPACING["xs"]))
        AppEntry(self._date_range_row, placeholder_text="ГГГГ-ММ-ДД", width=130, size="sm",
                 textvariable=self._date_from_var).pack(side="left")
        ctk.CTkLabel(self._date_range_row, text="До", text_color=C["text_sec"], font=font(12)).pack(side="left", padx=(SPACING["md"], SPACING["xs"]))
        AppEntry(self._date_range_row, placeholder_text="ГГГГ-ММ-ДД", width=130, size="sm",
                 textvariable=self._date_to_var).pack(side="left")
        ctk.CTkLabel(self._date_range_row, text="Локальное время (напр. 2025-01-15)", text_color=C["text_dim"], font=font(11)).pack(side="left", padx=(SPACING["sm"], 0))
        for e in [self._date_range_row.winfo_children()[1], self._date_range_row.winfo_children()[3]]:
            e.bind("<FocusOut>", self._apply_custom_dates)
            e.bind("<Return>", self._apply_custom_dates)
        # скрыта по умолчанию

        # === ПОИСК ===
        self._search_entry = AppEntry(self, placeholder_text="🔍  Поиск чатов...")
        self._search_entry.pack(fill="x", padx=SPACING["xl"], pady=(SPACING["md"], SPACING["xs"]))
        self._search_entry.bind("<KeyRelease>", self._on_search)

        # === СТАТУС ===
        self._status_lbl = ctk.CTkLabel(
            self, text="", font=font(12), text_color=C["text_sec"], anchor="w",
        )
        self._status_lbl.pack(fill="x", padx=SPACING["xl"] + SPACING["xs"], pady=(0, SPACING["xs"]))

        # === СПИСОК ЧАТОВ ===
        list_frame = ctk.CTkFrame(self, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=SPACING["md"], pady=(0, SPACING["xs"]))

        self._listbox = tk.Listbox(
            list_frame,
            activestyle="none",
            selectmode=tk.SINGLE,
            borderwidth=0,
            highlightthickness=1,
            relief="flat",
            font=(font(14)[0], 14),
            bg=self._ctk_color(C["card"]),
            fg=self._ctk_color(C["text"]),
            selectbackground=self._ctk_color(C["primary"]),
            selectforeground="#FFFFFF",
            highlightbackground=self._ctk_color(C["border"]),
            highlightcolor=self._ctk_color(C["border"]),
            cursor="hand2",
        )
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=scrollbar.set)
        self._listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._listbox.bind("<Double-Button-1>", self._on_double_click)
        self._listbox.bind("<Return>", self._on_double_click)

        # === КНОПКА ЭКСПОРТА ===
        self._export_btn = AppButton(
            self, text="Экспортировать выбранный чат", variant="primary",
            command=self._export_selected,
        )
        self._export_btn.pack(fill="x", padx=SPACING["xl"], pady=(0, SPACING["lg"]))

    # ---- Public API ----

    def show_loading(self, text: str = "Загрузка чатов...") -> None:
        self._status_lbl.configure(text=text)
        self._listbox.delete(0, tk.END)

    def render_chats(self, dialogs: list) -> None:
        self.refresh_account_switcher()
        self._dialogs = dialogs or []
        self._dialog_map = {}
        self._listbox.delete(0, tk.END)
        if not self._dialogs:
            self._status_lbl.configure(text="Ничего не найдено")
            return
        for i, d in enumerate(self._dialogs):
            self._listbox.insert(tk.END, f"  {d.name or 'Без названия'}")
            self._dialog_map[i] = d
        self._status_lbl.configure(text=f"Чатов: {len(self._dialogs)}")

    def set_folders(self, folder_names: list[str]) -> None:
        self._folder_names = ["Все чаты"] + (folder_names or [])
        self._folder_menu.configure(values=self._folder_names)
        if self._folder_var.get() not in self._folder_names:
            self._folder_var.set("Все чаты")

    def set_status(self, text: str) -> None:
        self._status_lbl.configure(text=text)

    def refresh_account_switcher(self) -> None:
        """Обновляет подпись кнопки-переключателя под активный профиль."""
        active = self._app.active_profile()
        if active is None:
            label = "Аккаунт ▾"
        else:
            name = (active.display_name or active.phone or "").strip() or "Аккаунт"
            if len(name) > 18:
                name = name[:17] + "…"
            label = f"{name} ▾"
        try:
            self._account_btn.set_idle_text(label)
        except Exception:
            pass

    def _show_account_menu(self) -> None:
        """Открывает popup-меню со списком профилей и действиями."""
        profiles = self._app.profiles()
        active = self._app.active_profile()
        active_phone = active.phone if active else None

        menu = tk.Menu(self, tearoff=0)
        if profiles:
            for p in profiles:
                title = (p.display_name or p.phone or "").strip() or p.phone
                prefix = "● " if p.phone == active_phone else "   "
                menu.add_command(
                    label=f"{prefix}{title}   {p.phone}",
                    command=lambda phone=p.phone: self._on_switch_profile(phone),
                )
            menu.add_separator()
        menu.add_command(label="+ Добавить аккаунт", command=self._app.show_add_account)
        if active is not None:
            menu.add_command(
                label=f"Удалить «{active.display_name or active.phone}»",
                command=lambda: self._on_remove_profile(active.phone),
            )
        try:
            x = self._account_btn.winfo_rootx()
            y = self._account_btn.winfo_rooty() + self._account_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _on_switch_profile(self, phone: str) -> None:
        active = self._app.active_profile()
        if active and active.phone == phone:
            return
        self._app.switch_profile(phone)

    def _on_remove_profile(self, phone: str) -> None:
        import tkinter.messagebox as mb
        if not mb.askyesno("Удалить аккаунт", f"Удалить профиль {phone} и его сессию?"):
            return
        self._app.remove_profile(phone)
        self.refresh_account_switcher()

    def selected_dialog(self) -> Optional[object]:
        sel = self._listbox.curselection()
        if not sel:
            return None
        return self._dialog_map.get(sel[0])

    # ---- Handlers ----

    def _on_search(self, _event=None) -> None:
        self._app.filter_chats(self._search_entry.get().strip())

    def _on_folder_change(self, value: str) -> None:
        self._app.set_current_folder(value)
        self._app.filter_chats(self._search_entry.get().strip())

    def _on_period_change(self, value: str) -> None:
        if value == "Свой период":
            if not self._date_range_row.winfo_ismapped():
                self._date_range_row.pack(fill="x", pady=(0, SPACING["xs"]), after=self._folder_menu.master)
            self._app.set_date_period(0)
        else:
            if self._date_range_row.winfo_ismapped():
                self._date_range_row.pack_forget()
            self._app.set_custom_date_range(None, None)
            self._app.set_date_period(_PERIOD_DAYS.get(value, 0))

    def _apply_custom_dates(self, *_args) -> None:
        date_from = _parse_date(self._date_from_var.get())
        date_to = _parse_date(self._date_to_var.get())
        self._app.set_custom_date_range(date_from, date_to)

    def _export_selected(self) -> None:
        dialog = self.selected_dialog()
        if dialog is None:
            self._status_lbl.configure(text="Выберите чат из списка")
            return
        self._app.show_export_dialog(dialog)

    def _on_double_click(self, _event=None) -> None:
        self._export_selected()

    def _export_folder(self) -> None:
        self._app.export_current_folder(
            mode=self._folder_mode_var.get(),
            transcribe=self._folder_transcribe_var.get(),
        )

    # ---- Helpers ----

    def _ctk_color(self, pair) -> str:
        """Возвращает строку цвета для нативного tk.Listbox."""
        import customtkinter as ctk
        return pair[0] if ctk.get_appearance_mode() == "Light" else pair[1]


def _parse_date(raw: str) -> Optional[datetime.datetime]:
    """
    Парсит пользовательскую дату в локальном времени и возвращает aware-UTC.

    Naive-даты ("2025-01-15" или "2025-01-15 10:00") интерпретируются в локальной
    таймзоне пользователя и конвертируются в UTC через astimezone. Если вводят
    дату с явным offset (+03:00 / Z) — она уже aware, её не трогаем в смысле
    временной метки, только приводим к UTC.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # локальная таймзона хоста
    return dt.astimezone(datetime.timezone.utc)
