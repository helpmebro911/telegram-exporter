"""
BackgroundWorker — управление фоновым потоком и очередью событий для UI.

Архитектура:
- Один фоновый поток (daemon) выполняет задачи последовательно.
- Результаты передаются в UI через thread-safe UIEvent queue.
- UI читает очередь с помощью polling (after() в Tkinter).

UIEvent — типизированное событие от фонового потока к UI:
    ("progress", ExportProgressSnapshot)
    ("done", ExportResult)
    ("error", str)
    ("login_code_required", None)
    ("dialogs_loaded", list[DialogInfo])
    ...
"""

from __future__ import annotations

import queue
import threading
import traceback
from typing import Any, Callable, Optional


# Тип события: (event_name, payload)
UIEvent = tuple[str, Any]


class BackgroundWorker:
    """
    Выполняет задачи в одном фоновом потоке.
    Отправляет UIEvent в очередь для обработки UI.

    Один экземпляр живёт всё время работы приложения.
    """

    def __init__(self) -> None:
        self._ui_queue: queue.Queue[UIEvent] = queue.Queue()
        self._task_queue: queue.Queue[Optional[Callable]] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="bg-worker",
        )
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Запускает фоновый поток. Безопасно вызывать только один раз."""
        with self._lock:
            if self._started:
                return
            self._started = True
        self._thread.start()

    def submit(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
        """
        Ставит задачу в очередь выполнения.
        Задачи выполняются последовательно в фоновом потоке.
        Если во время выполнения возникает необработанное исключение —
        отправляется UIEvent("worker_error", traceback_str).
        """
        self._task_queue.put(lambda: fn(*args, **kwargs))

    def put_event(self, event_type: str, payload: Any = None) -> None:
        """
        Отправляет событие в UI-очередь.
        Вызывается из фонового потока или из UI.
        """
        self._ui_queue.put((event_type, payload))

    def poll_events(self, max_events: int = 20) -> list[UIEvent]:
        """
        Вычитывает до max_events из UI-очереди без блокировки.
        Вызывается из UI-потока (в Tkinter — через after()).
        """
        events: list[UIEvent] = []
        for _ in range(max_events):
            try:
                events.append(self._ui_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def shutdown(self, timeout: float = 3.0) -> None:
        """
        Сигнализирует фоновому потоку завершиться и ждёт timeout секунд.
        Безопасен для вызова из UI при закрытии приложения.
        """
        self._task_queue.put(None)  # sentinel
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    # ---- Internal ----

    def _run_loop(self) -> None:
        while True:
            task = self._task_queue.get()
            if task is None:
                break  # shutdown sentinel
            try:
                task()
            except Exception:
                tb = traceback.format_exc()
                self._ui_queue.put(("worker_error", tb))


class EventDispatcher:
    """
    Регистрирует обработчики UIEvent и диспетчеризует их.

    Используется в App для чистой обработки событий вместо длинного if/elif.

    Пример:
        dispatcher = EventDispatcher()
        dispatcher.on("progress", self._handle_progress)
        dispatcher.on("done", self._handle_done)

        # В polling loop:
        for event_type, payload in worker.poll_events():
            dispatcher.dispatch(event_type, payload)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}

    def on(self, event_type: str, handler: Callable[[Any], None]) -> None:
        """Регистрирует обработчик для типа события."""
        self._handlers.setdefault(event_type, []).append(handler)

    def off(self, event_type: str, handler: Callable) -> None:
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def dispatch(self, event_type: str, payload: Any = None) -> None:
        """Вызывает все зарегистрированные обработчики для данного события."""
        for handler in self._handlers.get(event_type, []):
            try:
                handler(payload)
            except Exception:
                # Ошибка в обработчике не должна ронять polling loop
                pass

    def dispatch_event(self, event: UIEvent) -> None:
        self.dispatch(event[0], event[1])
