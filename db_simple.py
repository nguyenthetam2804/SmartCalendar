import sqlite3
from datetime import datetime, timedelta

def create_database():
    # Kết nối đến file agent_storage để lấy dtb (các table phía dưới đuôi lưu tại đây)
    conn = sqlite3.connect('agent_storage.db') 
    cursor = conn.cursor()
    
    # Bảng lưu các task
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS TASKS(
            TASK_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TITLE TEXT,
            DEADLINE DATETIME,
            SESSIONS_NEEDED INTEGER DEFAULT 1
        )''')
    # Bảng lưu session (lịch chi tiết)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS SESSIONS(
            SESSION_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TASK_ID INTEGER,
            START_TIME DATETIME,
            END_TIME DATETIME,
            FOREIGN KEY (TASK_ID) REFERENCES TASKS(TASK_ID)
        )''')
    
    # Bảng lưu lịch sử chat
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS CHAT_HIS(
            CHAT_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            CONTENT TEXT,
            TIME_CHAT DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
                   
    # Lọc email đọc hay chưa
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Ma_Emails(
            EMAIL_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            SUBJECT TEXT,
            PROCESSED_AT DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')

    conn.commit()
    conn.close()
    
    return "Khởi tạo thành công cấu trúc hệ thống Database."
    
def handle_reschedule_specific(search_keyword: str, new_start: str, old_date: str):
    if not old_date or old_date.strip() == "null" or old_date.strip() == "":
        return "Lỗi: Vui lòng cung cấp ngày cần dời lịch."

    conn = sqlite3.connect('agent_storage.db')
    cursor = conn.cursor()
    cursor.execute("SELECT TASK_ID, TITLE FROM TASKS WHERE TITLE LIKE ? LIMIT 1", (f'%{search_keyword}%',))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return f"Không tìm thấy công việc nào khớp với từ khóa '{search_keyword}'."
    task_id, title = task
    cursor.execute("""
        SELECT START_TIME, END_TIME 
        FROM SESSIONS 
        WHERE TASK_ID = ? AND date(START_TIME) = date(?)
    """, (task_id, old_date))
    sessions_today = cursor.fetchall()

    if not sessions_today:
        conn.close()
        return f"Vào ngày {old_date}, công việc '{title}' không có lịch trình nào để dời."

    total_hours_to_move = 0
    for st, en in sessions_today:
        cursor.execute("SELECT (julianday(?) - julianday(?)) * 24", (en, st))
        res = cursor.fetchone()
        if res and res[0]:
            total_hours_to_move += res[0]

    total_hours_to_move = round(total_hours_to_move)
    if total_hours_to_move <= 0:
        total_hours_to_move = 3 
    new_start_clean = new_start.strip()
    has_time = len(new_start_clean) > 10  

    from scheduler import _is_forbidden, _get_free_slots_in_day
    from datetime import datetime, timedelta

    sessions_to_insert = []
    current_session_start = None
    current_session_end = None
    hours_placed = 0

    if has_time:
        try:
            current_slot = datetime.strptime(new_start_clean, "%Y-%m-%d %H:%M")
        except ValueError:
            conn.close()
            return f"Lỗi định dạng thời gian mới: {new_start_clean}"

        while hours_placed < total_hours_to_move:
            if _is_forbidden(current_slot.hour):
                if current_session_start and current_session_end:
                    sessions_to_insert.append((current_session_start, current_session_end))
                    current_session_start = None
                    current_session_end = None
                current_slot += timedelta(hours=1)
                continue
                
            slot_end = current_slot + timedelta(hours=1)
            cursor.execute("""
                SELECT 1 FROM SESSIONS
                WHERE NOT (END_TIME <= ? OR START_TIME >= ?)
                AND NOT (TASK_ID = ? AND date(START_TIME) = date(?))
                LIMIT 1
            """, (current_slot.strftime("%Y-%m-%d %H:%M"), slot_end.strftime("%Y-%m-%d %H:%M"), task_id, old_date))
            
            if cursor.fetchone():
                if current_session_start and current_session_end:
                    sessions_to_insert.append((current_session_start, current_session_end))
                    current_session_start = None
                    current_session_end = None
                current_slot += timedelta(hours=1)
                continue
                
            if current_session_start is None:
                current_session_start = current_slot
                current_session_end = slot_end
            elif current_slot == current_session_end:
                current_session_end = slot_end
            else:
                sessions_to_insert.append((current_session_start, current_session_end))
                current_session_start = current_slot
                current_session_end = slot_end

            current_slot = slot_end
            hours_placed += 1

        if current_session_start and current_session_end:
            sessions_to_insert.append((current_session_start, current_session_end))

    else:
        try:
            target_date = datetime.strptime(new_start_clean[:10], "%Y-%m-%d").date()
        except ValueError:
            conn.close()
            return f"Lỗi định dạng ngày mới: {new_start_clean}"

        day_free_slots = _get_free_slots_in_day(cursor, target_date, [])
        if not day_free_slots:
            conn.close()
            return f"Thất bại: Ngày mới {new_start_clean} không còn slot trống."

        for slot_start, slot_end in day_free_slots:
            if hours_placed >= total_hours_to_move:
                break

            if current_session_start is None:
                current_session_start = slot_start
                current_session_end = slot_end
            elif slot_start == current_session_end:
                current_session_end = slot_end
            else:
                sessions_to_insert.append((current_session_start, current_session_end))
                current_session_start = slot_start
                current_session_end = slot_end

            hours_placed += 1

        if current_session_start and current_session_end:
            sessions_to_insert.append((current_session_start, current_session_end))
    if hours_placed < total_hours_to_move:
        conn.close()
        return f"Thất bại: Không đủ thời gian trống ở lịch mới"
    try:
        cursor.execute("""
            DELETE FROM SESSIONS 
            WHERE TASK_ID = ? AND date(START_TIME) = date(?)
        """, (task_id, old_date))
        for start_dt, end_dt in sessions_to_insert:
            cursor.execute("""
                INSERT INTO SESSIONS (TASK_ID, START_TIME, END_TIME)
                VALUES (?, ?, ?)
            """, (task_id, start_dt.strftime("%Y-%m-%d %H:%M"), end_dt.strftime("%Y-%m-%d %H:%M")))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return f"Lỗi hệ thống khi dời lịch: {str(e)}"
    conn.close()
    return f"Đã dời thành công lịch của việc '{title}' ở ngày {old_date} sang ngày mới {new_start_clean}"

# --- XÓA TASK ---
def handle_delete_task(search_keyword):
    conn = sqlite3.connect('agent_storage.db')
    cursor = conn.cursor()

    # 1. Tìm task
    cursor.execute("SELECT TASK_ID FROM TASKS WHERE TITLE LIKE ?", (f'%{search_keyword}%',))
    task = cursor.fetchone()

    if task:
        task_id = task[0]
        cursor.execute("DELETE FROM SESSIONS WHERE TASK_ID = ?", (task_id,))
        cursor.execute("DELETE FROM TASKS WHERE TASK_ID = ?", (task_id,))
        
        conn.commit()
        conn.close()
        return f"Đã xóa hoàn toàn Task ID {task_id} và giải phóng các slot lịch tương ứng."
    
    conn.close()
    return f"Không tìm thấy công việc nào khớp với từ khóa '{search_keyword}' để thực hiện xóa."


# --- PHÂN TÍCH MẬT ĐỘ LỊCH TRÌNH ---
def analyze_workload(target_date):
    conn = sqlite3.connect('agent_storage.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) 
        FROM TASKS 
        WHERE date(DEADLINE) = ?
    """, (target_date,))

    count = cursor.fetchone()[0] or 0
    conn.close()

    if count == 0:
        return "Lịch trình trống"
    if count > 3:
        return "Lịch trình quá tải."
    return "Lịch trình ổn định"

if __name__ == "__main__":
    thong_bao = create_database()
    print(thong_bao)