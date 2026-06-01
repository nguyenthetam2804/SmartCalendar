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

    prompt = f"""
Bạn là một AI Agent điều phối lịch trình cá nhân, vận hành như một bộ phân tách dữ liệu (Parser) chính xác 100%.
Nhiệm vụ của bạn là chuyển đổi văn bản đầu vào của người dùng thành cấu trúc dữ liệu JSON để nạp vào SQLite Database.

THỜI GIAN HIỆN TẠI HỆ THỐNG: {current_date}

CÁC QUY TẮC BẮT BUỘC

BƯỚC 1: PHÂN LOẠI HÀNH ĐỘNG (ACTION)
Dựa vào văn bản đầu vào để phân tích và chọn duy nhất một hành động phù hợp:
1. 'insert': Khi người dùng muốn thêm mới, tạo, đặt lịch, nhắc nhở hoặc thông báo một công việc chưa có.
2. 'reschedule_task': Khi người dùng muốn thay đổi thời gian, dời lịch, hoãn lịch của một công việc SẴN CÓ sang một mốc thời gian khác.
3. 'delete': Khi người dùng muốn hủy bỏ, loại bỏ hoàn toàn một công việc SẴN CÓ khỏi lịch trình.
4. 'analyze': Khi người dùng hỏi về mật độ, tình trạng bận rảnh của lịch trình.

BƯỚC 2: TRÍCH XUẤT THỰC THỂ (TITLE / SEARCH_KEYWORD)
- Nếu action = 'insert': Trích xuất tên việc vào key "title". Loại bỏ từ ra lệnh ở đầu câu.
- Nếu action = 'delete' hoặc 'reschedule_task': Trích xuất tên việc vào key "search_keyword" (viết thường).

BƯỚC 3: QUY TẮC PHÂN LOẠI FIXED_SCHEDULE VÀ TÍNH TOÁN THỜI GIAN
Định dạng chuỗi thời gian bắt buộc tuyệt đối: YYYY-MM-DD HH:MM

QUY TẮC PHÂN BIỆT RÕ RÀNG (ĐỌC KỸ TRƯỚC KHI QUYẾT ĐỊNH):

TRƯỜNG HỢP A — fixed_schedule = true
- ĐIỀU KIỆN BẮT BUỘC: Văn bản PHẢI chứa đồng thời cả hai mốc: GIỜ BẮT ĐẦU và GIỜ KẾT THÚC rõ ràng (Ví dụ: "từ 14:00 đến 16:30", "8h-11h").
- Giá trị trích xuất:
  + "fixed_schedule": true
  + "start": <Chuỗi YYYY-MM-DD HH:MM trích từ giờ bắt đầu>
  + "end": <Chuỗi YYYY-MM-DD HH:MM trích từ giờ kết thúc>
  + "deadline": Giá trị bằng với "end"
  + "sessions_needed": 1

TRƯỜNG HỢP B — fixed_schedule = false (Mặc định cho mọi trường hợp còn lại)
- ĐIỀU KIỆN áp dụng: Người dùng chỉ nói một mốc giờ duy nhất, hoặc chỉ nói ngày bắt đầu thực hiện, hoặc không nói mốc thời gian nào cả.
- LUÔN LUÔN xử lý quy tắc ĐẶC BIỆT QUAN TRỌNG sau:
  + "start": null  ← Bắt buộc điền null (Không tự bịa giờ bắt đầu)
  + "end": null    ← Bắt buộc điền null (Không tự bịa giờ kết thúc)
  
  + QUY TẮC LOGIC CHỐT (QUAN TRỌNG NHẤT): Kể cả khi người dùng có nói ngày bắt đầu (ví dụ: "Thứ hai tuần sau bắt đầu học"), nếu họ KHÔNG ĐỀ CẬP đến thời hạn chót phải hoàn thành (Deadline), bạn BẮT BUỘC phải điền:
    * "deadline": null
    * "sessions_needed": null  <-- TUYỆT ĐỐI KHÔNG ĐƯỢC TỰ SINH SESSIONS NẾU DEADLINE BẰNG NULL.
    
  + Ngược lại, CHỈ KHI NÀO văn bản có thời hạn chót hoàn thành rõ ràng (Deadline), bạn mới trích xuất "deadline" (chuỗi YYYY-MM-DD HH:MM) và ước lượng "sessions_needed" từ 1 đến 5 theo độ khó.

BƯỚC 4: ĐỊNH DẠNG CẤU TRÚC ĐẦU RA (JSON ONLY)
Chỉ trả về đúng 1 JSON object theo các biểu mẫu sau:

Khi action = "insert" VÀ fixed_schedule = false (Trường hợp deadline là null):
{{"action":"insert","fixed_schedule":false,"title":"<tên công việc>","start":null,"end":null,"deadline":null,"sessions_needed":null}}

Khi action = "insert" VÀ fixed_schedule = false (Trường hợp có deadline):
{{"action":"insert","fixed_schedule":false,"title":"<tên công việc>","start":null,"end":null,"deadline":"YYYY-MM-DD HH:MM","sessions_needed":<1-5>}}

... (Giữ nguyên các JSON mẫu còn lại của bạn) ...

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
        ai_sessions_needed = result.get("sessions_needed")

        # --- LỚP BẢO VỆ CỦA PYTHON: SỬA ĐÚNG MONG MUỐN CỦA BẠN ---
        # Nếu AI trả về deadline bằng null hoặc rỗng, ta cưỡng ép sessions_needed về None (NULL) lập tức
        # Bất kể AI trước đó có lỡ tính toán ra số mấy đi chăng nữa.
        if deadline is None or deadline == "":
            deadline_str = None
            ai_sessions_needed = None
        else: 
            try:
                deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M")
                deadline_str = deadline_dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                conn.close()
                return {"status": "failed", "message": "Định dạng chuỗi ngày tháng từ AI không hợp lệ."}

        if not title:
            conn.close()
            return {"status": "failed", "message": "AI không trích xuất được tiêu đề (title) công việc."}

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
                if (dt_end - dt_start).total_seconds() > 1800:
                    is_valid_fixed = True
            except ValueError:
                is_valid_fixed = False

        if is_valid_fixed:
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
            # Chỉ bẫy nâng session học thuật nâng cao nếu ban đầu ai_sessions_needed có giá trị số hợp lệ
            if ai_sessions_needed is not None and ("luyện đề" in title.lower() or "học thuật" in title.lower()):
                if ai_sessions_needed <= 1:
                    ai_sessions_needed = 3
                    cursor.execute("UPDATE TASKS SET SESSIONS_NEEDED = ? WHERE TASK_ID = ?", (ai_sessions_needed, task_id))
                    conn.commit()

            conn.close()
            
            # --- KIỂM TRA ĐIỀU KIỆN CHẠY AUTO_SCHEDULE ---
            # Nếu ai_sessions_needed là None (tương ứng deadline = null), đây là việc ghi chú
            if ai_sessions_needed is None:
                status_report["message"] = f"Đã lưu tác vụ ghi nhớ: '{title}' (Không có hạn chót, không xếp lịch chi tiết)."
                status_report["scheduler_logs"] = ["- Tác vụ không có deadline, bỏ qua xếp lịch tự động."]
                return status_report

            status_report["message"] = f"Đã thêm công việc mới: '{title}' vào Database. Tiến hành xếp lịch tự động..."
            
            # Chỉ kích hoạt thuật toán xếp lịch tự động khi task thực sự có deadline và cần session
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
    print(run_agent("Thứ hai tuần sau bắt đầu học lập trình"))