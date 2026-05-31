"""
================================================================================
  mail_worker.py
  Môn   : Lập trình ứng dụng
  Phần  : Gmail Module - Smart Task Planner Agent
  Nhiệm vụ: Kết nối Gmail → Lọc spam → Trả ra danh sách email hợp lệ
================================================================================

  CHỨC NĂNG:
    1. Xác thực OAuth2 với Google (tự động refresh token)
    2. Quét hòm thư lấy email CHƯA ĐỌC trong INBOX
    3. Lọc spam 4 tầng:
         Tầng 1 - Google tự gắn nhãn SPAM
         Tầng 2 - Gmail phân loại tab tự động (Quảng cáo, Cập nhật...)
         Tầng 3 - Header List-Unsubscribe (mail marketing/newsletter)
         Tầng 4 - Từ khóa trong subject/sender
    4. Trích xuất nội dung text từ email (xử lý cả multipart lồng nhau)
    5. Trả ra list email hợp lệ cho các module khác xử lý
    6. Đánh dấu đã đọc trên Gmail sau khi xử lý


================================================================================
"""

import os
import base64
import schedule
import time
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# CẤU HÌNH 

# Quyền truy cập Gmail: đọc mail + đánh dấu đã đọc
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',  # Quyền đọc/sửa Gmail
    'https://www.googleapis.com/auth/calendar',     # Quyền đọc/ghi Lịch
    'https://www.googleapis.com/auth/tasks'
]
TOKEN_FILE = 'token.json'
# Tần suất quét hòm thư (phút)
CHECK_INTERVAL_MINUTES = 5

# Tầng 4: Từ khóa nhận biết mail quảng cáo/tự động
SPAM_KEYWORDS = [
    "quảng cáo", "[qc]", "shopee", "lazada", "tiki",
    "khuyến mãi", "flash sale", "ưu đãi", "giảm giá",
    "miễn phí", "trúng thưởng"
]

# Tầng 2: Nhãn Gmail tự động phân loại
AUTO_LABELS = [
    'CATEGORY_PROMOTIONS',  # Tab Quảng cáo
    'CATEGORY_UPDATES',     # Tab Cập nhật
    'CATEGORY_FORUMS',      # Tab Diễn đàn
    'CATEGORY_SOCIAL'       # Tab Mạng xã hội
]
class GmailWorker:
    """
    Class chính của Gmail Module.

    Đóng gói toàn bộ logic kết nối Gmail, lọc spam và trích xuất nội dung.
    Các module khác chỉ cần khởi tạo class và gọi get_new_emails().
    """

    def __init__(self):
        print(" Khởi động Gmail Worker...")
        self._credentials = self._authenticate()
        self._service     = build('gmail', 'v1', credentials=self._credentials)
        print(" Gmail Worker sẵn sàng!\n")

    #   XÁC THỰC GOOGLE (OAuth2)

    def _authenticate(self):
        """
        Xử lý luồng OAuth2 gộp với Google.

        Đọc và ghi duy nhất vào file token.json (chứa cả quyền Gmail + Calendar).
        Lần đầu chạy : mở trình duyệt đăng nhập 1 lần tích 2 ô quyền -> lưu token.json
        Lần sau       : đọc token.json, tự refresh nếu hết hạn
        """
        creds = None

        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("  Token hết hạn, đang tự động làm mới...")
                creds.refresh(Request())
            else:
                print("  Mở trình duyệt để xin quyền gộp (Gmail + Calendar) lần đầu...")
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)

            with open(TOKEN_FILE, 'w') as f:
                f.write(creds.to_json())
            print(" Xác thực thành công! Đã lưu token đồng bộ Gmail và Calendar.")

        return creds

    #   LỌC SPAM - 4 TẦNG

    def _is_google_spam(self, label_ids):
        """
        Tầng 1: Google đã tự gắn nhãn SPAM chưa?

        Google tự động phát hiện spam dựa trên nhiều yếu tố phức tạp.
        Đây là tầng lọc đầu tiên và đáng tin cậy nhất.

        Args:
            label_ids (list): Danh sách nhãn Gmail. VD: ['INBOX', 'UNREAD']

        Returns:
            bool: True nếu mail bị Google đánh dấu SPAM
        """
        return 'SPAM' in (label_ids or [])

    def _is_auto_category(self, label_ids):
        """
        Tầng 2: Gmail tự phân loại mail vào các tab không phải Primary.

        Gmail phân loại mail vào 5 tab:
          Primary (INBOX)   → mail quan trọng, cần xử lý  
          Promotions        → quảng cáo, khuyến mãi        
          Updates           → thông báo hệ thống, hóa đơn  
          Forums            → diễn đàn, group email        
          Social            → Facebook, Twitter...          

        Mail ngoài Primary thường không cần tạo task.

        Args:
            label_ids (list): Danh sách nhãn Gmail

        Returns:
            (bool, str): (True, tên_tab) nếu là auto category
        """
        label_names = {
            'CATEGORY_PROMOTIONS': 'Tab Quảng cáo',
            'CATEGORY_UPDATES'   : 'Tab Cập nhật',
            'CATEGORY_FORUMS'    : 'Tab Diễn đàn',
            'CATEGORY_SOCIAL'    : 'Tab Mạng xã hội'
        }
        for label, name in label_names.items():
            if label in (label_ids or []):
                return True, name
        return False, ""

    def _has_unsubscribe_header(self, headers):
        """
        Tầng 3: Kiểm tra header List-Unsubscribe.

        Theo chuẩn quốc tế , tất cả mail marketing/newsletter
        BẮT BUỘC phải có header này. Đây là dấu hiệu chắc chắn nhất
        của mail quảng cáo dù không chứa từ khóa nào.

        VD: List-Unsubscribe: <mailto:unsub@shopee.com>

        Args:
            headers (list): Danh sách headers từ Gmail API

        Returns:
            bool: True nếu có header List-Unsubscribe
        """
        return any(h['name'] == 'List-Unsubscribe' for h in headers)

    def _is_promotional_keyword(self, subject, sender):
        """
        Tầng 4: Từ khóa trong subject/sender.

        Lưới lọc cuối cho những mail lọt qua 3 tầng trên.
        So sánh không phân biệt hoa thường.

        Args:
            subject (str): Tiêu đề email
            sender  (str): Địa chỉ người gửi

        Returns:
            (bool, str): (True, từ_khóa_khớp) nếu phát hiện spam
        """
        text = (subject + sender).lower()
        for kw in SPAM_KEYWORDS:
            if kw in text:
                return True, kw
        return False, ""

    def _check_spam(self, label_ids, headers, subject, sender):
        """
        Gộp 4 tầng lọc, trả về kết quả cuối cùng.

        Mail bị bắt ở bất kỳ tầng nào → là spam.

        Args:
            label_ids (list): Nhãn Gmail
            headers   (list): Headers email
            subject   (str) : Tiêu đề
            sender    (str) : Người gửi

        Returns:
            (bool, str): (True, lý_do) nếu là spam, (False, "") nếu hợp lệ
        """
        # Tầng 1: Google Spam label
        if self._is_google_spam(label_ids):
            return True, "Google gắn nhãn SPAM"

        # Tầng 2: Gmail auto category
        flagged, tab_name = self._is_auto_category(label_ids)
        if flagged:
            return True, f"Gmail phân loại: {tab_name}"

        # Tầng 3: List-Unsubscribe header
        if self._has_unsubscribe_header(headers):
            return True, "Có header List-Unsubscribe (mail marketing)"

        # Tầng 4: Từ khóa
        flagged, kw = self._is_promotional_keyword(subject, sender)
        if flagged:
            return True, f"Chứa từ khóa: '{kw}'"

        return False, ""

    #   TRÍCH XUẤT NỘI DUNG EMAIL

    def _extract_body(self, payload):
        """
        Trích xuất nội dung text thuần từ payload email.

        Email có 2 dạng cấu trúc:
          Đơn giản  : payload.body.data chứa thẳng nội dung
          Multipart : payload.parts[] chứa nhiều phần, có thể lồng nhau

        Ưu tiên text/plain. Fallback sang text/html nếu không có.

        Args:
            payload (dict): Payload từ Gmail API

        Returns:
            str: Nội dung text đã giải mã, hoặc "" nếu không tìm được
        """
        plain_text = ''
        html_text  = ''

        def _decode(data):
            """Giải mã base64url → chuỗi UTF-8"""
            return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')

        def _walk(parts):
            """Duyệt đệ quy qua tất cả parts kể cả lồng nhau"""
            nonlocal plain_text, html_text
            for part in parts:
                mime = part.get('mimeType', '')
                if mime.startswith('multipart') and 'parts' in part:
                    _walk(part['parts'])        # đệ quy tiếp
                elif mime == 'text/plain':
                    data = part.get('body', {}).get('data', '')
                    if data and not plain_text:
                        plain_text = _decode(data)
                elif mime == 'text/html':
                    data = part.get('body', {}).get('data', '')
                    if data and not html_text:
                        html_text = _decode(data)

        # Email đơn giản (không có parts)
        if 'parts' not in payload:
            data = payload.get('body', {}).get('data', '')
            return _decode(data) if data else ''

        # Email multipart → duyệt đệ quy
        _walk(payload['parts'])
        return plain_text or html_text

    #   ĐÁNH DẤU ĐÃ ĐỌC

    def mark_as_read(self, msg_id):
        """
        Đánh dấu email đã đọc trên Gmail (xóa nhãn UNREAD).

        Gọi hàm này SAU KHI đã xử lý xong email.
        Nếu xử lý lỗi thì KHÔNG gọi → lần quét sau sẽ thử lại.

        Args:
            msg_id (str): ID email trên Gmail
        """
        try:
            self._service.users().messages().modify(
                userId='me',
                id=msg_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
        except Exception as e:
            print(f"  Không thể đánh dấu đã đọc: {e}")

    #   HÀM CHÍNH: LẤY EMAIL MỚI

    def get_new_emails(self):
        """
        Quét hòm thư, lọc spam và trả về danh sách email hợp lệ.

        Đây là hàm các module khác gọi để lấy dữ liệu email.

        Quy trình:
          1. Lấy danh sách mail UNREAD trong INBOX
          2. Với mỗi mail: lấy metadata → chạy 4 tầng lọc
          3. Mail spam → bỏ qua, đánh dấu đã đọc
          4. Mail hợp lệ → tải body → thêm vào kết quả

        LƯU Ý: Hàm này KHÔNG tự đánh dấu đã đọc mail hợp lệ.
                Module khác tự gọi mark_as_read(id) sau khi xử lý xong.
                Lý do: nếu xử lý lỗi → mail vẫn unread → lần sau thử lại.

        Returns:
            list[dict]: Danh sách email hợp lệ, mỗi email là dict:
                {
                    "id"     : str,  # ID Gmail, dùng để gọi mark_as_read()
                    "subject": str,  # Tiêu đề
                    "sender" : str,  # Người gửi
                    "body"   : str   # Nội dung text (tối đa 3000 ký tự)
                }
        """
        timestamp = datetime.now().strftime('%H:%M:%S')
        print(f"\n{'='*55}")
        print(f" [{timestamp}] Đang quét hòm thư...")
        spam_count = 0
        result = []

        try:
            response = self._service.users().messages().list(
                userId='me',
                q='is:unread in:inbox'  # chỉ INBOX, loại trừ Sent/Drafts/Trash
            ).execute()

            messages = response.get('messages', [])

            if not messages:
                print(" Không có email mới.")
                print(f"{'='*55}")
                return []

            print(f" Phát hiện {len(messages)} email chưa đọc.")

            for i, msg in enumerate(messages, 1):
                msg_id = msg['id']

                try:
                    # BƯỚC 1: Lấy metadata + labels + List-Unsubscribe header
                    meta = self._service.users().messages().get(
                        userId='me',
                        id=msg_id,
                        format='metadata',
                        metadataHeaders=['Subject', 'From', 'List-Unsubscribe']
                    ).execute()

                    headers   = meta.get('payload', {}).get('headers', [])
                    label_ids = meta.get('labelIds', [])

                    subject = next(
                        (h['value'] for h in headers if h['name'] == 'Subject'),
                        '(Không có tiêu đề)'
                    )
                    sender = next(
                        (h['value'] for h in headers if h['name'] == 'From'),
                        '(Ẩn danh)'
                    )

                    # BƯỚC 2: Chạy 4 tầng lọc spam
                    is_spam, spam_reason = self._check_spam(
                        label_ids, headers, subject, sender
                    )

                    # BƯỚC 3: Spam → bỏ qua
                    if is_spam:
                        print(f"  [{i}] Spam: [{subject}] | {spam_reason}")
                        spam_count += 1
                        self.mark_as_read(msg_id)
                        continue

                    # BƯỚC 4: Hợp lệ → tải body đầy đủ
                    print(f"  [{i}] Hợp lệ: [{subject}] từ <{sender}>")

                    full_msg = self._service.users().messages().get(
                        userId='me',
                        id=msg_id,
                        format='full'
                    ).execute()

                    body = self._extract_body(full_msg.get('payload', {}))

                    if not body.strip():
                        print(f"  [{i}]  Email rỗng, bỏ qua.")
                        self.mark_as_read(msg_id)
                        continue

                    # BƯỚC 5: Thêm vào kết quả
                    result.append({
                        "id"     : msg_id,
                        "subject": subject,
                        "sender" : sender,
                        "body"   : body[:3000]  # giới hạn 3000 ký tự
                    })

                except Exception as e:
                    print(f"  [{i}] Lỗi mail {msg_id}: {e}")
                    continue

        except Exception as e:
            print(f" Lỗi kết nối Gmail: {e}")

        print(f"\n Kết quả: {len(result)} hợp lệ | {spam_count} spam bỏ qua.")
        print(f"{'='*55}")
        return result

    def run_loop(self):
        """Chạy quét liên tục mỗi CHECK_INTERVAL_MINUTES phút."""
        self.get_new_emails()
        schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(self.get_new_emails)
        print(f"\n Quét mỗi {CHECK_INTERVAL_MINUTES} phút. Nhấn Ctrl+C để dừng.")
        while True:
            schedule.run_pending()
            time.sleep(1)
