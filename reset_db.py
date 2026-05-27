import sqlite3

def reset_database():
    conn = sqlite3.connect('agent_storage.db')
    cursor = conn.cursor()
    
    try:
        # Xóa dữ liệu trong bảng SESSIONS (Lịch chi tiết)
        cursor.execute("DELETE FROM SESSIONS;")
        
        # Xóa dữ liệu trong bảng TASKS (Danh sách công việc thô)
        cursor.execute("DELETE FROM TASKS;")
        
        # Reset lại bộ đếm ID tự động tăng về 0
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('TASKS', 'SESSIONS');")
        
        conn.commit()
        print("🎉 Đã xóa sạch dữ liệu trong các bảng TASKS và SESSIONS thành công!")
    except sqlite3.OperationalError as e:
        print(f"❌ Lỗi: {e} (Có thể bảng chưa được tạo hoặc sai tên bảng)")
    finally:
        conn.close()

if __name__ == "__main__":
    reset_database()