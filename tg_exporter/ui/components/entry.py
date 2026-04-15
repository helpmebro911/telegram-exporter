"""AppEntry — поле ввода с исправленной вставкой из буфера обмена."""

from __future__ import annotations
import tkinter as tk
import customtkinter as ctk
from ..theme import C, RADIUS, WIDGET, font


class AppEntry(ctk.CTkEntry):
    """
    Стандартное поле ввода с:
    - правильной поддержкой Cmd+V / Ctrl+V на macOS и Windows
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

    def _bind_clipboard(self) -> None:
        # Биндинги нужно ставить на внутренний tk.Entry (_entry), а не на CTkEntry-обёртку.
        # CTkEntry перехватывает события сам и до нас они не доходят.
        inner = self._entry

        inner.bind("<<Paste>>", self._paste)
        for seq in ("<Command-v>", "<Command-V>", "<Control-v>", "<Control-V>"):
            inner.bind(seq, self._paste)
        # Русская раскладка: физическая клавиша V даёт keysym Cyrillic_em (м)
        inner.bind("<Command-KeyPress>", self._on_modifier_key)
        inner.bind("<Control-KeyPress>", self._on_modifier_key)

    def _on_modifier_key(self, event) -> str | None:
        keysym = getattr(event, "keysym", "")
        if keysym.lower() in ("v", "cyrillic_em"):
            return self._paste()
        return None

    def _paste(self, _event=None) -> str:
        try:
            text = self.clipboard_get()
            try:
                if self._entry.selection_present():
                    self._entry.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            self._entry.insert(tk.INSERT, text)
        except Exception:
            pass
        return "break"

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
