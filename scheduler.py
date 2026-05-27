import sqlite3
from datetime import datetime, timedelta, date
from typing import Optional

DB_PATH = "agent_storage.db"

SESSION_HOURS = 3          
MAX_SESSIONS_PER_DAY = 5   

FORBIDDEN_RANGES = [
    (0, 4),   
    (6, 7),   
    (11, 13),  
    (19, 20),  
]
VALID_START_HOURS = [7, 8, 9, 10, 13, 14, 15, 16, 17, 18]

def _is_forbidden(hour: int) -> bool:
    for (s, e) in FORBIDDEN_RANGES:
        if s <= hour < e:
            return True
    return False


def _valid_starts_for_day(day: date) -> list[datetime]:
    result = []
    for h in VALID_START_HOURS:
        end_h = h + SESSION_HOURS
        blocked = any(_is_forbidden(t) for t in range(h, end_h))
        if not blocked:
            result.append(datetime(day.year, day.month, day.day, h, 0))
    return result


def _sessions_on_day(cursor, target_date: date) -> list[dict]:
    d_str = target_date.strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT SESSION_ID, TASK_ID, START_TIME, END_TIME
        FROM SESSIONS
        WHERE date(START_TIME) = ?
        ORDER BY START_TIME
    """, (d_str,))
    rows = cursor.fetchall()
    return [{"session_id": r[0], "task_id": r[1],
             "start": r[2], "end": r[3]} for r in rows]


def _is_overlap_dt(start1: datetime, end1: datetime,
                   start2: datetime, end2: datetime) -> bool:
    return not (end1 <= start2 or start1 >= end2)


def _slot_is_free(cursor, start_dt: datetime, end_dt: datetime,
                  pending_sessions: list[dict]) -> bool:
    start_s = start_dt.strftime("%Y-%m-%d %H:%M")
    end_s = end_dt.strftime("%Y-%m-%d %H:%M")

    cursor.execute("""
        SELECT 1 FROM SESSIONS
        WHERE NOT (END_TIME <= ? OR START_TIME >= ?)
        LIMIT 1
    """, (start_s, end_s))
    if cursor.fetchone():
        return False

    for ps in pending_sessions:
        ps_start = datetime.strptime(ps["start"], "%Y-%m-%d %H:%M")
        ps_end = datetime.strptime(ps["end"], "%Y-%m-%d %H:%M")
        if _is_overlap_dt(start_dt, end_dt, ps_start, ps_end):
            return False

    return True

def _compute_start_day(deadline: Optional[str],
                       urgency_rank: int,
                       total_tasks: int,
                       today: date) -> date:
    if not deadline:
        return today + timedelta(days=urgency_rank + 1)

    try:
        dl = datetime.strptime(deadline[:10], "%Y-%m-%d").date()
    except ValueError:
        return today + timedelta(days=urgency_rank + 1)

    days_left = (dl - today).days
    if days_left <= 0:
        return today  
    if total_tasks <= 1:
        offset = 0
    else:
        ratio = urgency_rank / (total_tasks - 1)  
        max_offset = max(0, days_left - 1)
        offset = int(ratio * max_offset)

    return today + timedelta(days=offset)

def _find_free_day(cursor,
                   from_day: date,
                   deadline_day: Optional[date],
                   pending_sessions: list[dict],
                   look_ahead: int = 60) -> Optional[date]:
    limit = deadline_day if deadline_day else (from_day + timedelta(days=look_ahead))

    d = from_day
    while d <= limit:
        existing = _sessions_on_day(cursor, d)
        pending_today = sum(
            1 for ps in pending_sessions
            if ps["start"].startswith(d.strftime("%Y-%m-%d"))
        )
        if len(existing) + pending_today < MAX_SESSIONS_PER_DAY:
            return d
        d += timedelta(days=1)

    cursor.execute("""
        SELECT DISTINCT date(T.DEADLINE)
        FROM TASKS T
        JOIN SESSIONS S ON T.TASK_ID = S.TASK_ID
        WHERE date(T.DEADLINE) BETWEEN ? AND ?
        ORDER BY date(T.DEADLINE)
    """, (from_day.strftime("%Y-%m-%d"), limit.strftime("%Y-%m-%d")))

    expiry_dates = [row[0] for row in cursor.fetchall() if row[0]]

    for ed_str in expiry_dates:
        ed = datetime.strptime(ed_str, "%Y-%m-%d").date()
        candidate = ed + timedelta(days=1)
        if candidate > limit:
            continue
        existing = _sessions_on_day(cursor, candidate)
        pending_today = sum(
            1 for ps in pending_sessions
            if ps["start"].startswith(candidate.strftime("%Y-%m-%d"))
        )
        if len(existing) + pending_today < MAX_SESSIONS_PER_DAY:
            return candidate

    return None

def _schedule_one_task(cursor,
                        task_id: int,
                        title: str,
                        deadline: Optional[str],
                        sessions_needed: int,
                        start_day: date,
                        pending_sessions: list[dict]) -> list[dict]:
    dl_date = None
    if deadline:
        try:
            dl_date = datetime.strptime(deadline[:10], "%Y-%m-%d").date()
        except ValueError:
            pass

    new_sessions = []
    current_day = start_day
    remaining = sessions_needed

    while remaining > 0:
        free_day = _find_free_day(cursor, current_day, dl_date,
                                   pending_sessions + new_sessions)
        if free_day is None:
            return []

        valid_starts = _valid_starts_for_day(free_day)
        placed = False
        for s_dt in valid_starts:
            e_dt = s_dt + timedelta(hours=SESSION_HOURS)
            all_pending = pending_sessions + new_sessions
            if _slot_is_free(cursor, s_dt, e_dt, all_pending):
                new_sessions.append({
                    "task_id": task_id,
                    "start": s_dt.strftime("%Y-%m-%d %H:%M"),
                    "end": e_dt.strftime("%Y-%m-%d %H:%M"),
                })
                remaining -= 1
                placed = True
                if remaining == 0:
                    break

        current_day = free_day + timedelta(days=1)

    return new_sessions

def auto_schedule(db_path: str = DB_PATH) -> dict:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    today = date.today()

    cursor.execute("""
        SELECT T.TASK_ID, T.TITLE, T.DEADLINE,
               COUNT(S.SESSION_ID) AS session_count,
               T.SESSIONS_NEEDED
        FROM TASKS T
        LEFT JOIN SESSIONS S ON T.TASK_ID = S.TASK_ID
        WHERE T.DEADLINE IS NOT NULL   
        GROUP BY T.TASK_ID
        HAVING session_count < T.SESSIONS_NEEDED
        ORDER BY date(T.DEADLINE)
    """)

    tasks = cursor.fetchall()  

    if not tasks:
        conn.close()
        return {"message": "Tất cả công việc đã được xếp lịch trước đó.", "task_logs": [], "scheduled": [], "failed": []}

    total_tasks = len(tasks)
    pending_sessions: list[dict] = []   
    result_scheduled = []
    result_failed = []
    task_logs = []  

    for rank, (task_id, title, deadline, current_count, sessions_needed) in enumerate(tasks):
        needed = sessions_needed - current_count
        if needed <= 0:
            continue

        start_day = _compute_start_day(deadline, rank, total_tasks, today)

        
        task_logs.append(
            f"[{rank+1}/{total_tasks}] '{title}' | deadline={deadline} "
            f"| cần {needed} session | dự kiến bắt đầu từ {start_day}"
        )

        new_sessions = _schedule_one_task(
            cursor, task_id, title, deadline,
            needed, start_day, pending_sessions
        )

        if new_sessions:
            pending_sessions.extend(new_sessions)
            result_scheduled.append({
                "task_id": task_id,
                "title": title,
                "sessions": new_sessions,
            })
            for s in new_sessions:
                task_logs.append(f"   ✓ Thành công: {s['start']} → {s['end']}")
        else:
            result_failed.append({"task_id": task_id, "title": title})
            task_logs.append(f"Thất bại: '{title}' không tìm thấy slot trống phù hợp.")

    
    for ps in pending_sessions:
        cursor.execute("""
            INSERT INTO SESSIONS (TASK_ID, START_TIME, END_TIME)
            VALUES (?, ?, ?)
        """, (ps["task_id"], ps["start"], ps["end"]))

    conn.commit()
    conn.close()

    return {
        "message": f"Đã xếp lịch: {len(result_scheduled)} task | Thất bại: {len(result_failed)} task",
        "task_logs": task_logs,
        "scheduled": result_scheduled,
        "failed": result_failed
    }