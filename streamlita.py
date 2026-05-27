import streamlit as st
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
from calendar_service import create_event
from insert import run_agent

# --- KÍCH HOẠT WATCHER CHẠY NGẦM QUÉT DATABASE ---
try:
    from autocheck import AutoCheckWatcher
    if "watcher_started" not in st.session_state:
        st.session_state.watcher = AutoCheckWatcher(poll_interval=10)
        st.session_state.watcher.start()
        st.session_state.watcher_started = True
except Exception as watcher_err:
    st.sidebar.error(f"⚠️ Không thể chạy Watcher ngầm: {watcher_err}")

# Cấu hình trang
st.set_page_config(page_title="AI Planner System", layout="wide")

# --- HÀM TÍNH TOÁN CHỈ SỐ CORTISOL THÔNG MINH ---
def calculate_dynamic_cortisol():
    cortisol = 40 
    try:
        with sqlite3.connect('agent_storage.db') as conn:
            cursor = conn.cursor()
            now = datetime.now()
            start_of_week = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d 00:00')
            end_of_week = (now + timedelta(days=(6 - now.weekday()))).strftime('%Y-%m-%d 23:59')
            
            cursor.execute("SELECT COUNT(*) FROM SESSIONS WHERE START_TIME BETWEEN ? AND ?", (start_of_week, end_of_week))
            session_count = cursor.fetchone()[0]
            cortisol += (session_count * 15)
            
            two_days_later = (now + timedelta(days=2)).strftime('%Y-%m-%d %H:%M')
            now_str = now.strftime('%Y-%m-%d %H:%M')
            
            cursor.execute("SELECT COUNT(*) FROM TASKS WHERE DEADLINE BETWEEN ? AND ?", (now_str, two_days_later))
            urgent_tasks = cursor.fetchone()[0]
            cortisol += (urgent_tasks * 30)
    except:
        pass
    return min(cortisol, 150)

# --- SIDEBAR DISPLAY ---
with st.sidebar:
    st.title("🤖 AI Control Center")
    menu = st.radio("Menu chính", ["Trang chủ", "Chat với Groq", "Google Calendar Live", "Google Tasks Live", "Quản lý Lịch", "Cài đặt"])
    st.divider()
    
    current_cortisol = calculate_dynamic_cortisol()
    st.metric(label="Chỉ số Cortisol hiện tại", value=f"{current_cortisol} ng/mL")
    st.success("Google Calendar: Connected")
    st.warning("Groq API: Connected")
    
    # ─────────────────────────────────────────────────────────────────
    # 🔥 ĐÃ SỬA: Thụt lề toàn bộ khu vực này vào trong để đẩy về Sidebar cũ
    # ─────────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Danger Zone")
    
    confirm_delete = st.checkbox("Xác nhận muốn xóa sạch lịch")
    
    if st.button("🗑️ Xóa toàn bộ dữ liệu lịch", use_container_width=True, type="primary", disabled=not confirm_delete):
        with st.spinner("Đang xử lý xóa dữ liệu cục bộ và đồng bộ Google Tasks..."):
            try:
                # 1. KẾT NỐI DATABASE CỤC BỘ
                with sqlite3.connect('agent_storage.db') as conn:
                    cursor = conn.cursor()
                    
                    # Lấy chính xác các mã GOOGLE_TASK_ID chưa trống trong bảng TASKS
                    cursor.execute("SELECT DISTINCT GOOGLE_TASK_ID FROM TASKS WHERE GOOGLE_TASK_ID IS NOT NULL;")
                    google_task_ids = [row[0] for row in cursor.fetchall()]
                    
                    # 2. GỌI HÀM XÓA CỦA BẠN TRONG NHÓM (GIỮ NGUYÊN FILE GOOGLE_API)
                    from google_api import delete_google_task
                    
                    for g_id in google_task_ids:
                        if g_id and not g_id.endswith('@google.com'): 
                            delete_google_task(g_id)  # Chạy trực tiếp hàm nguyên bản của bạn bạn
                    
                    # 3. TIẾN HÀNH DỌN DẸP SẠCH DATABASE CỤC BỘ
                    cursor.execute("DELETE FROM SESSIONS;")
                    cursor.execute("DELETE FROM TASKS;")
                    cursor.execute("DELETE FROM sqlite_sequence WHERE name='SESSIONS';")
                    cursor.execute("DELETE FROM sqlite_sequence WHERE name='TASKS';")
                    conn.commit()
                
                # 4. THÔNG BÁO VÀ LÀM TƯƠI LẠI GIAO DIỆN
                st.sidebar.success("🎉 Đã dọn dẹp hệ thống và cập nhật Google Tasks thành công!")
                st.rerun()
                
            except Exception as delete_err:
                st.sidebar.error(f"Lỗi khi thực hiện dọn dẹp: {delete_err}")

# --- TRANG CHỦ ---
if menu == "Trang chủ":
    st.header("🏠 Bảng điều khiển")
    
    # ─────────────────────────────────────────────────────────────────
    # 🔥 KHU VỰC ĐỒNG BỘ: GMAIL WORKER & GOOGLE TASKS WORKER
    # ─────────────────────────────────────────────────────────────────
    col_title, col_gmail_btn, col_tasks_btn = st.columns([2, 1, 1])
    
    with col_gmail_btn:
        if st.button("🔄 Quét và Đồng bộ Gmail", use_container_width=True):
            with st.spinner("Gmail Worker đang lục hòm thư chưa đọc..."):
                try:
                    from mail_worker import GmailWorker
                    worker = GmailWorker()
                    new_emails = worker.get_new_emails()
                    
                    if not new_emails:
                        st.toast("📨 Không có email công việc mới nào cần xử lý.")
                    else:
                        success_count = 0
                        for email in new_emails:
                            chat_payload = f"Thêm công việc từ email. Tiêu đề: {email['subject']}. Nội dung: {email['body']}"
                            ai_result = run_agent(chat_payload)
                            
                            if isinstance(ai_result, dict) and ai_result.get("status") == "success":
                                success_count += 1
                                worker.mark_as_read(email['id'])
                        
                        if success_count > 0:
                            st.success(f"🎯 Agent đã xử lý thành công {success_count} email công việc mới!")
                            st.balloons()
                        else:
                            st.warning("⚠️ Đã đọc email nhưng AI không bóc tách được tác vụ phù hợp.")
                except Exception as mail_err:
                    st.error(f"Lỗi kết nối hoặc đồng bộ luồng Gmail: {mail_err}")
                    
    with col_tasks_btn:
        if st.button("🎯 Đồng bộ Google Tasks", use_container_width=True):
            with st.spinner("Đang lọc việc Deadline = NULL để đẩy lên Google Tasks..."):
                try:
                    from sync_tasks import sync_null_deadline_tasks
                    sync_null_deadline_tasks()
                    st.success("✅ Đã đồng bộ các công việc không có hạn chót lên Google Tasks!")
                    st.toast("🎯 Kiểm tra danh sách việc cần làm trên Google Tasks của bạn!")
                    st.rerun()
                except ModuleNotFoundError:
                    st.error("❌ Không tìm thấy file code xử lý đồng bộ. Vui lòng đảm bảo bạn đã lưu file code kia với tên 'sync_tasks.py'")
                except Exception as tasks_err:
                    st.error(f"Lỗi khi đồng bộ lên Google Tasks: {tasks_err}")
    
    # --- LOGIC HIỂN THỊ BẢNG TRANG CHỦ ---
    try:
        conn = sqlite3.connect('agent_storage.db')
        total_tasks = pd.read_sql_query("SELECT COUNT(*) FROM TASKS", conn).iloc[0,0]
        
        now = datetime.now()
        start_of_week = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d 00:00')
        end_of_week = (now + timedelta(days=(6 - now.weekday()))).strftime('%Y-%m-%d 23:59')
        
        query = """
            SELECT T.TITLE as 'Tên công việc', 
                   IFNULL(S.START_TIME, '⚠️ Chưa được xếp ca chi tiết') as 'Khung giờ bắt đầu', 
                   IFNULL(S.END_TIME, '---') as 'Khung giờ kết thúc',
                   IFNULL(T.DEADLINE, '--- Không có hạn chót') as 'Hạn chót (Deadline)'
            FROM TASKS T
            LEFT JOIN SESSIONS S ON T.TASK_ID = S.TASK_ID
            WHERE (S.START_TIME BETWEEN ? AND ?) OR (S.START_TIME IS NULL)
            ORDER BY S.START_TIME ASC, T.TASK_ID DESC
        """
        df_week = pd.read_sql_query(query, conn, params=(start_of_week, end_of_week))
        conn.close()
    except Exception as e:
        st.error(f"Lỗi truy xuất lịch trình từ Database: {e}")
        total_tasks = 0
        df_week = pd.DataFrame()

    scheduled_count = df_week['Khung giờ kết thúc'].ne('---').sum() if not df_week.empty else 0
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(label="Tổng công việc hệ thống", value=total_tasks)
    with col2:
        st.metric(label="Khung giờ làm việc (Thứ 2 - CN)", value=scheduled_count)
    with col3:
        if current_cortisol < 70:
            st.metric(label="Trạng thái cơ thể", value=f"{current_cortisol} 🟢 Thoải mái")
        elif current_cortisol < 110:
            st.metric(label="Trạng thái cơ thể", value=f"{current_cortisol} 🟡 Áp lực")
        else:
            st.metric(label="Trạng thái cơ thể", value=f"{current_cortisol} 🔴 Quá tải!")

    st.divider()

    st.subheader(f"📅 Kế hoạch chi tiết từ Thứ Hai đến Chủ Nhật")
    st.caption(f"Khoảng thời gian: T2 ({start_of_week[:10]}) ➔ CN ({end_of_week[:10]})")
    
    if not df_week.empty:
        st.dataframe(df_week, width="stretch", hide_index=True)
    else:
        st.info("Tuần này hoàn toàn trống lịch. Hãy nghỉ ngơi hoặc nạp thêm task mới!")

# --- CHAT VỚI GROK ---
elif menu == "Chat với Groq":
    st.header("💬 Chat với Grok AI Agent")
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Nhập yêu cầu quản lý lịch trình hoặc câu hỏi..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Grok Agent đang xử lý..."):
                ket_qua = run_agent(prompt) 
                chuoi_hien_thi = ""
                if isinstance(ket_qua, dict):
                    if ket_qua.get("status") == "success":
                        chuoi_hien_thi += f"{ket_qua.get('message')}\n\n"
                        logs = ket_qua.get("scheduler_logs", [])
                        if logs:
                            chuoi_hien_thi += "**🛠️ Nhật ký xếp lịch tự động:**\n"
                            for log in logs:
                                chuoi_hien_thi += f"{log}\n"
                    else:
                        chuoi_hien_thi += f"❌ **Thất bại:** {ket_qua.get('message')}"
                else:
                    chuoi_hien_thi = str(ket_qua)
                    try:
                        import json
                        data_loi = json.loads(chuoi_hien_thi)
                        if isinstance(data_loi, dict):
                            chuoi_hien_thi = data_loi.get("message") or data_loi.get("title") or chuoi_hien_thi
                    except:
                        pass

                st.markdown(chuoi_hien_thi)
                st.session_state.messages.append({"role": "assistant", "content": chuoi_hien_thi})

# --- GOOGLE CALENDAR LIVE ---
elif menu == "Google Calendar Live":
    st.header("📅 Giao diện xem lịch trực tiếp")
    from calendar_service import get_logged_in_user_email
    with st.spinner("Đang kiểm tra thông tin tài khoản Google..."):
        user_email = get_logged_in_user_email()

    if user_email:
        st.success(f"🔒 Đang hiển thị thời gian thực lịch của tài khoản: **{user_email}**")
        encoded_email = user_email.replace("@", "%40")
        dynamic_embed_url = f"https://calendar.google.com/calendar/embed?src={encoded_email}&ctz=Asia%2FHo_Chi_Minh"
        st.components.v1.iframe(dynamic_embed_url, height=700, scrolling=True)
    else:
        st.warning("⚠️ Hệ thống chưa nhận diện được phiên đăng nhập Google Calendar của bạn.")

# --- GIAO DIỆN KIỂM TRA GOOGLE TASKS LIVE ---
elif menu == "Google Tasks Live":
    st.header("🎯 Danh sách việc cần làm (Google Tasks Cloud)")
    st.write("Dưới đây là các tác vụ không có deadline đang lưu trữ thời gian thực trên ứng dụng Google Tasks của bạn.")
    
    if st.button("🔄 Làm mới dữ liệu từ Google", use_container_width=True):
        st.rerun()
        
    with st.spinner("Hệ thống đang đồng bộ dữ liệu trực tiếp từ Google API..."):
        try:
            from google_api import get_incomplete_google_tasks
            cloud_tasks = get_incomplete_google_tasks()
            
            if not cloud_tasks:
                st.info("🎉 Tuyệt vời! Hiện tại không có công việc tồn đọng nào trên Google Tasks Cloud.")
            else:
                tasks_data = []
                for item in cloud_tasks:
                    title = item.get('title', '--- Không có tên ---')
                    due_date = item.get('due', '--- Không có hạn chót ---')
                    if due_date != '--- Không có hạn chót ---':
                        due_date = due_date.split('T')[0]
                    
                    tasks_data.append({
                        "Tên tác vụ trên Google Tasks": title,
                        "Hạn chót thiết làm": due_date,
                        "Trạng thái": "⏳ Đang thực hiện"
                    })
                
                df_tasks = pd.DataFrame(tasks_data)
                st.dataframe(df_tasks, use_container_width=True, hide_index=True)
                
        except Exception as api_err:
            st.error(f"Không thể kết nối lấy dữ liệu từ Google Tasks: {api_err}")
            st.info("💡 Mẹo: Hãy kiểm tra chắc chắn bạn đã kích hoạt Google Tasks API trên Google Cloud Console!")

# --- QUẢN LÝ LỊCH ---
# --- QUẢN LÝ LỊCH ---
elif menu == "Quản lý Lịch":
    st.header("📅 Điều phối Google Calendar")
    
    # Bắt đầu form
    with st.form("calendar_form"):
        col_a, col_b = st.columns(2)
        with col_a:
            task_name = st.text_input("Tên sự kiện/tác vụ")
            start_date = st.date_input("Ngày bắt đầu")
        with col_b:
            location = st.text_input("Địa điểm")
            start_time = st.time_input("Giờ bắt đầu")
            
        description = st.text_area("Mô tả chi tiết")
        
        # 🚨 ĐẢM BẢO: Dòng này phải được thụt lề (Tab) nằm TRONG khối "with st.form"
        submitted = st.form_submit_button("Lưu vào Google Calendar và Đồng bộ Hệ thống")
        
        if submitted:
            if not task_name:
                st.error("Vui lòng nhập tên sự kiện!")
            else:
                start_datetime = datetime.combine(start_date, start_time)
                iso_start = start_datetime.strftime('%Y-%m-%dT%H:%M:%S')
                iso_end = (start_datetime + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')

                with st.spinner("Đang đẩy lịch lên Google Calendar và ghi nhận dữ liệu..."):
                    success, result = create_event(task_name, iso_start, iso_end, description)
                    if success:
                        try:
                            db_start = start_datetime.strftime('%Y-%m-%d %H:%M')
                            db_end = (start_datetime + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
                            with sqlite3.connect('agent_storage.db') as conn:
                                cursor = conn.cursor()
                                cursor.execute("INSERT INTO TASKS (TITLE, DEADLINE) VALUES (?, ?)", (task_name, db_end))
                                last_id = cursor.lastrowid
                                cursor.execute("INSERT INTO SESSIONS (TASK_ID, START_TIME, END_TIME) VALUES (?, ?, ?)", (last_id, db_start, db_end))
                                conn.commit()
                            st.success("✅ Đã tạo lịch thành công!")
                        except Exception as db_err:
                            st.error(f"Lỗi ghi nhận cục bộ: {db_err}")
                    else:
                        st.error(f"Lỗi kết nối API Google: {result}")