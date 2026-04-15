"""
HelpModal — пользовательская инструкция по работе с приложением.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import customtkinter as ctk

from ..theme import C, SPACING, font, font_display
from ..components.button import AppButton
from ..modal_utils import prepare_modal, show_modal, setup_smooth_scroll

if TYPE_CHECKING:
    from ..app import App


_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "1. Авторизация",
        [
            ("API ключи",
             "При первом запуске нажмите «Настроить API ключи». Получите api_id и api_hash на "
             "https://my.telegram.org → API development tools. Введите их в окне настроек."),
            ("Вход",
             "Введите номер телефона в международном формате (например, +79991234567), "
             "получите код в Telegram, при необходимости введите 2FA-пароль."),
            ("Хранение секретов",
             "Все ключи и сессия сохраняются в системном Keyring (Связка ключей на macOS, "
             "Credential Manager на Windows). В файлах конфигурации секреты не хранятся."),
        ],
    ),
    (
        "2. Главный экран — список чатов",
        [
            ("Папка",
             "Выпадающий список ваших папок Telegram. Выберите «Все чаты» или конкретную папку — "
             "список ниже отфильтруется."),
            ("Период",
             "Период, за который брать сообщения: Неделя, Месяц, 3 месяца, Год, Всё время. "
             "Опция «Свой период» открывает поля для ввода дат вручную (формат ГГГГ-ММ-ДД, "
             "локальное время)."),
            ("Поиск",
             "Поле поиска фильтрует список чатов по имени в реальном времени."),
            ("Обновить",
             "Перезагружает список диалогов и папок из Telegram."),
        ],
    ),
    (
        "3. Экспорт одного чата",
        [
            ("Запуск",
             "Двойной клик по чату или выделить + кнопка «Экспортировать выбранный чат» внизу. "
             "Откроется окно экспорта с параметрами."),
            ("Формат",
             "JSON — машинно-читаемый формат, удобен для дальнейшей обработки. "
             "Markdown — человеко-читаемый, разбивается на части по количеству слов."),
            ("Медиа",
             "Включите чекбокс «Скачивать медиа» — фото, видео, документы будут сохранены "
             "в подпапки внутри директории экспорта."),
            ("Транскрипция",
             "Если включено, голосовые сообщения и видеокружки переводятся в текст. "
             "Провайдер выбирается в Настройках (локальный Whisper или облачный Deepgram). "
             "Лимит — 15 минут на сообщение."),
            ("Аналитика",
             "Дополнительно создаёт файлы top_authors.md (топ авторов) и activity.md "
             "(активность по датам)."),
            ("Фильтр по автору",
             "Опционально — экспортировать только сообщения от конкретного пользователя "
             "(по username или ID)."),
            ("Инкрементальный экспорт",
             "При повторном запуске экспортируются только новые сообщения с момента "
             "предыдущего экспорта (история хранится в ~/.tg_exporter/export_history.json)."),
        ],
    ),
    (
        "4. Экспорт целой папки",
        [
            ("Запуск",
             "На главном экране выберите папку и нажмите «Экспортировать папку». "
             "Все чаты из папки добавятся в очередь экспорта."),
            ("Режим",
             "По чатам — каждый чат в свою подпапку (как обычный экспорт). "
             "Один .md на чат — каждый чат в один Markdown без разбивки. "
             "Один .md на папку — все чаты в один общий Markdown-файл."),
            ("Транскрипция",
             "Чекбокс рядом с кнопкой включает транскрипцию для всех чатов папки."),
        ],
    ),
    (
        "5. Настройки приложения",
        [
            ("Транскрипция → Провайдер",
             "Локальный Whisper — работает офлайн, требует загрузки модели при первом "
             "использовании (от 75 МБ для tiny до 3 ГБ для large). "
             "Deepgram — облачный, требует API-ключ (получить на console.deepgram.com)."),
            ("Модель Whisper",
             "Tiny / Base — быстро, но ниже качество. Medium / Large — медленно, "
             "но высокое качество. Базовый выбор: Base — оптимальный баланс."),
            ("Язык",
             "«Авто» — определяется автоматически, медленнее. Указание конкретного языка "
             "ускоряет распознавание."),
            ("Экспорт по умолчанию",
             "Включать ли автора и временные метки в Markdown-файлы по умолчанию. "
             "Изменения применяются к новым экспортам."),
        ],
    ),
    (
        "6. Где находятся файлы",
        [
            ("Результат экспорта",
             "В выбранной вами папке создаётся подпапка вида «Имя чата_2026-04-15_18-30-00» "
             "со всеми файлами внутри."),
            ("Конфигурация и логи",
             "Папка ~/.tg_exporter/ — config.json (несекретные настройки), app.log (лог), "
             "export_history.json (история инкрементальных экспортов)."),
        ],
    ),
    (
        "7. Полезные советы",
        [
            ("Отмена экспорта",
             "Кнопка «Отмена» в окне экспорта останавливает процесс. Уже скачанные файлы "
             "и записанные сообщения сохраняются."),
            ("Большие чаты",
             "Для каналов с десятками тысяч сообщений рекомендуется указывать период "
             "(месяц/год) и использовать инкрементальный экспорт при повторных запусках."),
            ("Только одна сессия",
             "Параллельно запустить две копии приложения нельзя (используется один файл "
             "сессии). Закройте предыдущую копию перед запуском новой."),
        ],
    ),
]


class HelpModal(ctk.CTkToplevel):

    def __init__(self, app: "App") -> None:
        super().__init__(app)
        prepare_modal(self, app, 640, 640, "Инструкция")
        self._app = app
        self._build()
        show_modal(self, app)
        self.after(100, lambda: setup_smooth_scroll(self, self._scroll))

    def _build(self) -> None:
        pad = SPACING["2xl"]

        ctk.CTkLabel(
            self, text="Инструкция",
            font=font_display(20, "bold"), text_color=C["text"],
        ).pack(pady=(pad, SPACING["sm"]))

        ctk.CTkLabel(
            self, text="Краткое руководство по основным функциям приложения",
            font=font(12), text_color=C["text_sec"],
        ).pack(pady=(0, SPACING["md"]))

        self._scroll = ctk.CTkScrollableFrame(self, fg_color=C["bg"])
        self._scroll.pack(fill="both", expand=True, padx=pad)

        for title, items in _SECTIONS:
            self._section(self._scroll, title)
            for subtitle, body in items:
                self._item(self._scroll, subtitle, body)
            ctk.CTkFrame(self._scroll, height=1, fg_color=C["border"]).pack(
                fill="x", pady=(SPACING["sm"], SPACING["md"]),
            )

        AppButton(self, text="Закрыть", variant="primary", command=self.destroy).pack(
            fill="x", padx=pad, pady=(SPACING["sm"], pad),
        )

    def _section(self, parent, text: str) -> None:
        ctk.CTkLabel(
            parent, text=text,
            font=font(14, "bold"), text_color=C["text"], anchor="w",
        ).pack(fill="x", pady=(SPACING["md"], SPACING["xs"]))

    def _item(self, parent, subtitle: str, body: str) -> None:
        ctk.CTkLabel(
            parent, text=subtitle,
            font=font(12, "bold"), text_color=C["text"], anchor="w",
        ).pack(fill="x", pady=(SPACING["xs"], 0))
        ctk.CTkLabel(
            parent, text=body,
            font=font(12), text_color=C["text_sec"],
            anchor="w", justify="left", wraplength=540,
        ).pack(fill="x", pady=(0, SPACING["xs"]))

