"""
Общие утилиты для модальных окон:
- init_modal: правильное появление (без прыжка/мигания), фон, transient, фокус.
- setup_smooth_scroll: одинаковая скорость прокрутки колесом на всех платформах.
"""

from __future__ import annotations

import sys
from typing import Optional

from .theme import C


def prepare_modal(modal, parent, width: int, height: int, title: str) -> None:
    """
    ВЫЗЫВАТЬ ПЕРВЫМ ДЕЛОМ В __init__ модалки (сразу после super().__init__).

    - Прячет окно до построения UI (нет вспышки «CTkToplevel» в углу).
    - Сразу задаёт правильную геометрию и заголовок.
    - Заливает фон в цвет приложения (нет чёрной подложки).
    """
    modal.withdraw()  # ВАЖНО: до любых других вызовов — иначе видна вспышка.
    modal.title(title)
    modal.configure(fg_color=C["bg"])

    # Геометрия — задаём сразу, до отрисовки.
    parent.update_idletasks()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    pw = parent.winfo_width() or width
    ph = parent.winfo_height() or height
    x = px + max(0, (pw - width) // 2)
    y = py + max(0, (ph - height) // 2)
    modal.geometry(f"{width}x{height}+{x}+{y}")


def show_modal(modal, parent, resizable: tuple[bool, bool] = (False, False)) -> None:
    """
    ВЫЗЫВАТЬ В КОНЦЕ __init__ — после построения UI.

    - Делает окно видимым уже на правильной позиции и с готовым контентом.
    - Привязывает к родителю (не теряется за главным).
    - Включает grab + фокус.
    - Биндит «вспышку» при клике по заблокированному родителю.
    """
    modal.resizable(*resizable)
    try:
        modal.transient(parent)
    except Exception:
        pass
    modal.deiconify()
    modal.lift()
    modal.focus_force()
    modal.grab_set()
    _bind_parent_focus_hint(modal, parent)


def _bind_parent_focus_hint(modal, parent) -> None:
    """
    Когда пользователь кликает по заблокированному родителю — модалка
    мигает / лифтится, подсказывая «вот где взаимодействие».
    """
    flash_state = {"flashing": False}

    def _flash():
        if flash_state["flashing"] or not modal.winfo_exists():
            return
        flash_state["flashing"] = True
        try:
            modal.lift()
            modal.focus_force()
            # Кратковременная «вспышка» через bell + изменение alpha
            modal.bell()
            try:
                modal.attributes("-alpha", 0.7)
                modal.after(80, lambda: modal.winfo_exists() and modal.attributes("-alpha", 1.0))
            except Exception:
                pass
        finally:
            modal.after(200, lambda: flash_state.update(flashing=False))

    def _on_parent_click(_event):
        if modal.winfo_exists():
            _flash()

    # Биндим только на сам корневой Toplevel/Canvas, не на детей —
    # grab_set уже блокирует обычные виджеты.
    try:
        parent.bind("<Button-1>", _on_parent_click, add="+")

        def _cleanup(_e=None):
            try:
                parent.unbind("<Button-1>", _on_parent_click)  # noqa
            except Exception:
                pass

        modal.bind("<Destroy>", _cleanup, add="+")
    except Exception:
        pass


def setup_smooth_scroll(modal, scrollable_frame) -> None:
    """
    Адекватная скорость колеса мыши на всех ОС.
    На macOS event.delta = ±1..±5 (мелкие тики),
    на Win/Linux — ±120 кратно.
    """
    try:
        canvas = scrollable_frame._parent_canvas
    except AttributeError:
        return

    def _scroll_fn(event):
        if sys.platform == "darwin":
            # macOS: event.delta = ±1..±5; домножаем на 3 для комфортной скорости.
            step = -3 if event.delta > 0 else 3
        else:
            # Win/Linux: event.delta кратен 120; 3 строки за один «щелчок».
            step = -3 * (1 if event.delta > 0 else -1)
        if step:
            canvas.yview_scroll(step, "units")

    def _on_enter(_):
        modal.bind_all("<MouseWheel>", _scroll_fn)

    def _on_leave(_):
        modal.unbind_all("<MouseWheel>")

    scrollable_frame.bind("<Enter>", _on_enter, add="+")
    scrollable_frame.bind("<Leave>", _on_leave, add="+")
    _bind_to_children(scrollable_frame, _on_enter, _on_leave)


def _bind_to_children(widget, on_enter, on_leave) -> None:
    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")
    for child in widget.winfo_children():
        _bind_to_children(child, on_enter, on_leave)
