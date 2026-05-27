import sqlite3
import threading
import time
import logging
from datetime import datetime

from scheduler import auto_schedule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [autocheck] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

DB_PATH = "agent_storage.db"
POLL_INTERVAL = 10

def _get_db_state(db_path: str) -> tuple[int, int]:
    try:
        conn = sqlite3.connect(db_path, timeout=20)
        cursor = conn.cursor()

        cursor.execute("SELECT MAX(TASK_ID) FROM TASKS")
        row_id = cursor.fetchone()
        max_id = row_id[0] if row_id and row_id[0] is not None else 0

        # Chỉ đếm task chưa có lịch VÀ KHÔNG phải fixed_schedule
        # (fixed_schedule đã có session ngay khi insert nên không cần auto_schedule)
        cursor.execute("""
            SELECT COUNT(*)
            FROM TASKS T
            LEFT JOIN SESSIONS S ON T.TASK_ID = S.TASK_ID
            WHERE S.SESSION_ID IS NULL
              AND T.DEADLINE IS NOT NULL
        """)
        row_count = cursor.fetchone()
        unscheduled_count = row_count[0] if row_count else 0

        conn.close()
        return max_id, unscheduled_count
    except sqlite3.Error as e:
        log.error(f"Lỗi kiểm tra DB: {e}")
        return 0, 0


def _watch_loop(poll_interval: int, db_path: str, stop_event: threading.Event):
    last_max_id, last_unscheduled = _get_db_state(db_path)

    log.info(f"Khởi động Watcher | Poll: {poll_interval}s | DB: {db_path}")
    log.info(f"Trạng thái ban đầu: MaxID={last_max_id}, Chưa xếp={last_unscheduled}")

    while not stop_event.is_set():
        if stop_event.wait(poll_interval):
            break

        try:
            curr_max_id, curr_unscheduled = _get_db_state(db_path)

            has_new_task = curr_max_id > last_max_id
            has_state_change = curr_unscheduled != last_unscheduled and curr_unscheduled > 0

            if has_new_task or has_state_change:
                if has_new_task:
                    log.info(f"Phát hiện Task mới (ID {last_max_id} -> {curr_max_id})")

                # Chỉ chạy auto_schedule nếu thực sự còn task chưa có lịch
                if curr_unscheduled > 0:
                    log.info(f"Tiến hành xếp lịch cho {curr_unscheduled} task...")

                    result = auto_schedule(db_path=db_path)  # FIX: bỏ sessions_per_task không tồn tại
                    scheduled_count = len(result.get("scheduled", []))

                    if scheduled_count > 0:
                        log.info(f"Xếp thành công {scheduled_count} task.")
                        logs = result.get("task_logs", [])
                        if logs:
                            log.info("--- Chi tiết xếp lịch hệ thống ---")
                            for line in logs:
                                log.info(line)

                last_max_id, last_unscheduled = _get_db_state(db_path)

        except Exception as e:
            log.error(f"Lỗi trong vòng lặp watcher: {e}", exc_info=True)

    log.info("Watcher đã dừng.")


class AutoCheckWatcher:
    def __init__(self, poll_interval: int = POLL_INTERVAL, db_path: str = DB_PATH):
        self.poll_interval = poll_interval
        self.db_path = db_path
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=_watch_loop,
            args=(self.poll_interval, self.db_path, self._stop_event),
            daemon=True,
            name="AutoCheckThread"
        )
        self._thread.start()
        log.info("Thread AutoCheck đã chạy ngầm.")

    def stop(self, timeout: float = 5.0):
        if not self._thread:
            return
        log.info("Đang yêu cầu dừng AutoCheck...")
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        log.info("AutoCheck đã tắt.")