<div align="center">
  <img src="https://raw.githubusercontent.com/morf3uzzz/telegram-exporter/main/assets/app_icon.png" width="128" alt="Telegram Exporter Logo">
  
  <h1>Telegram Exporter</h1>
  
  <p><b>Мощный и удобный инструмент для экспорта сообщений из Telegram каналов и чатов в форматы JSON и Markdown.</b><br>
  Приложение поддерживает локальную транскрипцию голосовых сообщений, скачивание медиафайлов и продвинутую фильтрацию.</p>
  
  <p>
    <a href="https://t.me/+cK5SwFPffNViOWUy">
      <img src="https://img.shields.io/badge/TELEGRAM-%D0%9A%D0%90%D0%9D%D0%90%D0%9B_%D0%90%D0%92%D0%A2%D0%9E%D0%A0%D0%90-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white&labelColor=555555" alt="Telegram Канал Автора">
    </a>
    <a href="https://www.youtube.com/channel/UCLk7uewdd5s7kszfy736ScA">
      <img src="https://img.shields.io/badge/YOUTUBE-%D0%9A%D0%90%D0%9D%D0%90%D0%9B_%D0%90%D0%92%D0%A2%D0%9E%D0%A0%D0%90-FF0000?style=for-the-badge&logo=youtube&logoColor=white&labelColor=555555" alt="YouTube Канал Автора">
    </a>
  </p>

  <p>
    <a href="https://github.com/morf3uzzz/telegram-exporter/releases">
      <img src="https://img.shields.io/github/v/release/morf3uzzz/telegram-exporter?style=flat-square" alt="GitHub Release">
    </a>
    <a href="https://opensource.org/licenses/MIT">
      <img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square" alt="License: MIT">
    </a>
  </p>
</div>


## ✨ Основные возможности

- **📁 Гибкий экспорт**: Сохранение истории сообщений в JSON (со всеми метаданными) или Markdown (удобно для чтения и Obsidian).
- **📝 Локальная транскрипция**: Распознавание голосовых сообщений и видео-кружков прямо на вашем компьютере с помощью:
  - **Faster-Whisper** (Tiny, Base, Small, Medium, Large-v2, Large-v3)
  - **Silero STT** (Русский и Английский)
  - **NVIDIA Parakeet**
- **☁️ Облачное распознавание**: Поддержка Deepgram API для быстрой и качественной транскрипции.
- **🖼️ Скачивание медиа**: Возможность выгрузить все фото, видео, голосовые сообщения и документы в структурированные папки.
- **📅 Экспорт за период**: Выбор конкретных дат или предустановок (последние 7/30 дней).
- **👤 Фильтрация авторов**: Экспорт сообщений только от выбранных участников чата.
- **📊 Аналитика каналов**: Сбор статистики просмотров и репостов для постов в каналах.
- **⚡️ Быстро и безопасно**: Работает через официальный Telegram API (Telethon). Данные авторизации хранятся в системном защищенном хранилище (Keyring).

## 🚀 Установка и запуск

### Для пользователей (готовые сборки)

Перейдите в раздел **[Releases](https://github.com/morf3uzzz/telegram-exporter/releases)** и скачайте версию для вашей ОС:

- **macOS (Universal)**: Скачайте `.dmg` файл, откройте его и перетащите приложение в папку Applications. Поддерживает Intel и Apple Silicon (M1/M2/M3).
- **Windows**: Скачайте `TelegramExporterSetup.exe` и следуйте инструкциям установщика.

### Для разработчиков (из исходников)

1. Клонируйте репозиторий:
   ```bash
   git clone https://github.com/morf3uzzz/telegram-exporter.git
   cd telegram-exporter
   ```
2. Создайте виртуальное окружение и установите зависимости:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Для Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Запустите приложение:
   ```bash
   python app.py
   ```

## ⚙️ Настройка транскрипции

Для использования локальной транскрипции убедитесь, что у вас достаточно оперативной памяти (для моделей `large-v3` рекомендуется 8ГБ+). При первом запуске локальной модели она будет автоматически скачана (от 50МБ до 3ГБ в зависимости от модели).

## 📄 Лицензия

Распространяется под лицензией MIT. Подробности в файле [LICENSE](LICENSE).

---
*Разработано с ❤️ для сообщества Telegram.*
