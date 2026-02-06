# Telegram Exporter (macOS / Windows)

Простое локальное приложение для экспорта истории чатов/каналов Telegram
в `result.json`, совместимый по структуре с экспортом Telegram Desktop.

## Что делает

- Авторизация через Telegram (пользовательская сессия)
- Выбор чата/канала из списка
- Экспорт всей истории в JSON
- Поддержка больших чатов (стриминговая запись в файл)

## Скачать и установить

### macOS
1) Скачай `TelegramExporter.dmg` из **Releases**
2) Открой DMG → перетащи приложение в **Applications**
3) Запусти приложение

### Windows
1) Скачай `TelegramExporterSetup.exe` из **Releases**
2) Запусти установщик → Next → Install

## Полный запуск вручную (если нет релиза)

### macOS — пошагово
1) Открой **Terminal** (⌘+Space → введи “Terminal” → Enter)
2) Перейди в папку проекта:
```
cd "/Users/ТВОЁ_ИМЯ/Documents/Cursor/Парсер тг"
```
3) Создай виртуальное окружение:
```
python3 -m venv .venv
```
4) Активируй окружение:
```
source .venv/bin/activate
```
5) Установи зависимости:
```
pip install -r requirements.txt
```
6) Запусти приложение:
```
python3 app.py
```

### Windows — пошагово
1) Открой **PowerShell** (Win → введи “PowerShell” → Enter)
2) Перейди в папку проекта:
```
cd "C:\Users\ТВОЁ_ИМЯ\Documents\Cursor\Парсер тг"
```
3) Создай виртуальное окружение:
```
python -m venv .venv
```
4) Активируй окружение:
```
.venv\Scripts\Activate.ps1
```
5) Если появится ошибка про ExecutionPolicy, выполни:
```
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
и снова активируй окружение:
```
.venv\Scripts\Activate.ps1
```
6) Установи зависимости:
```
pip install -r requirements.txt
```
7) Запусти приложение:
```
python app.py
```

### Первый запуск без подписи (macOS)
Если появится предупреждение безопасности:
1) Открой `Applications` и сделай правый клик по приложению → **Open**
2) Подтверди запуск
3) Либо: System Settings → Privacy & Security → **Open Anyway**

### Первый запуск без подписи (Windows)
Если SmartScreen блокирует запуск:
1) Нажми **More info**
2) Нажми **Run anyway**

## Получение API ID / API Hash

1) Перейди на https://my.telegram.org
2) Войди по номеру телефона
3) Открой раздел **API Development tools**
4) Создай приложение и получи **API ID** и **API Hash**

Каждый пользователь использует **свои** ключи.

## Как пользоваться

1) Введи API ID и API Hash
2) Введи номер телефона → нажми **Отправить код**
3) Введи код из Telegram → нажми **Подтвердить**
4) Нажми **Обновить**, если список не появился
5) Выбери чат → нажми **Экспортировать выбранный чат**

В результате получишь папку:
`<НазваниеЧата>_YYYY-MM-DD_HH-MM-SS/result.json`
которую можно загрузить в твой конвертер.

## Для разработчиков (сборка)

### macOS (DMG)
```
./scripts/build_mac.sh
```
Файл: `dist/TelegramExporter.dmg`

### Windows (EXE)
```
powershell -ExecutionPolicy Bypass -File .\scripts\build_win.ps1
```
Файл: `dist/TelegramExporter.exe`

### Windows (Installer: Next → Next → Install)
1) Скачай и установи Inno Setup: https://jrsoftware.org/isinfo.php
2) Собери EXE:
```
powershell -ExecutionPolicy Bypass -File .\scripts\build_win_installer.ps1
```
3) Открой `installer\TelegramExporter.iss` в Inno Setup и нажми **Compile**.
Файл: `dist\TelegramExporterSetup.exe`

## Иконка приложения

Положи PNG 1024×1024 в `assets/app_icon.png`.
Скрипты сборки сами создадут `.icns` и `.ico` и подключат их.

## Примечания

- Экспортируются только чаты/каналы, где ты участник.
- Секретные чаты (Secret Chat) не доступны через API.
- Для огромных чатов процесс может идти долго — не закрывай приложение.
