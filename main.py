"""
main.py — точка входа нового приложения.

Запуск:
    python main.py

Старый app.py остаётся нетронутым как fallback.
"""

import sys
import traceback
from pathlib import Path


def main() -> None:
    try:
        from tg_exporter.ui.app import App
        app = App()
        app.mainloop()
    except Exception as exc:
        # Фатальная ошибка до старта UI
        tb = traceback.format_exc()
        try:
            from tg_exporter.utils.logger import logger
            logger.fatal("Fatal startup error", exc=exc)
        except Exception:
            pass
        # Показываем messagebox если возможно
        try:
            import tkinter.messagebox as mb
            mb.showerror("Ошибка запуска", f"{exc}\n\nПодробности в ~/.tg_exporter/app.log")
        except Exception:
            print(f"FATAL: {exc}\n{tb}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
