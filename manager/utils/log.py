"""统一日志：写入 DEV_HOME/logs/manager，控制台输出由 commands 层负责。"""
from __future__ import annotations

import datetime
import os
import threading
from pathlib import Path
from typing import Optional

_LOCK = threading.Lock()


def _log_dir() -> Path:
    root = os.environ.get("DEV_HOME")
    if root:
        return Path(root).expanduser() / "logs" / "manager"
    return Path(__file__).resolve().parents[2] / "logs" / "manager"


class Logger:
    def __init__(self, name: str = "manager") -> None:
        self.name = name
        self.path = _log_dir() / f"{name}.log"

    def _write(self, level: str, message: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"[{stamp}] [{level}] {message}\n"
            with _LOCK:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(line)
        except OSError:
            pass

    def debug(self, message: str) -> None:
        self._write("DEBUG", message)

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def warn(self, message: str) -> None:
        self._write("WARN", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)


_logger: Optional[Logger] = None


def get_logger(name: str = "manager") -> Logger:
    global _logger
    if _logger is None:
        _logger = Logger(name)
    return _logger
