import sqlite3
from google_api import create_google_task

def sync_null_deadline_tasks():
    # 1. Kết nối vào đúng cấu trúc DB gốc của bạn
    conn = sqlite3.connect('agent_storage.db')
    cursor = conn.cursor()

    # 2. 🌟 ĐÃ SỬA: Lọc theo GOOGLE_TASK_ID IS NULL (những việc chưa từng đồng bộ)
    cursor.execute("SELECT TASK_ID, TITLE FROM TASKS WHERE DEADLINE IS NULL AND GOOGLE_TASK_ID IS NULL")
    tasks = cursor.fetchall()

    if not tasks:
        print("Khong co cong viec nao khong co deadline de dong bo.")
        conn.close()
        return

    print(f"🔎 Tim thay {len(tasks)} cong viec co deadline = NULL. Dang day len Google Tasks...")

    # 3. Đẩy từng task lên Google Tasks
    count = 0
    for task in tasks:
        task_id = task[0]
        title = task[1]
        
        try:
            # 🌟 ĐÃ SỬA: Hàm này sẽ trả về 1 chuỗi mã ID từ Google Cloud (Ví dụ: 'MHg3M...')
            g_task_id = create_google_task(title, None) 
            
            # 🌟 ĐÃ THÊM: Nếu tạo thành công trên Google, lưu ngay mã ID đó vào DB cục bộ
            if g_task_id:
                cursor.execute("UPDATE TASKS SET GOOGLE_TASK_ID = ? WHERE TASK_ID = ?", (g_task_id, task_id))
                print(f"  ✓ Da day thanh cong va luu ID: {title}")
                count += 1
                
        except Exception as e:
            print(f"  ❌ Loi khi day task '{title}': {e}")

    # 🌟 ĐÃ THÊM: Luôn luôn Commit để ghi nhận thay đổi UPDATE vào file DB
    conn.commit()
    conn.close()
    print(f"\n✅ Hoan tat! Da dong bo {count}/{len(tasks)} cong viec len Google Tasks.")

if __name__ == "__main__":
    sync_null_deadline_tasks()