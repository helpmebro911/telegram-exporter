"""AppButton — кнопка с вариантами: primary, secondary, ghost, danger."""

from __future__ import annotations
import customtkinter as ctk
from ..theme import C, RADIUS, WIDGET, font


class AppButton(ctk.CTkButton):
    """
    Стандартная кнопка приложения.

    variant:
        "primary"   — синяя, заливка
        "secondary" — серый фон, бордер
        "ghost"     — прозрачный фон, только текст
        "danger"    — красный фон
    """

    _STYLES: dict[str, dict] = {
        "primary": {
            "fg_color":    C["primary"],
            "hover_color": C["primary_h"],
            "text_color":  C["primary_text"],
            "border_width": 0,
        },
        "secondary": {
            "fg_color":    C["card"],
            "hover_color": C["card_hover"],
            "text_color":  C["text"],
            "border_width": 1,
            "border_color": C["border"],
        },
        "ghost": {
            "fg_color":    "transparent",
            "hover_color": C["card"],
            "text_color":  C["text_sec"],
            "border_width": 0,
        },
        "danger": {
            "fg_color":    C["error"],
            "hover_color": ("#DC2626", "#DC2626"),
            "text_color":  ("#FFFFFF", "#FFFFFF"),
            "border_width": 0,
        },
    }

    def __init__(
        self,
        master,
        variant: str = "primary",
        size: str = "md",  # "md" | "sm"
        **kwargs,
    ) -> None:
        style = dict(self._STYLES.get(variant, self._STYLES["primary"]))

        h = WIDGET["btn_h"] if size == "md" else WIDGET["btn_h_sm"]
        fs = 13 if size == "md" else 12
        bold = variant == "primary"

        style.setdefault("corner_radius", RADIUS["md"])
        style.setdefault("height", h)
        style.setdefault("font", font(fs, "bold" if bold else "normal"))

        # Позволяем вызывающему коду переопределить любой параметр
        style.update(kwargs)
        super().__init__(master, **style)

    def set_loading(self, loading: bool, loading_text: str = "...") -> None:
        """Переводит кнопку в состояние загрузки (disabled + текст)."""
        if loading:
            self._original_text = self.cget("text")
            self.configure(text=loading_text, state="disabled")
        else:
            self.configure(
                text=getattr(self, "_original_text", self.cget("text")),
                state="normal",
            )

    def set_idle_text(self, text: str) -> None:
        """
        Обновляет текст кнопки и "оригинальный" текст, на который она вернётся
        после set_loading(False). Публичная замена прямой записи _original_text.
        """
        self._original_text = text
        self.configure(text=text)
