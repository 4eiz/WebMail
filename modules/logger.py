# app/logging.py
import logging
from typing import Optional
from rich.logging import RichHandler

class LoggerManager:
    def __init__(
        self,
        root_name: str = "app",
        level: int = logging.DEBUG,
        fmt: str = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt: str = "%H:%M:%S",
        log_file: Optional[str] = None,
    ):
        self.root_name = root_name
        self.level = level
        self.fmt = fmt
        self.datefmt = datefmt
        self.log_file = log_file
        self._configured = False

    def configure(self):
        if self._configured:
            return

        formatter = logging.Formatter(self.fmt, datefmt=self.datefmt)
        root = logging.getLogger(self.root_name)
        root.setLevel(self.level)

        # Чистим хендлеры, если перезапускаем в тестах/uvicorn и т.п.
        root.handlers.clear()

        console = RichHandler(rich_tracebacks=True)
        console.setLevel(self.level)
        console.setFormatter(formatter)
        root.addHandler(console)

        if self.log_file:
            fh = logging.FileHandler(self.log_file, encoding="utf-8")
            fh.setLevel(self.level)
            fh.setFormatter(formatter)
            root.addHandler(fh)

        # Важно: дочерние логгеры наследуют хендлеры
        root.propagate = False
        self._configured = True

    def get_logger(self, name: Optional[str] = None) -> logging.Logger:
        self.configure()
        if not name or name == self.root_name:
            return logging.getLogger(self.root_name)
        # Дочерний логгер: app.mail, app.api.users и т.д.
        return logging.getLogger(f"{self.root_name}.{name}")

# Глобальный экземпляр
_logger_manager = LoggerManager()

def init_logging(*, level: int = logging.DEBUG, log_file: Optional[str] = None):
    _logger_manager.level = level
    _logger_manager.log_file = log_file
    _logger_manager.configure()

def get_logger(module_name: str) -> logging.Logger:
    # Преобразуем "mail_client.imap_client" → дочерний от "app"
    child_name = module_name.replace("/", ".").replace("\\", ".")
    return _logger_manager.get_logger(child_name)
