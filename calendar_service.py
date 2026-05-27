import datetime
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Quyền truy cập: Đọc và ghi lịch
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',  # Quyền đọc/sửa Gmail
    'https://www.googleapis.com/auth/calendar',       # Quyền đọc/ghi Lịch
    'https://www.googleapis.com/auth/tasks'
]
TOKEN_FILE = 'token.json'
def get_calendar_service():
    creds = None
    # File token.json lưu trữ quyền đăng nhập của người dùng
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # Nếu không có token hợp lệ, bắt đầu đăng nhập
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Lưu lại token cho lần sau
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)

def create_event(summary, start_time_str, end_time_str, description=""):
    try:
        service = get_calendar_service()
        
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time_str,
                'timeZone': 'Asia/Ho_Chi_Minh',
            },
            'end': {
                'dateTime': end_time_str, # Thêm thời gian kết thúc chuẩn ở đây
                'timeZone': 'Asia/Ho_Chi_Minh',
            },
        }

        event = service.events().insert(calendarId='primary', body=event).execute()
        return True, event.get('htmlLink')
    except Exception as e:
        return False, str(e)
    
def get_logged_in_user_email():
    """
    Tự động gọi Google API để lấy chính xác địa chỉ Email 
    của tài khoản đang đăng nhập hiện tại trong token.json
    """
    try:
        # Gọi lại hàm lấy service bạn đã viết ở trên
        service = get_calendar_service()
        
        # Lấy thông tin chi tiết của bộ lịch chính ('primary') - chính là email của chủ tài khoản
        calendar_metadata = service.calendars().get(calendarId='primary').execute()
        
        # Trường 'id' của lịch primary luôn luôn trả về địa chỉ Email (VD: nguyenthetam@gmail.com)
        return calendar_metadata.get('id')
    except Exception as e:
        print(f"Lỗi lấy thông tin email: {e}")
        return None