"""
SettingsModal — настройки приложения (транскрипция, экспорт).
"""

from __future__ import annotations

import webbrowser
from typing import TYPE_CHECKING
import customtkinter as ctk

from ..theme import C, SPACING, WIDGET, font, font_display
from ..components.button import AppButton
from ..components.entry import AppEntry
from ..modal_utils import prepare_modal, show_modal, setup_smooth_scroll

if TYPE_CHECKING:
    from ..app import App

_PROVIDER_LABELS = {
    "local":    "Локальный Whisper",
    "deepgram": "Deepgram (облако)",
}

_LANG_LABELS = {
    "multi": "Авто (несколько языков)",
    "ru":    "Русский",
    "en":    "Английский",
    "de":    "Немецкий",
    "fr":    "Французский",
    "es":    "Испанский",
    "zh":    "Китайский",
    "ja":    "Японский",
}

_MODEL_LABELS = {
    "tiny":   "Tiny (быстро, ниже качество)",
    "base":   "Base (баланс)",
    "small":  "Small",
    "medium": "Medium",
    "large":  "Large (медленно, высокое качество)",
}



class SettingsModal(ctk.CTkToplevel):

    def __init__(self, app: "App") -> None:
        super().__init__(app)
        prepare_modal(self, app, 500, 540, "Настройки")
        self._app = app
        self._build()
        self._load()
        show_modal(self, app)
        self.after(100, lambda: setup_smooth_scroll(self, self._scroll))

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        pad = SPACING["2xl"]

        ctk.CTkLabel(
            self, text="Настройки",
            font=font_display(18, "bold"), text_color=C["text"],
        ).pack(pady=(pad, SPACING["lg"]))

        self._scroll = ctk.CTkScrollableFrame(self, fg_color=C["bg"])
        self._scroll.pack(fill="both", expand=True, padx=pad)
        s = self._scroll

        # ── Транскрипция ──────────────────────────────────────────────────
        self._section(s, "Транскрипция голосовых и видеокружков")

        self._row_label(s, "Провайдер")
        self._provider_var = ctk.StringVar(value="local")
        self._provider_menu = ctk.CTkOptionMenu(
            s,
            values=list(_PROVIDER_LABELS.values()),
            command=self._on_provider_change,
            height=WIDGET["entry_h_sm"], font=font(13),
        )
        self._provider_menu.pack(fill="x", pady=(SPACING["xs"], SPACING["sm"]))

        # Единый контейнер — внутри показываем либо Whisper, либо Deepgram блок
        self._provider_options = ctk.CTkFrame(s, fg_color="transparent")
        self._provider_options.pack(fill="x")

        # Блок Whisper модели
        self._model_block = ctk.CTkFrame(self._provider_options, fg_color="transparent")
        self._row_label(self._model_block, "Модель Whisper")
        self._model_var = ctk.StringVar(value="base")
        self._model_menu = ctk.CTkOptionMenu(
            self._model_block,
            values=list(_MODEL_LABELS.values()),
            command=self._on_model_change,
            height=WIDGET["entry_h_sm"], font=font(13),
        )
        self._model_menu.pack(fill="x", pady=(SPACING["xs"], SPACING["sm"]))
        self._model_block.pack(fill="x")  # показан по умолчанию

        # Блок Deepgram ключа
        self._deepgram_block = ctk.CTkFrame(self._provider_options, fg_color="transparent")
        self._row_label(self._deepgram_block, "Deepgram API Key")
        self._deepgram_entry = AppEntry(
            self._deepgram_block, placeholder_text="Вставьте ключ", show="•", size="sm",
        )
        self._deepgram_entry.pack(fill="x", pady=(SPACING["xs"], 0))
        dg_link = ctk.CTkLabel(
            self._deepgram_block, text="🔗 console.deepgram.com",
            font=font(11), text_color=C["primary"], cursor="hand2",
        )
        dg_link.pack(anchor="w", pady=(2, SPACING["sm"]))
        dg_link.bind("<Button-1>", lambda _: webbrowser.open("https://console.deepgram.com/"))

        # Язык
        self._row_label(s, "Язык распознавания")
        self._lang_var = ctk.StringVar(value="multi")
        self._lang_menu = ctk.CTkOptionMenu(
            s,
            values=list(_LANG_LABELS.values()),
            command=self._on_lang_change,
            height=WIDGET["entry_h_sm"], font=font(13),
        )
        self._lang_menu.pack(fill="x", pady=(SPACING["xs"], SPACING["lg"]))

        # ── Разделитель ───────────────────────────────────────────────────
        ctk.CTkFrame(s, height=1, fg_color=C["border"]).pack(fill="x", pady=(0, SPACING["md"]))

        # ── Экспорт ───────────────────────────────────────────────────────
        self._section(s, "Экспорт по умолчанию")

        self._row_label(s, "Включать автора сообщения")
        self._include_author_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            s, text="", variable=self._include_author_var,
            onvalue=True, offvalue=False,
        ).pack(anchor="w", pady=(SPACING["xs"], SPACING["sm"]))

        self._row_label(s, "Включать временные метки")
        self._include_ts_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            s, text="", variable=self._include_ts_var,
            onvalue=True, offvalue=False,
        ).pack(anchor="w", pady=(SPACING["xs"], SPACING["sm"]))

        # ── Кнопки ───────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=pad, pady=(SPACING["md"], pad))
        AppButton(btn_row, text="Отмена", variant="secondary", command=self.destroy).pack(
            side="left", expand=True, fill="x", padx=(0, SPACING["sm"]),
        )
        AppButton(btn_row, text="Сохранить", variant="primary", command=self._save).pack(
            side="left", expand=True, fill="x",
        )

    # ------------------------------------------------------------------ helpers

    def _section(self, parent, text: str) -> None:
        ctk.CTkLabel(
            parent, text=text,
            font=font(13, "bold"), text_color=C["text"], anchor="w",
        ).pack(fill="x", pady=(0, SPACING["xs"]))

    def _row_label(self, parent, text: str) -> None:
        ctk.CTkLabel(
            parent, text=text,
            font=font(12), text_color=C["text_sec"], anchor="w",
        ).pack(fill="x")

    def _on_provider_change(self, display_val: str) -> None:
        key = next((k for k, v in _PROVIDER_LABELS.items() if v == display_val), "local")
        self._provider_var.set(key)
        self._model_block.pack_forget()
        self._deepgram_block.pack_forget()
        if key == "deepgram":
            self._deepgram_block.pack(fill="x", in_=self._provider_options)
        else:
            self._model_block.pack(fill="x", in_=self._provider_options)

    def _on_model_change(self, display_val: str) -> None:
        key = next((k for k, v in _MODEL_LABELS.items() if v == display_val), "base")
        self._model_var.set(key)

    def _on_lang_change(self, display_val: str) -> None:
        key = next((k for k, v in _LANG_LABELS.items() if v == display_val), "multi")
        self._lang_var.set(key)

    # ------------------------------------------------------------------ load/save

    def _load(self) -> None:
        cfg = self._app.config

        provider = cfg.transcription_provider
        self._provider_var.set(provider)
        self._provider_menu.set(_PROVIDER_LABELS.get(provider, _PROVIDER_LABELS["local"]))

        if provider == "deepgram":
            self._model_block.pack_forget()
            self._deepgram_block.pack(fill="x", in_=self._provider_options)
            dg_key = self._app.credentials.load_deepgram_key() or ""
            if dg_key:
                self._deepgram_entry.set_text(dg_key)
        else:
            self._deepgram_block.pack_forget()

        model = cfg.local_whisper_model
        self._model_var.set(model)
        self._model_menu.set(_MODEL_LABELS.get(model, _MODEL_LABELS["base"]))

        lang = cfg.transcription_language
        self._lang_var.set(lang)
        self._lang_menu.set(_LANG_LABELS.get(lang, _LANG_LABELS["multi"]))

        md_cfg = cfg.markdown
        self._include_author_var.set(getattr(md_cfg, "include_author", True))
        self._include_ts_var.set(getattr(md_cfg, "include_timestamps", True))

    def _save(self) -> None:
        import dataclasses
        cfg = self._app.config

        provider = self._provider_var.get()
        self._app.set_transcription_provider(provider)
        self._app.set_local_whisper_model(self._model_var.get())

        if provider == "deepgram":
            dg_key = self._deepgram_entry.get().strip()
            if dg_key:
                self._app.credentials.save_deepgram_key(dg_key)

        lang = self._lang_var.get()
        md_cfg = dataclasses.replace(
            cfg.markdown,
            include_author=self._include_author_var.get(),
            include_timestamps=self._include_ts_var.get(),
        )
        new_cfg = dataclasses.replace(cfg, transcription_language=lang, markdown=md_cfg)
        self._app.config = new_cfg
        new_cfg.save()
        self.destroy()
