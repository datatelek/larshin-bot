"""Запуск двух независимых Telegram-ботов в одном Render Worker."""

from __future__ import annotations

import logging
import signal
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger("launcher")

COMMANDS = (
    ("карьерный бот", [sys.executable, "bot.py"]),
    ("внутренний AI-бот", [sys.executable, "-m", "app.main"]),
)


def stop_processes(processes: list[tuple[str, subprocess.Popen]]) -> None:
    for name, process in processes:
        if process.poll() is None:
            LOGGER.info("Останавливаю: %s", name)
            process.terminate()

    deadline = time.monotonic() + 20
    for name, process in processes:
        if process.poll() is not None:
            continue
        timeout = max(deadline - time.monotonic(), 0)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            LOGGER.warning("Принудительно останавливаю: %s", name)
            process.kill()


def main() -> int:
    processes: list[tuple[str, subprocess.Popen]] = []
    stopping = False

    def handle_shutdown(signum: int, _frame) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        LOGGER.info("Получен сигнал остановки: %s", signum)
        stop_processes(processes)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        for name, command in COMMANDS:
            LOGGER.info("Запускаю: %s", name)
            processes.append((name, subprocess.Popen(command)))

        while not stopping:
            for name, process in processes:
                return_code = process.poll()
                if return_code is not None:
                    LOGGER.error("Процесс '%s' остановился с кодом %s", name, return_code)
                    stop_processes(processes)
                    return return_code or 1
            time.sleep(1)
    finally:
        stop_processes(processes)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
