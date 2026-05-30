from datetime import datetime
import sqlite3
import json
from groq import Groq
from typing import Optional
from db_simple import analyze_workload, handle_delete_task, handle_reschedule_specific
from scheduler import auto_schedule



client = Groq(api_key="")

def ask_groq(email_content: str) -> Optional[dict]:
    current_date = datetime.now().strftime('%Y-%m-%d')

    prompt = fprompt = f"""
Bạn là một AI Agent điều phối lịch trình cá nhân, vận hành như một bộ phân tách dữ liệu (Parser) chính xác 100%.
Nhiệm vụ của bạn là chuyển đổi văn bản đầu vào của người dùng thành cấu trúc dữ liệu JSON để nạp vào SQLite Database.

THỜI GIAN HIỆN TẠI HỆ THỐNG: {current_date}

CÁC QUY TẮC BẮT BUỘC

BƯỚC 1: PHÂN LOẠI HÀNH ĐỘNG (ACTION)
Dựa vào văn bản đầu vào để phân tích và chọn duy nhất một hành động phù hợp:
1. 'insert': Khi người dùng muốn thêm mới, tạo, đặt lịch, nhắc nhở hoặc thông báo một công việc chưa có.
   Dấu hiệu: "thêm lịch...", "nhắc tôi...", "tạo task...", "đặt lịch..."
2. 'reschedule_task': Khi người dùng muốn thay đổi thời gian, dời lịch, hoãn lịch của một công việc SẴN CÓ sang một mốc thời gian khác.
   Dấu hiệu: "dời lịch...", "đổi giờ...", "hoãn sang...", "lùi lại...", "chuyển sang ngày..."
3. 'delete': Khi người dùng muốn hủy bỏ, loại bỏ hoàn toàn một công việc SẴN CÓ khỏi lịch trình.
   Dấu hiệu: "xóa lịch...", "hủy lịch...", "bỏ task...", "không cần làm... nữa", "ngừng..."
4. 'analyze': Khi người dùng hỏi về mật độ, tình trạng bận rảnh của lịch trình.
   Dấu hiệu: "xem lịch ngày...", "ngày mai có bận không", "kiểm tra mật độ công việc..."

BƯỚC 2: TRÍCH XUẤT THỰC THỂ (TITLE / SEARCH_KEYWORD)
NẾU ACTION = 'insert': 
  1. Trích xuất giá trị cho key "title".
  2. Chỉ loại bỏ các từ ra lệnh/từ đệm ở đầu câu (như: hãy, thêm, xếp lịch, nhắc tôi, giúp tôi...). 
  3. TUYỆT ĐỐI KHÔNG tự bổ sung thêm từ ngữ nếu văn bản gốc của người dùng không có.

NẾU ACTION = 'delete' HOẶC 'reschedule_task':
  1. Trích xuất tên công việc cần tìm vào key "search_keyword".
  2. BẮT BUỘC chuyển toàn bộ ký tự về dạng VIẾT THƯỜNG (lowercase).
  3. QUY TẮC LỌC BỎ: Phải loại bỏ hoàn toàn các từ ra lệnh ("xóa", "hủy", "dời", "đổi", "chuyển") VÀ các cụm từ chỉ thời gian gây nhiễu ("chiều nay", "ngày mai", "thứ hai", "ngày 30/5", "vào lúc..."). Chỉ giữ lại đúng thực thể tên của công việc để câu lệnh SQL LIKE tìm kiếm.

BƯỚC 3: QUY TẮC PHÂN LOẠI FIXED_SCHEDULE VÀ TÍNH TOÁN THỜI GIAN
Định dạng chuỗi thời gian bắt buộc tuyệt đối: YYYY-MM-DD HH:MM

QUY TẮC PHÂN BIỆT RÕ RÀNG (ĐỌC KỸ TRƯỚC KHI QUYẾT ĐỊNH):

TRƯỜNG HỢP A — fixed_schedule = true
- ĐIỀU KIỆN BẮT BUỘC: Văn bản PHẢI chứa đồng thời cả hai mốc: GIỜ BẮT ĐẦU và GIỜ KẾT THÚC rõ ràng (Ví dụ: "từ 14:00 đến 16:30", "8h-11h", "bắt đầu lúc 9h và kết thúc lúc 10h").
- TUYỆT ĐỐI KHÔNG bật true nếu người dùng chỉ nói một mốc giờ duy nhất.
- Giá trị trích xuất:
  + "fixed_schedule": true
  + "start": <Chuỗi YYYY-MM-DD HH:MM trích từ giờ bắt đầu>
  + "end": <Chuỗi YYYY-MM-DD HH:MM trích từ giờ kết thúc>
  + "deadline": Giá trị bằng với "end"
  + "sessions_needed": 1

TRƯỜNG HỢP B — fixed_schedule = false (Mặc định cho mọi trường hợp còn lại)
- ĐIỀU KIỆN áp dụng: Văn bản CHỈ chứa một mốc thời gian (như mốc deadline, mốc ngày hoàn thành, hoặc mốc giờ đơn lẻ như "hạn vào 14:00 ngày...").
- LUÔN LUÔN trả về:
  + "fixed_schedule": false
  + "start": null  ← TUYỆT ĐỐI KHÔNG TỰ BỊA GIỜ, bắt buộc phải điền null
  + "end": null    ← TUYỆT ĐỐI KHÔNG TỰ BỊA GIỜ, bắt buộc phải điền null
  + "deadline": <Chuỗi YYYY-MM-DD HH:MM chỉ định thời hạn chót> (Nếu người dùng không nói giờ, mặc định điền là "23:59")
  + "sessions_needed": Ước lượng từ 1 đến 5 dựa theo các phân loại độ khó sau:

    * "sessions_needed" = 5 (Dự án lớn / Nghiên cứu khoa học): Xây dựng hệ thống từ đầu, nghiên cứu công nghệ mới, báo cáo khoa học (NCKH), tiểu luận chuyên ngành.
    * "sessions_needed" = 4 (Xây dựng module / Tính năng lớn): Triển khai module phức tạp, thiết kế cơ sở dữ liệu nâng cao, viết tài liệu kỹ thuật dài.
    * "sessions_needed" = 3 (Học thuật nâng cao / Luyện kỹ năng chuyên sâu): Luyện đề thi, học kiến thức mới có hệ thống có độ khó cao, ôn luyện chuyên sâu.
    * "sessions_needed" = 2 (Học tập thông thường / Chuẩn bị bài): Tích lũy kiến thức ngắn hạn, làm bài tập nhỏ hoặc ôn tập định kỳ.
    * "sessions_needed" = 1 (Tác vụ đơn lẻ / Sinh hoạt / Thủ tục hành chính): Tác vụ nhanh gọn, thực hiện một lần.

BƯỚC 4: ĐỊNH DẠNG CẤU TRÚC ĐẦU RA (JSON ONLY)
TUYỆT ĐỐI KHÔNG giải thích, KHÔNG viết thêm văn bản dài dòng, KHÔNG bọc trong block markdown ```json. Chỉ trả về đúng 1 JSON object theo các biểu mẫu sau:

Khi action = "insert" VÀ fixed_schedule = true:
{{"action":"insert","fixed_schedule":true,"title":"<tên công việc>","start":"YYYY-MM-DD HH:MM","end":"YYYY-MM-DD HH:MM","duration_hours":<số thực>,"deadline":"YYYY-MM-DD HH:MM","sessions_needed":1}}

Khi action = "insert" VÀ fixed_schedule = false:
{{"action":"insert","fixed_schedule":false,"title":"<tên công việc>","start":null,"end":null,"deadline":"YYYY-MM-DD HH:MM","sessions_needed":<1-5>}}

Khi action = "reschedule_task":
{{
  "action": "reschedule_task",
  "data": {{
    "search_keyword": "<tên công việc viết thường>",
    "old_date": "YYYY-MM-DD",
    "new_start": "YYYY-MM-DD HH:MM hoặc YYYY-MM-DD"
  }}
}}

Trường new_start có thể chỉ là ngày YYYY-MM-DD (nếu người dùng chỉ bảo dời sang ngày khác và muốn hệ thống tự xếp giờ) hoặc có cả giờ YYYY-MM-DD HH:MM (nếu người dùng chỉ định giờ chính xác ở ngày mới)

Khi action = "delete":
{{"action":"delete","search_keyword":"<tên công việc viết thường>"}}

Khi action = "analyze":
{{"action":"analyze","target_date":"YYYY-MM-DD"}}

Hãy thực hiện văn bản sau:
"{email_content}"
"""
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        return {"error": f"Lỗi kết nối Groq Cloud: {str(e)}"}


def run_agent(email_text: str) -> dict:
    result = ask_groq(email_text)

    if not result:
        return {"status": "failed", "message": "Không nhận được phản hồi từ AI."}

    if "error" in result:
        return {"status": "failed", "message": result["error"]}

    action = result.get("action")
    status_report = {"status": "success", "action": action, "message": "", "scheduler_logs": []}

    if action == "insert":
        conn = sqlite3.connect('agent_storage.db')
        cursor = conn.cursor()
        title = result.get("title")
        deadline = result.get("deadline")
        fixed_schedule = result.get("fixed_schedule", False)
        ai_sessions_needed = result.get("sessions_needed", 1)

        if not title:
            conn.close()
            return {"status": "failed", "message": "AI không trích xuất được tiêu đề (title) công việc."}

        if deadline:
            try:
                deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M")
                deadline_str = deadline_dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                conn.close()
                return {"status": "failed", "message": "Định dạng chuỗi ngày tháng từ AI không hợp lệ."}
        else:
            deadline_str = None

        # Kiểm tra trùng lặp
        cursor.execute("""
            SELECT 1 FROM TASKS 
            WHERE TITLE = ? AND DEADLINE IS ?
            LIMIT 1
        """, (title, deadline_str))

        if cursor.fetchone():
            conn.close()
            return {"status": "failed", "message": f"Task '{title}' đã tồn tại trong danh sách, bỏ qua insert."}

        # Insert task vào TASKS
        cursor.execute("""
            INSERT INTO TASKS (TITLE, DEADLINE, SESSIONS_NEEDED)
            VALUES (?, ?, ?)
        """, (title, deadline_str, ai_sessions_needed))

        task_id = cursor.lastrowid
        conn.commit()

        start_str = result.get("start")
        end_str = result.get("end")

        is_valid_fixed = False
        if fixed_schedule and start_str and end_str:
            try:
                dt_start = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
                dt_end = datetime.strptime(end_str, "%Y-%m-%d %H:%M")
                # Nếu khoảng cách lớn hơn 30 phút mới coi là lịch cố định thực tế do người dùng chỉ định
                if (dt_end - dt_start).total_seconds() > 1800:
                    is_valid_fixed = True
            except ValueError:
                is_valid_fixed = False

        if is_valid_fixed:
            # Trường hợp A thực sự: Xếp thẳng giờ cố định vào bảng SESSIONS
            try:
                cursor.execute("""
                    INSERT INTO SESSIONS (TASK_ID, START_TIME, END_TIME)
                    VALUES (?, ?, ?)
                """, (task_id, start_str, end_str))
                conn.commit()
                conn.close()

                status_report["message"] = f"Đã thêm công việc '{title}' và xếp lịch cố định: {start_str} → {end_str}"
                status_report["scheduler_logs"] = [f"✓ Lịch cố định: {start_str} → {end_str}"]
                return status_report
            except Exception as e:
                conn.close()
                return {"status": "failed", "message": f"Lỗi insert lịch cố định: {str(e)}"}
        else:
            # Trường hợp B hoặc Fallback: Chuyển toàn bộ sang tự xếp lịch tự động (auto_schedule)
            # Khôi phục lại đúng số lượng sessions cần thiết cho việc học thuật nâng cao nếu AI lỡ ép về 1
            if "luyện đề" in title.lower() or "học thuật" in title.lower():
                if ai_sessions_needed <= 1:
                    ai_sessions_needed = 3
                    cursor.execute("UPDATE TASKS SET SESSIONS_NEEDED = ? WHERE TASK_ID = ?", (ai_sessions_needed, task_id))
                    conn.commit()

            conn.close()
            status_report["message"] = f"Đã thêm công việc mới: '{title}' vào Database. Tiến hành xếp lịch tự động..."
            
            # Kích hoạt thuật toán từ scheduler.py
            schedule_res = auto_schedule()
            status_report["scheduler_logs"] = schedule_res.get("task_logs", [])
            return status_report

    elif action == "reschedule_task":
        data = result.get("data", {})
        msg = handle_reschedule_specific(
            search_keyword=data.get('search_keyword', ''),
            new_start=data.get('new_start', ''),
            old_date=data.get('old_date', None)
        )
        status_report["message"] = msg

    elif action == "delete":
        keyword = result.get("search_keyword")
        msg = handle_delete_task(keyword)
        status_report["message"] = msg
        schedule_res = auto_schedule()
        status_report["scheduler_logs"] = schedule_res.get("task_logs", [])

    elif action == "analyze":
        status = analyze_workload(result.get("target_date"))
        status_report["message"] = f"Kết quả phân tích mật độ công việc: {status}"

    elif action == "reschedule_all":
        schedule_res = auto_schedule()
        status_report["message"] = "Đã thực hiện tái cấu trúc phân bổ lại toàn bộ lịch trình."
        status_report["scheduler_logs"] = schedule_res.get("task_logs", [])

    else:
        return {"status": "failed", "message": f"Hành động '{action}' không được hệ thống hỗ trợ xử lý."}

    return status_report
 
if __name__ == "__main__":
    # # Test case: giờ cố định do người dùng chỉ định
    run_agent("Dời lịch Luyện đề và học thuật nâng cao môn Hệ quản trị cơ sở dữ liệu ngày 2026-06-03 sang 10:00 2026-05-31")
