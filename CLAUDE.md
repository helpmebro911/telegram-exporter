# CLAUDE.md — Telegram Exporter

> **🔴 ГЛАВНОЕ ПРАВИЛО**
>
> **Любое изменение, вносимое в проект (любым агентом или человеком с участием Claude), должно немедленно фиксироваться в этом файле** — в разделе [Журнал изменений](#журнал-изменений) внизу документа.
>
> Если изменение затрагивает архитектуру, модули, контракты или зависимости — **также обязательно обновить соответствующий раздел** этого документа (модуль, диаграмму потоков, таблицу контрактов и т.д.), чтобы CLAUDE.md всегда отражал актуальное состояние кода.
>
> Порядок работы для Claude:
> 1. Внести изменение в код.
> 2. Обновить профильный раздел CLAUDE.md (если структура затронута).
> 3. Добавить запись в «Журнал изменений» (дата, файлы, суть).
> 4. Только после этого считать задачу завершённой.

---

## 1. Обзор проекта

**Telegram Exporter** — десктопное приложение (Tk/CustomTkinter) на Python для экспорта истории сообщений из Telegram-каналов и чатов в форматы **JSON** и **Markdown** с дополнительными функциями:

- Локальная транскрипция голосовых сообщений и видео-кружков (Whisper / Silero / Parakeet) и облачная (Deepgram).
- Скачивание медиа (фото, видео, аудио, документы) в структурированные папки.
- Фильтрация по дате, папкам Telegram, авторам.
- Аналитика (топ авторов, активность по датам).
- Инкрементальный экспорт (только новые сообщения с момента последнего запуска).
- Безопасное хранение секретов (`api_hash`, `session`, Deepgram key) в системном Keyring.

Точка входа: `main.py` → `tg_exporter.ui.app.App`.

- **Платформы:** macOS (Intel + Apple Silicon, `.dmg`), Windows (`.exe` через Inno Setup).
- **Python:** 3.11 (зафиксировано в GitHub Actions).
- **Лицензия:** MIT.

---

## 2. Структура репозитория

```
Парсер тг/
├── main.py                         # Точка входа приложения
├── requirements.txt                # Зависимости рантайма
├── Telegram Exporter.spec          # PyInstaller spec (сборка macOS/Win)
├── README.md                       # Пользовательская документация
├── LICENSE
├── CLAUDE.md                       # ← этот файл
│
├── tg_exporter/                    # Основной пакет приложения
│   ├── __init__.py
│   ├── core/                       # Доменное ядро (Telegram, auth, оркестрация)
│   │   ├── client.py               # TelegramClientManager
│   │   ├── auth.py                 # AuthService (login flow)
│   │   ├── credentials.py          # CredentialsManager (Keyring)
│   │   ├── converter.py            # Telethon Message → ExportMessage
│   │   └── orchestrator.py         # ExportOrchestrator (основной цикл экспорта)
│   │
│   ├── models/                     # Чистые dataclass-модели (без зависимостей от внешних API)
│   │   ├── config.py               # AppConfig, MarkdownSettings (+ валидация)
│   │   ├── export_task.py          # ExportTask, ExportProgress, AuthorFilter
│   │   └── message.py              # ExportMessage, MediaType, ReactionItem, PollData, LinkItem
│   │
│   ├── exporters/                  # Форматы вывода
│   │   ├── base.py                 # BaseExporter (контракт open/write/finalize) + sanitize_filename
│   │   ├── json_exporter.py        # Потоковая запись result.json
│   │   └── markdown_exporter.py    # MD с разбивкой по словам, топики форумов, «популярные»
│   │
│   ├── services/                   # Прикладные сервисы
│   │   ├── analytics.py            # AnalyticsCollector + render_top_authors/render_activity
│   │   ├── media_downloader.py     # MediaDownloader, MediaDirs, AudioPrepResult
│   │   ├── export_history.py       # ExportHistory (инкрементальные last_id)
│   │   └── transcription/
│   │       ├── base.py             # BaseTranscriber, TranscriptionError
│   │       ├── factory.py          # create_transcriber(config, key)
│   │       ├── whisper_local.py    # faster-whisper
│   │       ├── silero.py           # Silero STT
│   │       ├── parakeet.py         # NVIDIA Parakeet
│   │       └── deepgram.py         # Deepgram API
│   │
│   ├── ui/                         # UI-слой (customtkinter)
│   │   ├── app.py                  # App (главное окно, контроллер)
│   │   ├── theme.py                # Цвета/шрифты/отступы — единая дизайн-система
│   │   ├── components/             # Переиспользуемые виджеты
│   │   │   ├── button.py           # AppButton
│   │   │   ├── entry.py            # AppEntry
│   │   │   └── progress_bar.py     # ExportProgressWidget
│   │   └── views/                  # Экраны
│   │       ├── login_view.py       # Авторизация (phone → code → 2FA)
│   │       ├── chat_list_view.py   # Список чатов + фильтры
│   │       ├── export_modal.py     # Настройки экспорта + прогресс
│   │       └── settings_modal.py   # Глобальные настройки (транскрипция)
│   │
│   └── utils/                      # Инфраструктурные утилиты
│       ├── worker.py               # BackgroundWorker + EventDispatcher (фоновый поток + UI-очередь)
│       ├── cancellation.py         # CancellationToken + CancelledError
│       └── logger.py               # AppLogger с redact() секретов
│
├── tests/                          # Unit-тесты (unittest)
│   ├── test_models.py
│   ├── test_services.py
│   └── test_exporters.py
│
├── scripts/                        # Скрипты сборки
│   ├── build_mac.sh                # Сборка .dmg (universal/arm64/intel по GH matrix)
│   ├── build_mac_intel.sh
│   ├── build_win.ps1
│   ├── build_win_installer.ps1
│   └── make_icons.py
│
├── installer/
│   └── TelegramExporter.iss        # Inno Setup installer config (Windows)
│
├── assets/
│   └── app_icon.png                # Исходная иконка (1024×1024)
│
├── icons/
│   └── app.icns                    # Сгенерированная macOS-иконка
│
└── .github/workflows/
    └── build_release.yml           # CI: DMG (macos-13, macos-14) + EXE (windows-latest)
```

---

## 3. Архитектурные принципы

1. **Слои с односторонней зависимостью** (сверху вниз):
   ```
   UI  →  App (контроллер)  →  core/orchestrator  →  services + exporters  →  models
                                    ↓
                             core/client, core/auth, core/credentials  →  models
   ```
   - `models/` **ни от чего не зависят** (чистые dataclass).
   - `exporters/` и `services/` работают только с `ExportMessage` — не видят Telethon.
   - Единственный модуль, знающий Telethon, — `core/converter.py` и `core/client.py`.

2. **UI отделён от бизнес-логики.** `App` — тонкий контроллер, делегирующий:
   - Аутентификацию → `AuthService`.
   - Экспорт → `ExportOrchestrator`.
   - Секреты → `CredentialsManager`.
   - Асинхронщину → `BackgroundWorker` + `EventDispatcher`.

3. **Фоновый поток + очередь событий.** Tkinter-цикл не блокируется:
   - `BackgroundWorker` (daemon thread) выполняет задачи из `task_queue`.
   - Прогресс и результаты отправляются в `ui_queue` как `UIEvent = (event_type, payload)`.
   - `App._poll()` вызывается каждые **80 мс** через `self.after(80, self._poll)` и диспетчеризует события через `EventDispatcher`.

4. **Кооперативная отмена.** `CancellationToken` передаётся сквозь все слои; длинные операции (итерации сообщений, скачивание медиа, транскрипция) вызывают `token.raise_if_cancelled()` в точках прерывания.

5. **Безопасность секретов:**
   - `api_hash`, `session_string`, `deepgram_api_key` хранятся **только** в системном Keyring (`tg_exporter` service).
   - `api_id` — несекретный, лежит в `~/.tg_exporter/config.json`.
   - Логи пропускаются через `redact()` — секреты заменяются на `<redacted>`.
   - Конфиг-файл получает права `0o600` (кроме Windows).
   - При запуске выполняется миграция: если старый `config.json` содержит `api_hash`/`session` — они переносятся в Keyring и удаляются из файла (`App._migrate_legacy_config`).

6. **Иммутабельность там, где можно.** `ExportTask`, `ExportMessage`, `AppConfig`, `MarkdownSettings`, `ReactionItem`, `PollData` и т.д. — `@dataclass(frozen=True)` или с `dataclasses.replace()` для эволюции.

---

## 4. Модули — подробный справочник

### 4.1. `main.py`
Обёртка-лаунчер. Импортирует `App`, ловит фатальные исключения до старта UI, пишет их в `~/.tg_exporter/app.log` и показывает `messagebox`.

### 4.2. `tg_exporter/models/`

| Модуль              | Ключевые типы                                                    | Назначение                                     |
| ------------------- | ---------------------------------------------------------------- | ---------------------------------------------- |
| `config.py`         | `AppConfig`, `MarkdownSettings`, `ConfigValidationError`         | Конфиг (только несекретные поля), валидация    |
| `export_task.py`    | `ExportTask`, `ExportProgress`, `AuthorFilter`, `ExportFormat`, `ExportStatus` | Параметры задачи + изменяемый прогресс |
| `message.py`        | `ExportMessage`, `MediaType`, `LinkItem`, `ReactionItem`, `PollAnswer`, `PollData` | Промежуточный формат сообщения     |

- Персистентность: `AppConfig.load()` / `AppConfig.save()` → `~/.tg_exporter/config.json`.
- Секреты в `AppConfig` **никогда не сериализуются** (метод `to_dict` их опускает).
- `ExportProgress` даёт производные метрики: `progress_ratio`, `messages_per_second`, `eta_seconds`.

### 4.3. `tg_exporter/core/`

| Модуль            | Класс                        | Ответственность                                                                 |
| ----------------- | ---------------------------- | ------------------------------------------------------------------------------- |
| `credentials.py`  | `CredentialsManager`         | Keyring CRUD для `api_hash`/`session`/`deepgram`. Миграция из legacy plaintext. |
| `client.py`       | `TelegramClientManager`      | Жизненный цикл `TelegramClient` (Telethon) + thread-local asyncio loop. `use_session(str)` — подмена сессии для мульти-профилей. |
| `profiles.py`     | `ProfileManager`, `Profile`  | Мульти-аккаунты: метаданные в `~/.tg_exporter/profiles.json`, сессии в Keyring `{api_id}:session:{phone}`. Thread-safe CRUD. |
| `auth.py`         | `AuthService`, `AuthResult`, `AuthStep` | Login flow: `send_code` → `verify_code` → `verify_password` (2FA) → `SUCCESS`. Human-readable ошибки (`_friendly`). |
| `converter.py`    | `message_to_export(msg)`     | Единственная точка контакта с Telethon-объектами.                               |
| `orchestrator.py` | `ExportOrchestrator`         | Оркестрирует один экспорт: подсчёт, цикл итерации, транскрипция, медиа, аналитика, финализация. |

**Сервис Keyring:** `tg_exporter`. Ключи:
- `{api_id}:api_hash`
- `{api_id}:session` — сессия по умолчанию (legacy + первый логин)
- `{api_id}:session:{phone}` — сессии мульти-профилей
- `deepgram_api_key`

### 4.4. `tg_exporter/exporters/`

Контракт (`BaseExporter`):
```python
exporter.open(export_dir, chat_name, topic_title=None)
for msg in messages:
    exporter.write(msg)
files: list[str] = exporter.finalize()   # или exporter.close() при отмене
```

| Экспортёр            | Выходные файлы                                          | Особенности                                                     |
| -------------------- | ------------------------------------------------------- | --------------------------------------------------------------- |
| `JsonExporter`       | `result.json`                                           | Потоковая запись (без накопления), совместим с текущим форматом |
| `MarkdownExporter`   | `{chat}_part_1.md`, `{chat}_part_2.md`, … (опц. `_popular.md`) | Разбивка по `words_per_file`, поддержка топиков форумов      |

`sanitize_filename(name)` — утилита в `base.py` для безопасных имён.

### 4.5. `tg_exporter/services/`

| Модуль                          | Ключевые типы                              | Что делает                                                                 |
| ------------------------------- | ------------------------------------------ | -------------------------------------------------------------------------- |
| `analytics.py`                  | `AnalyticsCollector`, `AnalyticsResult`, `AuthorStats`, `render_top_authors`, `render_activity` | Считает топ авторов и активность по датам; рендерит в MD.  |
| `media_downloader.py`           | `MediaDownloader`, `MediaDirs`, `AudioPrepResult`, `MediaTooLongError`, `MediaProcessingError` | Скачивает медиа, готовит аудио (ogg→wav через ffmpeg) для транскрипции. Лимит 15 мин. |
| `export_history.py`             | `ExportHistory`                            | Хранит `peer_id → last_message_id` в `~/.tg_exporter/export_history.json`. |
| `transcription/base.py`         | `BaseTranscriber`, `TranscriptionError`    | Контракт: `preload()` → `transcribe(audio_data, content_type, language)` → `unload()`. |
| `transcription/factory.py`      | `create_transcriber(config, deepgram_key)` | Выбирает провайдер по `config.transcription_provider` / `local_whisper_model`. |
| `transcription/whisper_local.py`| `WhisperTranscriber`                       | faster-whisper (tiny/base/small/medium/large-v2/large-v3). HF-кеш + прогресс-бар. |
| `transcription/deepgram.py`     | `DeepgramTranscriber`                      | Облачный Deepgram API (nova-3 для en/multi, nova-2 для non-EN). Ключ — только из Keyring. |

### 4.6. `tg_exporter/ui/`

- **`app.py` — `App(ctk.CTk)`.** Главный контроллер, владеет всеми сервисами (config, credentials, client_mgr, auth, history, worker, dispatcher, token). Навигация между `LoginView` и `ChatListView`, открытие модалок (`SettingsModal`, `ExportModal`).
  - Регистрирует обработчики событий в `_register_handlers()`.
  - `_poll()` — периодический drain `worker.poll_events()` → `dispatcher.dispatch()`.
  - Поддерживает экспорт **целой папки Telegram** (последовательно в очередь) с режимами `По чатам` / `Один .md на чат` / `Один .md на папку`.
  - `_migrate_legacy_config()` — миграция секретов из старого plaintext-конфига.

- **`theme.py` — единая дизайн-система.** Все цвета (`C[...]` — кортежи `(light, dark)`), шрифты по OS, `RADIUS`, `SPACING`, `WIDGET`, `WINDOW`. **Нигде в UI нет хардкода цветов/шрифтов.**

- **`components/`** — переиспользуемые виджеты (`AppButton`, `AppEntry`, `ExportProgressWidget`).

- **`views/`**:
  - `LoginView` — карточка авторизации, состояния `phone` → `code` → `loading`, inline-ошибки.
  - `ChatListView` — список чатов, выбор папки Telegram, период, поиск, кнопки экспорта.
  - `ExportModal` — все опции экспорта (формат, медиа, транскрипция, аналитика, автор-фильтр, дата, инкрементальный) + прогресс-виджет.
  - `SettingsModal` — провайдер транскрипции, модель, язык, Deepgram ключ.

### 4.7. `tg_exporter/utils/`

- **`worker.py`:**
  - `BackgroundWorker`: один daemon-поток, `task_queue` (callables) + `ui_queue` (UIEvent). `submit(fn, *args)` ставит в очередь, `poll_events()` дрейнит в UI. Shutdown через sentinel `None`.
  - `EventDispatcher`: `on(event_type, handler)` / `dispatch(event, payload)`.

- **`cancellation.py`:** `CancellationToken` (threading.Event внутри) + `CancelledError`. Метод `raise_if_cancelled()` + `wait_for_cancel(timeout)`.

- **`logger.py`:** `AppLogger` пишет в `~/.tg_exporter/app.log` (ротация на 5 MB → `.log.old`). `redact()` маскирует `api_hash`, `api_id`, `session`, телефоны, Bearer-токены.

---

## 5. Поток выполнения экспорта (happy path)

```
UI (ChatListView)
  → user кликает «Экспортировать» для диалога
  → App.show_export_dialog(dialog)
  → ExportModal открывается, пользователь настраивает опции
  → ExportModal вызывает App.start_export(dialog, output_path, modal)

App.start_export
  → собирает ExportTask из options
  → определяет last_id из ExportHistory (если incremental)
  → создаёт CancellationToken
  → создаёт ExportOrchestrator (client_mgr, config, history, deepgram_key)
  → worker.submit(orch.run, dialog, task, token, progress, send_event)

[фоновый поток]
ExportOrchestrator.run
  → client.ensure_connected()
  → создаёт export_dir = {output_path}/{chat_title}_{timestamp}/
  → _count_messages() → total (для прогресс-бара)
  → send("export_start", (chat_name, total))
  → (опц.) preload transcriber, media_dirs, analytics
  → открывает JsonExporter / MarkdownExporter
  → for msg in client.iter_messages(dialog, reverse=True, ...):
        token.raise_if_cancelled()
        конверт. → ExportMessage
        (опц.) транскрипция: media_downloader.prepare_audio → transcriber.transcribe
        exporter.write(msg)
        (опц.) media_downloader.download
        send("export_progress", (count, total))
  → finalize экспортёров
  → рендер analytics → top_authors.md, activity.md
  → history.set_last_id(peer_id, max_msg_id)
  → transcriber.unload()
  → send("export_done", (export_dir, output_files))

[UI-поток каждые 80 мс]
App._poll
  → worker.poll_events() → [("export_progress", ...), ("export_done", ...), ...]
  → dispatcher.dispatch → App._on_export_progress / _on_export_done
  → ExportModal обновляет прогресс / показывает результат
```

### UIEvent — полный список типов

| event_type          | payload                            | Источник                    |
| ------------------- | ---------------------------------- | --------------------------- |
| `login_success`     | `None`                             | `AuthService`               |
| `code_sent`         | `None`                             | `AuthService`               |
| `login_error`       | `str`                              | `AuthService`               |
| `login_2fa`         | `None`                             | `AuthService`               |
| `logout_done`       | `None`                             | `AuthService`               |
| `chats_loaded`      | `list[Dialog]`                     | `App._bg_load_chats`        |
| `folders_loaded`    | `list[str]`                        | `App._process_filters`      |
| `error`             | `str`                              | любой слой                  |
| `info`              | `str`                              | orchestrator/transcription  |
| `worker_error`      | `str` (traceback)                  | `BackgroundWorker`          |
| `export_start`      | `(chat_name, total_or_None)`       | `ExportOrchestrator`        |
| `export_progress`   | `(count, total_or_None)`           | `ExportOrchestrator`        |
| `export_status`     | `str`                              | `ExportOrchestrator`        |
| `export_done`       | `(export_dir, list[file_paths])`   | `ExportOrchestrator`        |
| `export_error`      | `str`                              | `ExportOrchestrator`        |
| `export_cancelled`  | `None`                             | `ExportOrchestrator`        |
| `folder_progress`   | `(current, total, label)`          | `App` (folder export)       |
| `folder_done`       | `total`                            | `App` (folder export)       |

---

## 6. Файлы и директории в рантайме (`~/.tg_exporter/`)

| Путь                        | Назначение                                                     |
| --------------------------- | -------------------------------------------------------------- |
| `~/.tg_exporter/config.json`| Несекретные настройки (`api_id`, транскрипция, markdown)       |
| `~/.tg_exporter/app.log`    | Лог приложения (ротация на 5 MB → `app.log.old`)               |
| `~/.tg_exporter/export_history.json` | Инкрементальный `peer_id → last_message_id`          |
| `~/.tg_exporter/profiles.json` | Мульти-профили: `active_phone` + список (phone, display_name, api_id). Без секретов. |
| Keyring `tg_exporter/*`     | `api_hash`, `session`, `session:{phone}`, `deepgram_api_key`   |

---

## 7. Зависимости

```txt
telethon               # Telegram API client
customtkinter          # UI framework (обёртка Tkinter)
keyring                # Системное хранилище секретов
imageio-ffmpeg         # ffmpeg для конвертации аудио
PySocks                # прокси (опционально в telethon)
faster-whisper         # локальная транскрипция Whisper
```

Дополнительные зависимости для Deepgram не требуются — используется стандартный `urllib`.

---

## 8. Сборка и релиз

### Локальная сборка

- **macOS:** `./scripts/build_mac.sh` → `dist/Telegram Exporter.app` + `dist/TelegramExporter.dmg`.
  - Переменная `DMG_NAME` переопределяет имя.
  - Иконка генерируется из `assets/app_icon.png` через `sips` + `iconutil` → `icons/app.icns`.
- **Windows:** `scripts/build_win.ps1` (EXE) + `scripts/build_win_installer.ps1` + `iscc installer/TelegramExporter.iss` → `dist/TelegramExporterSetup.exe`.

### CI/CD (`.github/workflows/build_release.yml`)

Триггеры: `workflow_dispatch`, push тегов `v*`.

| Job             | Runner         | Артефакт                              |
| --------------- | -------------- | ------------------------------------- |
| `build-macos`   | `macos-13`     | `TelegramExporter-mac-intel.dmg`      |
| `build-macos`   | `macos-14`     | `TelegramExporter-mac-arm64.dmg`      |
| `build-windows` | `windows-latest` | `TelegramExporterSetup.exe`         |

На пушах тегов артефакты автоматически прикладываются к GitHub Release (`softprops/action-gh-release@v2`).

---

## 9. Тестирование

- Тесты — **stdlib unittest** (без pytest), находятся в `tests/`.
- Запуск: `python -m unittest discover tests`.
- Покрытие: `test_models.py` (AppConfig/ExportMessage/ExportTask), `test_services.py`, `test_exporters.py`.
- Тесты не трогают сеть и Keyring (используют моки/временные директории).

---

## 10. Дополнительные соглашения

1. **Никаких секретов в файлах конфигурации или логах.** Всё идёт через `CredentialsManager` и `redact()`.
2. **UI не импортирует Telethon напрямую** (разрешено только `core.*`). Если замечено — это архитектурное нарушение, требующее рефакторинга.
3. **Все длинные операции проверяют `token.raise_if_cancelled()`** как минимум раз в итерацию/перед IO.
4. **Новые экспортёры** → наследуются от `BaseExporter`, регистрируются в `exporters/__init__.py`.
5. **Новые транскриберы** → наследуются от `BaseTranscriber`, подключаются в `transcription/factory.py` и (если нужно) в `models/config.py` константах.
6. **Никаких блокирующих вызовов в UI-потоке.** Всё → через `worker.submit()`.
7. **Строка `from __future__ import annotations`** используется во всех модулях пакета — это часть стиля.

---

## 11. Точки расширения (куда смотреть при типовых задачах)

| Задача                                      | Куда смотреть / что менять                                                              |
| ------------------------------------------- | --------------------------------------------------------------------------------------- |
| Добавить новый формат экспорта              | `exporters/` — новый `BaseExporter` + регистрация в `__init__.py` + вызов в `orchestrator.py` |
| Добавить новый провайдер транскрипции       | `services/transcription/` + `factory.py` + константы в `models/config.py`               |
| Изменить UI (цвета, шрифты, отступы)        | **только** `ui/theme.py`                                                                |
| Новый экран                                 | `ui/views/` + переключение из `App`                                                     |
| Новый тип UIEvent                           | `App._register_handlers()` + обработчик `_on_...`                                       |
| Новое поле сообщения                        | `models/message.py` (ExportMessage) + `core/converter.py` + вывод в экспортёрах          |
| Новая настройка пользователя                | `models/config.py` (поле + валидация) + `ui/views/settings_modal.py`                    |
| Изменить сборку                             | `Telegram Exporter.spec`, `scripts/build_*.sh/ps1`, `.github/workflows/build_release.yml` |

---

## 12. Известные ограничения

- **Транскрипция ограничена 15 минутами** на сообщение (`BaseTranscriber.MAX_DURATION_SEC = 900`).
- **Отмена экспорта не прерывает текущее скачивание медиа** мгновенно — дожидается конца IO.
- **JSON при отмене остаётся невалидным** (`close()` не дописывает финальный `]`) — это допустимо, т.к. частичные данные не рассчитаны на повторное чтение.
- **Сессия Telegram — одна на api_id.** Параллельно запустить две копии приложения нельзя (`database is locked`) — в UI показывается понятная ошибка.

---

## 13. Контакты / мета

- Репозиторий: `morf3uzzz/telegram-exporter` (main branch).
- Основная ветка: `main`.
- Python: 3.11.
- Язык интерфейса и сообщений в коде: **русский** (комментарии, UI-тексты, сообщения об ошибках).

---

## Журнал изменений

> Каждое изменение в проекте должно добавляться сюда новой записью.
> Формат: `YYYY-MM-DD — краткая суть — затронутые файлы/модули — причина/контекст (опц.)`.

- **2026-04-15** — Создан `CLAUDE.md` с полным описанием архитектуры, модулей, потоков экспорта, UI-событий, сборки и правил расширения. Установлено главное правило: любое изменение в проекте должно фиксироваться в этом файле. — `CLAUDE.md` (новый файл).
- **2026-04-15** — Диагностика «зависания» транскрипции: пользователь не видел, что Whisper-модель синхронно качается из HuggingFace (~140 МБ для base) без индикации, и экспорт просто «висел». Затронутые файлы:
  - `tg_exporter/services/transcription/whisper_local.py` — добавлен `set_status_callback()`, эвристика `_whisper_cache_exists()` (смотрит `~/.cache/huggingface/hub/models--Systran--faster-whisper-*`). Если модель не скачана — посылает пользователю сообщение «Скачивание модели Whisper «base» (~140 МБ). Это происходит один раз, может занять несколько минут...». Добавлено детальное логирование (`logger.info`/`logger.error`) с таймингами на всех этапах load/transcribe.
  - `tg_exporter/core/orchestrator.py` — `transcribe_failed=True` теперь выставляется при падении `preload()` (раньше оставался False, и каждое сообщение безуспешно пыталось заново). Подключён status-колбэк транскрибера → `send("export_status", text)` — пользователь видит реальный статус скачивания модели. Добавлено логирование старта/конца preload + catch-all `except Exception`.
  - `tg_exporter/services/media_downloader.py` — добавлено логирование с таймингами для `_prepare_voice` (download ogg) и `_prepare_video_note` (download mp4 + ffmpeg extract) — теперь в `~/.tg_exporter/app.log` видно, на каком шаге застряло.
- **2026-04-15** — Реальный прогресс скачивания Whisper-модели + фикс перекрытия статуса со счётчиком. Затронутые файлы:
  - `tg_exporter/services/transcription/whisper_local.py` — `snapshot_download(repo_id=_MODEL_REPO[model], tqdm_class=...)` с кастомным `_make_progress_tqdm` агрегирует байты по всем файлам и шлёт ratio 0..1 + текст в UI. Новый `set_progress_callback()`. Перед скачиванием — `_check_disk_space()` (требует `size_mb * 2.5` свободных МБ; бросает `TranscriptionError` с понятным текстом если места нет). Новое UIEvent `model_download_progress: (ratio, text)`.
  - `tg_exporter/core/orchestrator.py` — регистрирует progress-колбэк, который шлёт `model_download_progress` в UI.
  - `tg_exporter/ui/components/progress_bar.py` — статус вынесен на **отдельную строку** под счётчиком (больше не перекрывает «0 / 405»). ETA переехало в собственный `_eta_lbl`. Новый метод `set_download_progress(ratio, text)` — показывает прогресс-бар как download-индикатор (`42%` вместо `0 / total`).
  - `tg_exporter/ui/app.py` / `tg_exporter/ui/views/export_modal.py` — регистрация обработчика `model_download_progress` → `ExportModal.on_model_download_progress()` → `progress.set_download_progress()`.
- **2026-04-15** — Аудит безопасности/надёжности: исправления 18 пунктов. Затронутые файлы:
  - `tg_exporter/ui/app.py` — `_migrate_legacy_config` проверяет возврат `migrate_from_plaintext`; атомарная запись конфига (tmp+fsync+replace) чтобы не затирать секреты при сбое миграции.
  - `tg_exporter/exporters/base.py` — `sanitize_filename` чистит control-символы, Windows-reserved имена (CON, PRN, …), `..`, длину ≤120; добавлен `safe_join` (realpath guard от path traversal).
  - `tg_exporter/ui/components/entry.py` / `button.py` — публичные `set_text/clear/set_show` и `set_idle_text` вместо доступа к приватным `_entry`/`_original_text`.
  - `tg_exporter/ui/views/login_view.py` / `export_modal.py` — маскирование Deepgram ключа (`show="•"`), переход на публичный API компонентов.
  - `tg_exporter/services/transcription/silero.py` — `torch.hub.load(trust_repo="check")` вместо `True` (supply-chain).
  - `requirements.txt` — зафиксированы верхние границы версий (telethon, customtkinter, keyring, imageio-ffmpeg, PySocks, faster-whisper).
  - `Telegram Exporter.spec` / `scripts/build_mac.sh` / `.github/workflows/build_release.yml` — `TARGET_ARCH` автодетект по `uname -m`, CI-матрица с `x86_64` и `arm64`.
  - `tg_exporter/ui/views/chat_list_view.py` / `export_modal.py` — парсинг даты в naive-local через `astimezone()` + корректная метка «Локальное время».
  - `tg_exporter/exporters/json_exporter.py` — `close()` (отмена) дописывает закрывающие `]}` чтобы partial JSON оставался валидным.
  - `tg_exporter/services/analytics.py` — ограничения памяти: `deque(maxlen=5000)` на автора, обрезка записей до 2000 символов (защита от OOM на больших чатах).
  - `tg_exporter/models/config.py` — битый `config.json` бэкапится в `config.broken.{ts}.json` вместо молчаливой перезаписи; атомарное сохранение.
  - `tg_exporter/services/export_history.py` — атомарная запись истории (tmp+fsync+replace).
  - `tg_exporter/utils/logger.py` — `threading.Lock` вокруг ротации+записи; сужен regex телефона (`\+\d{10,15}\b`); добавлен паттерн `Token <…>`.
  - `tg_exporter/services/transcription/deepgram.py` — `_REQUEST_TIMEOUT=300s`, retry (3 попытки, backoff 2/5s) на URLError/timeout/429; 4xx не ретраятся.
  - `tg_exporter/exporters/markdown_exporter.py` — `_build_topic_comment` экранирует `--` через zero-width-space (HTML-валидно, без искажения текста).
  - `tg_exporter/core/converter.py` — `message.date is None` не роняет конвертацию (редкие сервисные сообщения / старые чаты).
  - `README.md` — `python app.py` → `python main.py`.
- **2026-04-15** — Пост-аудит: верификация и чистка мёртвого кода. 108 unit-тестов проходят. Затронутые файлы:
  - `scripts/build_win_installer.ps1` — переписан: ссылался на удалённый `app.py`, что ломало Windows CI; теперь использует `main.py` + array-splatting тех же флагов, что и `build_mac.sh`/`spec`.
  - `tg_exporter/ui/views/settings_modal.py` — `_deepgram_entry.insert(0, dg_key)` → `set_text(dg_key)`: повторное открытие модалки дублировало ключ Deepgram в поле.
  - `tg_exporter/exporters/base.py` — удалены неиспользуемые `safe_join()` и `BaseExporter._safe_chat_name()` (никем не импортировались/не вызывались).
  - `tg_exporter/utils/worker.py` — удалён неиспользуемый `from dataclasses import dataclass`.
  - `tg_exporter/services/transcription/silero.py` — удалён неиспользуемый `Any` из импорта `typing`.
- **2026-04-15** — UI: иконка ⚙ в шапке заменена на текстовую кнопку «Настройки»; toolbar `ChatListView` разбит на две строки (фильтры + действия) — больше не обрезается при сужении окна. Затронутые файлы:
  - `tg_exporter/ui/views/chat_list_view.py` — header: `⚙` → `Настройки` (variant=ghost); toolbar переписан как `row1` (Папка/Период) + `row2` (Экспортировать папку/режим/Транскрипция), убран фиксированный `height` и `pack_propagate(False)`.
  - `tg_exporter/ui/theme.py` — `WINDOW.size` 920×680 → 920×720, `min_size` (760, 560) → (640, 600): уже по ширине, выше по высоте под две строки.
- **2026-04-15** — UI: toolbar `ChatListView` — финальная версия: одна строка на всю ширину, фиксированная высота 38px (`pack_propagate(False)`); все элементы (Папка / Период / Экспортировать папку / режим / Транскрипция) в один ряд. Уменьшены ширины меню (160/120/150). — `tg_exporter/ui/views/chat_list_view.py`.
- **2026-04-15** — UI: добавлена кнопка «Инструкция» в шапке `ChatListView` (справа от заголовка) и модалка `HelpModal` с пользовательским руководством (7 разделов: авторизация, главный экран, экспорт чата/папки, настройки, файловая структура, советы). Добавлены файлы/изменения:
  - `tg_exporter/ui/views/help_modal.py` — новая модалка с прокручиваемым контентом.
  - `tg_exporter/ui/app.py` — импорт `HelpModal` + метод `App.show_help()`.
  - `tg_exporter/ui/views/chat_list_view.py` — кнопка `Инструкция` (variant=ghost) рядом с заголовком.
- **2026-04-15** — UI: единый helper для модалок — устранены 4 проблемы (прыжок при появлении / чёрная подложка / слишком быстрый скролл на macOS / окно теряется при клике мимо). Файлы:
  - `tg_exporter/ui/modal_utils.py` — новый модуль: `init_modal()` (withdraw → fg_color → transient → geometry → deiconify → grab; bell+alpha-вспышка при клике по родителю) и `setup_smooth_scroll()` (на macOS ±1 единица вместо `event.delta`-множителя).
  - `tg_exporter/ui/views/help_modal.py`, `settings_modal.py`, `export_modal.py` — заменён boilerplate (`grab_set/lift/focus/_setup_scroll/_center_on_parent/_bind_scroll_to_children`) вызовом `init_modal()` + `setup_smooth_scroll()`.
- **2026-04-15** — UI: исправлены остаточные проблемы модалок (вспышка «CTkToplevel» перед нормальным размером / тёмные полосы по краям / скорость скролла). Файлы:
  - `tg_exporter/ui/modal_utils.py` — `init_modal()` разделён на `prepare_modal()` (вызывать **первой строкой** `__init__`: withdraw + title + fg_color + geometry до отрисовки) и `show_modal()` (последней: transient + deiconify + grab + focus_hint). Скролл — 3 строки за щелчок на всех ОС.
  - `tg_exporter/ui/views/{help_modal,settings_modal,export_modal}.py` — `prepare_modal()` сразу после `super().__init__()`, `show_modal()` после `_build()`. `CTkScrollableFrame(fg_color="transparent" → C["bg"])` — убраны тёмные полосы вокруг скролл-зоны.
- **2026-04-15** — Транскрипция: удалены неиспользуемые провайдеры Silero и Parakeet (в UI всё равно выбирались только Whisper и Deepgram). Deepgram обновлён на nova-3 (быстрее и точнее nova-2), с автоматическим fallback на nova-2 для не-английских языков (nova-3 поддерживает только en/multi). Затронутые файлы:
  - `tg_exporter/services/transcription/silero.py`, `parakeet.py` — **удалены**.
  - `tg_exporter/services/transcription/__init__.py` — убраны импорты SileroTranscriber/ParakeetTranscriber.
  - `tg_exporter/services/transcription/factory.py` — убраны ветки `silero-*`/`parakeet-*`, фабрика всегда возвращает Whisper или Deepgram.
  - `tg_exporter/services/transcription/deepgram.py` — модель `nova-2` → `nova-3` (для en/multi), nova-2 как fallback для ru/de/fr/es/zh/ja; URL собирается через `urlencode`, добавлен `&language=multi` для авто-детекта.
  - `tg_exporter/models/config.py` — `TRANSCRIPTION_PROVIDERS` сокращено до `("local", "deepgram")`, `WHISPER_MODELS` расширено до `(tiny, base, small, medium, large, large-v2, large-v3)` (валидация теперь принимает -v2/-v3, которые UI уже выводил).
  - `tg_exporter/ui/views/export_modal.py` — `_WHISPER_MODELS` сокращён до 6 Whisper-опций (убраны 4 записи Parakeet/Silero). Provider-dropdown: «Локальная (Whisper / Silero / Parakeet)» → «Локальный Whisper». Строковый матчинг `"Локальная" in value` → `"Whisper" in value`.
  - `requirements.txt`, `CLAUDE.md` (разделы 4.5 и 7) — убраны упоминания Silero/Parakeet.
- **2026-04-15** — Мульти-аккаунты: быстрое переключение между несколькими Telegram-сессиями без повторного ввода кода. В шапке `ChatListView` слева от «Обновить» — кнопка «Аккаунт ▾» с popup-меню: список профилей, «+ Добавить аккаунт», «Удалить текущий». При добавлении — отдельный `TelegramClient(StringSession())` делает phone/code/2FA, не трогая активного клиента. Сессии хранятся в Keyring как `{api_id}:session:{phone}`, метаданные — в `~/.tg_exporter/profiles.json`. Первый логин автоматически создаёт профиль через `get_me()`. Затронутые файлы:
  - `tg_exporter/core/profiles.py` — **новый**: `ProfileManager` (thread-safe CRUD, atomic write, 0o600), `Profile` dataclass, `_normalize_phone()`.
  - `tg_exporter/core/client.py` — `TelegramClientManager.use_session(session_string)`: подмена сессии + destroy клиента; `_build_client()` учитывает `_session_override` до обращения к Keyring.
  - `tg_exporter/ui/views/add_account_modal.py` — **новый**: phone → code → 2FA на локальном `TelegramClient(StringSession())`; после успеха вызывает `ProfileManager.add_or_update(...)` и эмитит `add_account_done`.
  - `tg_exporter/ui/app.py` — `_profiles = ProfileManager(...)`, публичное API `profiles()/active_profile()/switch_profile()/remove_profile()/save_active_profile_session()/show_add_account()`, фоновый `_bg_switch_profile()` (disconnect → load session → `use_session()` → `ensure_connected()` → `is_user_authorized` check), обработчики `add_account_{code_sent,2fa,done,error}` + `profile_switched`. `_on_login_success` теперь всегда вызывает `save_active_profile_session()` — миграция старой одиночной сессии в профиль через `get_me()`.
  - `tg_exporter/ui/views/chat_list_view.py` — кнопка «Аккаунт ▾» слева от «Обновить», `_show_account_menu()` (popup через `tk.Menu.tk_popup`), `refresh_account_switcher()` (обновляется автоматически при `render_chats` и `profile_switched`).
  - `tests/test_profiles.py` — **новый**: 17 тестов (CRUD, keyring-ключи, переключение, удаление, персистентность, нормализация телефона, изоляция секретов от файла).
  - `CLAUDE.md` — §4.3 (ProfileManager, новый keyring-ключ), §6 (profiles.json в рантайме), журнал изменений.
