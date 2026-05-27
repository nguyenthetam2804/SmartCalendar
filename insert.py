import sqlite3
import json
from datetime import datetime, timedelta
from groq import Groq
from typing import Optional

from db_simple import analyze_workload, handle_delete_task, handle_reschedule_specific
from scheduler import auto_schedule
import scheduler

api_key = os.environ.get("GROQ_API_KEY") or st.secrets.get("GROQ_API_KEY", "") if "st" in globals() else ""
#client = Groq(api_key="")

def ask_groq(email_content: str) -> Optional[dict]:
    current_date = datetime.now().strftime('%Y-%m-%d')

    prompt = f"""
Bạn là một AI Agent điều phối lịch trình cá nhân, vận hành như một bộ phân tách dữ liệu (Parser) chính xác 100%.
Nhiệm vụ của bạn là chuyển đổi văn bản đầu vào của người dùng thành cấu trúc dữ liệu JSON để nạp vào SQLite Database.

THỜI GIAN HIỆN TẠI HỆ THỐNG: {current_date}

CÁC QUY TẮC BẮT BUỘC

BƯỚC 1: PHÂN LOẠI HÀNH ĐỘNG CỰC (ACTION)
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
Nếu action = 'insert': 
  1. Trích xuất giá trị cho key "title".
  2. Chỉ loại bỏ các từ ra lệnh/từ đệm ở đầu câu (như: hãy, thêm, xếp lịch, nhắc tôi, giúp tôi...). 
  3. TUYỆT ĐỐI KHÔNG sử dụng các từ ngữ nếu văn bản của người dùng không có.

NẾU ACTION = 'delete' HOẶC 'reschedule_task':
  1. Trích xuất tên công việc cần tìm vào key "search_keyword".
  2. BẮT BUỘC chuyển toàn bộ ký tự về dạng VIẾT THƯỜNG (lowercase).
  3. QUY TẮC LỌC BỎ : Phải loại bỏ sạch các từ ra lệnh ("xóa", "hủy", "dời", "đổi", "chuyển") VÀ các từ chỉ thời gian gây nhiễu ("chiều nay", "ngày mai", "thứ hai", "ngày 30/5"). Chỉ giữ lại đúng thực thể tên của công việc để câu lệnh SQL LIKE tìm kiếm.
     Ví dụ: "Xóa lịch học java mvc chiều nay" -> search_keyword phải là: "học java mvc" (vứt chữ 'xóa' và 'chiều nay').
     Ví dụ: "Dời lịch code fe medical records sang ngày mai" -> search_keyword phải là: "code fe medical records" (vứt chữ 'dời lịch' và 'sang ngày mai').

BƯỚC 3: QUY TẮC ĐỊNH DẠNG VÀ TÍNH TOÁN THỜI GIAN
Định dạng chuỗi thời gian bắt buộc: YYYY-MM-DD HH:MM
 
PHÂN BIỆT HAI TRƯỜNG HỢP — ĐỌC KỸ TRƯỚC KHI QUYẾT ĐỊNH:
 
TRƯỜNG HỢP A — fixed_schedule = true
ĐIỀU KIỆN BẮT BUỘC: Văn bản phải có ĐỦ CẢ HAI: giờ bắt đầu VÀ giờ kết thúc rõ ràng.
Dấu hiệu: "từ 17:00 đến 18:00", "lúc 9h tới 10h30", "8:00 - 9:00", "bắt đầu X kết thúc Y".
  - "fixed_schedule": true
  - "start": giờ bắt đầu người dùng nói (YYYY-MM-DD HH:MM)
  - "end": giờ kết thúc người dùng nói (YYYY-MM-DD HH:MM)
  - "deadline": bằng giá trị "end"
  - "sessions_needed": 1
 
TRƯỜNG HỢP B — fixed_schedule = false
ĐIỀU KIỆN: Văn bản CHỈ có tên việc + deadline/ngày hoàn thành, KHÔNG có cả hai giờ bắt đầu và kết thúc.
  - "fixed_schedule": false
  - "start": null  ← LUÔN LUÔN là null, TUYỆT ĐỐI không tự bịa giờ
  - "end": null    ← LUÔN LUÔN là null, TUYỆT ĐỐI không tự bịa giờ
  - "deadline": ngày hạn chót (YYYY-MM-DD HH:MM) hoặc null nếu không có
  - "sessions_needed": ước lượng 1-5
  Phân loại ước lượng
"sessions_needed" = 5 (Dự án lớn/Nghiên cứu khoa học): Các công việc mang tính chất xây dựng hệ thống từ đầu, nghiên cứu công nghệ mới, viết báo cáo khoa học, tiểu luận chuyên ngành.

"sessions_needed" =  4 (Xây dựng module/Tính năng lớn): Các công việc triển khai một phần lớn của dự án, thiết kế cơ sở dữ liệu nâng cao, viết tài liệu kỹ thuật dài.

"sessions_needed" = 3 (Học thuật nâng cao/Luyện kỹ năng chuyên sâu): Đòi hỏi tư duy cao, luyện đề, học kiến thức mới có tính hệ thống.

"sessions_needed" = 2 (Học tập thông thường/Chuẩn bị bài): Các công việc mang tính chất tích lũy kiến thức ngắn hạn hoặc ôn tập định kỳ.

"sessions_needed" = 1 (Tác vụ đơn lẻ/Sinh hoạt/Nhắc nhở hành chính): Công việc chỉ làm một lần, mang tính thủ tục hoặc kiểm tra nhanh.
 
KIỂM TRA TRƯỚC KHI QUYẾT ĐỊNH fixed_schedule:
  → Văn bản có từ "deadline", "hạn", "trước ngày", "hoàn thành trước"? → TH B (false)
  → Văn bản có "từ X đến Y giờ" với cả X lẫn Y? → TH A (true)
  → Chỉ có một mốc thời gian duy nhất (ví dụ chỉ "ngày 30/06")? → TH B (false)
 
QUY TẮC ƯỚC LƯỢNG sessions_needed (chỉ dùng khi fixed_schedule = false):
   1. Các việc nhẹ, đơn giản (đi học, khám răng, mua đồ, check mail...): trả về 1
   2. Các việc vừa phải (luyện viết essay IELTS, ôn tập chương, học từ vựng...): trả về 2 hoặc 3
   3. Các dự án phức tạp (code FE Medical Records, nghiên cứu RAG model, viết báo cáo NCKH...): trả về 4 hoặc 5
BƯỚC 4: ĐỊNH DẠNG CẤU TRÚC ĐẦU RA (JSON ONLY)
TUYỆT ĐỐI KHÔNG giải thích, KHÔNG viết thêm văn bản dài dòng, KHÔNG bọc trong block markdown ```json. Chỉ trả về đúng 1 JSON object theo các biểu mẫu sau:

Khi action = "insert" VÀ fixed_schedule = true (người dùng cho giờ cụ thể):
{{"action":"insert","fixed_schedule":true,"title":"<tên công việc>","start":"YYYY-MM-DD HH:MM","end":"YYYY-MM-DD HH:MM","duration_hours":<số thực>,"deadline":"YYYY-MM-DD HH:MM","sessions_needed":1}}

Khi action = "insert" VÀ fixed_schedule = false (để auto xếp lịch):
{{"action":"insert","fixed_schedule":false,"title":"<tên công việc>","start":null,"end":null,"deadline":"YYYY-MM-DD HH:MM hoặc null","sessions_needed":<1-5>}}

Khi action = "reschedule_task":
{{"action":"reschedule_task","data":{{"search_keyword":"<tên công việc viết thường>","new_start":"YYYY-MM-DD HH:MM"}}}}

Khi action = "delete":
{{"action":"delete","search_keyword":"<tên công việc viết thường>"}}

Khi action = "analyze":
{{"action":"analyze","target_date":"YYYY-MM-DD"}}

Hãy thực hiện văn bản sau và chọn "sessions_needed" phù hợp:
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

        # --- FIX CHÍNH: Nếu người dùng cho giờ cụ thể → insert thẳng vào SESSIONS ---
        if fixed_schedule:
            start_str = result.get("start")
            end_str = result.get("end")

            if start_str and end_str:
                try:
                    # Validate định dạng
                    datetime.strptime(start_str, "%Y-%m-%d %H:%M")
                    datetime.strptime(end_str, "%Y-%m-%d %H:%M")

                    cursor.execute("""
                        INSERT INTO SESSIONS (TASK_ID, START_TIME, END_TIME)
                        VALUES (?, ?, ?)
                    """, (task_id, start_str, end_str))
                    conn.commit()
                    conn.close()

                    status_report["message"] = (
                        f"Đã thêm công việc '{title}' và xếp lịch cố định: "
                        f"{start_str} → {end_str}"
                    )
                    status_report["scheduler_logs"] = [
                        f"✓ Lịch cố định (do người dùng chỉ định): {start_str} → {end_str}"
                    ]
                    return status_report

                except ValueError:
                    conn.close()
                    return {"status": "failed", "message": "Định dạng start/end từ AI không hợp lệ."}
            else:
                # fixed_schedule=true nhưng AI không trả start/end → fallback auto
                conn.close()
                status_report["message"] = f"Đã thêm công việc mới: '{title}'. Fallback sang auto_schedule."
                schedule_res = auto_schedule()
                status_report["scheduler_logs"] = schedule_res.get("task_logs", [])
                return status_report
        else:
            # Trường hợp B: để auto_schedule tự xếp
            conn.close()
            status_report["message"] = f"Đã thêm công việc mới: '{title}' vào Database."
            schedule_res = auto_schedule()
            status_report["scheduler_logs"] = schedule_res.get("task_logs", [])
            return status_report

    elif action == "reschedule_task":
        data = result.get("data", {})
        msg = handle_reschedule_specific(
            data.get('search_keyword', ''),
            data.get('new_start', '')
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
    run_agent("Thêm lịch nghiên cứu khoa học hạn vào 00:00 ngày 30/04/2027")