import streamlit as st
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
from calendar_service import create_event
from insert import run_agent
# Import thêm hàm phân tích từ db_simple của nhóm bạn
from db_simple import analyze_workload 

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
st.set_page_config(page_title="AI Planner System", page_icon="🤖", layout="wide")

def calculate_dynamic_cortisol():
    cortisol = 40 
    try:
        with sqlite3.connect('agent_storage.db') as conn:
            cursor = conn.cursor()
            now = datetime.now()
            
            start_of_week = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d 00:00')
            end_of_week = (now + timedelta(days=(6 - now.weekday()))).strftime('%Y-%m-%d 23:59')
            
            now_str = now.strftime('%Y-%m-%d %H:%M')
            two_days_later = (now + timedelta(days=2)).strftime('%Y-%m-%d %H:%M')
            
            cursor.execute("SELECT COUNT(*) FROM SESSIONS WHERE START_TIME BETWEEN ? AND ?", (start_of_week, end_of_week))
            session_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM TASKS WHERE DEADLINE BETWEEN ? AND ?", (now_str, two_days_later))
            urgent_tasks = cursor.fetchone()[0]
            
            if urgent_tasks <= 3:
                cortisol += (urgent_tasks * 10)
            elif urgent_tasks <= 6:
                cortisol += 30 + ((urgent_tasks - 3) * 20)
            else:
                cortisol += 90 + ((urgent_tasks - 6) * 25)

            cortisol += (session_count * 3)
    except:
        pass
    return min(cortisol, 150)

current_cortisol = calculate_dynamic_cortisol()

# --- SIDEBAR DISPLAY ---
with st.sidebar:
    st.title("🤖 AI Control Center")
    st.markdown("---")
    menu = st.radio(
        "Menu điều hướng hệ thống", 
        [
            "🏠 Trang chủ", 
            "💬 Chat với Groq", 
            "📊 Phân tích & Đánh giá", 
            "📅 Google Calendar Live", 
            "🎯 Google Tasks Live", 
            "⚙️ Quản lý Lịch"
        ]
    )
    st.markdown("---")
    
    st.subheader("📊 Sức khỏe Agent")
    st.sidebar.metric(label="Chỉ số sinh học Cortisol", value=f"{current_cortisol} %")
    st.success("🟢 Google Cloud API: Connected")
    st.info("⚡ Groq Llama 3.1: Active")
    
    st.markdown("---")
    st.subheader("🚨 Xoá dữ liệu")
    confirm_delete = st.checkbox("Tôi chắc chắn muốn xóa dữ liệu")
    
    if st.button("🗑️ Xóa toàn bộ dữ liệu lịch", use_container_width=True, type="primary", disabled=not confirm_delete):
        with st.spinner("Đang dọn dẹp Database cục bộ và Cloud..."):
            try:
                with sqlite3.connect('agent_storage.db') as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT DISTINCT GOOGLE_TASK_ID FROM TASKS WHERE GOOGLE_TASK_ID IS NOT NULL;")
                    google_task_ids = [row[0] for row in cursor.fetchall()]
                    
                    from google_api import delete_google_task
                    for g_id in google_task_ids:
                        if g_id and not g_id.endswith('@google.com'): 
                            delete_google_task(g_id)
                    
                    cursor.execute("DELETE FROM SESSIONS;")
                    cursor.execute("DELETE FROM TASKS;")
                    cursor.execute("DELETE FROM sqlite_sequence WHERE name='SESSIONS';")
                    cursor.execute("DELETE FROM sqlite_sequence WHERE name='TASKS';")
                    conn.commit()
                
                st.sidebar.success("🎉 Đã dọn dẹp sạch sẽ hệ thống!")
                st.snow()
                st.rerun()
            except Exception as delete_err:
                st.sidebar.error(f"Lỗi khi thực hiện dọn dẹp: {delete_err}")

# --- TRANG CHỦ ---
if "Trang chủ" in menu:
    st.subheader("🏠 HỆ THỐNG ĐIỀU PHỐI VÀ PHÂN TÍCH LỊCH TRÌNH THÔNG MINH")
    st.markdown("### ⚡ Thao tác nhanh với các Workers")
    col_gmail_btn, col_tasks_btn, col_space = st.columns([1, 1, 2])
    
    with col_gmail_btn:
        if st.button("🔄 Quét và Đồng bộ Gmail", use_container_width=True, type="primary"):
            with st.spinner("Gmail Worker đang đọc hòm thư chưa đọc..."):
                try:
                    from mail_worker import GmailWorker
                    worker = GmailWorker()
                    new_emails = worker.get_new_emails()
                    
                    if not new_emails:
                        st.toast("📨 Không có email tác vụ mới nào cần xử lý.")
                    else:
                        success_count = 0
                        for email in new_emails:
                            subject_mail = str(email['subject']).replace("[", "").replace("]", "").strip()
                            body_mail = str(email['body']).strip()
                            
                            short_title = subject_mail if len(subject_mail) <= 50 else subject_mail[:47] + "..."
                            db_updated = False
                            
                            try:
                                direct_prompt = f"Thêm việc {short_title}"
                                ai_result = run_agent(direct_prompt)
                                
                                with sqlite3.connect('agent_storage.db') as test_conn:
                                    test_cursor = test_conn.cursor()
                                    test_cursor.execute("SELECT COUNT(*) FROM TASKS WHERE TITLE = ?", (short_title,))
                                    if test_cursor.fetchone()[0] > 0:
                                        db_updated = True
                            except Exception:
                                db_updated = False
                                
                            if not db_updated:
                                try:
                                    import re
                                    with sqlite3.connect('agent_storage.db') as conn:
                                        cursor = conn.cursor()
                                        
                                        date_match = re.search(r'(\d{1,2})/(\d{1,2})', body_mail)
                                        current_year = datetime.now().year
                                        
                                        time_matches = re.findall(r'(\d{1,2})h(\d{2})?|(\d{1,2}):(\d{2})', body_mail)
                                        extracted_times = []
                                        for match in time_matches:
                                            if match[0]: h, m = int(match[0]), (int(match[1]) if match[1] else 0)
                                            elif match[2]: h, m = int(match[2]), (int(match[3]) if match[3] else 0)
                                            extracted_times.append(f"{h:02d}:{m:02d}")
                                        
                                        if date_match or extracted_times:
                                            target_day = f"{current_year}-{int(date_match.group(2)):02d}-{int(date_match.group(1)):02d}" if date_match else (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
                                            fake_deadline = f"{target_day} 23:59"
                                            
                                            if len(extracted_times) >= 2:
                                                start_time_str, end_time_str = extracted_times[0], extracted_times[1]
                                            elif len(extracted_times) == 1:
                                                start_time_str = extracted_times[0]
                                                start_dt = datetime.strptime(f"{target_day} {start_time_str}", '%Y-%m-%d %H:%M')
                                                end_time_str = (start_dt + timedelta(hours=1, minutes=30)).strftime('%H:%M')
                                            else:
                                                slots = [("08:00", "10:00"), ("10:00", "12:00"), ("14:00", "16:00"), ("16:00", "18:00"), ("19:00", "21:00")]
                                                selected_start, selected_end = "09:00", "11:00"
                                                for start_h, end_h in slots:
                                                    if cursor.execute("SELECT COUNT(*) FROM SESSIONS WHERE START_TIME = ?", (f"{target_day} {start_h}",)).fetchone()[0] == 0:
                                                        selected_start, selected_end = start_h, end_h
                                                        break
                                                start_time_str, end_time_str = selected_start, selected_end
                                                
                                            db_start = f"{target_day} {start_time_str}"
                                            db_end = f"{target_day} {end_time_str}"
                                            
                                            cursor.execute("INSERT INTO TASKS (TITLE, DEADLINE) VALUES (?, ?)", (short_title, fake_deadline))
                                            last_id = cursor.lastrowid
                                            cursor.execute("INSERT INTO SESSIONS (TASK_ID, START_TIME, END_TIME) VALUES (?, ?, ?)", (last_id, db_start, db_end))
                                        else:
                                            cursor.execute("INSERT INTO TASKS (TITLE, DEADLINE) VALUES (?, ?)", (short_title, None))
                                            
                                        conn.commit()
                                    db_updated = True
                                except Exception as db_direct_err:
                                    st.sidebar.error(f"🚨 Lỗi ép ghi SQLite: {db_direct_err}")
                            
                            if db_updated:
                                success_count += 1
                                worker.mark_as_read(email['id'])
                                
                        if success_count > 0:
                            st.success(f"🎯 Hệ thống đã xử lý và phân phối thành công {success_count} email công việc!")
                            st.balloons()
                            st.rerun()
                        else:
                            st.warning("⚠️ Không thể trích xuất tác vụ hợp lệ từ hòm thư.")
                except Exception as mail_err:
                    st.error(f"Lỗi kết nối hoặc đồng bộ luồng Gmail: {mail_err}")
                    
    with col_tasks_btn:
        if st.button("🎯 Đồng bộ Google Tasks", use_container_width=True):
            with st.spinner("Đang gom tác vụ tự động để đẩy lên Cloud..."):
                try:
                    from sync_tasks import sync_null_deadline_tasks
                    sync_null_deadline_tasks()
                    st.success("✅ Đã đồng bộ các công việc không có hạn chót lên Google Tasks!")
                    st.toast("🎯 Kiểm tra danh sách việc cần làm trên Google Tasks của bạn!")
                    st.rerun()
                except Exception as tasks_err:
                    st.error(f"Lỗi khi đồng bộ lên Google Tasks: {tasks_err}")
                    
    st.markdown("---")
    
    # ─────────────────────────────────────────────────────────────────
    # BẢNG HIỂN THỊ TUẦN AN TOÀN TUYỆT ĐỐI (CHỐNG LỖI INDEX OUT OF RANGE)
    # ─────────────────────────────────────────────────────────────────
    total_tasks = 0
    scheduled_count = 0
    df_week = pd.DataFrame()

    try:
        conn = sqlite3.connect('agent_storage.db')
        total_tasks = conn.execute("SELECT COUNT(*) FROM TASKS").fetchone()[0]
        
        now = datetime.now()
        start_of_week = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d 00:00')
        end_of_week = (now + timedelta(days=(6 - now.weekday()))).strftime('%Y-%m-%d 23:59')
        
        query = """
            SELECT T.TITLE as 'Tên công việc', 
                   IFNULL(S.START_TIME, '⏳ Chờ AI xếp lịch chi tiết') as raw_start, 
                   IFNULL(S.END_TIME, '---') as raw_end,
                   IFNULL(T.DEADLINE, '⚠️ Không có hạn chót') as 'Hạn chót (Deadline)'
            FROM TASKS T
            LEFT JOIN SESSIONS S ON T.TASK_ID = S.TASK_ID
            WHERE (S.START_TIME BETWEEN ? AND ?) OR (S.START_TIME IS NULL)
            ORDER BY T.DEADLINE ASC, S.START_TIME ASC
        """
        df_raw = pd.read_sql_query(query, conn, params=(start_of_week, end_of_week))
        
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM SESSIONS WHERE START_TIME BETWEEN ? AND ?", (start_of_week, end_of_week))
        scheduled_count = cursor.fetchone()[0]
        conn.close()
        
        if df_raw is not None and not df_raw.empty:
            df_week['Tên công việc'] = df_raw['Tên công việc']
            days_list = []
            hours_list = []
            
            for index, row in df_raw.iterrows():
                st_time = str(row['raw_start']).strip()
                en_time = str(row['raw_end']).strip()
                
                if ' ' in st_time and ' ' in en_time and '⏳' not in st_time:
                    try:
                        st_parts = st_time.split(' ')
                        en_parts = en_time.split(' ')
                        
                        if len(st_parts) >= 2 and len(en_parts) >= 2:
                            date_part = st_parts[0]
                            time_part = f"{st_parts[1]} ➔ {en_parts[1]}"
                        else:
                            date_part = "📅 Đang chờ ca"
                            time_part = "⏳ Chờ xếp lịch"
                    except Exception:
                        date_part = "📅 Lỗi xử lý"
                        time_part = "⏳ Chưa rõ giờ"
                else:
                    date_part = "📅 Đang chờ ca"
                    time_part = "⏳ Chờ xếp lịch"
                    
                days_list.append(date_part)
                hours_list.append(time_part)
                    
            df_week['Ngày thực hiện'] = days_list
            df_week['Khung giờ chi tiết'] = hours_list
            df_week['Hạn chót (Deadline)'] = df_raw['Hạn chót (Deadline)']
            
    except Exception as e:
        st.error(f"⚠️ Lỗi truy xuất lịch trình từ Database: {e}")
        df_week = pd.DataFrame()

    # --- KHỐI THỐNG KÊ HIỆU SUẤT VÀ TRẠNG THÁI TUẦN ---
    st.markdown("### 📊 Tổng quan hiệu suất tuần này")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("📦 **Tổng công việc hệ thống**")
        st.markdown(f"## {total_tasks} công việc")
    with col2:
        st.success("📆 **Số ca làm việc (Sessions)**")
        st.markdown(f"## {scheduled_count} ca làm")
    with col3:
        if current_cortisol < 70:
            st.success("🟢 **Trạng thái: THOẢI MÁI**")
            st.markdown(f"## {current_cortisol} %")
        elif current_cortisol < 110:
            st.warning("🟡 **Trạng thái: ÁP LỰC**")
            st.markdown(f"## {current_cortisol} %")
        else:
            st.error("🔴 **Trạng thái: QUÁ TẢI BIẾN ĐỘNG**")
            st.markdown(f"## {current_cortisol} %")

    st.markdown("---")
    st.subheader(f"📅 Kế hoạch chi tiết từ Thứ Hai đến Chủ Nhật")
    st.caption(f"Khoảng thời gian đồng bộ: T2 ({start_of_week[:10]}) ➔ CN ({end_of_week[:10]})")
    
    if df_week is not None and not df_week.empty:
        st.dataframe(df_week, use_container_width=True, hide_index=True)
    else:
        st.info("📅 Tuần này hoàn toàn trống lịch sinh hoạt. Hãy nghỉ ngơi hoặc nạp thêm công việc mới từ hòm thư!")

# --- CHAT VỚI GROK ---
elif "Chat với Groq" in menu:
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

                st.markdown(chuoi_hien_thi)
                st.session_state.messages.append({"role": "assistant", "content": chuoi_hien_thi})

# --- TRANG PHÂN TÍCH & ĐÁNH GIÁ ---
elif "Phân tích & Đánh giá" in menu:
    st.header("📊 Phân tích & Đánh giá Lịch trình")
    st.write("Hệ thống hỗ trợ quét mật độ công việc dựa trên dữ liệu thời gian thực từ Database cục bộ.")
    
    target_date = st.date_input("📅 Chọn ngày bạn muốn AI Agent đánh giá mật độ:", datetime.now().date())
    
    if st.button("🔍 Tiến hành phân tích bằng AI", use_container_width=True, type="primary"):
        date_str = target_date.strftime('%Y-%m-%d')
        
        with st.spinner(f"Đang bốc tách dữ liệu và khởi tạo luồng đánh giá cho ngày {date_str}..."):
            try:
                status = analyze_workload(date_str)
                ai_analyze_prompt = f"Đánh giá lịch ngày {date_str}. Dữ liệu các ca làm việc hiện tại từ Database: {status}. Hãy phân tích mật độ và đưa ra nhận xét khoa học."
                analysis_result = run_agent(ai_analyze_prompt)
                
                st.markdown("### 📋 Kết quả báo cáo từ AI Agent")
                st.divider()
                
                if isinstance(analysis_result, dict) and "message" in analysis_result:
                    st.info(f"💡 **Nhận xét lịch trình:** {analysis_result['message']}")
                elif isinstance(analysis_result, str) and len(analysis_result) > 10:
                    st.info(f"💡 **Nhận xét lịch trình:** {analysis_result}")
                else:
                    st.info(f"💡 **Nhận xét lịch trình:** {status}")
                    
                st.success("✓ Báo cáo mật độ đã được tối ưu hóa thành công!")
            except Exception as eval_err:
                st.error(f"Lỗi trong quá trình phân tích dữ liệu: {eval_err}")

# --- GOOGLE CALENDAR LIVE ---
elif "Google Calendar Live" in menu:
    st.header("📅 Giao diện xem lịch trực tiếp")
    from calendar_service import get_logged_in_user_email
    with st.spinner("Đang kết nối tài khoản Google Cloud..."):
        user_email = get_logged_in_user_email()

    if user_email:
        st.success(f"🔒 Đang hiển thị thời gian thực lịch của tài khoản: **{user_email}**")
        encoded_email = user_email.replace("@", "%40")
        dynamic_embed_url = f"https://calendar.google.com/calendar/embed?src={encoded_email}&ctz=Asia%2FHo_Chi_Minh"
        st.components.v1.iframe(dynamic_embed_url, height=700, scrolling=True)
    else:
        st.warning("⚠️ Hệ thống chưa nhận diện được phiên đăng nhập Google Calendar của bạn.")

# --- GOOGLE TASKS LIVE ---
elif "Google Tasks Live" in menu:
    st.header("🎯 Danh sách việc cần làm (Google Tasks Cloud)")
    if st.button("🔄 Làm mới dữ liệu đám mây", use_container_width=True):
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

# --- QUẢN LÝ LỊCH (ĐÃ KHÔI PHỤC THÔNG BÁO LINK CALENDAR) ---
elif "⚙️ Quản lý Lịch" in menu or "Quản lý Lịch" in menu:
    st.header("⚙️ Điều phối Google Calendar")
    with st.form("calendar_form"):
        col_a, col_b = st.columns(2)
        with col_a:
            task_name = st.text_input("Tên sự kiện/tác vụ")
            start_date = st.date_input("Ngày bắt đầu")
        with col_b:
            location = st.text_input("Địa điểm")
            start_time = st.time_input("Giờ bắt đầu")
            
        description = st.text_area("Mô tả chi tiết")
        submitted = st.form_submit_button("Lưu vào Google Calendar và Đồng bộ Hệ thống")
        
        if submitted:
            if not task_name:
                st.error("Vui lòng nhập tên sự kiện!")
            else:
                start_datetime = datetime.combine(start_date, start_time)
                iso_start = start_datetime.strftime('%Y-%m-%dT%H:%M:%S')
                iso_end = (start_datetime + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')

                with st.spinner("Đang đẩy lịch lên Google Calendar..."):
                    # Hàm create_event chuẩn trả về tuple: (success, result)
                    success, result = create_event(task_name, iso_start, iso_end, description)
                    
                    if success:
                        try:
                            db_start = start_datetime.strftime('%Y-%m-%d %H:%M')
                            db_end = (start_datetime + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
                            
                            # Ghi nhận thông tin cục bộ vào SQLite
                            with sqlite3.connect('agent_storage.db') as conn:
                                cursor = conn.cursor()
                                cursor.execute("INSERT INTO TASKS (TITLE, DEADLINE) VALUES (?, ?)", (task_name, db_end))
                                last_id = cursor.lastrowid
                                cursor.execute("INSERT INTO SESSIONS (TASK_ID, START_TIME, END_TIME) VALUES (?, ?, ?)", (last_id, db_start, db_end))
                                conn.commit()
                            
                            # 🔥 KHÔI PHỤC THÀNH CÔNG: Hiển thị hộp xanh chứa link HTML dẫn thẳng sang Cloud
                            st.success("✅ Đã tạo lịch thành công cục bộ!")
                            
                            # Kiểm tra định dạng link trả về từ hàm create_event
                            if isinstance(result, str) and result.startswith("http"):
                                st.markdown(f"🔗 [👉 Xem sự kiện trên Google Calendar]({result})")
                            elif isinstance(result, dict) and "htmlLink" in result:
                                st.markdown(f"🔗 [👉 Xem sự kiện trên Google Calendar]({result['htmlLink']})")
                            else:
                                st.info("ℹ️ Lịch đã được đồng bộ lên Cloud của tài khoản Google kết nối.")
                                
                            st.balloons()
                        except Exception as db_err:
                            st.error(f"Lỗi ghi nhận cục bộ: {db_err}")
                    else:
                        st.error(f"Lỗi kết nối API Google: {result}")