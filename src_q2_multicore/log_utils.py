from __future__ import annotations

from datetime import datetime


def log(message: str, indent: int = 0) -> None:
    """轻量中文运行日志。"""

    prefix = "  " * indent
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[Q2 {timestamp}] {prefix}{message}", flush=True)
