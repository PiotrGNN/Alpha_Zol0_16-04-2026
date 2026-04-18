"""
Scheduler for periodic news/social fetching in ZoL0
(threaded, async-ready).
"""

import threading
import time
import logging
from typing import Callable, List


class NewsSocialScheduler:
    def __init__(self, fetch_func: Callable, interval_sec: int = 300):
        self.fetch_func = fetch_func
        self.interval_sec = interval_sec
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.last_result = []

    def _run(self):
        while not self._stop.is_set():
            try:
                self.last_result = self.fetch_func()
            except Exception as exc:
                logging.warning(
                    "NewsSocialScheduler: fetch_func failed: %s",
                    exc,
                )
            time.sleep(self.interval_sec)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join()

    def get_latest(self) -> List:
        return self.last_result
