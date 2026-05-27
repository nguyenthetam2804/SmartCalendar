import sqlite3
from datetime import datetime

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
    
# --- DỜI TASK ---
def handle_reschedule_specific(search_keyword, new_start):
    conn = sqlite3.connect('agent_storage.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TASK_ID, TITLE
        FROM TASKS
        WHERE TITLE LIKE ?
        LIMIT 1
    """, (f'%{search_keyword}%',))

    task = cursor.fetchone()

    if not task:
        conn.close()
        return "Không tìm thấy task để điều chỉnh"

    task_id, title = task
    cursor.execute("""
        SELECT SESSION_ID, START_TIME, END_TIME
        FROM SESSIONS
        WHERE TASK_ID = ?
        ORDER BY abs(strftime('%s', START_TIME) - strftime('%s', 'now'))
        LIMIT 1
    """, (task_id,))

    session = cursor.fetchone()

    if not session:
        conn.close()
        return "Task hiện tại chưa được xếp session nào để dời."

    session_id, old_start, old_end = session
    cursor.execute("""
        SELECT (julianday(?) - julianday(?)) * 24
    """, (old_end, old_start))

    row = cursor.fetchone()
    duration = row[0] if row else 0
    cursor.execute("""
        SELECT datetime(?, '+' || ? || ' hours')
    """, (new_start, duration))

    new_end = cursor.fetchone()[0]
    cursor.execute("""
        SELECT 1 FROM SESSIONS
        WHERE SESSION_ID != ?
        AND NOT (END_TIME <= ? OR START_TIME >= ?)
        LIMIT 1
    """, (session_id, new_start, new_end))
    
    if cursor.fetchone():
        conn.close()
        return f"Thời gian mới đề xuất cho '{title}' bị trùng với lịch cố định khác."
    cursor.execute("""
        UPDATE SESSIONS
        SET START_TIME = ?, END_TIME = ?
        WHERE SESSION_ID = ?
    """, (new_start, new_end, session_id))

    conn.commit()
    conn.close()

    return f"Hệ thống đã dời session thành công của việc: '{title}' sang {new_start}."


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