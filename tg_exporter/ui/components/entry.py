"""AppEntry — поле ввода с исправленной вставкой из буфера обмена."""

from __future__ import annotations
import sys
import tkinter as tk
import customtkinter as ctk
from ..theme import C, RADIUS, WIDGET, font


# keysym'ы клавиши V на разных раскладках (RU, UK и пр.).
_PASTE_KEYSYMS = {"v", "cyrillic_em"}
_COPY_KEYSYMS = {"c", "cyrillic_es"}
_CUT_KEYSYMS = {"x", "cyrillic_che"}
_SELECT_ALL_KEYSYMS = {"a", "cyrillic_ef"}


class AppEntry(ctk.CTkEntry):
    """
    Стандартное поле ввода с:
    - правильной поддержкой Cmd+V / Ctrl+V на macOS и Windows (включая RU раскладку)
    - контекстным меню (ПКМ) с «Вырезать/Копировать/Вставить»
    - унифицированным стилем из theme.py
    """

    def __init__(self, master, size: str = "md", **kwargs) -> None:
        h = WIDGET["entry_h"] if size == "md" else WIDGET["entry_h_sm"]
        fs = 13 if size == "md" else 12

        defaults = dict(
            corner_radius=RADIUS["md"],
            height=h,
            font=font(fs),
            fg_color=C["surface"],
            border_color=C["border"],
            border_width=1,
            text_color=C["text"],
        )
        defaults.update(kwargs)
        super().__init__(master, **defaults)
        self._bind_clipboard()
        self._bind_context_menu()

    def _bind_clipboard(self) -> None:
        # Биндинги на внутренний tk.Entry (_entry), потому что CTkEntry — это
        # фрейм-обёртка, и его собственные bind'ы до реального Entry не доходят.
        inner = self._entry

        # 1) Виртуальный <<Paste>> — стандартный Tk-paste (Ctrl+V на Win/Linux,
        #    Cmd+V на macOS, и пункт меню «Вставить»).
        inner.bind("<<Paste>>", self._paste)
        inner.bind("<<Copy>>", self._copy)
        inner.bind("<<Cut>>", self._cut)

        # 2) Прямые комбинации — на случай когда <<Paste>> не эмитится
        #    (например, PyInstaller-бандл на Windows с подставленным Tcl/Tk,
        #    русская раскладка где KeyPress даёт Cyrillic_em вместо V).
        inner.bind("<KeyPress>", self._on_keypress, add="+")

    def _on_keypress(self, event) -> str | None:
        # state: биты-флаги модификаторов. Control = 0x4, Command/Meta на macOS = 0x8/0x10.
        state = getattr(event, "state", 0) or 0
        keysym = (getattr(event, "keysym", "") or "").lower()

        is_ctrl = bool(state & 0x4)
        is_cmd = sys.platform == "darwin" and bool(state & (0x8 | 0x10))
        if not (is_ctrl or is_cmd):
            return None

        if keysym in _PASTE_KEYSYMS:
            return self._paste()
        if keysym in _COPY_KEYSYMS:
            return self._copy()
        if keysym in _CUT_KEYSYMS:
            return self._cut()
        if keysym in _SELECT_ALL_KEYSYMS:
            self._entry.select_range(0, tk.END)
            self._entry.icursor(tk.END)
            return "break"
        return None

    def _paste(self, _event=None) -> str:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            if self._entry.selection_present():
                self._entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        try:
            self._entry.insert(tk.INSERT, text)
        except tk.TclError:
            pass
        return "break"

    def _copy(self, _event=None) -> str:
        try:
            if self._entry.selection_present():
                text = self._entry.selection_get()
                self.clipboard_clear()
                self.clipboard_append(text)
        except tk.TclError:
            pass
        return "break"

    def _cut(self, _event=None) -> str:
        try:
            if self._entry.selection_present():
                text = self._entry.selection_get()
                self.clipboard_clear()
                self.clipboard_append(text)
                self._entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        return "break"

    def _bind_context_menu(self) -> None:
        menu = tk.Menu(self._entry, tearoff=0)
        menu.add_command(label="Вырезать", command=self._cut)
        menu.add_command(label="Копировать", command=self._copy)
        menu.add_command(label="Вставить", command=self._paste)
        menu.add_separator()
        menu.add_command(
            label="Выделить всё",
            command=lambda: (self._entry.select_range(0, tk.END), self._entry.icursor(tk.END)),
        )

        def _popup(event):
            try:
                self._entry.focus_set()
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        # ПКМ на Win/Linux = Button-3, на macOS = Button-2 + Control-Button-1.
        self._entry.bind("<Button-3>", _popup)
        self._entry.bind("<Button-2>", _popup)
        self._entry.bind("<Control-Button-1>", _popup)

    # ---- Public API ----

    def set_text(self, value: str) -> None:
        """Заменяет содержимое поля (публичная альтернатива доступу к _entry)."""
        self.delete(0, tk.END)
        if value:
            self.insert(0, value)

    def clear(self) -> None:
        self.delete(0, tk.END)

    def set_show(self, char: str) -> None:
        """Маскирует ввод (например '•' для паролей/ключей). '' = показывать."""
        try:
            self._entry.configure(show=char)
        except tk.TclError:
            pass
