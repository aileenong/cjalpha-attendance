import streamlit as st
import sqlite3
import qrcode
import numpy as np
from io import BytesIO
from PIL import Image
import pandas as pd
import cv2
import av
from streamlit_webrtc import webrtc_streamer
import logging
from datetime import datetime
import time
import datetime

logging.getLogger("streamlit").setLevel(logging.ERROR)

# -----------------------------
# Login Setup
# -----------------------------
USERS = {
    "amy": "password123",   # replace with your desired password
    "jehan": "secure456"    # replace with your desired password
}

def login():
    st.title("🔐 CJ Alpha Attendance Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username in USERS and USERS[username] == password:
            st.session_state["authenticated"] = True
            st.session_state["user"] = username
            st.success(f"Welcome, {username}!")
            # wait 2 seconds before redirecting to the application
            time.sleep(2)
            st.rerun()
        else:
            st.error("Invalid username or password")

# -----------------------------
# Date Helpers
# -----------------------------
def get_current_month_range():
    today = datetime.date.today()
    start_date = today.replace(day=1)  # first day of month
    if today.month == 12:
        next_month = today.replace(year=today.year+1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month+1, day=1)
    end_date = next_month - datetime.timedelta(days=1)
    return start_date, end_date

# -----------------------------
# Database Setup
# -----------------------------
conn = sqlite3.connect("attendance.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    department TEXT,
    qr_code BLOB
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    check_in_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    check_out_time DATETIME,
    status TEXT,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
)
""")
conn.commit()

# -----------------------------
# Helper Functions
# -----------------------------
def add_employee(employee_code, name, department):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(employee_code)
    qr.make(fit=True)
    img = qr.make_image(fill="black", back_color="white")

    buf = BytesIO()
    img.save(buf, format="PNG")
    qr_bytes = buf.getvalue()

    cursor.execute(
        "INSERT INTO employees (employee_code, name, department, qr_code) VALUES (?, ?, ?, ?)",
        (employee_code, name, department, qr_bytes)
    )
    conn.commit()

    # Save QR locally too
    filename = f"{employee_code}_qr.png"
    img.save(filename, format="PNG")

def show_employee_qr(employee_code):
    cursor.execute("SELECT qr_code FROM employees WHERE employee_code=? or name=?", (employee_code,employee_code))
    row = cursor.fetchone()
    if row:
        qr_bytes = row[0]
        img = Image.open(BytesIO(qr_bytes))
        st.image(img, caption=f"QR Code for {employee_code}")

def log_attendance(emp_code):
    cursor.execute("SELECT id, name FROM employees WHERE employee_code=?", (emp_code,))
    row = cursor.fetchone()
    if not row:
        st.error("Employee not found!")
        return
       
    emp_id = row[0]
    name = row[1]
    
    cursor.execute("""
        SELECT id FROM attendance
        WHERE employee_id=? AND date(check_in_time)=date('now')
    """, (emp_id,))
    existing = cursor.fetchone()


    if existing:
        st.warning(f"Attendance already logged today for {emp_code} - {name}")
    else:
       # Insert with current timestamp
        cursor.execute(
            "INSERT INTO attendance (employee_id, status, check_in_time) VALUES (?, ?, datetime('now'))",
            (emp_id, "Present")
        )
        conn.commit()
        st.success(f"Attendance logged for {emp_code} - {name} at {datetime.now().strftime('%H:%M:%S')}")

def show_daily_report():
    query = """
    SELECT e.employee_code, e.name, e.department, a.check_in_time, a.check_out_time, a.status
    FROM attendance a
    JOIN employees e ON a.employee_id = e.id
    ORDER BY a.check_in_time DESC
    """
    df = pd.read_sql_query(query, conn)
    st.dataframe(df)

def show_employee_report(identifier, start_date=None, end_date=None):
    query = """
    SELECT e.employee_code, e.name, date(a.check_in_time) AS date_present
    FROM attendance a
    JOIN employees e ON a.employee_id = e.id
    WHERE (e.employee_code = ? OR e.name = ?)
    """
    params = [identifier, identifier]

    if start_date and end_date:
        query += " AND date(a.check_in_time) BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    elif start_date:
        query += " AND date(a.check_in_time) >= ?"
        params.append(start_date)
    elif end_date:
        query += " AND date(a.check_in_time) <= ?"
        params.append(end_date)

    query += " ORDER BY a.check_in_time DESC"

    df = pd.read_sql_query(query, conn, params=params)
    if df.empty:
        st.warning(f"No attendance records found for {identifier}")
    else:
        st.subheader(f"Attendance Report for {identifier}")
        st.dataframe(df)

        total_days = df["date_present"].nunique()
        st.info(f"{identifier} was present on {total_days} day(s) "
                f"between {start_date} and {end_date}.")

# -----------------------------
# QR Scanner using OpenCV
# -----------------------------
detector = cv2.QRCodeDetector()
placeholder = st.empty()

def video_frame_callback(frame):
    img = frame.to_ndarray(format="bgr24")
    data, bbox, _ = detector.detectAndDecode(img)

    if bbox is not None and data:
        st.session_state["last_qr"] = data.strip()
        n = len(bbox[0])
        for i in range(n):
            pt1 = tuple(bbox[0][i].astype(int))
            pt2 = tuple(bbox[0][(i+1) % n].astype(int))
            cv2.line(img, pt1, pt2, (0, 255, 0), 2)

    return av.VideoFrame.from_ndarray(img, format="bgr24")

def decode_qr_from_upload(uploaded_file):
    file_bytes = np.asarray(bytearray(uploaded_file.read()), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)

    detector = cv2.QRCodeDetector()
    data, bbox, _ = detector.detectAndDecode(img)

    if data:
        return data.strip()
    else:
        return None

# -----------------------------
# Main App
# -----------------------------
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    login()
else:
    st.sidebar.title("Attendance System")
    st.sidebar.write(f"Logged in as: {st.session_state['user']}")

    # Logout button
    if st.sidebar.button("Logout"):
        st.session_state["authenticated"] = False
        st.session_state["user"] = None
        st.rerun()

    # Restrict menu based on user
    if st.session_state["user"] == "amy":
        # Amy only sees Attendance
        menu = st.sidebar.selectbox("Main Menu", ["Attendance"])
    else:
        # Other users see full menu
        menu = st.sidebar.selectbox("Main Menu", ["Home", "Employee Management", "Attendance"])

    if menu == "Home":  
        st.title("🏠 Attendance Tracking System")
        st.write("Use the sidebar to navigate between Employee Management and Attendance.")

    elif menu == "Employee Management":
        st.title("👥 Employee Management")
        choice = st.radio("Options", ["Add Employee", "View Employees", "Show Employee QR"])

        if choice == "Add Employee":
            st.subheader("Add New Employee")
            code = st.text_input("Employee Code")
            name = st.text_input("Name")
            dept = st.text_input("Department")
            if st.button("Add"):
                if code and name:
                    try:
                        add_employee(code, name, dept)
                        st.success(f"Employee {name} added successfully!")
                    except Exception as e:
                        st.error(f"Error: {e}")
                else:
                    st.warning("Please enter both Employee Code and Name.")

        elif choice == "View Employees":
            st.subheader("All Employees")
            df = pd.read_sql_query("SELECT id, employee_code, name, department FROM employees", conn)
            st.dataframe(df)

            # Add delete options for each employee
            st.write("### Delete an Employee")
            for _, row in df.iterrows():
                col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 2])
                with col1:
                    st.write(row["employee_code"])
                with col2:
                    st.write(row["name"])
                with col3:
                    st.write(row["department"])
                with col4:
                    if st.button(f"Delete", key=row["id"]):
                        cursor.execute("DELETE FROM employees WHERE id=?", (row["id"],))
                        conn.commit()
                        st.warning(f"Employee {row['employee_code']} deleted.")
                        st.rerun()

        elif choice == "Show Employee QR":
            st.subheader("Show Employee QR Code")
            code = st.text_input("Enter Employee Code or Name")
            if st.button("Show QR"):
                show_employee_qr(code)

    elif menu == "Attendance":
        st.title("📅 Attendance")
        choice = st.radio("Options", ["Scan QR Code", "Daily Report", "Employee Report"])

        if choice == "Scan QR Code":
            st.subheader("Scan Employee QR Code")
            method = st.radio("Choose Scan Method", ["Upload QR Image", "Camera Scan"])

            if method == "Upload QR Image":
                uploaded_file = st.file_uploader("Upload QR Code Image", type=["png", "jpg", "jpeg"])
                if uploaded_file is not None:
                    qr_data = decode_qr_from_upload(uploaded_file)
                    if qr_data:
                        st.success(f"Decoded QR: {qr_data}")
                        if st.button("Log Attendance"):
                            log_attendance(qr_data)
                    else:
                        st.error("No QR code detected")
            
        elif choice == "Daily Report":
            st.subheader("Daily Attendance Report")
            show_daily_report()

        elif choice == "Employee Report":
            st.subheader("Employee Attendance Report")
            code = st.text_input("Enter Employee Code or Name")
            # Default to current month
            default_start, default_end = get_current_month_range()
            start_date = st.date_input("Start Date", default_start) 
            end_date = st.date_input("End Date", default_end)
            if st.button("Show Report"):
                start_str = start_date.strftime("%Y-%m-%d") if start_date else None
                end_str = end_date.strftime("%Y-%m-%d") if end_date else None
                show_employee_report(code, start_str, end_str)
