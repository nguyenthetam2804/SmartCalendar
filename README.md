B1:
# 1. Tạo môi trường ảo mới 
python -m venv venv

# 2. Kích hoạt môi trường ảo lên
# Đối với Windows (nếu dùng PowerShell):
.\venv\Scripts\activate

# Đối với Windows (nếu dùng CMD):
.\venv\Scripts\activate.bat

cài đặt 1 cột cho ggtask

python -c "import sqlite3; conn = sqlite3.connect('agent_storage.db'); cursor = conn.cursor(); cursor.execute('ALTER TABLE TASKS ADD COLUMN GOOGLE_TASK_ID TEXT DEFAULT NULL;'); conn.commit(); conn.close(); print('🎉 Đã chèn cột GOOGLE_TASK_ID thành công!')"

B2: Cài đặt toàn bộ thư viện bằng 1 lệnh
pip install -r requirements.txt

B3: cho file credentials.json vào thư mục (hoặc tự lấy trên gg console)

B4: Cài đặt Groq API Key trên file insert

B5: streamlit run streamlita.py để chạy

*Chú ý
Nếu db lỗi thì chạy riêng để khởi tạo db bằng lệnh này trước rồi chạy ctrinh
python db_simple.py
