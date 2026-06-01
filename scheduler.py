import sqlite3
from datetime import datetime, timedelta, date
from typing import Optional

DB_PATH = "agent_storage.db"

SESSION_HOURS = 3          
MAX_SESSIONS_PER_DAY = 5   

# Khung giờ nghỉ/bận cố định
FORBIDDEN_RANGES = [
    (0, 4),   
    (6, 7),   
    (11, 13),  
    (19, 20),  
]

def _is_forbidden(hour: int) -> bool:
    for (s, e) in FORBIDDEN_RANGES:
        if s <= hour < e:
            return True
    return False

def _get_free_slots_in_day(cursor, target_date: date, pending_sessions: list[dict]) -> list[tuple[datetime, datetime]]:
    """
    Quét chi tiết từng block 1 tiếng trong ngày để tìm khoảng trống thực tế
    """
    free_slots = []
    start_hour = 0
    
    while start_hour < 24:
        if _is_forbidden(start_hour):
            start_hour += 1
            continue
            
        slot_start = datetime(target_date.year, target_date.month, target_date.day, start_hour, 0)
        slot_end = slot_start + timedelta(hours=1)
        
        slot_start_str = slot_start.strftime("%Y-%m-%d %H:%M")
        slot_end_str = slot_end.strftime("%Y-%m-%d %H:%M")
        
        # Kiểm tra DB trùng lịch
        cursor.execute("""
            SELECT 1 FROM SESSIONS
            WHERE NOT (END_TIME <= ? OR START_TIME >= ?)
            LIMIT 1
        """, (slot_start_str, slot_end_str))
        
        if cursor.fetchone():
            start_hour += 1
            continue
            
        # Kiểm tra hàng đợi pending trùng lịch
        is_pending_overlap = False
        for ps in pending_sessions:
            ps_start = datetime.strptime(ps["start"], "%Y-%m-%d %H:%M")
            ps_end = datetime.strptime(ps["end"], "%Y-%m-%d %H:%M")
            if not (slot_end <= ps_start or slot_start >= ps_end):
                is_pending_overlap = True
                break
                
        if is_pending_overlap:
            start_hour += 1
            continue
            
        free_slots.append((slot_start, slot_end))
        start_hour += 1
        
    return free_slots

def _find_free_day(cursor, from_day: date, deadline_day: Optional[date], pending_sessions: list[dict], look_ahead: int = 60) -> Optional[date]:
    # Cho phép hệ thống quét tìm slot thoải mái trong khoảng look_ahead ngày.
    limit = from_day + timedelta(days=look_ahead)
    d = from_day
    while d <= limit:
        cursor.execute("SELECT COUNT(*) FROM SESSIONS WHERE date(START_TIME) = ?", (d.strftime("%Y-%m-%d"),))
        existing_count = cursor.fetchone()[0] or 0
        pending_today = sum(1 for ps in pending_sessions if ps["start"].startswith(d.strftime("%Y-%m-%d")))
        
        if existing_count + pending_today < MAX_SESSIONS_PER_DAY:
            return d
        d += timedelta(days=1)
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
    
    # Quy đổi tổng số giờ cần phân bổ (Ví dụ: 3 sessions * 3h = 9 giờ cần xếp)
    hours_needed = sessions_needed * SESSION_HOURS 

    while hours_needed > 0:
        free_day = _find_free_day(cursor, current_day, dl_date, pending_sessions + new_sessions)
        if free_day is None:
            break

        day_free_slots = _get_free_slots_in_day(cursor, free_day, pending_sessions + new_sessions)
        
        if not day_free_slots:
            current_day = free_day + timedelta(days=1)
            continue

        # Đặt giới hạn giờ làm việc của công việc này trong ngày để bắt buộc CHIA ĐỀU LỊCH
        if dl_date:
            days_left = (dl_date - free_day).days
            if days_left <= 1:
                max_hours_today = 6   # Sát hạn: Cho phép làm tối đa 6 tiếng/ngày (2 sessions)
            elif hours_needed >= days_left * 4:
                max_hours_today = 6   # Gấp: Tối đa 6 tiếng/ngày
            else:
                max_hours_today = 3   # Thong thả: ÉP LÀM ĐÚNG 3 TIẾNG/NGÀY rồi nhảy sang ngày khác
        else:
            max_hours_today = 3

        current_session_start = None
        current_session_end = None
        hours_contributed_today = 0
        
        for slot_start, slot_end in day_free_slots:
            if hours_needed <= 0 or hours_contributed_today >= max_hours_today:
                break
                
            if current_session_start is None:
                current_session_start = slot_start
                current_session_end = slot_end
            elif slot_start == current_session_end:
                current_session_end = slot_end
            else:
                # Bị ngắt quãng do dính khung giờ cấm -> Chốt session cũ
                duration = (current_session_end - current_session_start).total_seconds() / 3600
                if duration >= 1.0:
                    new_sessions.append({
                        "task_id": task_id,
                        "start": current_session_start.strftime("%Y-%m-%d %H:%M"),
                        "end": current_session_end.strftime("%Y-%m-%d %H:%M")
                    })
                current_session_start = slot_start
                current_session_end = slot_end
                
            hours_needed -= 1
            hours_contributed_today += 1

        # Chốt khối thời gian cuối cùng của ngày hôm nay
        if current_session_start and current_session_end:
            duration = (current_session_end - current_session_start).total_seconds() / 3600
            if duration >= 1.0:
                new_sessions.append({
                    "task_id": task_id,
                    "start": current_session_start.strftime("%Y-%m-%d %H:%M"),
                    "end": current_session_end.strftime("%Y-%m-%d %H:%M")
                })

        # BẮT BUỘC: Xử lý xong ngày hiện tại là phải nhảy sang ngày hôm sau ngay
        # để đảm bảo phân rã đều lịch ra, không dồn cục một ngày
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

        # Tính ngày bắt đầu phân bổ dựa theo thứ tự ưu tiên deadline
        def _compute_start_day(deadline: Optional[str], urgency_rank: int, total_tasks: int, today: date) -> date:
            if not deadline: return today
            try: dl = datetime.strptime(deadline[:10], "%Y-%m-%d").date()
            except ValueError: return today
            days_left = (dl - today).days
            if days_left <= 0: return today  
            offset = 0 if total_tasks <= 1 else int((urgency_rank / (total_tasks - 1)) * max(0, days_left - 1))
            return today + timedelta(days=offset)

        start_day = _compute_start_day(deadline, rank, total_tasks, today)

        task_logs.append(
            f"[{rank+1}/{total_tasks}] '{title}' | deadline={deadline} "
            f"| cần phân bổ tiếp {needed * SESSION_HOURS} giờ | dự kiến từ {start_day}"
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
                task_logs.append(f"   ✓ Phân bổ thành công: {s['start']} → {s['end']}")
        else:
            result_failed.append({"task_id": task_id, "title": title})
            task_logs.append(f"Thất bại: '{title}' không đủ slot trống.")

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