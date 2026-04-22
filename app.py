from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import threading
import time
import PyPDF2
import docx
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

app = Flask(__name__)
app.secret_key = "super_secret_key"

@app.context_processor
def inject_unread_counts():
    counts = {'admin_unread': 0, 'student_unread': 0}
    try:
        conn = get_db()
        cur = conn.cursor()
        
        if 'admin' in session:
            cur.execute("SELECT COUNT(*) FROM messages WHERE sender = 'student' AND is_read = 0")
            counts['admin_unread'] = cur.fetchone()[0]
            
        if 'student_id' in session:
            student_id = session['student_id']
            cur.execute("SELECT COUNT(*) FROM messages WHERE student_id = ? AND sender = 'admin' AND is_read = 0", (student_id,))
            counts['student_unread'] = cur.fetchone()[0]
            
        conn.close()
    except Exception:
        pass
    
    return counts

def send_email(to_email, subject, body, is_html=False):
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    APP_PASSWORD = os.getenv("SENDER_PASSWORD")

    try:
        msg = MIMEText(body, "html" if is_html else "plain")
        msg["Subject"] = subject
        msg["From"] = f"CareerConnect <{SENDER_EMAIL}>"
        msg["To"] = to_email

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False

# ----------------ADMIN LOGIN----------------
ADMIN_CREDENTIALS = {
    "admin": "123"
}

# ---------------- DATABASE CONNECTION ----------------
def get_db():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "database.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------- CREATE TABLE ----------------
def create_table():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll_number TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            course TEXT NOT NULL,
            section TEXT NOT NULL
        )
    """)
    cur.execute("PRAGMA table_info(students)")
    columns = [col[1] for col in cur.fetchall()]
    if "photo" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN photo TEXT")
    if "phone" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN phone TEXT")
    if "email" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN email TEXT")
    if "cgpa" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN cgpa REAL")
    if "current_sem_percentage" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN current_sem_percentage REAL")
    if "current_sem" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN current_sem TEXT")
    if "sslc_percentage" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN sslc_percentage REAL")
    if "puc_percentage" not in columns:
        cur.execute("ALTER TABLE students ADD COLUMN puc_percentage REAL")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            about TEXT NOT NULL,
            end_date TEXT
        )
    """)
    cur.execute("PRAGMA table_info(companies)")
    columns = [col[1] for col in cur.fetchall()]
    if "end_date" not in columns:
        cur.execute("ALTER TABLE companies ADD COLUMN end_date TEXT")
    if "reminder_sent" not in columns:
        cur.execute("ALTER TABLE companies ADD COLUMN reminder_sent INTEGER DEFAULT 0")
        
    # Check for job_remarks updates
    cur.execute("PRAGMA table_info(job_remarks)")
    columns = [col[1] for col in cur.fetchall()]
    if "admin_reply" not in columns and len(columns) > 0:
        cur.execute("ALTER TABLE job_remarks ADD COLUMN admin_reply TEXT")
        
    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT,
            photo TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS job_remarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            admin_reply TEXT,
            is_resolved INTEGER DEFAULT 0,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id),
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS achievement_action (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            achievement_id INTEGER,
            student_id INTEGER,
            action_type TEXT,
            FOREIGN KEY (achievement_id) REFERENCES achievements(id),
            FOREIGN KEY (student_id) REFERENCES students(id),
            UNIQUE(achievement_id, student_id, action_type)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read INTEGER DEFAULT 0,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    """)
    conn.commit()
    conn.close()

create_table()

def extract_text_from_pdf(file_path):
    text = ""
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text()
    except Exception as e:
        print(f"Error extracting PDF: {e}")
    return text

def extract_text_from_docx(file_path):
    text = ""
    try:
        doc = docx.Document(file_path)
        for para in doc.paragraphs:
            text += para.text + "\n"
    except Exception as e:
        print(f"Error extracting DOCX: {e}")
    return text

def get_gemini_analysis(resume_text, job_name=None):
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    if job_name:
        prompt = f"""
        Analyze the following resume for the job role: {job_name}.
        1. Determine if the resume is suitable for this job (Yes/No/Partial).
        2. Provide a brief explanation of why.
        3. Suggest specifically what elements, skills, or projects the student should add to their resume to make it more suitable for this job.
        
        Resume Content:
        {resume_text}
        
        Format the response in HTML (use <h3>, <p>, <ul>, <li> tags).
        """
    else:
        prompt = f"""
        Analyze the following resume and suggest suitable job roles or career paths for this student.
        Explain why these roles are suitable based on their current skills and experience.
        
        Resume Content:
        {resume_text}
        
        Format the response in HTML (use <h3>, <p>, <ul>, <li> tags).
        """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"<h3>Error during analysis</h3><p>{str(e)}</p>"

# ---------------- LOGIN ----------------
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_type = request.form.get('user_type')

        # -------- ADMIN LOGIN --------
        if user_type == 'admin':
            username = request.form.get('username')
            password = request.form.get('password')

            if ADMIN_CREDENTIALS.get(username) == password:
                session['admin'] = username
                return redirect(url_for('admin_dashboard'))
            else:
                flash("Invalid Admin Credentials!", "error")

        # -------- STUDENT LOGIN --------
        elif user_type == 'student':
            reg_no = request.form.get('reg_no', '').strip()
            password = request.form.get('password', '').strip()

            # Typically roll numbers are uppercase
            reg_no_upper = reg_no.upper()

            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM students WHERE UPPER(roll_number)=? AND password=?",
                (reg_no_upper, password)
            )
            student = cur.fetchone()
            conn.close()

            if student:
                session['student_id'] = student['id']
                return redirect(url_for('student_profile'))
            else:
                flash("Invalid Registration Number or Password!", "error")

        return render_template('login.html', user_type=user_type)

    return render_template('login.html')


# ---------------- ADMIN DASHBOARD ----------------
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin' not in session:
        return redirect(url_for('login'))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students")
    students = cur.fetchall()

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("SELECT * FROM companies WHERE end_date >= ? OR end_date IS NULL", (now_str,))
    companies = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM achievements")
    total_achievements = cur.fetchone()[0]

    cur.execute("""
        SELECT s.name as student_name, s.roll_number, c.name as company_name, 
               datetime(a.applied_at, 'localtime') as applied_at 
        FROM applications a
        JOIN students s ON a.student_id = s.id
        JOIN companies c ON a.company_id = c.id
        ORDER BY a.applied_at DESC
    """)
    applications = cur.fetchall()

    total_students = len(students)
    total_companies = len(companies)
    total_applications = len(applications)

    # Chart 1: Applications Over Time (Last 7 Days)
    cur.execute("""
        SELECT date(applied_at, 'localtime') as app_date, COUNT(*) as count 
        FROM applications 
        GROUP BY date(applied_at, 'localtime') 
        ORDER BY app_date DESC LIMIT 7
    """)
    apps_by_date = cur.fetchall()
    apps_by_date = sorted([dict(row) for row in apps_by_date], key=lambda x: x['app_date'])
    
    # Chart 2: Students By Course
    cur.execute("SELECT course, COUNT(*) as count FROM students GROUP BY course")
    students_by_course = [dict(row) for row in cur.fetchall()]

    # Chart 3: Applications By Company
    cur.execute("""
        SELECT c.name, COUNT(a.id) as count 
        FROM companies c 
        LEFT JOIN applications a ON c.id = a.company_id 
        GROUP BY c.id 
        ORDER BY count DESC LIMIT 5
    """)
    apps_by_company = [dict(row) for row in cur.fetchall()]

    # --- USEFUL INSIGHTS CALCULATIONS ---
    # 1. Peak Application Day
    peak_day = "None"
    if apps_by_date:
        peak_day = sorted(apps_by_date, key=lambda x: x['count'], reverse=True)[0]['app_date']
        peak_day = datetime.strptime(peak_day, '%Y-%m-%d').strftime('%A')
    
    # 2. Most Active Course
    most_active_course = "N/A"
    cur.execute("""
        SELECT s.course, COUNT(a.id) as count 
        FROM applications a 
        JOIN students s ON a.student_id = s.id 
        GROUP BY s.course ORDER BY count DESC LIMIT 1
    """)
    res = cur.fetchone()
    if res:
        most_active_course = res['course']
    
    # 3. Upcoming Deadlines (Next 48 Hours)
    deadline_threshold = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("SELECT COUNT(*) FROM companies WHERE end_date <= ? AND end_date >= ?", (deadline_threshold, now_str))
    upcoming_deadlines = cur.fetchone()[0]

    conn.close()
    
    return render_template('admin_dashboard.html', 
                           students=students, 
                           applications=applications,
                           total_students=total_students,
                           total_companies=total_companies,
                           total_applications=total_applications,
                           total_achievements=total_achievements,
                           apps_by_date=apps_by_date,
                           students_by_course=students_by_course,
                           apps_by_company=apps_by_company,
                           peak_day=peak_day,
                           most_active_course=most_active_course,
                           upcoming_deadlines=upcoming_deadlines)


# -------------- ADMIN STUDENTS PAGE --------------
@app.route('/admin_students')
def admin_students():
    if 'admin' not in session:
        return redirect(url_for('login'))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students")
    students = cur.fetchall()
    conn.close()
    return render_template('admin_students.html', students=students)


# ---------------- ADMIN ACHIEVEMENTS PAGE ----------------
@app.route('/admin_achievements')
def admin_achievements():
    if 'admin' not in session:
        return redirect(url_for('login'))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.description, a.photo, a.created_at,
               (SELECT COUNT(*) FROM achievement_action WHERE achievement_id = a.id AND action_type = 'view') as views,
               (SELECT COUNT(*) FROM achievement_action WHERE achievement_id = a.id AND action_type = 'like') as likes,
               (SELECT GROUP_CONCAT(s.name, ', ') 
                FROM achievement_action ac 
                JOIN students s ON ac.student_id = s.id 
                WHERE ac.achievement_id = a.id AND ac.action_type = 'view') as viewer_names
        FROM achievements a
        ORDER BY a.created_at DESC
    """)
    achievements = cur.fetchall()
    conn.close()
    
    return render_template('admin_achievements.html', achievements=achievements)


@app.route('/add_achievement', methods=['GET', 'POST'])
def add_achievement():
    if 'admin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        description = request.form.get('description', '')
        photo = request.files.get('photo')

        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            upload_folder = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            photo_path = os.path.join(upload_folder, filename)
            photo.save(photo_path)

            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO achievements (description, photo)
                VALUES (?, ?)
            """, (description, filename))
            conn.commit()
            conn.close()

            flash("Achievement Added Successfully!", "success")
            return redirect(url_for('admin_achievements'))
        else:
            flash("Please upload a photo.", "error")

    return render_template('add_achievement.html')

# ---------------- STUDENT ACHIEVEMENTS PAGE ----------------
@app.route('/student_achievements')
def student_achievements():
    if 'student_id' not in session:
        return redirect(url_for('login'))

    student_id = session['student_id']
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT a.id, a.description, a.photo, a.created_at,
               (SELECT COUNT(*) FROM achievement_action WHERE achievement_id = a.id AND action_type = 'view') as views,
               (SELECT COUNT(*) FROM achievement_action WHERE achievement_id = a.id AND action_type = 'like') as likes,
               EXISTS(SELECT 1 FROM achievement_action WHERE achievement_id = a.id AND student_id = ? AND action_type = 'like') as liked_by_me
        FROM achievements a
        ORDER BY a.created_at DESC
    """, (student_id,))
    achievements_raw = cur.fetchall()
    achievements = [dict(a) for a in achievements_raw]
    
    cur.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    student = cur.fetchone()
    conn.close()
    
    return render_template('student_achievements.html', achievements=achievements, student=student)


@app.route('/achievement_action', methods=['POST'])
def achievement_action():
    if 'student_id' not in session:
        return {'status': 'error', 'message': 'Not logged in'}, 401
        
    student_id = session['student_id']
    achievement_id = request.form.get('achievement_id')
    action_type = request.form.get('action_type')
    
    if not achievement_id or not action_type:
        return {'status': 'error'}, 400
        
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT OR IGNORE INTO achievement_action (achievement_id, student_id, action_type)
            VALUES (?, ?, ?)
        """, (achievement_id, student_id, action_type))
        conn.commit()
        
        cur.execute("SELECT COUNT(*) as count FROM achievement_action WHERE achievement_id = ? AND action_type = ?", (achievement_id, action_type))
        count = cur.fetchone()['count']
        
        cur.execute("SELECT 1 FROM achievement_action WHERE achievement_id = ? AND student_id = ? AND action_type = 'like'", (achievement_id, student_id))
        liked_by_me = cur.fetchone() is not None
        
        conn.close()
        return {'status': 'success', 'count': count, 'liked_by_me': liked_by_me}
    except Exception as e:
        return {'status': 'error'}, 500


# ---------------- ADMIN COMPANIES PAGE ----------------
@app.route('/admin_companies')
def admin_companies():
    if 'admin' not in session:
        return redirect(url_for('login'))
        
    conn = get_db()
    cur = conn.cursor()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("SELECT * FROM companies WHERE end_date >= ? OR end_date IS NULL", (now_str,))
    companies = cur.fetchall()
    conn.close()
    
    return render_template('admin_companies.html', companies=companies)


# ---------------- ADD STUDENT ----------------
@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if 'admin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        roll = request.form['roll_number']
        course = request.form['course']
        section = request.form['section']

        phone = request.form.get('phone')
        email = request.form.get('email')
        cgpa = request.form.get('cgpa')
        current_sem_percentage = request.form.get('current_sem_percentage')
        current_sem = request.form.get('current_sem')
        sslc_percentage = request.form.get('sslc_percentage')
        puc_percentage = request.form.get('puc_percentage')

        password = roll  # Default password
        
        photo = request.files.get('photo')
        photo_filename = None
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            upload_folder = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            photo_path = os.path.join(upload_folder, filename)
            photo.save(photo_path)
            photo_filename = filename

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO students (name, roll_number, password, course, section, photo, phone, email, cgpa, current_sem_percentage, current_sem, sslc_percentage, puc_percentage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, roll, password, course, section, photo_filename, phone, email, cgpa, current_sem_percentage, current_sem, sslc_percentage, puc_percentage))
            conn.commit()
            conn.close()

            if email:
                subject = "Welcome to CareerConnect!"
                body = f"Hello {name},\n\nYour account has been created.\nYour Roll Number is: {roll}\nYour Default Password is: {password}\n\nPlease login and update your profile."
                send_email(email, subject, body)

            flash("Student Added Successfully!", "success")
            return redirect(url_for('admin_dashboard'))

        except sqlite3.IntegrityError:
            flash("Roll Number Already Exists!", "error")

    return render_template('add_student.html')


# ---------------- EDIT STUDENT ----------------
@app.route('/edit_student/<int:id>', methods=['GET', 'POST'])
def edit_student(id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        roll = request.form['roll_number']
        course = request.form['course']
        section = request.form['section']
        phone = request.form.get('phone')
        email = request.form.get('email')
        cgpa = request.form.get('cgpa')
        current_sem_percentage = request.form.get('current_sem_percentage')
        current_sem = request.form.get('current_sem')
        sslc_percentage = request.form.get('sslc_percentage')
        puc_percentage = request.form.get('puc_percentage')

        # Photo handling
        photo = request.files.get('photo')
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            upload_folder = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            photo_path = os.path.join(upload_folder, filename)
            photo.save(photo_path)
            
            cur.execute("""
                UPDATE students SET name=?, roll_number=?, course=?, section=?, phone=?, email=?, photo=?, cgpa=?, current_sem_percentage=?, current_sem=?, sslc_percentage=?, puc_percentage=? WHERE id=?
            """, (name, roll, course, section, phone, email, filename, cgpa, current_sem_percentage, current_sem, sslc_percentage, puc_percentage, id))
        else:
            cur.execute("""
                UPDATE students SET name=?, roll_number=?, course=?, section=?, phone=?, email=?, cgpa=?, current_sem_percentage=?, current_sem=?, sslc_percentage=?, puc_percentage=? WHERE id=?
            """, (name, roll, course, section, phone, email, cgpa, current_sem_percentage, current_sem, sslc_percentage, puc_percentage, id))
            
        conn.commit()
        conn.close()
        flash("Student Updated Successfully!", "success")
        return redirect(url_for('admin_students'))

    cur.execute("SELECT * FROM students WHERE id=?", (id,))
    student = cur.fetchone()
    conn.close()
    
    if not student:
        flash("Student not found", "error")
        return redirect(url_for('admin_students'))
        
    return render_template('edit_student.html', student=student)


# ---------------- DELETE STUDENT ----------------
@app.route('/delete_student/<int:id>', methods=['POST'])
def delete_student(id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()
    # Also delete applications if any
    cur.execute("DELETE FROM applications WHERE student_id=?", (id,))
    cur.execute("DELETE FROM students WHERE id=?", (id,))
    conn.commit()
    conn.close()
    
    flash("Student Deleted Successfully!", "success")
    return redirect(url_for('admin_students'))


# ---------------- STUDENT PROFILE ----------------
@app.route('/student_profile')
def student_profile():
    if 'student_id' not in session:
        return redirect(url_for('login'))

    student_id = session['student_id']

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()

    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("SELECT * FROM companies WHERE end_date >= ? OR end_date IS NULL", (now_str,))
    companies_raw = cur.fetchall()
    # Achievements logic moved to separate route
    
    conn.close()

    companies = []
    for c in companies_raw:
        c_dict = dict(c)
        if c_dict.get('end_date'):
            ed_str = c_dict['end_date'].replace('T', ' ')
            if len(ed_str) == 16:
                ed_str += ':00'
            try:
                try:
                    end_dt = datetime.strptime(ed_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    end_dt = datetime.strptime(ed_str, '%Y-%m-%d')
                
                diff = end_dt - now
                if timedelta(0) < diff <= timedelta(hours=24):
                    c_dict['show_timer'] = True
                    c_dict['end_timestamp'] = end_dt.timestamp() * 1000
            except ValueError:
                pass
        companies.append(c_dict)

    return render_template('student_profile.html', student=student, companies=companies)


# ---------------- EDIT MY PROFILE ----------------
@app.route('/edit_my_profile', methods=['GET', 'POST'])
def edit_my_profile():
    if 'student_id' not in session:
        return redirect(url_for('login'))

    student_id = session['student_id']
    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        phone = request.form.get('phone')
        email = request.form.get('email')
        cgpa = request.form.get('cgpa')
        current_sem_percentage = request.form.get('current_sem_percentage')
        current_sem = request.form.get('current_sem')
        sslc_percentage = request.form.get('sslc_percentage')
        puc_percentage = request.form.get('puc_percentage')

        try:
            cur.execute("""
                UPDATE students SET phone=?, email=?, cgpa=?, current_sem_percentage=?, current_sem=?, sslc_percentage=?, puc_percentage=? WHERE id=?
            """, (phone, email, cgpa, current_sem_percentage, current_sem, sslc_percentage, puc_percentage, student_id))
            conn.commit()
            flash("Profile Updated Successfully!", "success")
            return redirect(url_for('student_profile'))
        except Exception as e:
            flash("Update failed, please try again.", "error")
        finally:
            conn.close()

    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()
    conn.close()

    return render_template('edit_my_profile.html', student=student)


# ---------------- RESUME BUILDER ----------------
@app.route('/resume_builder')
def resume_builder():
    if 'student_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE id = ?", (session['student_id'],))
    student = cur.fetchone()
    conn.close()
    
    return render_template('resume_templates.html', student=student)

@app.route('/resume_builder/<template_id>')
def edit_resume(template_id):
    if 'student_id' not in session:
        return redirect(url_for('login'))
    
    student_id = session['student_id']
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()
    conn.close()

    return render_template('edit_resume.html', template_id=template_id, student=student)


# ---------------- LOGOUT ----------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------- APPLY TO COMPANY ----------------
@app.route('/apply/<int:company_id>')
def apply_company(company_id):
    if 'student_id' not in session:
        return redirect(url_for('login'))
        
    student_id = session['student_id']
    
    conn = get_db()
    cur = conn.cursor()
    
    # Track the application if it hasn't been tracked yet
    cur.execute("SELECT id FROM applications WHERE student_id=? AND company_id=?", (student_id, company_id))
    if not cur.fetchone():
        cur.execute("INSERT INTO applications (student_id, company_id) VALUES (?, ?)", (student_id, company_id))
        conn.commit()
        
    # Log that the student opened the job link
    cur.execute("INSERT INTO job_remarks (student_id, company_id, status) VALUES (?, ?, 'Opened')", (student_id, company_id))
    conn.commit()
    
    cur.execute("SELECT url FROM companies WHERE id=?", (company_id,))
    company = cur.fetchone()
    conn.close()
    
    if company:
        return redirect(company['url'])
        
    return redirect(url_for('student_profile'))


# ---------------- SUBMIT JOB REMARK ----------------
@app.route('/submit_job_remark', methods=['POST'])
def submit_job_remark():
    if 'student_id' not in session:
        return redirect(url_for('login'))
        
    student_id = session['student_id']
    company_id = request.form.get('company_id')
    status = request.form.get('status')
    message = request.form.get('message', '')
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO job_remarks (student_id, company_id, status, message)
            VALUES (?, ?, ?, ?)
        """, (student_id, company_id, status, message))
        
        # If status is Applied, also track application if not tracked yet
        if status == 'Applied':
            cur.execute("SELECT id FROM applications WHERE student_id=? AND company_id=?", (student_id, company_id))
            if not cur.fetchone():
                cur.execute("INSERT INTO applications (student_id, company_id) VALUES (?, ?)", (student_id, company_id))
        
        conn.commit()
        flash("Remark submitted successfully!", "success")
    except Exception as e:
        flash("Error submitting remark.", "error")
    finally:
        conn.close()
        
    return redirect(url_for('student_profile'))


# ----------------- RESUME ANALYZER ROUTE -----------------
@app.route('/resume_analyzer', methods=['GET', 'POST'])
def resume_analyzer():
    if 'student_id' not in session:
        return redirect(url_for('login'))
        
    analysis = None
    job_name = None
    
    if request.method == 'POST':
        job_name = request.form.get('job_name')
        resume_file = request.files.get('resume')
        
        if resume_file and resume_file.filename:
            filename = secure_filename(resume_file.filename)
            upload_folder = os.path.join(app.root_path, 'static', 'uploads', 'resumes')
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, filename)
            resume_file.save(file_path)
            
            # Extract text
            if filename.lower().endswith('.pdf'):
                resume_text = extract_text_from_pdf(file_path)
            elif filename.lower().endswith('.docx'):
                resume_text = extract_text_from_docx(file_path)
            else:
                flash("Unsupported file format. Please upload PDF or DOCX.", "error")
                return redirect(url_for('resume_analyzer'))
            
            if not resume_text.strip():
                flash("Could not extract text from the resume. Please check the file.", "error")
                return redirect(url_for('resume_analyzer'))
            
            # Get Gemini analysis
            analysis = get_gemini_analysis(resume_text, job_name)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE id = ?", (session['student_id'],))
    student = cur.fetchone()
    conn.close()

    return render_template('resume_analyzer.html', analysis=analysis, job_name=job_name, student=student)


# ---------------- MOCK INTERVIEW ----------------
@app.route('/mock_interview')
def mock_interview():
    if 'student_id' not in session:
        return redirect(url_for('login'))
        
    student_id = session['student_id']
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    student = cur.fetchone()
    conn.close()

    step = session.get('int_step', 0)
    question = session.get('int_current_q', '')
    history = session.get('int_history', [])
    feedback = session.get('int_feedback', None)

    return render_template('mock_interview.html', 
                         student=student, 
                         step=step, 
                         question=question, 
                         history=history,
                         feedback=feedback)

@app.route('/mock_interview/start', methods=['POST'])
def mock_interview_start():
    if 'student_id' not in session:
        return redirect(url_for('login'))
    
    resume_file = request.files.get('resume')
    if not resume_file or not resume_file.filename:
        flash("Please upload a resume to start.", "error")
        return redirect(url_for('mock_interview'))
    
    filename = secure_filename(resume_file.filename)
    upload_folder = os.path.join(app.root_path, 'static', 'uploads', 'resumes')
    os.makedirs(upload_folder, exist_ok=True)
    file_path = os.path.join(upload_folder, filename)
    resume_file.save(file_path)
    
    if filename.lower().endswith('.pdf'):
        resume_text = extract_text_from_pdf(file_path)
    elif filename.lower().endswith('.docx'):
        resume_text = extract_text_from_docx(file_path)
    else:
        flash("Unsupported format.", "error")
        return redirect(url_for('mock_interview'))
    
    if not resume_text.strip():
        flash("Could not extract text.", "error")
        return redirect(url_for('mock_interview'))
    
    # Initialize session
    session['int_resume_text'] = resume_text
    session['int_history'] = []
    session['int_step'] = 1
    
    # Generate first question
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""
    You are a professional HR interviewer.
    Generate the FIRST unique interview question based on this resume.
    Resume: {resume_text}
    Rules:
    - Output ONLY the question.
    - No introductions or explanations.
    """
    try:
        response = model.generate_content(prompt)
        session['int_current_q'] = response.text.strip()
    except:
        session['int_current_q'] = "Can you tell me about yourself and your background?"
    
    return redirect(url_for('mock_interview'))

@app.route('/mock_interview/answer', methods=['POST'])
def mock_interview_answer():
    if 'student_id' not in session:
        return redirect(url_for('login'))
    
    answer = request.form.get('answer')
    if not answer:
        return redirect(url_for('mock_interview'))
    
    history = session.get('int_history', [])
    current_q = session.get('int_current_q', '')
    step = session.get('int_step', 1)
    resume_text = session.get('int_resume_text', '')
    
    history.append({'q': current_q, 'a': answer})
    session['int_history'] = history
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    if step < 5:
        # Generate next question
        session['int_step'] = step + 1
        # Format previous questions for the prompt
        prev_qs = [h['q'] for h in history]
        
        prompt = f"""
        You are a professional HR interviewer.
        Resume: {resume_text}
        
        List of previously asked questions:
        {prev_qs}
        
        Task: Generate the NEXT UNIQUE interview question (Question {step + 1} of 5).
        
        Rules:
        - DO NOT REPEAT any question from the list above.
        - Ensure the new question is completely different from previous ones.
        - The question should be relevant to the resume or a follow-up to the last answer.
        - Output ONLY the question text.
        """
        try:
            response = model.generate_content(prompt)
            # Check if history is already in response.text
            new_q = response.text.strip()
            if any(h['q'].lower() in new_q.lower() for h in history):
                 # Model repeated a question despite being told not to
                 raise Exception("Repeated question from model")
            session['int_current_q'] = new_q
        except:
            fallbacks = [
                "What motivates you to perform your best at work?",
                "Can you describe a challenge you've overcome in a previous project?",
                "Where do you see yourself in five years?",
                "What are your greatest professional strengths?",
                "How do you handle working in a high-pressure environment?",
                "What is your approach to teamwork and collaboration?",
                "Tell me about a time you had to learn a new skill quickly."
            ]
            # Get already used questions
            used = [h['q'].lower() for h in history]
            # Find a fallback that hasn't been used yet
            available = [f for f in fallbacks if f.lower() not in used]
            
            import random
            if available:
                session['int_current_q'] = random.choice(available)
            else:
                session['int_current_q'] = random.choice(fallbacks) # Last resort
    else:
        # Final feedback
        session['int_step'] = 6
        prompt = f"""
        The mock interview is complete. 
        Resume: {resume_text}
        Interview History: {history}
        
        Task: Provide a detailed evaluation of this mock interview.
        For each question-answer pair, provide:
        - A score (1-10)
        - Specific feedback on the user's answer (strengths/weaknesses)
        - A high-quality, professional IDEAL answer tailored to the resume
        - Specific improvement tips
        
        Handle weak answers (like "not sure", "don't know", or very short irrelevant text) by providing strong corrections and showing what a great answer looks like.
        
        Provide the evaluation in valid JSON format:
        {{
            "overall_score": <number 1-10>,
            "overall_feedback": "<comprehensive overview in HTML format>",
            "detailed_feedback": [
                {{
                    "question": "...",
                    "user_answer": "...",
                    "ideal_answer": "...",
                    "score": <number 1-10>,
                    "feedback": "...",
                    "improvement_tips": "..."
                }},
                ... (for all 5 questions)
            ]
        }}
        
        Rules:
        - Ideal answers should be professional, detailed, and realistic.
        - Tailor ideal answers based on the resume.
        - Feedback should be clear and constructive.
        - Overall feedback should use HTML (<h3>, <p>, <ul>, <li>).
        """
        try:
            response = model.generate_content(prompt)
            import json
            text = response.text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            feedback_data = json.loads(text.strip())
            session['int_feedback'] = feedback_data
        except:
            session['int_feedback'] = {"overall_score": 0, "overall_feedback": "<p>Error generating feedback. Please try again.</p>", "detailed_feedback": []}
            
    return redirect(url_for('mock_interview'))


@app.route('/mock_interview/reset')
def mock_interview_reset():
    # Clear all interview session variables
    keys_to_clear = ['int_step', 'int_current_q', 'int_history', 'int_feedback', 'int_resume_text']
    for key in keys_to_clear:
        session.pop(key, None)
    return redirect(url_for('mock_interview'))



# ---------------- ADD COMPANY ----------------
@app.route('/add_company', methods=['GET', 'POST'])
def add_company():
    if 'admin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        url = request.form['url']
        about = request.form['about']
        end_date = request.form.get('end_date')

        end_date_str = None
        if end_date:
            if len(end_date) == 10:
                end_date_str = f"{end_date} 23:59:59"
            else:
                end_date_str = end_date.replace('T', ' ')

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO companies (name, url, about, end_date)
                VALUES (?, ?, ?, ?)
            """, (name, url, about, end_date_str))
            
            cur.execute("SELECT email FROM students WHERE email IS NOT NULL AND email != ''")
            student_records = cur.fetchall()
            student_emails = [row['email'] for row in student_records]
            
            conn.commit()
            conn.close()

            subject = f"New Company Alert: {name}"
            body = f"Hello Student,\n\nA new company ({name}) is now accepting applications on CareerConnect!\n\nCheck your dashboard for details."
            
            for stu_email in student_emails:
                send_email(stu_email, subject, body)

            flash("Company details saved successfully!", "success")
            return redirect(url_for('admin_companies'))

        except Exception as e:
            flash("Not successful, please try again.", "error")

    return render_template('add_company.html')


# ---------------- EDIT COMPANY ----------------
@app.route('/edit_company/<int:id>', methods=['GET', 'POST'])
def edit_company(id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        url = request.form['url']
        about = request.form['about']
        end_date = request.form.get('end_date')

        end_date_str = None
        if end_date:
            if len(end_date) == 10:
                end_date_str = f"{end_date} 23:59:59"
            else:
                end_date_str = end_date.replace('T', ' ')

        try:
            cur.execute("""
                UPDATE companies SET name=?, url=?, about=?, end_date=? WHERE id=?
            """, (name, url, about, end_date_str, id))
            conn.commit()
            flash("Company Updated Successfully!", "success")
            return redirect(url_for('admin_companies'))
        except Exception as e:
            flash("Update failed, please try again.", "error")
        finally:
            conn.close()

    cur.execute("SELECT * FROM companies WHERE id=?", (id,))
    company = cur.fetchone()
    conn.close()
    
    if not company:
        flash("Company not found", "error")
        return redirect(url_for('admin_companies'))
        
    return render_template('edit_company.html', company=company)


# ---------------- DELETE COMPANY ----------------
@app.route('/delete_company/<int:id>', methods=['POST'])
def delete_company(id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor()
    # Delete applications related to this company first to maintain constraints
    cur.execute("DELETE FROM applications WHERE company_id=?", (id,))
    cur.execute("DELETE FROM companies WHERE id=?", (id,))
    conn.commit()
    conn.close()
    
    flash("Company Deleted Successfully!", "success")
    return redirect(url_for('admin_companies'))


# ---------------- REMINDER BACKGROUND THREAD ----------------
def reminder_worker():
    while True:
        try:
            conn = get_db()
            cur = conn.cursor()
            
            # Delete old achievements (> 3 days)
            cur.execute("SELECT id, photo FROM achievements WHERE created_at < datetime('now', '-3 days')")
            old_achievements = cur.fetchall()
            for oa in old_achievements:
                photo_path = os.path.join(app.root_path, 'static', 'uploads', oa['photo'])
                if os.path.exists(photo_path):
                    try:
                        os.remove(photo_path)
                    except:
                        pass
                cur.execute("DELETE FROM achievement_action WHERE achievement_id = ?", (oa['id'],))
                cur.execute("DELETE FROM achievements WHERE id = ?", (oa['id'],))
            
            conn.commit()

            now = datetime.now()
            
            # Find companies with an end date and where we haven't sent a reminder yet
            cur.execute("SELECT * FROM companies WHERE end_date IS NOT NULL AND reminder_sent = 0")
            companies = cur.fetchall()
            
            for comp in companies:
                c_dict = dict(comp)
                ed_str = c_dict['end_date'].replace('T', ' ')
                if len(ed_str) == 16:
                    ed_str += ':00'
                    
                try:
                    try:
                        end_dt = datetime.strptime(ed_str, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        end_dt = datetime.strptime(ed_str, '%Y-%m-%d')
                        
                    diff = end_dt - now
                    if timedelta(0) < diff <= timedelta(hours=24):
                        days = diff.days
                        hours, remainder = divmod(diff.seconds, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        
                        cur.execute("SELECT email FROM students WHERE email IS NOT NULL AND email != ''")
                        students = cur.fetchall()
                        student_emails = [s['email'] for s in students]
                        
                        subject = f"Urgent: {c_dict['name']} closing in less than 24 hours!"
                        
                        html_body = f"""
                        <div style="background-color: #ffda03; padding: 40px 20px; text-align: center; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; border-radius: 8px;">
                            <h1 style="color: #212135; margin-bottom: 10px; font-size: 28px;">Limited time offer</h1>
                            <p style="color: #4a4a4a; font-size: 18px; margin-bottom: 30px;">This application is available only for next...</p>
                            
                            <div style="margin-bottom: 30px;">
                                <div style="display: inline-block; text-align: center; margin: 0 10px; color: #212135;">
                                    <div style="font-size: 24px; font-weight: bold;">{days}</div>
                                    <div style="font-size: 14px;">Days</div>
                                </div>
                                <div style="display: inline-block; font-size: 24px; vertical-align: top; margin-top: 5px; color: #212135;">:</div>
                                <div style="display: inline-block; text-align: center; margin: 0 10px; color: #212135;">
                                    <div style="font-size: 24px; font-weight: bold;">{hours}</div>
                                    <div style="font-size: 14px;">Hours</div>
                                </div>
                                <div style="display: inline-block; font-size: 24px; vertical-align: top; margin-top: 5px; color: #212135;">:</div>
                                <div style="display: inline-block; text-align: center; margin: 0 10px; color: #212135;">
                                    <div style="font-size: 24px; font-weight: bold;">{minutes}</div>
                                    <div style="font-size: 14px;">Min</div>
                                </div>
                                <div style="display: inline-block; font-size: 24px; vertical-align: top; margin-top: 5px; color: #212135;">:</div>
                                <div style="display: inline-block; text-align: center; margin: 0 10px; color: #212135;">
                                    <div style="font-size: 24px; font-weight: bold;">{seconds}</div>
                                    <div style="font-size: 14px;">Sec</div>
                                </div>
                            </div>
                        
                            <p style="font-size: 18px; margin-bottom: 30px; color: #212135;"><strong>Company:</strong> {c_dict['name']}</p>
                        
                            <a href="{c_dict['url']}" style="display: inline-block; background-color: #212135; color: #ffffff; text-decoration: none; padding: 15px 50px; border-radius: 30px; font-size: 18px; font-weight: bold;">Show me</a>
                        </div>
                        """
                        
                        for stu_email in student_emails:
                            send_email(stu_email, subject, html_body, is_html=True)
                            
                        # Mark as sent
                        cur.execute("UPDATE companies SET reminder_sent = 1 WHERE id = ?", (c_dict['id'],))
                        conn.commit()
                        
                except Exception as e:
                    pass
            
            conn.close()
        except Exception as e:
            pass
            
        time.sleep(60)

# Start the thread safely
thread = threading.Thread(target=reminder_worker, daemon=True)
thread.start()

# ---------------- MESSAGING SYSTEM ----------------

@app.route('/student_messages', methods=['GET', 'POST'])
def student_messages():
    if 'student_id' not in session:
        return redirect(url_for('login'))
    
    student_id = session['student_id']
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        content = request.form.get('content')
        if content:
            cur.execute("INSERT INTO messages (student_id, sender, content) VALUES (?, ?, ?)",
                        (student_id, 'student', content))
            conn.commit()
    
    # Mark admin messages as read
    cur.execute("UPDATE messages SET is_read = 1 WHERE student_id = ? AND sender = 'admin'", (student_id,))
    conn.commit()
    
    cur.execute("SELECT * FROM messages WHERE student_id = ? ORDER BY timestamp ASC", (student_id,))
    chat_history = cur.fetchall()
    
    cur.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    student = cur.fetchone()
    conn.close()
    
    return render_template('student_messages.html', chat_history=chat_history, student=student)

@app.route('/admin_messages')
def admin_messages():
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    cur = conn.cursor()
    # Get all students to initiate or continue chats
    cur.execute("""
        SELECT s.id, s.name, s.roll_number, s.photo,
        (SELECT COUNT(*) FROM messages WHERE student_id = s.id AND sender = 'student' AND is_read = 0) as unread_count,
        (SELECT content FROM messages WHERE student_id = s.id ORDER BY timestamp DESC LIMIT 1) as last_msg
        FROM students s
        ORDER BY unread_count DESC, s.name ASC
    """)
    students = cur.fetchall()
    conn.close()
    return render_template('admin_messages.html', students=students)

@app.route('/admin_chat/<int:student_id>', methods=['GET', 'POST'])
def admin_chat(student_id):
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        content = request.form.get('content')
        if content:
            cur.execute("INSERT INTO messages (student_id, sender, content) VALUES (?, ?, ?)",
                        (student_id, 'admin', content))
            conn.commit()
    
    # Mark student messages as read
    cur.execute("UPDATE messages SET is_read = 1 WHERE student_id = ? AND sender = 'student'", (student_id,))
    conn.commit()
    
    cur.execute("SELECT * FROM messages WHERE student_id = ? ORDER BY timestamp ASC", (student_id,))
    chat_history = cur.fetchall()
    
    cur.execute("SELECT * FROM students WHERE id = ?", (student_id,))
    student = cur.fetchone()
    conn.close()
    
    return render_template('admin_chat.html', chat_history=chat_history, student=student)

@app.route('/admin_job_activity')
def admin_job_activity():
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Check if is_resolved column exists
    cur.execute("PRAGMA table_info(job_remarks)")
    columns = [col['name'] for col in cur.fetchall()]
    if 'is_resolved' not in columns:
        cur.execute("ALTER TABLE job_remarks ADD COLUMN is_resolved INTEGER DEFAULT 0")
        conn.commit()

    cur.execute("""
        SELECT jr.*, s.name as student_name, c.name as company_name 
        FROM job_remarks jr 
        JOIN students s ON jr.student_id = s.id 
        JOIN companies c ON jr.company_id = c.id
        ORDER BY jr.id DESC
    """)
    remarks = cur.fetchall()
    
    cur.execute("SELECT name FROM companies")
    companies = [r['name'] for r in cur.fetchall()]
    
    cur.execute("SELECT DISTINCT course FROM students")
    courses = [r['course'] for r in cur.fetchall() if r['course']]
    
    conn.close()
    return render_template('admin_job_activity.html', remarks=remarks, companies=companies, courses=courses)

@app.route('/resolve_remark/<int:id>', methods=['POST'])
def resolve_remark(id):
    if 'admin' not in session:
        return redirect(url_for('login'))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE job_remarks SET is_resolved = 1 WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash("Remark marked as resolved.", "success")
    return redirect(url_for('admin_job_activity'))

@app.route('/reply_remark/<int:id>', methods=['POST'])
def reply_remark(id):
    if 'admin' not in session:
        return redirect(url_for('login'))
        
    admin_reply = request.form.get('admin_reply')
    if admin_reply:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE job_remarks SET admin_reply = ? WHERE id = ?", (admin_reply, id))
        conn.commit()
        conn.close()
        flash("Reply sent successfully.", "success")
        
    return redirect(url_for('admin_job_activity'))

if __name__ == '__main__':
    app.run(debug=True)