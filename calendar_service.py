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
                'dateTime': end_time_str, 
                'timeZone': 'Asia/Ho_Chi_Minh',
            },
        }

        event = service.events().insert(calendarId='primary', body=event).execute()
        raw_id = event.get('id')
        
        if raw_id and raw_id.startswith('_'):
            raw_id = raw_id[1:]
            
        return True, raw_id
    except Exception as e:
        return False, str(e)
    
def get_logged_in_user_email():
    try:
        service = get_calendar_service()
        calendar_metadata = service.calendars().get(calendarId='primary').execute()
        return calendar_metadata.get('id')
    except Exception as e:
        print(f"Lỗi lấy thông tin email: {e}")
        return None

def delete_event(event_id, calendar_id='primary'):
    service = get_calendar_service()
    clean_id = str(event_id).strip()
    if clean_id.startswith('_'):
        clean_id = clean_id[1:]
    service.events().delete(calendarId=calendar_id, eventId=clean_id).execute()
    return True