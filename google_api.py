import os.path
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',  # Quyền Gmail
    'https://www.googleapis.com/auth/calendar',      # Quyền Lịch
    'https://www.googleapis.com/auth/tasks'          # Quyền Tasks (Mới thêm)
]

# Chỉ dùng duy nhất 1 file cấu hình cho toàn hệ thống
TOKEN_FILE = 'token.json'

def get_google_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('tasks', 'v1', credentials=creds)

def create_google_task(title, deadline_str=None):
    """Tạo một task mới trên Google và trả về ID của task đó"""
    service = get_google_service()
    task_body = {'title': title}
    
    if deadline_str:
        try:
            # Google API yêu cầu giờ định dạng RFC 3339 (chứa chữ T và Z)
            dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
            task_body['due'] = dt.isoformat() + 'Z'
        except Exception:
            pass # Nếu lỗi định dạng thời gian thì bỏ qua, chỉ tạo tên task

    result = service.tasks().insert(tasklist='@default', body=task_body).execute()
    return result.get('id')

def update_google_task_status(google_task_id, status='completed'):
    """Cập nhật trạng thái task. status có thể là 'completed' hoặc 'needsAction' (chưa xong)"""
    service = get_google_service()
    try:
        # Lấy thông tin task cũ về
        task = service.tasks().get(tasklist='@default', task=google_task_id).execute()
        # Đổi trạng thái
        task['status'] = status
        # Đẩy dữ liệu mới lên
        service.tasks().update(tasklist='@default', task=google_task_id, body=task).execute()
        return True
    except Exception as e:
        print(f"Lỗi cập nhật lên Google Task: {e}")
        return False

def get_incomplete_google_tasks():
    """Chỉ lấy về những task chưa hoàn thành từ Google (trạng thái needsAction)"""
    service = get_google_service()
    # Tham số showCompleted=False sẽ lọc tự động
    results = service.tasks().list(tasklist='@default', showCompleted=False).execute()
    return results.get('items', [])
def delete_google_task(google_task_id):
    """Xóa hoàn toàn một task khỏi Google Tasks"""
    service = get_google_service()
    try:
        service.tasks().delete(tasklist='@default', task=google_task_id).execute()
        return True
    except Exception as e:
        print(f"Lỗi khi xóa trên Google Task: {e}")
        return False